#!/usr/bin/env node
import { Command } from 'commander';
import { cachedProfileSession } from '../src/browser/cachedProfileSession.js';
import { detectLoginPage, waitForSettledPage } from '../src/automation/domScanner.js';
import { redactText, redactUrl } from '../src/security/redaction.js';
import { explorationAllowedHosts, assertAllowedBusinessUrl } from '../src/explorer/domainGuard.js';
import { attachSafeNetworkRecorder } from '../src/explorer/safeNetworkRecorder.js';
import { scanPageSurface } from '../src/explorer/surfaceScanner.js';
import { writeExplorationArtifacts } from '../src/explorer/artifacts.js';

const program = new Command();

program
  .description('Explore a PDM page using the cached PDM Playwright profile.')
  .requiredOption('-u, --url <url>', 'target PDM business URL')
  .option('-n, --name <name>', 'human-readable page name', 'PDM page')
  .option('--page-id <pageId>', 'stable page identifier', 'pdm-page')
  .option('--post-scan-wait-ms <ms>', 'wait before final API snapshot', Number, 800)
  .option('--full', 'print full report instead of summary only');

program.parse(process.argv);
const options = program.opts();

function summarize(report) {
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
    paginationCount: surface.pagination?.length || 0,
    apiCallCount: report.apiCalls?.length || 0,
    listApiCount: listApis.length
  };
}

async function main() {
  const allowedHosts = explorationAllowedHosts();
  const targetUrl = assertAllowedBusinessUrl(options.url, allowedHosts);
  const page = await cachedProfileSession.newPage();
  const recorder = attachSafeNetworkRecorder(page);

  await page.goto(targetUrl, { waitUntil: 'domcontentloaded' });
  await waitForSettledPage(page);
  const login = await detectLoginPage(page);
  const initialSurface = await scanPageSurface(page);
  await page.waitForTimeout(options.postScanWaitMs);
  const finalSurface = await scanPageSurface(page);

  const report = {
    schemaVersion: 1,
    name: options.name,
    pageId: options.pageId,
    exploredAt: new Date().toISOString(),
    targetUrl: redactUrl(targetUrl),
    finalUrl: redactUrl(page.url()),
    allowedHosts,
    requiresLogin: login.requiresLogin,
    login: {
      ...login,
      url: redactUrl(login.url),
      textSample: redactText(login.textSample || '')
    },
    initialApiCallCount: 0,
    initialSurface,
    finalSurface,
    actions: [],
    fieldDeltas: [],
    apiCalls: recorder.calls
  };

  const artifacts = writeExplorationArtifacts(report);
  const output = {
    ok: true,
    summary: summarize(report),
    artifacts,
    ...(options.full ? { report } : {})
  };
  console.log(JSON.stringify(output, null, 2));
}

main()
  .catch((error) => {
    console.error(JSON.stringify({ ok: false, error: error.message }, null, 2));
    process.exitCode = 1;
  })
  .finally(async () => {
    await cachedProfileSession.close().catch(() => {});
  });
