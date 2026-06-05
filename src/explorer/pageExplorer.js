import { edgeSession } from '../browser/edgeSession.js';
import { detectLoginPage, waitForSettledPage } from '../automation/domScanner.js';
import { redactText, redactUrl } from '../security/redaction.js';
import { assertAllowedBusinessUrl, explorationAllowedHosts, isHostAllowed } from './domainGuard.js';
import { attachSafeNetworkRecorder } from './safeNetworkRecorder.js';
import { scanPageSurface, diffFieldValues } from './surfaceScanner.js';
import { runExplorationActions } from './actionRunner.js';
import { writeExplorationArtifacts } from './artifacts.js';

async function waitForAllowedCurrentUrl(page, allowedHosts, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const current = new URL(page.url());
    if (current.protocol === 'https:' && isHostAllowed(current.hostname, allowedHosts)) return true;
    await page.waitForTimeout(1000);
  }
  return false;
}

function summarizeReport(report) {
  const surface = report.finalSurface || report.initialSurface || {};
  const listApis = (report.apiCalls || []).filter((call) => call.classification?.dataQueryCandidate);
  return {
    name: report.name,
    targetUrl: report.targetUrl,
    finalUrl: report.finalUrl,
    requiresLogin: report.requiresLogin,
    fieldCount: surface.fields?.length || 0,
    requiredFieldCount: (surface.fields || []).filter((field) => field.required).length,
    buttonCount: surface.buttons?.length || 0,
    tableCount: surface.tables?.length || 0,
    apiCallCount: report.apiCalls?.length || 0,
    listApiCount: listApis.length,
    fieldDeltaCount: report.fieldDeltas?.length || 0
  };
}

export async function explorePage(input = {}) {
  if (!input.url) throw new Error('explorePage requires url.');
  const allowedHosts = input.allowedHosts?.length ? input.allowedHosts : explorationAllowedHosts();
  const targetUrl = assertAllowedBusinessUrl(input.url, allowedHosts);
  const name = input.name || input.pageId || new URL(targetUrl).hostname;
  let page = null;
  try {
    page = await edgeSession.newPage();
    const recorder = attachSafeNetworkRecorder(page);

    await page.goto(targetUrl, { waitUntil: 'domcontentloaded' });
    if (input.allowManualLogin !== false) {
      await waitForAllowedCurrentUrl(page, allowedHosts, Number(input.loginTimeoutMs || 180000));
    }
    await waitForSettledPage(page);

    const login = await detectLoginPage(page);
    const safeLogin = {
      ...login,
      url: redactUrl(login.url),
      textSample: redactText(login.textSample || '')
    };
    const initialSurface = await scanPageSurface(page);
    const initialApiCount = recorder.count();
    const actions = [];
    let finalSurface = initialSurface;
    let fieldDeltas = [];

    if (!login.requiresLogin) {
      actions.push(...await runExplorationActions(page, input.interactions || [], recorder));
      finalSurface = await scanPageSurface(page);
      fieldDeltas = diffFieldValues(initialSurface, finalSurface);
    }

    await page.waitForTimeout(Number(input.postScanWaitMs || 800));
    const apiCalls = recorder.calls;
    const report = {
      schemaVersion: 1,
      name,
      pageId: input.pageId || null,
      exploredAt: new Date().toISOString(),
      targetUrl: redactUrl(targetUrl),
      finalUrl: redactUrl(page.url()),
      allowedHosts,
      requiresLogin: safeLogin.requiresLogin,
      login: safeLogin,
      initialApiCallCount: initialApiCount,
      initialSurface,
      finalSurface,
      actions,
      fieldDeltas,
      apiCalls
    };

    const artifacts = input.saveArtifact === false ? null : writeExplorationArtifacts(report);
    return {
      ok: true,
      summary: summarizeReport(report),
      artifacts,
      report
    };
  } finally {
    if (input.keepPageOpen !== true) {
      await page?.close().catch(() => {});
    }
  }
}
