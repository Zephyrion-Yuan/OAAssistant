import { chromium } from 'playwright';
import { browserLaunchOptions } from './browserLaunch.js';
import { cacheRoot, profileCacheStatus, profileName } from '../profile/profileCache.js';

export class CachedProfileSession {
  constructor() {
    this.context = null;
    this.launchPromise = null;
  }

  async getContext() {
    if (this.context) return this.context;
    if (this.launchPromise) return this.launchPromise;

    const status = profileCacheStatus();
    if (!status.exists) {
      throw new Error(`PDM cached profile does not exist: ${status.cachedProfile}. Run PDM cache flow first.`);
    }

    this.launchPromise = chromium
      .launchPersistentContext(
        cacheRoot,
        browserLaunchOptions({ args: [`--profile-directory=${profileName}`] })
      )
      .then((context) => {
        this.context = context;
        context.setDefaultTimeout(Number(process.env.MEGANT_PLAYWRIGHT_TIMEOUT_MS || 15000));
        context.setDefaultNavigationTimeout(Number(process.env.MEGANT_PLAYWRIGHT_NAV_TIMEOUT_MS || 45000));
        context.on('close', () => {
          this.context = null;
          this.launchPromise = null;
        });
        return context;
      })
      .finally(() => {
        if (!this.context) this.launchPromise = null;
      });

    return this.launchPromise;
  }

  async newPage() {
    const context = await this.getContext();
    const page = await context.newPage();
    await page.bringToFront();
    return page;
  }

  async close() {
    if (this.context) {
      await this.context.close();
      this.context = null;
    }
    this.launchPromise = null;
  }

  status() {
    return {
      browser: this.context ? 'running' : 'stopped',
      cache: profileCacheStatus()
    };
  }
}

export const cachedProfileSession = new CachedProfileSession();
