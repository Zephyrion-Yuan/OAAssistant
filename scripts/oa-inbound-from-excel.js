#!/usr/bin/env node
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { Command } from 'commander';

process.env.MEGANT_EDGE_PROFILE_MODE ||= 'sso-handoff';
process.env.MEGANT_EDGE_PROFILE_NAME ||= 'MEGAntBot';

// Thin CLI wrapper. The fill logic now lives in src/automation/flows/inbound.js
// (server-callable). Excel parsing stays here for backward-compatible CLI use:
// it shells out to the Python helper and passes the structured object to runInbound.
const { edgeSession } = await import('../src/browser/edgeSession.js');
const { readJson } = await import('../src/config.js');
const { runInbound, NeedInputError } = await import('../src/automation/flows/inbound.js');

const workflowConfig = readJson('config/oa-workflow-414-inbound.json');

function runExcelHelper({ file }) {
  const python = process.env.PYTHON || 'python';
  const helper = path.join(process.cwd(), 'scripts', 'inbound_excel.py');
  const output = execFileSync(python, [
    helper,
    '--input',
    file
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

function parseJsonOption(value, optionName) {
  if (!value) return {};
  const raw = fs.existsSync(path.resolve(value))
    ? fs.readFileSync(path.resolve(value), 'utf8')
    : value;
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error('expected a JSON object');
    }
    return parsed;
  } catch (error) {
    throw new Error(`${optionName} must be a JSON object or a path to a JSON file: ${error.message}`);
  }
}

const program = new Command();
program
  .description('Create an OA workflow 414 material inbound draft from a purchase workbook.')
  .requiredOption('-f, --file <path>', 'purchase request Excel file')
  .option('--url <url>', 'override OA workflow URL')
  .option('--user-json <path>', 'JSON file containing user basic info')
  .option('--user-department <text>', 'user department text for reporting')
  .option('--inbound-type <text>', 'inbound type option text', workflowConfig.inboundType)
  .option('--warehouse-type <text>', 'warehouse type option text; omit to keep page default', workflowConfig.warehouseType || undefined)
  .option('--voucher-search-by <text>', 'voucher search strategy', workflowConfig.voucherSearchBy)
  .option('--project-code <text>', 'project code to search project-return outbound voucher; default comes from Excel project definition')
  .option('--voucher-number <text>', 'specific outbound material voucher number when project code matches multiple rows')
  .option('--stock-location-name <text>', 'stock location display name, e.g. 设备零件仓')
  .option('--stock-location-sap <text>', 'stock location SAP code, e.g. D002')
  .option('--quantity-rule <text>', 'quantity rule', workflowConfig.quantityRule)
  .option('--quantity-overrides <jsonOrPath>', 'JSON object mapping materialCode to quantity when Excel cannot map uniquely')
  .option('--login-timeout-ms <ms>', 'wait for manual login if OA opens a login page', Number, 180000)
  .option('--pause-on-error-ms <ms>', 'keep the browser visible for inspection before closing after an error', Number, 120000)
  .option('--no-save', 'fill the form but do not click 保存');

program.parse(process.argv);
const options = program.opts();

const structured = runExcelHelper({ file: options.file });

runInbound({
  structured,
  url: options.url,
  userJson: options.userJson,
  userDepartment: options.userDepartment,
  inboundType: options.inboundType,
  warehouseType: options.warehouseType || null,
  voucherSearchBy: options.voucherSearchBy,
  projectCode: options.projectCode,
  voucherNumber: options.voucherNumber,
  stockLocationName: options.stockLocationName,
  stockLocationSapCode: options.stockLocationSap,
  quantityRule: options.quantityRule,
  quantityOverrides: parseJsonOption(options.quantityOverrides, '--quantity-overrides'),
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
