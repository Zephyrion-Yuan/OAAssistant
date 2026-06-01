import { chromium } from 'playwright';
import { browserLaunchOptions } from '../browser/browserLaunch.js';
import { pagesConfig } from '../config.js';
import { detectLoginPage, waitForSettledPage } from '../automation/domScanner.js';
import { assertEdgeClosed, cacheRoot, profileCacheStatus, profileName } from './profileCache.js';

async function checkPage(context, target) {
  const page = await context.newPage();
  await page.goto(target.url, { waitUntil: 'domcontentloaded' });
  await waitForSettledPage(page);
  const login = await detectLoginPage(page);
  const result = {
    id: target.id,
    name: target.name,
    url: page.url(),
    title: await page.title(),
    requiresLogin: login.requiresLogin,
    textSample: login.textSample
  };
  await page.close().catch(() => {});
  return result;
}

export async function testOaLiveSession(context) {
  const oaTarget = pagesConfig.oa.find((item) => item.id === 'oa-portal') || pagesConfig.oa[0];
  const oa = await checkPage(context, oaTarget);
  return {
    ok: !oa.requiresLogin,
    oa,
    testedAt: new Date().toISOString()
  };
}

export async function testPdmLiveSession(context) {
  const pdm = await checkPage(context, pagesConfig.pdm);
  return {
    ok: !pdm.requiresLogin,
    pdm,
    testedAt: new Date().toISOString()
  };
}

export async function testPdmCachedProfileLogin() {
  assertEdgeClosed();
  const status = profileCacheStatus();
  if (!status.exists) {
    throw new Error(`Cached profile does not exist: ${status.cachedProfile}`);
  }

  const context = await chromium.launchPersistentContext(
    cacheRoot,
    browserLaunchOptions({ args: [`--profile-directory=${profileName}`] })
  );

  try {
    const pdm = await checkPage(context, pagesConfig.pdm);
    return {
      ok: !pdm.requiresLogin,
      cache: status,
      pdm,
      testedAt: new Date().toISOString()
    };
  } finally {
    await context.close().catch(() => {});
  }
}

export async function testCachedProfileLogin() {
  assertEdgeClosed();
  const status = profileCacheStatus();
  if (!status.exists) {
    throw new Error(`Cached profile does not exist: ${status.cachedProfile}`);
  }

  const context = await chromium.launchPersistentContext(
    cacheRoot,
    browserLaunchOptions({ args: [`--profile-directory=${profileName}`] })
  );

  try {
    const oaTarget = pagesConfig.oa.find((item) => item.id === 'oa-portal') || pagesConfig.oa[0];
    const [oa, pdm] = await Promise.all([checkPage(context, oaTarget), checkPage(context, pagesConfig.pdm)]);
    return {
      ok: !oa.requiresLogin && !pdm.requiresLogin,
      cache: status,
      oa,
      pdm,
      testedAt: new Date().toISOString()
    };
  } finally {
    await context.close().catch(() => {});
  }
}
