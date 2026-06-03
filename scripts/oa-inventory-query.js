#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { Command } from 'commander';

process.env.MEGANT_EDGE_PROFILE_MODE ||= 'sso-handoff';
process.env.MEGANT_EDGE_PROFILE_NAME ||= 'MEGAntBot';

const { queryOaInventory } = await import('../src/automation/oaInventoryQuery.js');
const { edgeSession } = await import('../src/browser/edgeSession.js');
const { ensureDir, runtimeDir } = await import('../src/config.js');

const program = new Command();

function collectCondition(value, previous) {
  previous.push(value);
  return previous;
}

function parseConditionEntries(entries = []) {
  const conditions = {};
  for (const entry of entries) {
    const index = String(entry).indexOf('=');
    if (index <= 0) {
      throw new Error(`--condition must use KEY=VALUE format: ${entry}`);
    }
    const key = entry.slice(0, index).trim();
    const value = entry.slice(index + 1).trim();
    if (key && value) conditions[key] = value;
  }
  return conditions;
}

function outputPathFor(result, explicitPath) {
  if (explicitPath) return path.resolve(explicitPath);
  const query = result?.query || {};
  const label = [
    query.materialCode && `mat-${query.materialCode}`,
    query.factoryCode && `werks-${query.factoryCode}`,
    query.stockLocationCode && `lgort-${query.stockLocationCode}`,
    query.wbsCode && `wbs-${query.wbsCode}`
  ].filter(Boolean).join('_') || 'inventory-query';
  const outputDir = path.join(runtimeDir, 'inventory-query-results');
  ensureDir(outputDir);
  return path.join(outputDir, `${new Date().toISOString().replace(/[:.]/g, '-')}-${label.replace(/[^\w.-]+/g, '_')}.json`);
}

program
  .description('Query OA SAP inventory through the safe browser.SAPInventoryQueryInterface wrapper. Material code alone is enough for the default query.')
  .option('--material-code <code>', 'material code, mapped to MATNR; this can be the only input')
  .option('--factory-code <code>', 'factory/plant code, mapped to WERKS')
  .option('--warehouse-code <code>', 'warehouse/storage location SAP code, mapped to LGORT')
  .option('--stock-location-code <code>', 'alias for --warehouse-code')
  .option('--stock-location-sap <code>', 'alias for --warehouse-code')
  .option('--wbs <code>', 'WBS code, mapped to POSID')
  .option('--wbs-code <code>', 'alias for --wbs')
  .option('--condition <key=value>', 'extra raw browser query condition; can be repeated', collectCondition, [])
  .option('--workflow-id <id>', 'OA workflow id used as stable inventory entry', '414')
  .option('--page-id <id>', 'configured OA page id override')
  .option('--url <url>', 'OA workflow URL override')
  .option('--page-size <n>', 'browser data page size', Number, 50)
  .option('--max-pages <n>', 'maximum browser data pages to fetch', Number, 5)
  .option('--no-prefer-wbs', 'skip the WBS attempt and query without POSID')
  .option('--no-fallback', 'do not fallback to a non-WBS query when the WBS attempt returns no rows')
  .option('--login-timeout-ms <ms>', 'wait for manual login in managed Edge before returning requiresLogin', Number, 0)
  .option('--endpoint <url>', 'local MEGAnt API endpoint to reuse an already running authenticated Edge session', 'http://127.0.0.1:8787/api/oa/inventory-query')
  .option('--direct', 'launch Edge directly instead of trying the local MEGAnt API first')
  .option('--out <file>', 'write result JSON to a specific file');

program.parse(process.argv);
const options = program.opts();

function buildQueryInput() {
  return {
    materialCode: options.materialCode,
    factoryCode: options.factoryCode,
    stockLocationCode: options.stockLocationCode || options.stockLocationSap || options.warehouseCode,
    wbsCode: options.wbsCode || options.wbs,
    conditions: parseConditionEntries(options.condition),
    workflowId: options.workflowId,
    pageId: options.pageId,
    url: options.url,
    pageSize: options.pageSize,
    maxPages: options.maxPages,
    preferWbs: options.preferWbs,
    fallbackWarehouse: options.fallback,
    loginTimeoutMs: options.loginTimeoutMs
  };
}

async function queryViaApi(input, endpoint) {
  const response = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify(input)
  });
  const text = await response.text();
  let body = null;
  try {
    body = JSON.parse(text);
  } catch {
    body = null;
  }
  if (!response.ok) {
    throw new Error(body?.error || text.slice(0, 500) || response.statusText);
  }
  return body;
}

async function main() {
  const input = buildQueryInput();
  let result = null;
  let source = 'direct';
  let apiError = null;

  if (!options.direct) {
    try {
      result = await queryViaApi(input, options.endpoint);
      source = 'api';
    } catch (error) {
      apiError = error;
    }
  }

  if (!result) {
    result = await queryOaInventory(input);
    if (apiError) result.apiFallbackError = apiError.message;
  }

  const outputPath = outputPathFor(result, options.out);
  ensureDir(path.dirname(outputPath));
  fs.writeFileSync(outputPath, JSON.stringify(result, null, 2), 'utf8');
  console.log(JSON.stringify({
    ok: true,
    source,
    outputPath,
    requiresLogin: result.requiresLogin,
    selectedAttemptKind: result.search?.selectedAttemptKind || null,
    fallbackUsed: result.search?.fallbackUsed || false,
    total: result.search?.total || 0,
    rowCount: result.search?.rowCount || 0,
    fetchedPageCount: result.search?.fetchedPageCount || 0,
    truncated: result.search?.truncated || false
  }, null, 2));
}

main()
  .catch((error) => {
    console.error(JSON.stringify({ ok: false, error: error.message }, null, 2));
    process.exitCode = 1;
  })
  .finally(async () => {
    await edgeSession.close().catch(() => {});
  });
