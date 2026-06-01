import { edgeSession } from '../browser/edgeSession.js';
import { cachedProfileSession } from '../browser/cachedProfileSession.js';
import { publicRuntimePath, resolvePdmPage } from '../config.js';
import { detectLoginPage, scanDom, waitForSettledPage } from './domScanner.js';
import { redactText, redactUrl, sensitiveNamePattern } from '../security/redaction.js';

function compactUrl(rawUrl) {
  return redactUrl(rawUrl);
}

function sanitizePostData(postData) {
  if (!postData) return null;
  if (postData.length > 1200) return '[omitted: large post body]';
  try {
    const params = new URLSearchParams(postData);
    if (Array.from(params.keys()).length) {
      for (const key of Array.from(params.keys())) {
        if (sensitiveNamePattern.test(key)) params.set(key, '[redacted]');
      }
      return params.toString();
    }
  } catch {
    // fall through
  }
  return sensitiveNamePattern.test(postData) ? '[redacted: sensitive-looking body]' : postData;
}

function sanitizeBodySample(text) {
  if (!text) return '';
  return redactText(text)
    .replace(/\s+/g, ' ')
    .slice(0, 1200);
}

function sanitizeHeaders(headers) {
  const result = {};
  for (const [key, value] of Object.entries(headers || {})) {
    result[key] = sensitiveNamePattern.test(key) ? '[redacted]' : value;
  }
  return result;
}

export async function diagnosePdmLogin(input = {}) {
  const pageConfig = resolvePdmPage();
  const session = input.useLiveSession ? edgeSession : cachedProfileSession;
  const page = await session.newPage();
  const events = [];
  const requests = [];
  const responses = [];
  const assets = [];
  const startedAt = Date.now();

  const record = (type, payload) => {
    events.push({
      type,
      elapsedMs: Date.now() - startedAt,
      ...payload
    });
  };

  page.on('framenavigated', (frame) => {
    if (frame === page.mainFrame()) record('navigation', { url: compactUrl(frame.url()) });
  });

  page.on('popup', (popup) => {
    record('popup', { url: compactUrl(popup.url()) });
  });

  page.on('request', (request) => {
    if (['script', 'stylesheet'].includes(request.resourceType())) {
      assets.push({
        elapsedMs: Date.now() - startedAt,
        resourceType: request.resourceType(),
        url: compactUrl(request.url())
      });
      return;
    }
    if (!['xhr', 'fetch', 'document'].includes(request.resourceType())) return;
    requests.push({
      elapsedMs: Date.now() - startedAt,
      method: request.method(),
      resourceType: request.resourceType(),
      url: compactUrl(request.url()),
      postData: sanitizePostData(request.postData())
    });
  });

  page.on('response', async (response) => {
    const request = response.request();
    if (!['xhr', 'fetch', 'document'].includes(request.resourceType())) return;
    const headers = sanitizeHeaders(response.headers());
    const item = {
      elapsedMs: Date.now() - startedAt,
      status: response.status(),
      resourceType: request.resourceType(),
      url: compactUrl(response.url()),
      headers
    };
    const contentType = headers['content-type'] || headers['Content-Type'] || '';
    if (/json|text|html/i.test(contentType)) {
      const text = await response.text().catch(() => '');
      item.bodySample = sanitizeBodySample(text);
    }
    responses.push(item);
  });

  await page.goto(input.url || pageConfig.url, { waitUntil: 'domcontentloaded' });
  await waitForSettledPage(page);
  const extraWaitMs = Number(input.waitMs || 8000);
  await page.waitForTimeout(extraWaitMs);

  const login = await detectLoginPage(page);
  const dom = await scanDom(page);
  const screenshot = await edgeSession.captureLoginScreenshot(page, 'pdm-login-diagnose');
  const cookies = await page.context().cookies().catch(() => []);

  return {
    page: pageConfig,
    currentUrl: redactUrl(page.url()),
    login,
    screenshotUrl: screenshot.url,
    screenshotFile: screenshot.filePath,
    events,
    requests: requests.slice(-80),
    responses: responses.slice(-80),
    assets: assets.slice(-120),
    visibleFields: dom.fields,
    visibleButtons: dom.buttons,
    cookieSummary: cookies.map((cookie) => ({
      name: cookie.name,
      domain: cookie.domain,
      path: cookie.path,
      expires: cookie.expires,
      httpOnly: cookie.httpOnly,
      secure: cookie.secure,
      sameSite: cookie.sameSite
    })),
    note: `Cookie values and sensitive-looking request data are intentionally not returned. Open ${publicRuntimePath(screenshot.filePath)} from the local service to view the screenshot.`
  };
}

async function snapshotAuthPage(page, label) {
  await waitForSettledPage(page);
  const login = await detectLoginPage(page);
  const dom = await scanDom(page);
  const screenshot = await edgeSession.captureLoginScreenshot(page, `pdm-auth-probe-${label}`);
  return {
    label,
    url: page.url(),
    title: login.title,
    textSample: login.textSample,
    requiresLogin: login.requiresLogin,
    screenshotUrl: screenshot.url,
    fields: dom.fields,
    buttons: dom.buttons
  };
}

export async function probePdmAuth(input = {}) {
  const pageConfig = resolvePdmPage();
  const origin = new URL(input.url || pageConfig.url).origin;
  const routes = input.routes || [
    '/auth/login?redirect=%252Fmaterial%252Fmaterial-form',
    '/auth/qrcode-login',
    '/auth/code-login',
    '/auth/register',
    '/auth/forget-password'
  ];
  const results = [];

  for (const route of routes) {
    const page = await edgeSession.newPage();
    const url = route.startsWith('http') ? route : `${origin}${route}`;
    await page.goto(url, { waitUntil: 'domcontentloaded' });
    results.push(await snapshotAuthPage(page, route.replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '')));
    await page.close().catch(() => {});
  }

  const ssoPage = await edgeSession.newPage();
  await ssoPage.goto(`${origin}/auth/login?redirect=%252Fmaterial%252Fmaterial-form`, { waitUntil: 'domcontentloaded' });
  await waitForSettledPage(ssoPage);
  const beforeClick = await snapshotAuthPage(ssoPage, 'enterprise-sso-before-click');
  let clickResult = { clicked: false, reason: 'No enterprise SSO button found' };
  const ssoButton = ssoPage.getByText(/企业\s*SSO\s*登录|SSO|企业/i).first();
  if (await ssoButton.count().catch(() => 0)) {
    await ssoButton.click().catch((error) => {
      clickResult = { clicked: false, reason: error.message };
    });
    if (clickResult.reason) {
      // keep failure result
    } else {
      clickResult = { clicked: true };
    }
    await ssoPage.waitForTimeout(Number(input.afterClickWaitMs || 5000));
  }
  const afterClick = await snapshotAuthPage(ssoPage, 'enterprise-sso-after-click');
  await ssoPage.close().catch(() => {});

  return {
    page: pageConfig,
    origin,
    routes,
    results,
    enterpriseSso: {
      clickResult,
      beforeClick,
      afterClick
    },
    note: 'This probe does not read DingTalk local traffic, token values, or cookie values. It only tests visible web login routes and page navigation.'
  };
}
