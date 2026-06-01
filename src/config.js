import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
export const repoRoot = path.resolve(path.dirname(__filename), '..');
export const runtimeDir = path.join(repoRoot, '.runtime');

export function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

export function readJson(relativePath) {
  const fullPath = path.join(repoRoot, relativePath);
  return JSON.parse(fs.readFileSync(fullPath, 'utf8'));
}

export const pagesConfig = readJson('config/pages.json');

export function resolveOaPage({ pageId, workflowId, url }) {
  if (url) return { id: 'custom-oa-page', name: 'Custom OA Page', url };
  if (!pageId && !workflowId) return pagesConfig.oa[0];
  const page = pagesConfig.oa.find((item) => item.id === pageId || item.workflowId === workflowId);
  if (!page) {
    throw new Error(`Unknown OA page: ${pageId || workflowId || '(empty)'}`);
  }
  return page;
}

export function resolvePdmPage() {
  return pagesConfig.pdm;
}

export function publicRuntimePath(filePath) {
  const relative = path.relative(runtimeDir, filePath).replaceAll(path.sep, '/');
  return `/runtime/${relative}`;
}
