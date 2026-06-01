import fs from 'node:fs';
import path from 'node:path';
import { edgeSession } from '../../browser/edgeSession.js';
import { resolveOaPage, runtimeDir, ensureDir, readJson } from '../../config.js';
import { waitForSettledPage, detectLoginPage } from '../domScanner.js';
import { attachSafeNetworkRecorder } from '../../explorer/safeNetworkRecorder.js';
import { scanPageSurface } from '../../explorer/surfaceScanner.js';
import { redactUrl } from '../../security/redaction.js';

// Server-callable core of OA workflow 89 (stock transfer).
// Excel parsing has been lifted out: this module consumes already-structured
// `input.structured` (the shape produced by scripts/stock_transfer_excel.py or
// the Python orchestrator intake node) instead of a file path. The browser
// lifecycle is owned by the caller (server keeps edgeSession alive; the CLI
// wrapper closes it in finally).

const workflowConfig = readJson('config/oa-workflow-89-stock-transfer.json');
const transferRuntimeDir = path.join(runtimeDir, 'stock-transfer-requests');

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

async function modalRows(modal) {
  const rows = await modal.locator('tbody tr').evaluateAll((trs) => trs.map((tr) => (
    Array.from(tr.cells).map((cell) => cell.innerText.replace(/\s+/g, ' ').trim())
  )));
  return rows
    .filter((row) => row.some(Boolean))
    .filter((row) => !/暂无数据|No Data/.test(row.join(' ')));
}

async function stockLocationOptions(page) {
  const modal = page.locator('.ant-modal:visible, [role="dialog"]:visible').last();
  const rows = await modalRows(modal);
  return rows
    .filter((row) => row.length >= 3)
    .map((row) => ({
      stockLocationName: row[0] || '',
      factory: row[1] || '',
      sapCode: row[2] || ''
    }));
}

function buildTransferRows({ excel, quantityOverrides }) {
  return excel.materialPlans.map((row) => ({
    materialCode: row.materialCode,
    materialName: row.materialName,
    quantity: String(quantityOverrides[row.materialCode] || row.quantity),
    unit: row.unit
  }));
}

async function visibleDetailRowCount(page) {
  const inputs = page.locator(`input[id^="${workflowConfig.selectors.quantityPrefix}"]:visible`);
  return inputs.count();
}

async function ensureSupportedRowCount(page, transferRows) {
  const count = await visibleDetailRowCount(page);
  if (transferRows.length <= count) return count;
  throw new NeedInputError('Workflow 89 currently exposes fewer detail rows than the transfer plan requires.', {
    kind: 'detailRows',
    question: '库存转储页当前只确认了已有明细行填充方式。请减少本次测试物料到单行，或继续探索/固化明细新增行控件后再处理多行。',
    visibleDetailRowCount: count,
    requestedRowCount: transferRows.length,
    transferRows
  });
}

async function selectFactory(page, factoryCode) {
  const expectedFactoryName = workflowConfig.factoryNames[factoryCode];
  await openBrowserField(page, workflowConfig.selectors.factoryButton);
  const modal = page.locator('.ant-modal:visible, [role="dialog"]:visible').last();
  const row = modal.locator('tr', { hasText: factoryCode }).first();
  await row.waitFor({ timeout: 15000 });
  const rowText = await row.innerText().catch(() => '');
  if (expectedFactoryName && !rowText.includes(expectedFactoryName)) {
    throw new Error(`Factory code ${factoryCode} did not match expected factory "${expectedFactoryName}". Row text: ${rowText}`);
  }
  await row.click();
  await modal.waitFor({ state: 'hidden', timeout: 8000 }).catch(() => {});
  await waitForSettledPage(page);
  return { factoryCode, factoryName: expectedFactoryName || rowText.replace(/\s+/g, ' ').trim() };
}

async function selectMaterial(page, rowIndex, materialCode) {
  const selector = `#${workflowConfig.selectors.materialButtonPrefix}${rowIndex}span > div:nth-of-type(2) > button`;
  await openBrowserField(page, selector);
  const modal = page.locator('.ant-modal:visible, [role="dialog"]:visible').last();
  await page.locator(workflowConfig.selectors.materialCodeInput).last().fill(materialCode);
  const data = await clickSearchInModal(page, browserDataMatcher({
    contains: `MATNR=${encodeQueryValue(materialCode)}`
  }));
  if (data && resultCount(data) < 1) {
    throw new NeedInputError(`No material was found for materialCode=${materialCode}.`, {
      kind: 'material',
      question: '物料主数据查询没有返回结果，请确认物料编码或提供可选物料编码。',
      rowIndex,
      materialCode
    });
  }
  const clicked = await clickModalRow(page, modal, materialCode, 5000);
  if (!clicked) {
    throw new Error(`Could not select material row ${materialCode}.`);
  }
  await modal.waitFor({ state: 'hidden', timeout: 8000 }).catch(() => {});
  await waitForSettledPage(page);
  const description = await page.locator(`#${workflowConfig.selectors.materialDescriptionPrefix}${rowIndex}`).inputValue().catch(() => '');
  const unit = await page.locator(`#${workflowConfig.selectors.unitPrefix}${rowIndex}`).inputValue().catch(() => '');
  return { rowIndex, materialCode, description, unit };
}

async function fillQuantity(page, rowIndex, quantity) {
  const input = page.locator(`#${workflowConfig.selectors.quantityPrefix}${rowIndex}`).first();
  await input.waitFor({ timeout: 15000 });
  await input.scrollIntoViewIfNeeded().catch(() => {});
  await input.fill(String(quantity));
  await waitForSettledPage(page);
  return { rowIndex, quantity: String(quantity) };
}

async function inspectStockLocationOptions(page, rowIndex, side) {
  const prefix = side === 'out'
    ? workflowConfig.selectors.transferOutStockLocationButtonPrefix
    : workflowConfig.selectors.transferInStockLocationButtonPrefix;
  const selector = `#${prefix}${rowIndex}span > div:nth-of-type(2) > button`;
  await openBrowserField(page, selector);
  return stockLocationOptions(page);
}

async function selectStockLocation(page, rowIndex, side, { stockLocationName, stockLocationSapCode }) {
  const prefix = side === 'out'
    ? workflowConfig.selectors.transferOutStockLocationButtonPrefix
    : workflowConfig.selectors.transferInStockLocationButtonPrefix;
  const selector = `#${prefix}${rowIndex}span > div:nth-of-type(2) > button`;
  await openBrowserField(page, selector);
  const modal = page.locator('.ant-modal:visible, [role="dialog"]:visible').last();
  const expected = stockLocationSapCode || stockLocationName;
  const clicked = await clickModalRow(page, modal, expected, 5000);
  if (!clicked) {
    const options = await stockLocationOptions(page);
    throw new NeedInputError(`Stock location ${expected || ''} was not found for row ${rowIndex + 1}.`, {
      kind: side === 'out' ? 'transferOutStockLocation' : 'transferInStockLocation',
      question: '库存地点没有匹配到候选项，请提供库存地点名称或 SAP 编码后继续。',
      rowIndex,
      requested: { stockLocationName, stockLocationSapCode },
      options
    });
  }
  await modal.waitFor({ state: 'hidden', timeout: 8000 }).catch(() => {});
  await waitForSettledPage(page);
  return { rowIndex, side, stockLocationName: stockLocationName || '', stockLocationSapCode: stockLocationSapCode || '' };
}

function movementNeedsOutWbs(movementType) {
  return /^项目库存转储/.test(String(movementType || ''));
}

function movementNeedsInWbs(movementType) {
  return /至项目库存$/.test(String(movementType || ''));
}

async function selectWbs(page, rowIndex, side, wbsCode) {
  const prefix = side === 'out'
    ? workflowConfig.selectors.transferOutWbsButtonPrefix
    : workflowConfig.selectors.transferInWbsButtonPrefix;
  const selector = `#${prefix}${rowIndex}span > div:nth-of-type(2) > button`;
  await openBrowserField(page, selector);
  const modal = page.locator('.ant-modal:visible, [role="dialog"]:visible').last();
  await page.locator(workflowConfig.selectors.wbsCodeInput).last().fill(wbsCode);
  const data = await clickSearchInModal(page, browserDataMatcher({
    contains: `POSID=${encodeQueryValue(wbsCode)}`
  }));
  if (data && resultCount(data) < 1) {
    throw new NeedInputError(`No WBS row was found for ${wbsCode}.`, {
      kind: side === 'out' ? 'transferOutWbs' : 'transferInWbs',
      question: 'WBS 查询没有返回候选，请确认 WBS 编码。',
      rowIndex,
      wbsCode
    });
  }
  const clicked = await clickModalRow(page, modal, wbsCode, 5000);
  if (!clicked) throw new Error(`Could not select WBS row ${wbsCode}.`);
  await modal.waitFor({ state: 'hidden', timeout: 8000 }).catch(() => {});
  await waitForSettledPage(page);
  return { rowIndex, side, wbsCode };
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
    ensureDir(transferRuntimeDir);
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
      const failurePath = path.join(transferRuntimeDir, `${stamp}-failure.json`);
      fs.writeFileSync(failurePath, JSON.stringify(base, null, 2), 'utf8');
      return { failurePath };
    }
    const screenshotPath = path.join(transferRuntimeDir, `${stamp}-failure.png`);
    const surfacePath = path.join(transferRuntimeDir, `${stamp}-failure-surface.json`);
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
 * Fill OA workflow 89 (stock transfer) from already-structured input.
 *
 * input = {
 *   structured: { projectDefinition, wbsCode, demandFactoryCode, mrpController,
 *                 materialPlans: [{ materialCode, materialName, quantity, unit }] },
 *   url?, userInfo?/userJson?/userDepartment?,
 *   movementType?, warehouseType?, factoryCode?,
 *   stockLocationName?/stockLocationSapCode?,
 *   transferOutStockLocationName?/transferOutStockLocationSapCode?,
 *   transferInStockLocationName?/transferInStockLocationSapCode?,
 *   wbs?/transferOutWbs?/transferInWbs?,
 *   quantityRule?, quantityOverrides?, loginTimeoutMs?, save: boolean
 * }
 *
 * Throws NeedInputError (missing slot, with payload) or Error (failure); the
 * thrown error carries `.artifact` with screenshot/surface paths. Returns a
 * structured report on success. Never clicks 提交 — at most saves a draft.
 */
export async function runStockTransfer(input = {}) {
  let page = null;
  let recorder = null;
  try {
    const userInfo = loadUserInfo(input);
    const excel = input.structured;
    if (!excel || !Array.isArray(excel.materialPlans)) {
      throw new Error('runStockTransfer requires input.structured with a materialPlans array.');
    }

    const movementType = input.movementType || workflowConfig.movementType;
    const warehouseType = input.warehouseType ?? workflowConfig.warehouseType ?? null;
    const quantityRule = input.quantityRule || workflowConfig.quantityRule;
    const loginTimeoutMs = input.loginTimeoutMs ?? 180000;
    const save = Boolean(input.save);

    const transferRows = buildTransferRows({
      excel,
      quantityOverrides: input.quantityOverrides || {}
    });
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

    results.supportedRows = await step('Check visible detail row count', async () => (
      ensureSupportedRowCount(page, transferRows)
    ));
    results.movementType = await step(`Set 移动类型 ${movementType}`, async () => {
      await selectDropdownOption(page, workflowConfig.selectors.movementTypeCombobox, movementType);
      return movementType;
    });
    results.factory = await step(`Select 工厂 ${input.factoryCode || excel.demandFactoryCode}`, async () => (
      selectFactory(page, input.factoryCode || excel.demandFactoryCode)
    ));
    if (warehouseType) {
      results.warehouseType = await step(`Set 仓库类型 ${warehouseType}`, async () => {
        await selectDropdownOption(page, workflowConfig.selectors.warehouseTypeCombobox, warehouseType);
        return warehouseType;
      });
    }

    const needsOutWbs = movementNeedsOutWbs(movementType);
    const needsInWbs = movementNeedsInWbs(movementType);
    const transferOutWbs = input.transferOutWbs || input.wbs || excel.wbsCode;
    const transferInWbs = input.transferInWbs || input.wbs || excel.wbsCode;
    if (needsOutWbs && !transferOutWbs) {
      throw new NeedInputError('Transfer-out WBS is required for this movement type.', {
        kind: 'transferOutWbs',
        question: '当前移动类型需要转出 WBS，请提供 transferOutWbs 或 wbs。'
      });
    }
    if (needsInWbs && !transferInWbs) {
      throw new NeedInputError('Transfer-in WBS is required for this movement type.', {
        kind: 'transferInWbs',
        question: '当前移动类型需要转入 WBS，请提供 transferInWbs 或 wbs。'
      });
    }

    const transferOutStockLocationName = input.transferOutStockLocationName || input.stockLocationName;
    const transferOutStockLocationSapCode = input.transferOutStockLocationSapCode || input.stockLocationSapCode;
    const transferInStockLocationName = input.transferInStockLocationName || input.stockLocationName;
    const transferInStockLocationSapCode = input.transferInStockLocationSapCode || input.stockLocationSapCode;

    results.rows = [];
    for (const [rowIndex, row] of transferRows.entries()) {
      const rowResult = { rowIndex, materialCode: row.materialCode, quantity: row.quantity };
      rowResult.material = await step(`Select material row ${rowIndex + 1} ${row.materialCode}`, async () => (
        selectMaterial(page, rowIndex, row.materialCode)
      ));
      rowResult.quantity = await step(`Fill quantity row ${rowIndex + 1}`, async () => (
        fillQuantity(page, rowIndex, row.quantity)
      ));

      if (!transferOutStockLocationName && !transferOutStockLocationSapCode) {
        const options = await step(`Inspect transfer-out stock location options row ${rowIndex + 1}`, async () => (
          inspectStockLocationOptions(page, rowIndex, 'out')
        ));
        throw new NeedInputError('Transfer-out stock location is required before filling workflow 89.', {
          kind: 'transferOutStockLocation',
          question: '请提供转出库存地点名称或 SAP 编码，例如 transferOutStockLocationName 设备零件仓 或 transferOutStockLocationSapCode D002。',
          rowIndex,
          transferRows,
          options
        });
      }
      rowResult.transferOutStockLocation = await step(`Select transfer-out stock location row ${rowIndex + 1}`, async () => (
        selectStockLocation(page, rowIndex, 'out', {
          stockLocationName: transferOutStockLocationName,
          stockLocationSapCode: transferOutStockLocationSapCode
        })
      ));

      if (!transferInStockLocationName && !transferInStockLocationSapCode) {
        const options = await step(`Inspect transfer-in stock location options row ${rowIndex + 1}`, async () => (
          inspectStockLocationOptions(page, rowIndex, 'in')
        ));
        throw new NeedInputError('Transfer-in stock location is required before filling workflow 89.', {
          kind: 'transferInStockLocation',
          question: '请提供转入库存地点名称或 SAP 编码，例如 transferInStockLocationName 成品仓 或 transferInStockLocationSapCode A001。',
          rowIndex,
          transferRows,
          options
        });
      }
      rowResult.transferInStockLocation = await step(`Select transfer-in stock location row ${rowIndex + 1}`, async () => (
        selectStockLocation(page, rowIndex, 'in', {
          stockLocationName: transferInStockLocationName,
          stockLocationSapCode: transferInStockLocationSapCode
        })
      ));

      if (needsOutWbs) {
        rowResult.transferOutWbs = await step(`Select transfer-out WBS row ${rowIndex + 1}`, async () => (
          selectWbs(page, rowIndex, 'out', transferOutWbs)
        ));
      }
      if (needsInWbs) {
        rowResult.transferInWbs = await step(`Select transfer-in WBS row ${rowIndex + 1}`, async () => (
          selectWbs(page, rowIndex, 'in', transferInWbs)
        ));
      }
      results.rows.push(rowResult);
    }

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
        movementType,
        warehouseType,
        factoryCode: input.factoryCode || excel.demandFactoryCode,
        stockLocationName: input.stockLocationName,
        stockLocationSapCode: input.stockLocationSapCode,
        transferOutStockLocationName,
        transferOutStockLocationSapCode,
        transferInStockLocationName,
        transferInStockLocationSapCode,
        wbs: input.wbs,
        transferOutWbs,
        transferInWbs,
        quantityRule,
        save
      },
      transferRows,
      results,
      actions,
      finalSurface,
      apiCalls: recorder.calls
    };

    ensureDir(transferRuntimeDir);
    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    const reportPath = path.join(transferRuntimeDir, `${stamp}-oa-stock-transfer-from-excel.json`);
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
        movementType: results.movementType,
        warehouseType: results.warehouseType || null,
        factoryName: results.factory.factoryName,
        transferRowCount: results.rows.length,
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
