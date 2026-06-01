#!/usr/bin/env node
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { Command } from 'commander';

process.env.MEGANT_EDGE_PROFILE_MODE ||= 'sso-handoff';
process.env.MEGANT_EDGE_PROFILE_NAME ||= 'MEGAntBot';

// Thin CLI wrapper. The fill logic now lives in src/automation/flows/outbound.js
// (server-callable). Excel parsing stays here for backward-compatible CLI use:
// it shells out to the Python helper and passes the structured object to runOutbound.
const { edgeSession } = await import('../src/browser/edgeSession.js');
const { readJson } = await import('../src/config.js');
const { runOutbound, NeedInputError } = await import('../src/automation/flows/outbound.js');

const workflowConfig = readJson('config/oa-workflow-412-outbound.json');

function loadUserDepartment({ userJson, userDepartment }) {
  if (userJson) {
    const info = JSON.parse(fs.readFileSync(path.resolve(userJson), 'utf8'));
    return userDepartment || info.department || info.departmentName || info.userDepartment || '';
  }
  return userDepartment || '';
}

function runExcelHelper({ file, userDepartment }) {
  const python = process.env.PYTHON || 'python';
  const helper = path.join(process.cwd(), 'scripts', 'outbound_excel.py');
  const output = execFileSync(python, [
    helper,
    '--input',
    file,
    '--user-department',
    userDepartment
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
  .description('Create an OA workflow 412 material outbound draft from a purchase workbook.')
  .requiredOption('-f, --file <path>', 'purchase request Excel file')
  .option('--url <url>', 'override OA workflow URL')
  .option('--user-json <path>', 'JSON file containing user basic info; department/departmentName is used')
  .option('--user-department <text>', 'user department text, e.g. ACRO产品开发部')
  .option('--warehouse-type <text>', 'warehouse type option text', workflowConfig.warehouseType)
  .option('--login-timeout-ms <ms>', 'wait for manual login if OA opens a login page', Number, 180000)
  .option('--pause-on-error-ms <ms>', 'keep the browser visible for inspection before closing after an error', Number, 120000)
  .option('--no-save', 'fill the form but do not click 保存');

program.parse(process.argv);
const options = program.opts();

const userDepartment = loadUserDepartment(options);
if (!userDepartment) {
  console.error(JSON.stringify({ ok: false, error: 'User department is required. Pass --user-department or --user-json with department.' }, null, 2));
  process.exit(1);
}

const structured = runExcelHelper({ file: options.file, userDepartment });

runOutbound({
  structured,
  url: options.url,
  userJson: options.userJson,
  userDepartment,
  warehouseType: options.warehouseType,
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
