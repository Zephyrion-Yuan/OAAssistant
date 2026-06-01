import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ensureDir, runtimeDir } from '../config.js';

export const cacheRoot = path.join(runtimeDir, 'edge-profile-cache', 'User Data');
export const profileName = process.env.MEGANT_EDGE_PROFILE_NAME || 'Default';

export function edgeUserDataRoot() {
  if (process.platform === 'win32') {
    const localAppData = process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local');
    return path.join(localAppData, 'Microsoft', 'Edge', 'User Data');
  }
  if (process.platform === 'darwin') {
    return path.join(os.homedir(), 'Library', 'Application Support', 'Microsoft Edge');
  }
  return path.join(os.homedir(), '.config', 'microsoft-edge');
}

export function edgeProcesses() {
  if (process.platform !== 'win32') return [];
  const output = execFileSync('powershell.exe', [
    '-NoProfile',
    '-Command',
    "$p = Get-Process msedge -ErrorAction SilentlyContinue | Select-Object Id,MainWindowTitle; if ($p) { $p | ConvertTo-Json -Compress } else { '[]' }"
  ], { encoding: 'utf8' }).trim();
  if (!output) return [];
  const parsed = JSON.parse(output);
  return Array.isArray(parsed) ? parsed : [parsed];
}

export function assertEdgeClosed() {
  const processes = edgeProcesses();
  if (processes.length) {
    const visible = processes.filter((item) => item.MainWindowTitle);
    throw new Error(`Edge is still running (${processes.length} process(es), ${visible.length} visible window(s)). Close Edge before caching or testing the profile.`);
  }
}

export function closeEdgeBackgroundProcesses() {
  if (process.platform !== 'win32') {
    return {
      ok: false,
      message: 'Automatic Edge background cleanup is only implemented for Windows.',
      killed: []
    };
  }
  const before = edgeProcesses();
  const visible = before.filter((item) => item.MainWindowTitle);
  if (visible.length) {
    return {
      ok: false,
      message: `Refusing to close Edge because ${visible.length} visible window(s) are still open.`,
      visible,
      killed: []
    };
  }

  const output = execFileSync('powershell.exe', [
    '-NoProfile',
    '-Command',
    "$p = Get-Process msedge -ErrorAction SilentlyContinue | Where-Object { -not $_.MainWindowTitle } | Select-Object Id,MainWindowTitle; if ($p) { $p | Stop-Process -Force; $p | ConvertTo-Json -Compress } else { '[]' }"
  ], { encoding: 'utf8' }).trim();
  const parsed = output ? JSON.parse(output) : [];
  const killed = Array.isArray(parsed) ? parsed : [parsed];
  return {
    ok: true,
    killed,
    killedCount: killed.length,
    remaining: edgeProcesses(),
    closedAt: new Date().toISOString()
  };
}

export function closeAllEdgeProcesses() {
  if (process.platform !== 'win32') {
    return {
      ok: false,
      message: 'Automatic close-all Edge process cleanup is only implemented for Windows.',
      killed: []
    };
  }

  const before = edgeProcesses();
  const output = execFileSync('powershell.exe', [
    '-NoProfile',
    '-Command',
    "$p = Get-Process msedge -ErrorAction SilentlyContinue; if ($p) { $snapshot = $p | Select-Object Id,MainWindowTitle; $p | Stop-Process -Force; $snapshot | ConvertTo-Json -Compress } else { '[]' }"
  ], { encoding: 'utf8' }).trim();
  const parsed = output ? JSON.parse(output) : [];
  const killed = Array.isArray(parsed) ? parsed : [parsed];
  return {
    ok: true,
    killed,
    killedCount: killed.length,
    visibleKilledCount: before.filter((item) => item.MainWindowTitle).length,
    closedAt: new Date().toISOString()
  };
}

function assertInsideRuntime(targetPath) {
  const resolved = path.resolve(targetPath);
  const root = path.resolve(runtimeDir);
  if (!resolved.startsWith(root)) {
    throw new Error(`Refusing to write outside runtime dir: ${targetPath}`);
  }
}

function shouldCopy(src) {
  const name = path.basename(src);
  if (/^(Singleton|LOCK|lockfile|Crashpad|BrowserMetrics)/i.test(name)) return false;
  if (/\.(tmp|log|lock)$/i.test(name)) return false;
  const normalized = src.replaceAll(path.sep, '/');
  const excludedSegments = [
    '/Cache',
    '/Code Cache',
    '/GPUCache',
    '/DawnCache',
    '/GrShaderCache',
    '/ShaderCache',
    '/Crashpad',
    '/OptimizationGuidePredictionModels',
    '/Safe Browsing',
    '/component_crx_cache'
  ];
  return !excludedSegments.some((segment) => normalized.includes(segment));
}

export function cacheEdgeProfile({ force = true } = {}) {
  assertEdgeClosed();
  const sourceRoot = edgeUserDataRoot();
  const sourceProfile = path.join(sourceRoot, profileName);
  if (!fs.existsSync(sourceProfile)) {
    throw new Error(`Edge profile not found: ${sourceProfile}`);
  }

  assertInsideRuntime(cacheRoot);
  if (force && fs.existsSync(cacheRoot)) {
    fs.rmSync(cacheRoot, { recursive: true, force: true });
  }
  ensureDir(cacheRoot);

  const copied = [];
  const rootFiles = ['Local State', 'First Run', 'Last Version'];
  for (const fileName of rootFiles) {
    const from = path.join(sourceRoot, fileName);
    const to = path.join(cacheRoot, fileName);
    if (fs.existsSync(from) && shouldCopy(from)) {
      fs.cpSync(from, to, { force: true });
      copied.push(path.relative(cacheRoot, to));
    }
  }

  const profileTarget = path.join(cacheRoot, profileName);
  fs.cpSync(sourceProfile, profileTarget, {
    recursive: true,
    force: true,
    filter: shouldCopy
  });

  return {
    ok: true,
    sourceRoot,
    sourceProfile,
    cacheRoot,
    cachedProfile: profileTarget,
    profileName,
    copiedRootFiles: copied,
    cachedAt: new Date().toISOString()
  };
}

export function profileCacheStatus() {
  const cachedProfile = path.join(cacheRoot, profileName);
  return {
    cacheRoot,
    profileName,
    cachedProfile,
    exists: fs.existsSync(cachedProfile),
    updatedAt: fs.existsSync(cachedProfile) ? fs.statSync(cachedProfile).mtime.toISOString() : null
  };
}
