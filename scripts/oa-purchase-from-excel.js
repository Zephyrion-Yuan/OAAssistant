#!/usr/bin/env node
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import process from 'node:process';
import { Command } from 'commander';

process.env.MEGANT_EDGE_PROFILE_MODE ||= 'sso-handoff';
process.env.MEGANT_EDGE_PROFILE_NAME ||= 'MEGAntBot';

// Thin CLI wrapper. The fill logic now lives in src/automation/flows/purchase.js
// (server-callable). Excel parsing + attachment normalization stays here for
// backward-compatible CLI use: it shells out to the Python helper (which writes
// the normalized attachment) and passes the structured object to runPurchase.
const { edgeSession } = await import('../src/browser/edgeSession.js');
const { runtimeDir, ensureDir } = await import('../src/config.js');
const { runPurchase, NeedInputError } = await import('../src/automation/flows/purchase.js');

const purchaseRuntimeDir = path.join(runtimeDir, 'purchase-requests');
const attachmentRuntimeDir = path.join(purchaseRuntimeDir, 'attachments');

function runExcelHelper({ file, daysOffset }) {
  ensureDir(attachmentRuntimeDir);
  const python = process.env.PYTHON || 'python';
  const helper = path.join(process.cwd(), 'scripts', 'purchase_excel.py');
  const output = execFileSync(python, [
    helper,
    '--input',
    file,
    '--output-dir',
    attachmentRuntimeDir,
    '--days-offset',
    String(daysOffset)
  ], {
    encoding: 'utf8',
    env: {
      ...process.env,
      PYTHONIOENCODING: 'utf-8'
    }
  });
  const parsed = JSON.parse(output);
  if (!parsed.ok) throw new Error(parsed.error || 'Excel helper failed.');
  return parsed;
}

const program = new Command();
program
  .description('Create an OA workflow 458 purchase request draft from a normalized Excel attachment.')
  .requiredOption('-f, --file <path>', 'purchase request Excel file')
  .option('--url <url>', 'override OA workflow URL')
  .option('--purchase-type <text>', 'purchase type option text', '项目物资采购申请')
  .option('--project-type <text>', 'whether project type option text', '是')
  .option('--days-offset <days>', 'demand date offset from today', Number, 5)
  .option('--login-timeout-ms <ms>', 'wait for manual login if OA opens a login page', Number, 180000)
  .option('--pause-on-error-ms <ms>', 'keep the browser visible for inspection before closing after an error', Number, 120000)
  .option('--no-save', 'fill and upload but do not click 保存');

program.parse(process.argv);
const options = program.opts();

const structured = runExcelHelper({ file: options.file, daysOffset: options.daysOffset });

runPurchase({
  structured,
  url: options.url,
  purchaseType: options.purchaseType,
  projectType: options.projectType,
  loginTimeoutMs: options.loginTimeoutMs,
  save: options.save
})
  .then((result) => {
    console.log(JSON.stringify(result, null, 2));
  })
  .catch(async (error) => {
    const body = {
      ok: false,
      error: error.message,
      needsInput: error instanceof NeedInputError,
      input: error instanceof NeedInputError ? error.payload : undefined,
      artifact: error.artifact || null
    };
    console.error(JSON.stringify(body, null, 2));
    if (!(error instanceof NeedInputError) && options.pauseOnErrorMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, options.pauseOnErrorMs));
    }
    process.exitCode = 1;
  })
  .finally(async () => {
    await edgeSession.close().catch(() => {});
  });
