import fs from 'node:fs';
import path from 'node:path';
import { edgeSession } from '../../browser/edgeSession.js';
import { resolveOaPage, runtimeDir, ensureDir, readJson } from '../../config.js';
import { waitForSettledPage, detectLoginPage } from '../domScanner.js';
import { attachSafeNetworkRecorder } from '../../explorer/safeNetworkRecorder.js';
import { scanPageSurface } from '../../explorer/surfaceScanner.js';
import { redactUrl } from '../../security/redaction.js';

// Server-callable core of OA workflow 414 (material inbound / 物资入库).
// Excel parsing has been lifted out: this module consumes already-structured
// `input.structured` (the shape produced by scripts/inbound_excel.py or the
// Python orchestrator intake node) instead of a file path. The browser
// lifecycle is owned by the caller (server keeps edgeSession alive; the CLI
// wrapper closes it in finally).

const workflowConfig = readJson('config/oa-workflow-414-inbound.json');
const inboundRuntimeDir = path.join(runtimeDir, 'inbound-requests');

export class NeedInputError extends Error {
  constructor(message, payload = {}) {
    super(message);
    this.name = 'NeedInputError';
    this.payload = payload;
  }
}

function loadUserInfo({ userJson, userDepartment, userInfo } = {}) {
  if (userInfo && typeof userInfo === 'object') {
    return {
      ...userInfo,
      department: userDepartment || userInfo.department || userInfo.departmentName || userInfo.userDepartment || ''
    };
  }
  if (userJson) {
    const info = JSON.parse(fs.readFileSync(path.resolve(userJson), 'utf8'));
    return {
      ...info,
      department: userDepartment || info.department || info.departmentName || info.userDepartment || ''
    };
  }
  return { department: userDepartment || '' };
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function encodeQueryValue(value) {
  return encodeURIComponent(String(value)).replace(/%2E/g, '.');
}

function htmlText(value) {
  return String(value || '')
    .replace(/<[^>]*>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

async function clickExactText(page, text, options = {}) {
  const pattern = new RegExp(`^\\s*${escapeRegExp(text)}\\s*$`);
  const locator = page.getByText(pattern).last();
  await locator.waitFor({ timeout: options.timeoutMs || 15000 });
  await locator.scrollIntoViewIfNeeded().catch(() => {});
  await locator.click();
}

async function selectDropdownOption(page, comboboxSelector, optionText) {
  await page.locator(comboboxSelector).first().waitFor({ timeout: 15000 });
  await page.locator(comboboxSelector).first().click();
  await page.waitForTimeout(300);
  await clickExactText(page, optionText);
  await waitForSettledPage(page);
}

async function openBrowserField(page, buttonSelector) {
  const button = page.locator(buttonSelector).first();
  await button.waitFor({ timeout: 15000 });
  await button.scrollIntoViewIfNeeded();
  await button.click();
  await page.locator('.ant-modal:visible, [role="dialog"]:visible').last().waitFor({ timeout: 15000 });
  await page.waitForTimeout(500);
}

function browserDataMatcher({ contains }) {
  return (response) => (
    response.status() === 200
    && response.url().includes('/api/public/browser/data/')
    && (!contains || response.url().includes(contains))
  );
}

async function clickSearchInModal(page, responseMatcher = null) {
  const modal = page.locator('.ant-modal:visible, [role="dialog"]:visible').last();
  const responsePromise = responseMatcher
    ? page.waitForResponse(responseMatcher, { timeout: 15000 }).catch(() => null)
    : null;

  await modal.getByRole('button', { name: /^\s*搜\s*索\s*$/ }).first().click();

  if (!responsePromise) {
    await waitForSettledPage(page);
    return null;
  }

  const response = await responsePromise;
  if (!response) return null;
  return response.json().catch(() => null);
}

async function clickModalRow(page, modal, expectedText, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const row = modal.locator('tr', { hasText: expectedText }).filter({
      hasNotText: /^\s*(?:No Data|暂无数据)\s*$/
    }).first();
    if (await row.isVisible().catch(() => false)) {
      await row.scrollIntoViewIfNeeded().catch(() => {});
      await row.click();
      return true;
    }
    await page.waitForTimeout(100);
  }
  return false;
}

function resultCount(data) {
  return Number(data?.total ?? data?.count ?? data?.data?.total ?? 0);
}

function voucherOptions(data) {
  const rows = Array.isArray(data?.datas) ? data.datas : [];
  return rows.map((row) => ({
    voucherNumber: String(row.wlpzh || ''),
    projectCode: String(row.yfxm || ''),
    projectName: String(row.xmmc11 || ''),
    outboundType: String(row.sjly || ''),
    purpose: htmlText(row.yt),
    applyDate: String(row.sqrq || ''),
    applicant: htmlText(row.sqrmc),
    id: String(row.id || row.randomFieldId || '')
  })).filter((row) => row.voucherNumber || row.id);
}

async function selectCompany(page, factoryCode) {
  const expectedCompanyName = workflowConfig.factoryCompanyNames[factoryCode];
  await openBrowserField(page, workflowConfig.selectors.companyButton);
  const modal = page.locator('.ant-modal:visible, [role="dialog"]:visible').last();
  const row = modal.locator('tr', { hasText: factoryCode }).first();
  await row.waitFor({ timeout: 15000 });
  const rowText = await row.innerText().catch(() => '');
  if (expectedCompanyName && !rowText.includes(expectedCompanyName)) {
    throw new Error(`Factory code ${factoryCode} did not match expected company "${expectedCompanyName}". Row text: ${rowText}`);
  }
  await row.click();
  await modal.waitFor({ state: 'hidden', timeout: 8000 }).catch(() => {});
  await waitForSettledPage(page);
  return { factoryCode, companyName: expectedCompanyName || rowText.replace(/\s+/g, ' ').trim() };
}

function resolveVoucherSearchValue(input, excel) {
  if (input.projectCode) return input.projectCode;
  if (workflowConfig.voucherProjectCodeSource === 'wbsCode') return excel.wbsCode;
  return excel.projectDefinition;
}

async function selectProjectReturnVoucher(page, { excel, projectCode, voucherNumber }) {
  await openBrowserField(page, workflowConfig.selectors.projectReturnVoucherButton);
  const modal = page.locator('.ant-modal:visible, [role="dialog"]:visible').last();
  if (voucherNumber) {
    await page.locator(workflowConfig.selectors.projectReturnVoucherNumberInput).last().fill(voucherNumber);
  }
  if (projectCode) {
    await page.locator(workflowConfig.selectors.projectReturnProjectCodeInput).last().fill(projectCode);
  }

  const contains = voucherNumber
    ? `con7555_value=${encodeQueryValue(voucherNumber)}`
    : `con7547_value=${encodeQueryValue(projectCode)}`;
  const data = await clickSearchInModal(page, browserDataMatcher({ contains }));
  const options = voucherOptions(data);
  const total = resultCount(data);
  if (total < 1) {
    throw new NeedInputError(`No project return voucher was found for projectCode=${projectCode || ''}, voucherNumber=${voucherNumber || ''}.`, {
      kind: 'voucher',
      question: '没有找到可选的项目退料出库物料凭证，请确认项目编码或直接提供物料凭证号。',
      projectCode,
      voucherNumber,
      options
    });
  }

  let selected = null;
  if (voucherNumber) {
    selected = options.find((row) => row.voucherNumber === String(voucherNumber));
    if (!selected) {
      throw new NeedInputError(`Voucher ${voucherNumber} was not found in the query result.`, {
        kind: 'voucher',
        question: '指定的物料凭证号没有出现在当前查询结果中，请重新提供项目编码或凭证号。',
        projectCode,
        voucherNumber,
        options
      });
    }
  } else if (total === 1 && options.length === 1) {
    selected = options[0];
  } else {
    throw new NeedInputError(`Project code ${projectCode} matched ${total} project return vouchers.`, {
      kind: 'voucher',
      question: `项目编码 ${projectCode} 命中 ${total} 条项目退料出库物料凭证，请选择一个并用 voucherNumber 继续。`,
      projectCode,
      options,
      excelProjectDefinition: excel.projectDefinition,
      excelWbsCode: excel.wbsCode
    });
  }

  const sapResponsePromise = page.waitForResponse((response) => (
    response.status() === 200
    && response.request().method() === 'POST'
    && response.url().includes('/api/workflow/linkage/reqDataInputResult')
  ), { timeout: 15000 }).catch(() => null);
  const clicked = await clickModalRow(page, modal, selected.voucherNumber, 5000);
  if (!clicked) throw new Error(`Could not click voucher row ${selected.voucherNumber}.`);
  await modal.waitFor({ state: 'hidden', timeout: 8000 }).catch(() => {});
  const linkageResponse = await sapResponsePromise;
  const linkageData = linkageResponse ? await linkageResponse.json().catch(() => null) : null;
  await waitForSettledPage(page);
  return {
    ...selected,
    browserResultCount: total,
    linkageKeys: linkageData && typeof linkageData === 'object' ? Object.keys(linkageData) : []
  };
}

async function tableRows(page, selector) {
  return page.locator(selector).evaluate((table) => Array.from(table.querySelectorAll('tr')).map((tr) => (
    Array.from(tr.cells).map((cell) => cell.innerText.replace(/\s+/g, ' ').trim())
  )));
}

function columnIndex(headers, label) {
  return headers.findIndex((header) => header === label);
}

async function getProjectReturnMaterialRows(page) {
  await page.locator(workflowConfig.selectors.materialTable).waitFor({ timeout: 15000 });
  const rows = await tableRows(page, workflowConfig.selectors.materialTable);
  const headerIndex = rows.findIndex((row) => row.includes('物料编码') && row.includes('申请入库(退料)数量'));
  if (headerIndex < 0) throw new Error('Could not find the project return material table header.');
  const headers = rows[headerIndex];
  const indexes = {
    materialCode: columnIndex(headers, '物料编码'),
    materialDescription: columnIndex(headers, '物料描述'),
    applyQuantity: columnIndex(headers, '申请入库(退料)数量'),
    outboundQuantity: columnIndex(headers, '出库数量'),
    unit: columnIndex(headers, '单位'),
    factory: columnIndex(headers, '工厂'),
    stockLocation: columnIndex(headers, '库存地点'),
    wbsCode: columnIndex(headers, 'WBS编号'),
    reservationItem: columnIndex(headers, '预留行号')
  };
  if (indexes.materialCode < 0) throw new Error('Material table is missing 物料编码 column.');

  const materialRows = [];
  for (const row of rows.slice(headerIndex + 1)) {
    const materialCode = row[indexes.materialCode] || '';
    if (!materialCode) continue;
    materialRows.push({
      rowIndex: materialRows.length,
      materialCode,
      materialDescription: row[indexes.materialDescription] || '',
      outboundQuantity: row[indexes.outboundQuantity] || '',
      unit: row[indexes.unit] || '',
      factory: row[indexes.factory] || '',
      stockLocation: row[indexes.stockLocation] || '',
      wbsCode: row[indexes.wbsCode] || '',
      reservationItem: row[indexes.reservationItem] || ''
    });
  }
  if (!materialRows.length) throw new Error('No project return material rows were generated after selecting the voucher.');
  return materialRows;
}

async function stockLocationOptions(page) {
  const modal = page.locator('.ant-modal:visible, [role="dialog"]:visible').last();
  const rows = await modal.locator('tbody tr').evaluateAll((trs) => trs.map((tr) => (
    Array.from(tr.cells).map((cell) => cell.innerText.replace(/\s+/g, ' ').trim())
  )));
  return rows
    .filter((row) => row.length >= 3 && row.some(Boolean))
    .filter((row) => !/暂无数据|No Data/.test(row.join(' ')))
    .map((row) => ({
      stockLocationName: row[0] || '',
      factory: row[1] || '',
      sapCode: row[2] || ''
    }));
}

async function inspectStockLocationOptions(page, rowIndex) {
  const selector = `#${workflowConfig.selectors.materialStockLocationButtonPrefix}${rowIndex}span > div:nth-of-type(2) > button`;
  await openBrowserField(page, selector);
  const options = await stockLocationOptions(page);
  return options;
}

async function selectStockLocation(page, rowIndex, { stockLocationName, stockLocationSapCode }) {
  const selector = `#${workflowConfig.selectors.materialStockLocationButtonPrefix}${rowIndex}span > div:nth-of-type(2) > button`;
  await openBrowserField(page, selector);
  const modal = page.locator('.ant-modal:visible, [role="dialog"]:visible').last();
  const expected = stockLocationSapCode || stockLocationName;
  const clicked = await clickModalRow(page, modal, expected, 5000);
  if (!clicked) {
    const options = await stockLocationOptions(page);
    throw new NeedInputError(`Stock location ${expected || ''} was not found for material row ${rowIndex + 1}.`, {
      kind: 'stockLocation',
      question: '库存地点没有匹配到候选项，请提供库存地点名称或 SAP 编码后继续。',
      rowIndex,
      requested: { stockLocationName, stockLocationSapCode },
      options
    });
  }
  await modal.waitFor({ state: 'hidden', timeout: 8000 }).catch(() => {});
  await waitForSettledPage(page);
  return { rowIndex, stockLocationName: stockLocationName || '', stockLocationSapCode: stockLocationSapCode || '' };
}

function buildQuantityPlan({ materialRows, excel, quantityOverrides }) {
  const counts = new Map();
  for (const row of materialRows) {
    counts.set(row.materialCode, (counts.get(row.materialCode) || 0) + 1);
  }

  const missing = [];
  const duplicate = [];
  const plan = [];
  for (const row of materialRows) {
    const override = quantityOverrides[row.materialCode];
    const quantity = override || excel.quantityByMaterialCode[row.materialCode];
    if (!quantity) {
      missing.push(row);
      continue;
    }
    if ((counts.get(row.materialCode) || 0) > 1 && !override) {
      duplicate.push(row);
      continue;
    }
    plan.push({
      rowIndex: row.rowIndex,
      materialCode: row.materialCode,
      quantity: String(quantity)
    });
  }

  if (missing.length || duplicate.length) {
    throw new NeedInputError('Material quantity mapping requires user input.', {
      kind: 'quantity',
      question: '部分 OA 明细物料无法从采购表唯一确定申请入库数量，请提供物料编码到数量的 JSON 映射。',
      missingMaterials: missing,
      duplicateMaterials: duplicate,
      availableExcelQuantities: excel.quantityByMaterialCode,
      quantityOverridesExample: Object.fromEntries(
        [...missing, ...duplicate].map((row) => [row.materialCode, row.outboundQuantity || ''])
      )
    });
  }
  return plan;
}

async function fillMaterialQuantities(page, quantityPlan) {
  const filled = [];
  for (const item of quantityPlan) {
    const input = page.locator(`#${workflowConfig.selectors.materialApplyQuantityPrefix}${item.rowIndex}`).first();
    await input.waitFor({ timeout: 15000 });
    await input.scrollIntoViewIfNeeded().catch(() => {});
    await input.fill(item.quantity);
    filled.push(item);
  }
  await waitForSettledPage(page);
  return filled;
}

async function clickSave(page) {
  const saveResponsePromise = page.waitForResponse((response) => (
    response.status() === 200
    && response.request().method() === 'POST'
    && response.url().includes('/api/workflow/reqform/requestOperation')
  ), { timeout: 30000 }).catch(() => null);
  const saveButton = page.locator(workflowConfig.selectors.saveButton).first();
  await saveButton.waitFor({ timeout: 15000 });
  await saveButton.scrollIntoViewIfNeeded();
  await saveButton.click();
  const response = await saveResponsePromise;
  const body = response ? await response.json().catch(() => null) : null;
  await waitForSettledPage(page);
  await page.waitForTimeout(3000);
  const requestId = body?.data?.resultInfo?.requestid
    || body?.data?.submitParams?.requestid
    || new URL(page.url()).searchParams.get('requestid')
    || page.url().match(/[?&]requestid=(\d+)/)?.[1]
    || null;
  return {
    responseType: body?.data?.type || null,
    requestId: requestId ? String(requestId) : null,
    response: body
  };
}

function stableRequestUrl(requestId) {
  if (!requestId) return null;
  return `https://oa.megarobo.info/spa/workflow/static4form/index.html#/main/workflow/req?requestid=${encodeURIComponent(requestId)}`;
}

async function waitForLoginRecovery(page, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    await waitForSettledPage(page).catch(() => {});
    const login = await detectLoginPage(page);
    if (!login.requiresLogin) return false;
    await page.waitForTimeout(2000);
  }
  return true;
}

async function writeFailureArtifact(page, recorder, error) {
  try {
    ensureDir(inboundRuntimeDir);
    const targetPage = page && !page.isClosed()
      ? page
      : edgeSession.context?.pages?.().find((item) => !item.isClosed() && item.url() !== 'about:blank');
    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    const base = {
      ok: false,
      capturedAt: new Date().toISOString(),
      error: error.message,
      needsInput: error instanceof NeedInputError,
      input: error instanceof NeedInputError ? error.payload : null,
      apiCalls: recorder?.calls || []
    };
    if (!targetPage) {
      const failurePath = path.join(inboundRuntimeDir, `${stamp}-failure.json`);
      fs.writeFileSync(failurePath, JSON.stringify(base, null, 2), 'utf8');
      return { failurePath };
    }
    const screenshotPath = path.join(inboundRuntimeDir, `${stamp}-failure.png`);
    const surfacePath = path.join(inboundRuntimeDir, `${stamp}-failure-surface.json`);
    await targetPage.screenshot({ path: screenshotPath, fullPage: true }).catch(() => {});
    const surface = await scanPageSurface(targetPage).catch(() => null);
    fs.writeFileSync(surfacePath, JSON.stringify({
      ...base,
      url: redactUrl(targetPage.url()),
      surface
    }, null, 2), 'utf8');
    return { screenshotPath, surfacePath };
  } catch {
    return null;
  }
}

/**
 * Fill OA workflow 414 (material inbound / 物资入库) from already-structured input.
 *
 * input = {
 *   structured: { projectDefinition, wbsCode, demandFactoryCode, mrpController,
 *                 materialRows: [...], quantityByMaterialCode: {code: qty} },
 *   url?, userInfo?/userJson?/userDepartment?,
 *   inboundType?, warehouseType?, voucherSearchBy?, projectCode?, voucherNumber?,
 *   stockLocationName?/stockLocationSapCode?,
 *   quantityRule?, quantityOverrides?, loginTimeoutMs?, save: boolean
 * }
 *
 * Throws NeedInputError (missing slot, with payload) or Error (failure); the
 * thrown error carries `.artifact` with screenshot/surface paths. Returns a
 * structured report on success. Never clicks 提交 — at most saves a draft.
 */
export async function runInbound(input = {}) {
  let page = null;
  let recorder = null;
  try {
    const userInfo = loadUserInfo(input);
    const excel = input.structured;
    if (!excel || !excel.quantityByMaterialCode) {
      throw new Error('runInbound requires input.structured with a quantityByMaterialCode map.');
    }

    const inboundType = input.inboundType || workflowConfig.inboundType;
    const warehouseType = input.warehouseType ?? workflowConfig.warehouseType ?? null;
    const quantityRule = input.quantityRule || workflowConfig.quantityRule;
    const quantityOverrides = input.quantityOverrides || {};
    const loginTimeoutMs = input.loginTimeoutMs ?? 180000;
    const save = Boolean(input.save);

    const pageConfig = resolveOaPage({ pageId: workflowConfig.pageId, url: input.url });
    page = await edgeSession.newPage();
    recorder = attachSafeNetworkRecorder(page);
    const actions = [];
    const results = {};

    await page.goto(pageConfig.url, { waitUntil: 'domcontentloaded' });
    await waitForSettledPage(page);
    let login = await detectLoginPage(page);
    if (login.requiresLogin && loginTimeoutMs > 0) {
      const stillRequiresLogin = await waitForLoginRecovery(page, loginTimeoutMs);
      login = await detectLoginPage(page);
      if (stillRequiresLogin || login.requiresLogin) {
        throw new Error('OA page still requires login after waiting for manual login.');
      }
    } else if (login.requiresLogin) {
      throw new Error('OA page requires login. Complete manual login in the managed Edge profile first.');
    }

    async function step(name, fn) {
      recorder.setPhase(name);
      const startedCount = recorder.count();
      const startedAt = new Date().toISOString();
      try {
        const value = await fn();
        actions.push({
          name,
          ok: true,
          startedAt,
          finishedAt: new Date().toISOString(),
          newApiCallCount: recorder.count() - startedCount
        });
        return value;
      } catch (error) {
        actions.push({
          name,
          ok: false,
          error: error.message,
          startedAt,
          finishedAt: new Date().toISOString(),
          newApiCallCount: recorder.count() - startedCount
        });
        throw error;
      }
    }

    results.company = await step(`Select 所属记账主体 ${excel.demandFactoryCode}`, async () => (
      selectCompany(page, excel.demandFactoryCode)
    ));

    if (warehouseType) {
      results.warehouseType = await step(`Set 仓库类型 ${warehouseType}`, async () => {
        await selectDropdownOption(page, workflowConfig.selectors.warehouseTypeCombobox, warehouseType);
        return warehouseType;
      });
    }

    results.inboundType = await step(`Set 入库类型 ${inboundType}`, async () => {
      await selectDropdownOption(page, workflowConfig.selectors.inboundTypeCombobox, inboundType);
      return inboundType;
    });

    if (inboundType !== '项目退料') {
      throw new NeedInputError(`Inbound type ${inboundType} is not implemented for automatic filling yet.`, {
        kind: 'inboundType',
        question: '当前脚本已实现项目退料自动填单。其他入库类型需要继续探索选择规则后再固化。',
        inboundType,
        supportedInboundTypes: ['项目退料']
      });
    }

    const projectCode = resolveVoucherSearchValue(input, excel);
    results.voucher = await step(`Select project return voucher by projectCode=${projectCode}`, async () => (
      selectProjectReturnVoucher(page, {
        excel,
        projectCode,
        voucherNumber: input.voucherNumber
      })
    ));

    results.materialRows = await step('Read generated material rows', async () => (
      getProjectReturnMaterialRows(page)
    ));

    if (!input.stockLocationName && !input.stockLocationSapCode) {
      const options = await step('Inspect stock location options', async () => (
        inspectStockLocationOptions(page, 0)
      ));
      throw new NeedInputError('Stock location is required before saving workflow 414.', {
        kind: 'stockLocation',
        question: '请提供库存地点名称或 SAP 编码，例如 stockLocationName 设备零件仓 或 stockLocationSapCode D002。',
        materialRows: results.materialRows,
        options
      });
    }

    results.stockLocations = [];
    for (const row of results.materialRows) {
      results.stockLocations.push(await step(`Select 库存地点 row ${row.rowIndex + 1}`, async () => (
        selectStockLocation(page, row.rowIndex, input)
      )));
    }

    const quantityPlan = buildQuantityPlan({
      materialRows: results.materialRows,
      excel,
      quantityOverrides
    });
    results.materialQuantities = await step('Fill material quantities from purchase workbook', async () => (
      fillMaterialQuantities(page, quantityPlan)
    ));

    if (save) {
      results.save = await step('Click 保存', async () => clickSave(page));
    }

    recorder.setPhase('post-run-scan');
    const finalSurface = await scanPageSurface(page);
    const requestId = results.save?.requestId || null;
    const requestUrl = stableRequestUrl(requestId);
    const report = {
      ok: true,
      ranAt: new Date().toISOString(),
      page: {
        id: pageConfig.id,
        url: redactUrl(pageConfig.url),
        finalUrl: redactUrl(page.url()),
        requestId,
        requestUrl
      },
      userInfo,
      excel,
      parameters: {
        inboundType,
        warehouseType,
        voucherSearchBy: input.voucherSearchBy,
        projectCode,
        voucherNumber: input.voucherNumber,
        quantityRule,
        stockLocationName: input.stockLocationName,
        stockLocationSapCode: input.stockLocationSapCode,
        save
      },
      results,
      actions,
      finalSurface,
      apiCalls: recorder.calls
    };

    ensureDir(inboundRuntimeDir);
    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    const reportPath = path.join(inboundRuntimeDir, `${stamp}-oa-inbound-from-excel.json`);
    fs.writeFileSync(reportPath, JSON.stringify(report, null, 2), 'utf8');
    return {
      ok: true,
      reportPath,
      requestId,
      requestUrl,
      summary: {
        projectDefinition: excel.projectDefinition,
        wbsCode: excel.wbsCode,
        demandFactoryCode: excel.demandFactoryCode,
        inboundType: results.inboundType,
        companyName: results.company.companyName,
        voucherNumber: results.voucher.voucherNumber,
        projectCode,
        materialRowCount: results.materialQuantities.length,
        saved: save,
        actionCount: actions.length
      },
      actions
    };
  } catch (error) {
    error.artifact = await writeFailureArtifact(page, recorder, error).catch(() => null);
    throw error;
  }
}
