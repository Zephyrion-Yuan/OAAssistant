import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { chromium } from 'playwright';
import { browserLaunchOptions } from './browserLaunch.js';
import { ensureDir, publicRuntimePath, runtimeDir } from '../config.js';

const screenshotDir = path.join(runtimeDir, 'login-screenshots');

function defaultCurrentEdgeUserDataDir() {
  if (process.platform === 'win32') {
    const localAppData = process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local');
    return path.join(localAppData, 'Microsoft', 'Edge', 'User Data');
  }
  if (process.platform === 'darwin') {
    return path.join(os.homedir(), 'Library', 'Application Support', 'Microsoft Edge');
  }
  return path.join(os.homedir(), '.config', 'microsoft-edge');
}

function resolveProfileConfig() {
  const profileMode = process.env.MEGANT_EDGE_PROFILE_MODE || 'isolated';
  const profileName = process.env.MEGANT_EDGE_PROFILE_NAME || (profileMode === 'sso-handoff' ? 'MEGAntBot' : 'Default');
  const currentRoot = defaultCurrentEdgeUserDataDir();
  if (process.env.MEGANT_EDGE_USER_DATA_DIR) {
    return {
      mode: 'custom',
      userDataDir: process.env.MEGANT_EDGE_USER_DATA_DIR,
      profileName: ''
    };
  }
  if (profileMode === 'current-profile-dir') {
    return {
      mode: 'current-profile-dir',
      userDataDir: path.join(currentRoot, profileName),
      profileName: ''
    };
  }
  if (profileMode === 'current' || profileMode === 'sso-handoff') {
    return {
      mode: profileMode,
      userDataDir: currentRoot,
      profileName
    };
  }
  return {
    mode: 'isolated',
    userDataDir: path.join(runtimeDir, 'edge-profile'),
    profileName: ''
  };
}

export class EdgeSession {
  constructor() {
    this.context = null;
    this.profile = resolveProfileConfig();
    this.lastLoginScreenshot = null;
    ensureDir(runtimeDir);
    ensureDir(screenshotDir);
  }

  async getContext() {
    if (this.context) return this.context;

    ensureDir(this.profile.userDataDir);
    const args = [];
    if (this.profile.profileName) {
      args.push(`--profile-directory=${this.profile.profileName}`);
    }

    try {
      this.context = await chromium.launchPersistentContext(
        this.profile.userDataDir,
        browserLaunchOptions({ args })
      );
    } catch (error) {
      error.message = [
        `Failed to launch Edge with profile mode "${this.profile.mode}".`,
        `User data dir: ${this.profile.userDataDir}`,
        this.profile.profileName ? `Profile directory: ${this.profile.profileName}` : null,
        'Close all Edge windows and background Edge processes before using current/sso-handoff profile modes.',
        'For isolated mode, start with MEGANT_EDGE_PROFILE_MODE=isolated and scan login once.',
        error.message
      ].filter(Boolean).join('\n');
      throw error;
    }

    this.context.setDefaultTimeout(Number(process.env.MEGANT_PLAYWRIGHT_TIMEOUT_MS || 15000));
    this.context.setDefaultNavigationTimeout(Number(process.env.MEGANT_PLAYWRIGHT_NAV_TIMEOUT_MS || 45000));
    this.context.on('close', () => {
      this.context = null;
    });
    return this.context;
  }

  async newPage() {
    const context = await this.getContext();
    const page = await context.newPage();
    await page.bringToFront();
    return page;
  }

  async captureLoginScreenshot(page, reason = 'login') {
    const safeReason = reason.replace(/[^a-z0-9_-]+/gi, '-').toLowerCase();
    const filePath = path.join(screenshotDir, `${Date.now()}-${safeReason}.png`);
    await page.screenshot({ path: filePath, fullPage: true });
    this.lastLoginScreenshot = {
      filePath,
      url: publicRuntimePath(filePath),
      createdAt: new Date().toISOString()
    };
    return this.lastLoginScreenshot;
  }

  status() {
    return {
      browser: this.context ? 'running' : 'stopped',
      profile: this.profile,
      lastLoginScreenshot: this.lastLoginScreenshot,
      runtimeDir
    };
  }

  async close() {
    if (this.context) {
      await this.context.close();
      this.context = null;
    }
  }
}

export const edgeSession = new EdgeSession();
