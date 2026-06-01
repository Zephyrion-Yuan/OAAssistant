import { edgeSession } from '../browser/edgeSession.js';
import { pagesConfig } from '../config.js';
import { detectLoginPage, waitForSettledPage } from './domScanner.js';
import { redactUrl } from '../security/redaction.js';

function cookieSummary(cookie) {
  return {
    name: cookie.name,
    domain: cookie.domain,
    path: cookie.path,
    expires: cookie.expires,
    isSessionCookie: cookie.expires === -1,
    httpOnly: cookie.httpOnly,
    secure: cookie.secure,
    sameSite: cookie.sameSite
  };
}

export async function diagnoseSystemSession(input = {}) {
  const system = input.system || 'oa';
  const target = system === 'pdm'
    ? pagesConfig.pdm
    : pagesConfig.oa.find((item) => item.id === 'oa-portal') || pagesConfig.oa[0];

  const page = await edgeSession.newPage();
  await page.goto(input.url || target.url, { waitUntil: 'domcontentloaded' });
  await waitForSettledPage(page);
  const login = await detectLoginPage(page);
  const host = new URL(page.url()).hostname;
  const cookies = await page.context().cookies();
  const relevantCookies = cookies
    .filter((cookie) => host.endsWith(cookie.domain.replace(/^\./, '')) || cookie.domain.replace(/^\./, '').endsWith(host))
    .map(cookieSummary);
  const sessionCookieCount = relevantCookies.filter((cookie) => cookie.isSessionCookie).length;

  return {
    system,
    target: target.id,
    currentUrl: redactUrl(page.url()),
    title: await page.title(),
    requiresLogin: login.requiresLogin,
    textSample: login.textSample,
    cookies: relevantCookies,
    cookieCount: relevantCookies.length,
    sessionCookieCount,
    persistentCookieCount: relevantCookies.length - sessionCookieCount,
    likelyCloseInvalidatesLogin: sessionCookieCount > 0 && relevantCookies.length === sessionCookieCount,
    note: 'Cookie values are not returned. expires=-1 means a browser-session cookie; systems using only session cookies generally cannot be preserved by copying a closed browser profile.'
  };
}
