import fs from 'node:fs';
import path from 'node:path';
import { edgeSession } from '../../browser/edgeSession.js';
import { resolveOaPage, runtimeDir, ensureDir, readJson } from '../../config.js';
import { waitForSettledPage, detectLoginPage } from '../domScanner.js';
import { attachSafeNetworkRecorder } from '../../explorer/safeNetworkRecorder.js';
import { scanPageSurface } from '../../explorer/surfaceScanner.js';
import { redactUrl } from '../../security/redaction.js';

// Server-callable core of OA workflow 412 (material outbound / 物资出库).
// Excel parsing has been lifted out: this module consumes already-structured
// `input.structured` (the shape produced by scripts/outbound_excel.py or the
// Python orchestrator intake node) instead of a file path. The browser
// lifecycle is owned by the caller (server keeps edgeSession alive; the CLI
// wrapper closes it in finally).

const workflowConfig = readJson('config/oa-workflow-412-outbound.json');
const outboundRuntimeDir = path.join(runtimeDir, 'outbound-requests');
const activeOutboundRuntimes = new Map();

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

function normalizeText(value) {
  return String(value ?? '').trim();
}

function projectCodeFromWbs(wbsCode) {
  const code = normalizeText(wbsCode);
  return code ? code.split('.')[0] : '';
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
      const clicked = await row.click({ timeout: 1200 }).then(() => true).catch(() => false);
      if (clicked) return true;
    }
    await page.waitForTimeout(100);
  }
  return false;
}

async function clickFirstModalDataRow(page, modal) {
  const rows = modal.locator('.ant-table-tbody tr, tbody tr').filter({
    hasNotText: /^\s*(?:No Data|暂无数据)\s*$/
  });
  const firstRow = rows.first();
  if (await firstRow.isVisible().catch(() => false)) {
    return firstRow.click({ timeout: 1200 }).then(() => true).catch(() => false);
  }
  return false;
}

function resultCount(data) {
  return Number(data?.total ?? data?.count ?? data?.data?.total ?? 0);
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

async function selectCostCenter(page, costCenter) {
  await openBrowserField(page, workflowConfig.selectors.costCenterButton);
  const modal = page.locator('.ant-modal:visible, [role="dialog"]:visible').last();
  await page.locator(workflowConfig.selectors.costCenterNameInput).last().fill(costCenter.searchName);
  const data = await clickSearchInModal(page, browserDataMatcher({
    contains: `con7457_value=${encodeQueryValue(costCenter.searchName)}`
  }));
  if (data && resultCount(data) < 1) {
    throw new NeedInputError(`Cost center query returned no rows for ${costCenter.searchName}.`, {
      kind: 'costCenter',
      question: '成本中心查询没有返回候选，请确认成本中心名称或编码。',
      costCenter
    });
  }
  const row = modal.locator('tr', { hasText: costCenter.costCenterCode }).first();
  await row.waitFor({ timeout: 15000 });
  const rowText = await row.innerText().catch(() => '');
  if (!rowText.includes(costCenter.searchName)) {
    throw new Error(`Cost center ${costCenter.costCenterCode} did not match "${costCenter.searchName}". Row text: ${rowText}`);
  }
  await row.click();
  await modal.waitFor({ state: 'hidden', timeout: 8000 }).catch(() => {});
  await waitForSettledPage(page);
  return { code: costCenter.costCenterCode, name: costCenter.searchName };
}

function resolveProjectCode(excel) {
  return normalizeText(excel.projectDefinition) || projectCodeFromWbs(excel.wbsCode);
}

async function fillFirstVisibleModalInput(modal, value) {
  const inputs = modal.locator('input:visible');
  const count = await inputs.count();
  for (let index = 0; index < count; index += 1) {
    const input = inputs.nth(index);
    if (await input.isEnabled().catch(() => false)) {
      await input.fill(value);
      return index;
    }
  }
  throw new NeedInputError('Project code browser did not expose an editable search input.', {
    kind: 'projectCode',
    question: '项目编码浏览框没有出现可编辑搜索框。请在 OA 页面手动核对项目编码浏览框，处理后回复“已处理”，或回复新的 WBS 编码。',
    projectCode: value
  });
}

async function clickProjectSearchInModal(page, modal, projectCode) {
  const responsePromise = page.waitForResponse((response) => (
    response.status() === 200
    && response.url().includes('/api/public/browser/data/')
    && response.url().includes('type=browser.ProjectDate')
    && response.url().includes(encodeQueryValue(projectCode))
  ), { timeout: 15000 }).catch(() => null);

  const buttons = modal.locator('button:visible');
  const count = await buttons.count();
  for (let index = 0; index < count; index += 1) {
    const button = buttons.nth(index);
    const text = (await button.innerText().catch(() => '')).replace(/\s+/g, '');
    if (/(高级搜索|清除|取消)/.test(text)) continue;
    if (!(await button.isEnabled().catch(() => false))) continue;
    await button.click();
    const response = await responsePromise;
    if (response) return response.json().catch(() => null);
    await waitForSettledPage(page);
    return null;
  }
  throw new NeedInputError('Project code browser did not expose a search icon button.', {
    kind: 'projectCode',
    question: '项目编码浏览框没有出现可点击的搜索按钮。请在 OA 页面手动核对项目编码浏览框，处理后回复“已处理”，或回复新的 WBS 编码。',
    projectCode
  });
}

async function waitForBrowserSpanValue(page, spanSelector, expected, label) {
  const matched = await page.waitForFunction(({ selector, value }) => {
    const text = document.querySelector(selector)?.innerText || '';
    return text.includes(value);
  }, { selector: spanSelector, value: expected }, { timeout: 15000 }).then(() => true).catch(() => false);
  if (!matched) {
    const currentText = await page.locator(spanSelector).first().innerText().catch(() => '');
    throw new NeedInputError(`${label} did not autofill ${expected}.`, {
      kind: 'projectCode',
      question: `${label}选择后没有回填 ${expected}。请确认该项目编码是否有效；可回复新的 WBS 编码重新推导，也可在 OA 页面手动处理后回复“已处理”。`,
      projectCode: expected,
      currentText
    });
  }
}

async function selectProjectCode(page, excel) {
  const projectCode = resolveProjectCode(excel);
  if (!projectCode) {
    throw new NeedInputError('Project code is required for workflow 412.', {
      kind: 'projectCode',
      question: '出库流程需要项目编码。请在 WBS 配置中维护项目定义，或确认 WBS 编码可推导项目编码。',
      wbsCode: excel.wbsCode
    });
  }

  await openBrowserField(page, workflowConfig.selectors.projectCodeButton);
  const modal = page.locator('.ant-modal:visible, [role="dialog"]:visible').last();
  const inputIndex = await fillFirstVisibleModalInput(modal, projectCode);
  const data = await clickProjectSearchInModal(page, modal, projectCode);
  if (data && resultCount(data) < 1) {
    throw new NeedInputError(`Project code query returned no rows for ${projectCode}.`, {
      kind: 'projectCode',
      question: '项目编码查询没有返回候选，请确认 WBS 对应的项目编码。',
      projectCode,
      wbsCode: excel.wbsCode
    });
  }
  let clicked = await clickModalRow(page, modal, projectCode, 5000);
  if (!clicked) clicked = await clickFirstModalDataRow(page, modal);
  if (!clicked) {
    throw new NeedInputError(`Could not select project code row for ${projectCode}.`, {
      kind: 'projectCode',
      question: `项目编码 ${projectCode} 查询后没有可选择行。请确认 WBS/项目编码是否正确；可回复新的 WBS 编码重新推导，也可在 OA 页面手动处理后回复“已处理”。`,
      projectCode,
      wbsCode: excel.wbsCode
    });
  }
  await modal.waitFor({ state: 'hidden', timeout: 8000 }).catch(() => {});
  await waitForSettledPage(page);
  await waitForBrowserSpanValue(page, '#field7186span', projectCode, '项目编码');
  return { projectCode, browserResultCount: resultCount(data), inputIndex };
}

function resolvePurpose(wbsCode) {
  const match = workflowConfig.purposeByWbsPrefix.find((item) => (
    String(wbsCode || '').toUpperCase().startsWith(String(item.prefix || '').toUpperCase())
  ));
  if (!match) {
    throw new NeedInputError(`No purpose mapping configured for WBS ${wbsCode}.`, {
      kind: 'purpose',
      question: '当前 WBS 没有匹配到用途映射，请补充用途或更新 config/oa-workflow-412-outbound.json。',
      wbsCode,
      purposeByWbsPrefix: workflowConfig.purposeByWbsPrefix
    });
  }
  return match;
}

async function selectPurpose(page, wbsCode) {
  const purpose = resolvePurpose(wbsCode);
  await openBrowserField(page, workflowConfig.selectors.purposeButton);
  const modal = page.locator('.ant-modal:visible, [role="dialog"]:visible').last();
  const clicked = await clickModalRow(page, modal, purpose.purpose);
  if (!clicked) {
    throw new NeedInputError(`Could not select purpose "${purpose.purpose}".`, {
      kind: 'purpose',
      question: `用途 ${purpose.purpose} 没有可选择行。请确认 WBS ${wbsCode} 的用途映射是否正确；可回复新的 WBS 编码重新推导，也可在 OA 页面手动处理后回复“已处理”。`,
      wbsCode,
      purpose: purpose.purpose
    });
  }
  await modal.waitFor({ state: 'hidden', timeout: 8000 }).catch(() => {});
  await waitForSettledPage(page);
  return purpose;
}

async function selectReservation(page, { factoryCode, wbsCode }) {
  await openBrowserField(page, workflowConfig.selectors.reservationButton);
  const modal = page.locator('.ant-modal:visible, [role="dialog"]:visible').last();
  await page.locator(workflowConfig.selectors.reservationFactoryInput).last().fill(factoryCode);
  await page.locator(workflowConfig.selectors.reservationWbsInput).last().fill(wbsCode);
  const data = await clickSearchInModal(page, browserDataMatcher({
    contains: `WERKS=${encodeQueryValue(factoryCode)}&ZYL3=${encodeQueryValue(wbsCode)}`
  }));
  if (data && resultCount(data) < 1) {
    throw new NeedInputError(`Reservation query returned no rows for factory=${factoryCode}, WBS=${wbsCode}.`, {
      kind: 'reservation',
      question: '预留号查询没有返回候选，请确认需求工厂代码与 WBS 编码。',
      factoryCode,
      wbsCode
    });
  }

  const firstRowData = Array.isArray(data?.datas) ? data.datas[0] : null;
  const reservationNumber = firstRowData?.RSNUMs || firstRowData?.RSNUM || '';
  const sapResponsePromise = page.waitForResponse((response) => (
    response.status() === 200 && response.url().includes('/api/querySAPActionApi/IF031')
  ), { timeout: 15000 }).catch(() => null);

  let clicked = false;
  if (reservationNumber) {
    clicked = await clickModalRow(page, modal, String(reservationNumber), 1200);
  }
  if (!clicked) clicked = await clickFirstModalDataRow(page, modal);
  if (!clicked) {
    throw new NeedInputError(`Could not select reservation row for factory=${factoryCode}, WBS=${wbsCode}.`, {
      kind: 'reservation',
      question: `预留号没有可选择行。请确认需求工厂 ${factoryCode} 与 WBS ${wbsCode} 是否正确；可回复新的 WBS 编码重新推导，也可在 OA 页面手动处理后回复“已处理”。`,
      factoryCode,
      wbsCode
    });
  }

  await modal.waitFor({ state: 'hidden', timeout: 8000 }).catch(() => {});
  const sapResponse = await sapResponsePromise;
  const sapData = sapResponse ? await sapResponse.json().catch(() => null) : null;
  await waitForSettledPage(page);
  const sapRows = Array.isArray(sapData?.data?.LT_DATA) ? sapData.data.LT_DATA : [];
  return {
    reservationNumber: reservationNumber || String(sapRows[0]?.RSNUM || ''),
    browserResultCount: resultCount(data),
    sapRowCount: sapRows.length,
    sapRows
  };
}

async function checkAllMaterialRows(page) {
  const boxes = page.locator(workflowConfig.selectors.materialCheckboxes);
  await boxes.first().waitFor({ timeout: 15000 });
  const count = await boxes.count();
  for (let index = 0; index < count; index += 1) {
    const box = boxes.nth(index);
    if (!(await box.isChecked().catch(() => false))) {
      await box.check();
    }
  }
  await waitForSettledPage(page);
  return count;
}

function quantityText(value) {
  if (value === null || value === undefined || value === '') return '';
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : String(value);
  return String(value).trim();
}

async function fillMaterialQuantities(page, sapRows) {
  const inputs = page.locator(`#${workflowConfig.selectors.materialApplyQuantityPrefix.replace(/_$/, '')}_0`);
  await inputs.first().waitFor({ timeout: 15000 }).catch(() => {});
  const applyInputs = page.locator(`input[id^="${workflowConfig.selectors.materialApplyQuantityPrefix}"]:visible`);
  const count = await applyInputs.count();
  if (count < 1) throw new Error('No visible material apply quantity inputs were found.');
  if (sapRows.length && sapRows.length < count) {
    throw new Error(`SAP returned ${sapRows.length} material rows but the page has ${count} quantity inputs.`);
  }

  const filled = [];
  for (let index = 0; index < count; index += 1) {
    const sapRow = sapRows[index] || {};
    const quantity = quantityText(sapRow.BDMNG);
    if (!quantity) throw new Error(`Missing total demand quantity for material row ${index + 1}.`);
    const input = page.locator(`#${workflowConfig.selectors.materialApplyQuantityPrefix}${index}`).first();
    await input.waitFor({ timeout: 15000 });
    await input.scrollIntoViewIfNeeded().catch(() => {});
    await input.fill(quantity);
    filled.push({
      rowIndex: index,
      materialCode: String(sapRow.MATNR || ''),
      reservationItem: String(sapRow.RSPOS || ''),
      quantity
    });
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
    ensureDir(outboundRuntimeDir);
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
      const failurePath = path.join(outboundRuntimeDir, `${stamp}-failure.json`);
      fs.writeFileSync(failurePath, JSON.stringify(base, null, 2), 'utf8');
      return { failurePath };
    }
    const screenshotPath = path.join(outboundRuntimeDir, `${stamp}-failure.png`);
    const surfacePath = path.join(outboundRuntimeDir, `${stamp}-failure-surface.json`);
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
 * Fill OA workflow 412 (material outbound / 物资出库) from already-structured input.
 *
 * input = {
 *   structured: { projectDefinition, wbsCode, demandFactoryCode, mrpController,
 *                 mrpDescription, costCenter: { costCenterCode, searchName, ... },
 *                 materialRows: [...] },
 *   url?, userInfo?/userJson?/userDepartment?,
 *   warehouseType?, loginTimeoutMs?, runtimeKey?, save: boolean
 * }
 *
 * Throws NeedInputError (missing slot, with payload) or Error (failure); the
 * thrown error carries `.artifact` with screenshot/surface paths. Returns a
 * structured report on success. Never clicks 提交 — at most saves a draft.
 */
export async function runOutbound(input = {}) {
  let page = null;
  let recorder = null;
  let runtime = null;
  const runtimeKey = input.runtimeKey ? String(input.runtimeKey) : '';
  try {
    const userInfo = loadUserInfo(input);
    if (!userInfo.department) {
      throw new NeedInputError('User department is required.', {
        kind: 'userDepartment',
        question: '需要用户部门用于成本中心匹配，请提供 userDepartment 或 userInfo.department。'
      });
    }
    const excel = input.structured;
    if (!excel || !excel.costCenter) {
      throw new Error('runOutbound requires input.structured with a costCenter object.');
    }

    const warehouseType = input.warehouseType || workflowConfig.warehouseType;
    const loginTimeoutMs = input.loginTimeoutMs ?? 180000;
    const save = Boolean(input.save);

    const pageConfig = resolveOaPage({ pageId: workflowConfig.pageId, url: input.url });
    if (runtimeKey) {
      runtime = activeOutboundRuntimes.get(runtimeKey) || null;
      if (runtime?.page?.isClosed?.()) {
        activeOutboundRuntimes.delete(runtimeKey);
        runtime = null;
      }
    }

    if (!runtime) {
      page = await edgeSession.newPage();
      recorder = attachSafeNetworkRecorder(page);
      runtime = {
        key: runtimeKey,
        page,
        recorder,
        actions: [],
        results: {},
        createdAt: new Date().toISOString(),
        resumedCount: 0
      };
      if (runtimeKey) activeOutboundRuntimes.set(runtimeKey, runtime);

      await page.goto(pageConfig.url, { waitUntil: 'domcontentloaded' });
      await waitForSettledPage(page);
    } else {
      page = runtime.page;
      recorder = runtime.recorder;
      runtime.resumedCount = (runtime.resumedCount || 0) + 1;
      await waitForSettledPage(page).catch(() => {});
    }

    const actions = runtime.actions;
    const results = runtime.results;

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

    async function step(key, name, fn) {
      if (Object.prototype.hasOwnProperty.call(results, key)) {
        return results[key];
      }
      recorder.setPhase(name);
      const startedCount = recorder.count();
      const startedAt = new Date().toISOString();
      try {
        const value = await fn();
        results[key] = value;
        runtime.lastCompletedStep = { key, name, finishedAt: new Date().toISOString() };
        runtime.failedStep = null;
        actions.push({
          key,
          name,
          ok: true,
          startedAt,
          finishedAt: new Date().toISOString(),
          newApiCallCount: recorder.count() - startedCount
        });
        return value;
      } catch (error) {
        runtime.failedStep = { key, name, failedAt: new Date().toISOString(), error: error.message };
        actions.push({
          key,
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

    results.company = await step('company', `Select 所属记账主体 ${excel.demandFactoryCode}`, async () => (
      selectCompany(page, excel.demandFactoryCode)
    ));
    results.costCenter = await step('costCenter', `Select 成本中心 ${excel.costCenter.searchName}`, async () => (
      selectCostCenter(page, excel.costCenter)
    ));
    results.warehouseType = await step('warehouseType', `Set 仓库类型 ${warehouseType}`, async () => {
      await selectDropdownOption(page, workflowConfig.selectors.warehouseTypeCombobox, warehouseType);
      return warehouseType;
    });
    results.purpose = await step('purpose', `Select 用途 for WBS ${excel.wbsCode}`, async () => (
      selectPurpose(page, excel.wbsCode)
    ));
    results.reservation = await step('reservation', `Select 预留号 ${excel.demandFactoryCode}/${excel.wbsCode}`, async () => (
      selectReservation(page, {
        factoryCode: excel.demandFactoryCode,
        wbsCode: excel.wbsCode
      })
    ));
    results.checkedMaterialCheckboxCount = await step('checkedMaterialCheckboxCount', 'Check all material rows', async () => (
      checkAllMaterialRows(page)
    ));
    results.materialQuantities = await step('materialQuantities', 'Fill material apply quantities from total demand quantities', async () => (
      fillMaterialQuantities(page, results.reservation.sapRows)
    ));
    results.projectCode = await step('projectCode', `Select 项目编码 ${resolveProjectCode(excel)}`, async () => (
      selectProjectCode(page, excel)
    ));

    if (save) {
      results.save = await step('save', 'Click 保存', async () => clickSave(page));
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
        warehouseType,
        projectCode: results.projectCode.projectCode,
        save,
        runtimeKey: runtimeKey || null,
        resumedCount: runtime.resumedCount || 0
      },
      results,
      actions,
      finalSurface,
      apiCalls: recorder.calls
    };

    ensureDir(outboundRuntimeDir);
    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    const reportPath = path.join(outboundRuntimeDir, `${stamp}-oa-outbound-from-excel.json`);
    fs.writeFileSync(reportPath, JSON.stringify(report, null, 2), 'utf8');
    if (runtimeKey) activeOutboundRuntimes.delete(runtimeKey);
    return {
      ok: true,
      reportPath,
      requestId,
      requestUrl,
      summary: {
        projectDefinition: excel.projectDefinition,
        wbsCode: excel.wbsCode,
        demandFactoryCode: excel.demandFactoryCode,
        companyName: results.company.companyName,
        mrpController: excel.mrpController,
        mrpDescription: excel.mrpDescription,
        projectCode: results.projectCode.projectCode,
        costCenterName: excel.costCenter.searchName,
        costCenterCode: excel.costCenter.costCenterCode,
        warehouseType: results.warehouseType,
        purpose: results.purpose.purpose,
        reservationNumber: results.reservation.reservationNumber,
        materialRowCount: results.materialQuantities.length,
        saved: save,
        actionCount: actions.length,
        runtimeKey: runtimeKey || null,
        resumedCount: runtime.resumedCount || 0
      },
      actions
    };
  } catch (error) {
    if (runtimeKey && runtime) {
      runtime.lastErrorAt = new Date().toISOString();
      runtime.lastError = error.message;
      if (error instanceof NeedInputError) {
        error.payload = {
          ...(error.payload || {}),
          runtimeKey,
          failedStep: runtime.failedStep || null,
          lastCompletedStep: runtime.lastCompletedStep || null,
          resumableRuntime: true
        };
      }
    }
    error.artifact = await writeFailureArtifact(page, recorder, error).catch(() => null);
    throw error;
  }
}
