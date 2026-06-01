#!/usr/bin/env node
import fs from 'node:fs';
import { Command } from 'commander';
import { explorePage } from '../src/explorer/pageExplorer.js';
import { edgeSession } from '../src/browser/edgeSession.js';

function readInputFile(filePath) {
  if (!filePath) return {};
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

const program = new Command();
program
  .description('Explore a whitelisted post-login business page with Playwright Edge.')
  .option('-i, --input <file>', 'JSON request file')
  .option('-u, --url <url>', 'target business URL')
  .option('-n, --name <name>', 'human-readable page name')
  .option('--page-id <pageId>', 'stable page identifier')
  .option('--no-artifact', 'do not write .runtime exploration artifacts')
  .option('--no-manual-login', 'do not wait for manual login redirect recovery')
  .option('--login-timeout-ms <ms>', 'manual login wait timeout', Number)
  .option('--full', 'print full safe report instead of summary only');

program.parse(process.argv);
const options = program.opts();

async function main() {
  const fileInput = readInputFile(options.input);
  const request = {
    ...fileInput,
    url: options.url || fileInput.url,
    name: options.name || fileInput.name,
    pageId: options.pageId || fileInput.pageId,
    saveArtifact: options.artifact,
    allowManualLogin: options.manualLogin,
    loginTimeoutMs: options.loginTimeoutMs || fileInput.loginTimeoutMs
  };
  const result = await explorePage(request);
  const output = options.full
    ? result
    : {
        ok: result.ok,
        summary: result.summary,
        artifacts: result.artifacts
      };
  console.log(JSON.stringify(output, null, 2));
}

main()
  .catch((error) => {
    console.error(JSON.stringify({ ok: false, error: error.message }, null, 2));
    process.exitCode = 1;
  })
  .finally(async () => {
    await edgeSession.close().catch(() => {});
  });
