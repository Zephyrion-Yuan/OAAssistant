#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { Command } from 'commander';
import { queryPdmMaterial } from '../src/automation/pdmAutomation.js';
import { cachedProfileSession } from '../src/browser/cachedProfileSession.js';
import { edgeSession } from '../src/browser/edgeSession.js';
import { ensureDir, runtimeDir } from '../src/config.js';

const program = new Command();

program
  .description('Query PDM master data materials and export organized paged results.')
  .argument('[keyword...]', 'backward-compatible keyword; numeric defaults to exact materialCode, otherwise fuzzy materialName')
  .option('--material-code <code>', 'exact material code query')
  .option('--material-code-like <code>', 'material code fuzzy/prefix query')
  .option('--material-name <name>', 'material name fuzzy query')
  .option('--specification-model <text>', 'specification/model fuzzy query')
  .option('--material-group-code <code>', 'material group code query')
  .option('--material-group-desc <text>', 'material group description fuzzy query')
  .option('--brand <text>', 'brand fuzzy query')
  .option('--material-level <text>', 'material level query')
  .option('--query-type <type>', 'query type for --keyword: code, name, specification, groupCode, groupDesc, brand, level')
  .option('--keyword <text>', 'keyword used with --query-type')
  .option('--max-pages <n>', 'maximum result pages to read from UI pagination', Number, 5)
  .option('--no-exact', 'do not post-filter --material-code to exact equality')
  .option('--url <url>', 'PDM material page URL override')
  .option('--live-session', 'use currently managed Edge session instead of cached PDM profile')
  .option('--out <file>', 'write result JSON to a specific file');

program.parse(process.argv);
const options = program.opts();
const positional = program.args.join(' ').trim();

function firstText(...values) {
  return values.map((value) => String(value || '').trim()).find(Boolean) || '';
}

function outputPathFor(result, explicitPath) {
  if (explicitPath) return path.resolve(explicitPath);
  const filters = result?.query?.filters || {};
  const label = Object.entries(filters)
    .map(([key, value]) => `${key}-${String(value).replace(/[^\w\u4e00-\u9fff.-]+/g, '_').slice(0, 40)}`)
    .join('_') || 'query';
  const outputDir = path.join(runtimeDir, 'pdm-results');
  ensureDir(outputDir);
  return path.join(outputDir, `${new Date().toISOString().replace(/[:.]/g, '-')}-${label}.json`);
}

async function main() {
  const keyword = firstText(options.keyword, positional);
  const input = {
    materialCode: options.materialCode,
    materialCodeLike: options.materialCodeLike,
    materialName: options.materialName,
    specificationModel: options.specificationModel,
    materialGroupCode: options.materialGroupCode,
    materialGroupDesc: options.materialGroupDesc,
    brand: options.brand,
    materialLevel: options.materialLevel,
    queryType: options.queryType,
    keyword,
    maxPages: options.maxPages,
    exact: options.exact,
    url: options.url,
    useLiveSession: options.liveSession
  };

  const result = await queryPdmMaterial(input);
  const outputPath = outputPathFor(result, options.out);
  ensureDir(path.dirname(outputPath));
  fs.writeFileSync(outputPath, JSON.stringify(result, null, 2), 'utf8');
  console.log(JSON.stringify({
    ok: true,
    outputPath,
    requiresLogin: result.requiresLogin,
    filters: result.query?.filters || input,
    total: result.search?.total || 0,
    fetchedPageCount: result.search?.fetchedPageCount || 0,
    rowCount: result.rows?.length || 0,
    truncated: result.search?.truncated || false
  }, null, 2));
}

main()
  .catch((error) => {
    console.error(JSON.stringify({ ok: false, error: error.message }, null, 2));
    process.exitCode = 1;
  })
  .finally(async () => {
    await cachedProfileSession.close().catch(() => {});
    await edgeSession.close().catch(() => {});
  });
