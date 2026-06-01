#!/usr/bin/env node
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { Command } from 'commander';

process.env.MEGANT_EDGE_PROFILE_MODE ||= 'sso-handoff';
process.env.MEGANT_EDGE_PROFILE_NAME ||= 'MEGAntBot';

// Thin CLI wrapper. The fill logic now lives in src/automation/flows/stockTransfer.js
// (server-callable). Excel parsing stays here for backward-compatible CLI use:
// it shells out to the Python helper and passes the structured object to runStockTransfer.
const { edgeSession } = await import('../src/browser/edgeSession.js');
const { readJson } = await import('../src/config.js');
const { runStockTransfer, NeedInputError } = await import('../src/automation/flows/stockTransfer.js');

const workflowConfig = readJson('config/oa-workflow-89-stock-transfer.json');

function runExcelHelper({ file }) {
  const python = process.env.PYTHON || 'python';
  const helper = path.join(process.cwd(), 'scripts', 'stock_transfer_excel.py');
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
  .description('Create an OA workflow 89 stock transfer draft from a purchase workbook.')
  .requiredOption('-f, --file <path>', 'purchase request Excel file')
  .option('--url <url>', 'override OA workflow URL')
  .option('--user-json <path>', 'JSON file containing user basic info')
  .option('--user-department <text>', 'user department text for reporting')
  .option('--movement-type <text>', 'movement type option text', workflowConfig.movementType)
  .option('--warehouse-type <text>', 'warehouse type option text; omit to keep page default', workflowConfig.warehouseType || undefined)
  .option('--factory-code <text>', 'factory SAP code override; default comes from Excel demand factory code')
  .option('--stock-location-name <text>', 'same stock location display name for transfer-out and transfer-in')
  .option('--stock-location-sap <text>', 'same stock location SAP code for transfer-out and transfer-in')
  .option('--transfer-out-stock-location-name <text>', 'transfer-out stock location display name')
  .option('--transfer-out-stock-location-sap <text>', 'transfer-out stock location SAP code, e.g. D002')
  .option('--transfer-in-stock-location-name <text>', 'transfer-in stock location display name')
  .option('--transfer-in-stock-location-sap <text>', 'transfer-in stock location SAP code, e.g. A001')
  .option('--wbs <text>', 'same WBS code for required transfer-out/transfer-in project stock fields')
  .option('--transfer-out-wbs <text>', 'transfer-out WBS code when source is project stock')
  .option('--transfer-in-wbs <text>', 'transfer-in WBS code when destination is project stock')
  .option('--quantity-rule <text>', 'quantity rule', workflowConfig.quantityRule)
  .option('--quantity-overrides <jsonOrPath>', 'JSON object mapping materialCode to quantity')
  .option('--login-timeout-ms <ms>', 'wait for manual login if OA opens a login page', Number, 180000)
  .option('--pause-on-error-ms <ms>', 'keep the browser visible for inspection before closing after an error', Number, 120000)
  .option('--save', 'click 保存 after filling; never clicks 提交');

program.parse(process.argv);
const options = program.opts();

const structured = runExcelHelper({ file: options.file });

runStockTransfer({
  structured,
  url: options.url,
  userJson: options.userJson,
  userDepartment: options.userDepartment,
  movementType: options.movementType,
  warehouseType: options.warehouseType || null,
  factoryCode: options.factoryCode,
  stockLocationName: options.stockLocationName,
  stockLocationSapCode: options.stockLocationSap,
  transferOutStockLocationName: options.transferOutStockLocationName,
  transferOutStockLocationSapCode: options.transferOutStockLocationSap,
  transferInStockLocationName: options.transferInStockLocationName,
  transferInStockLocationSapCode: options.transferInStockLocationSap,
  wbs: options.wbs,
  transferOutWbs: options.transferOutWbs,
  transferInWbs: options.transferInWbs,
  quantityRule: options.quantityRule,
  quantityOverrides: parseJsonOption(options.quantityOverrides, '--quantity-overrides'),
  loginTimeoutMs: options.loginTimeoutMs,
  save: Boolean(options.save || workflowConfig.save)
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
