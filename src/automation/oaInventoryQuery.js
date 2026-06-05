import { edgeSession } from '../browser/edgeSession.js';
import { resolveOaPage } from '../config.js';
import { redactText, redactUrl } from '../security/redaction.js';
import { detectLoginPage, waitForSettledPage } from './domScanner.js';

const INVENTORY_BROWSER_TYPE = 'browser.SAPInventoryQueryInterface';
const DEFAULT_WORKFLOW_ID = '414';
const DEFAULT_PAGE_ID = 'oa-workflow-414';
const DEFAULT_PAGE_SIZE = 50;
const DEFAULT_MAX_PAGES = 5;
const DEFAULT_STOCK_LOCATIONS = [
  'A001',
  'B001',
  'C001',
  'D001',
  'D002',
  'E001',
  'F001',
  'G001',
  'H001',
  'S001',
  'SZ01'
];

const workflowInventoryDefaults = {
  89: { pageId: 'oa-workflow-89', fieldid: 10039, billid: -117, viewtype: 0 },
  412: { pageId: 'oa-workflow-412', fieldid: 9722, billid: -68, viewtype: 0 },
  414: { pageId: 'oa-workflow-414', fieldid: 10037, billid: -86, viewtype: 0 },
  458: { pageId: 'oa-workflow-458', fieldid: 17999, billid: -167, viewtype: 0 }
};

const inventoryFieldLabels = {
  MATNR: 'materialCode',
  MATNRs: 'materialCode',
  MAKTX: 'materialDescription',
  MAKTXs: 'materialDescription',
  WERKS: 'factoryCode',
  WERKSs: 'factoryCode',
  NAME1: 'factoryName',
  NAME1s: 'factoryName',
  LGORT: 'stockLocationCode',
  LGORTs: 'stockLocationCode',
  LGOBE: 'stockLocationName',
  LGOBEs: 'stockLocationName',
  POSID: 'wbsCode',
  POSIDs: 'wbsCode',
  PSPNR: 'wbsCode',
  PSPNRs: 'wbsCode',
  SSNUM: 'wbsCode',
  SSNUMs: 'wbsCode',
  PSPID: 'projectCode',
  PSPIDs: 'projectCode',
  MEINS: 'unit',
  MEINSs: 'unit',
  CHARG: 'batchNumber',
  CHARGs: 'batchNumber',
  LABST: 'unrestrictedStock',
  LABSTs: 'unrestrictedStock',
  INSME: 'qualityInspectionStock',
  INSMEs: 'qualityInspectionStock',
  SPEME: 'blockedStock',
  SPEMEs: 'blockedStock',
  UMLME: 'transferStock',
  UMLMEs: 'transferStock',
  CLABS: 'projectUnrestrictedStock',
  CLABSs: 'projectUnrestrictedStock',
  CINSM: 'projectQualityInspectionStock',
  CINSMs: 'projectQualityInspectionStock',
  CSPEM: 'projectBlockedStock',
  CSPEMs: 'projectBlockedStock',
  KALAB: 'vendorConsignmentStock',
  KALABs: 'vendorConsignmentStock',
  KASPE: 'vendorConsignmentBlockedStock',
  KASPEs: 'vendorConsignmentBlockedStock',
  RETME: 'returnsBlockedStock',
  RETMEs: 'returnsBlockedStock',
  SOBKZ: 'specialStockIndicator'
};

const organizedFieldAliases = {
  materialCode: ['MATNR', 'MATNRs', 'matnr', 'materialCode'],
  factoryCode: ['WERKS', 'WERKSs', 'werks', 'factoryCode'],
  stockLocationCode: ['LGORT', 'LGORTs', 'lgort', 'stockLocationCode'],
  wbsCode: ['POSID', 'POSIDs', 'PSPNR', 'PSPNRs', 'SSNUM', 'SSNUMs', 'posid', 'wbsCode'],
  batchNumber: ['CHARG', 'CHARGs', 'charg', 'batchNumber']
};

function normalizeText(value) {
  return String(value ?? '').trim();
}

function positiveInt(value, fallback) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function workflowIdFromUrl(rawUrl) {
  if (!rawUrl) return '';
  try {
    const url = new URL(rawUrl);
    const direct = url.searchParams.get('workflowid');
    if (direct) return direct;
    if (url.hash.includes('?')) {
      return new URLSearchParams(url.hash.slice(url.hash.indexOf('?') + 1)).get('workflowid') || '';
    }
  } catch {
    const match = String(rawUrl).match(/[?&]workflowid=([^&#]+)/);
    if (match) return decodeURIComponent(match[1]);
  }
  return '';
}

function normalizeInput(input = {}) {
  const workflowId = normalizeText(input.workflowId || input.workflowid || '');
  const pageId = normalizeText(input.pageId || (workflowId && workflowInventoryDefaults[workflowId]?.pageId) || '');
  const materialCode = normalizeText(input.materialCode || input.MATNR || '');
  const factoryCode = normalizeText(input.factoryCode || input.plantCode || input.WERKS || '');
  const stockLocationCode = normalizeText(
    input.stockLocationCode
      || input.stockLocationSapCode
      || input.storageLocationCode
      || input.warehouseCode
      || input.LGORT
      || ''
  );
  const wbsCode = normalizeText(input.wbsCode || input.wbs || input.POSID || '');
  const extraConditions = input.conditions && typeof input.conditions === 'object' && !Array.isArray(input.conditions)
    ? Object.fromEntries(Object.entries(input.conditions).map(([key, value]) => [key, normalizeText(value)]).filter(([, value]) => value))
    : {};

  return {
    ...input,
    workflowId,
    pageId,
    materialCode,
    factoryCode,
    stockLocationCode,
    wbsCode,
    extraConditions,
    pageSize: positiveInt(input.pageSize, DEFAULT_PAGE_SIZE),
    maxPages: positiveInt(input.maxPages, DEFAULT_MAX_PAGES),
    preferWbs: input.preferWbs !== false,
    fallbackWarehouse: input.fallbackWarehouse !== false,
    loginTimeoutMs: positiveInt(input.loginTimeoutMs, 0)
  };
}

function validateQueryInput(input) {
  if (!input.materialCode && !input.stockLocationCode && !Object.keys(input.extraConditions).length) {
    throw new Error('At least one inventory condition is required. Pass materialCode and stockLocationCode for normal use.');
  }
}

function scalarParams(source) {
  const params = {};
  if (!source || typeof source !== 'object' || Array.isArray(source)) return params;
  for (const [key, value] of Object.entries(source)) {
    if (value === null || value === undefined) continue;
    if (['string', 'number', 'boolean'].includes(typeof value)) params[key] = String(value);
  }
  return params;
}

function findInventoryConfig(root, seen = new Set()) {
  if (!root || typeof root !== 'object') return null;
  if (seen.has(root)) return null;
  seen.add(root);

  if (Object.prototype.hasOwnProperty.call(root, `161_${INVENTORY_BROWSER_TYPE}`)) {
    return root[`161_${INVENTORY_BROWSER_TYPE}`];
  }
  if (
    root.type === INVENTORY_BROWSER_TYPE
    || root.fielddbtype === INVENTORY_BROWSER_TYPE
    || root.dataParams?.type === INVENTORY_BROWSER_TYPE
    || root.conditionDataParams?.type === INVENTORY_BROWSER_TYPE
  ) {
    return root;
  }

  for (const value of Object.values(root)) {
    const found = findInventoryConfig(value, seen);
    if (found) return found;
  }
  return null;
}

function parseMaybeJson(text) {
  const trimmed = String(text || '').trim();
  if (!trimmed || !/^[{[]/.test(trimmed)) return null;
  try {
    return JSON.parse(trimmed);
  } catch {
    return null;
  }
}

async function gotoAndCaptureInventoryConfig(page, url) {
  const pending = [];
  let inventoryConfig = null;
  let sourceUrl = null;

  const handler = (response) => {
    const task = (async () => {
      if (inventoryConfig) return;
      const contentType = response.headers()['content-type'] || '';
      if (!/json|text/i.test(contentType)) return;
      const text = await response.text().catch(() => '');
      const body = parseMaybeJson(text);
      const found = findInventoryConfig(body);
      if (found) {
        inventoryConfig = found;
        sourceUrl = redactUrl(response.url());
      }
    })();
    pending.push(task);
  };

  page.on('response', handler);
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  await waitForSettledPage(page);
  await Promise.allSettled(pending);
  page.off('response', handler);
  return { inventoryConfig, sourceUrl };
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

function baseParamsFromConfig(config) {
  return {
    ...scalarParams(config?.conditionDataParams),
    ...scalarParams(config?.destDataParams),
    ...scalarParams(config?.completeParams),
    ...scalarParams(config?.dataParams)
  };
}

function attemptIncludesWbs(attemptKind) {
  return String(attemptKind || '').endsWith('-wbs');
}

function baseAttemptKind(input, includeWbs = false) {
  const hasWarehouseScope = Boolean(input.factoryCode || input.stockLocationCode);
  if (includeWbs) return hasWarehouseScope ? 'warehouse-wbs' : 'material-wbs';
  return hasWarehouseScope ? 'warehouse' : 'material';
}

function queryConditionsForAttempt(input, attemptKind) {
  const conditions = {};
  if (input.materialCode) conditions.MATNR = input.materialCode;
  if (input.factoryCode) conditions.WERKS = input.factoryCode;
  if (input.stockLocationCode) conditions.LGORT = input.stockLocationCode;
  if (attemptIncludesWbs(attemptKind) && input.wbsCode) conditions.POSID = input.wbsCode;
  return {
    ...conditions,
    ...input.extraConditions
  };
}

function buildBrowserDataParams({ input, workflowId, defaults, config, attemptKind, current }) {
  const now = Date.now();
  const pageSize = input.pageSize;
  const min = ((current - 1) * pageSize) + 1;
  const max = current * pageSize;
  const configParams = baseParamsFromConfig(config);
  const params = {
    pageSize,
    current,
    min,
    max,
    companyId: 1,
    ...configParams,
    type: INVENTORY_BROWSER_TYPE,
    fielddbtype: INVENTORY_BROWSER_TYPE,
    currenttime: configParams.currenttime || now,
    requestid: configParams.requestid || -1,
    workflowid: workflowId,
    wfid: workflowId,
    billid: configParams.billid || defaults.billid,
    isbill: configParams.isbill || 1,
    fieldid: configParams.fieldid || defaults.fieldid,
    viewtype: configParams.viewtype || defaults.viewtype || 0,
    fromModule: configParams.fromModule || 'workflow',
    disabledConditionCache: 'true',
    __random__: now,
    ...queryConditionsForAttempt(input, attemptKind)
  };

  return Object.fromEntries(
    Object.entries(params)
      .filter(([, value]) => value !== undefined && value !== null && String(value) !== '')
      .map(([key, value]) => [key, String(value)])
  );
}

async function fetchBrowserData(page, params) {
  return page.evaluate(async ({ entries }) => {
    const url = new URL('/api/public/browser/data/161', window.location.origin);
    for (const [key, value] of entries) url.searchParams.set(key, value);
    const response = await fetch(url.toString(), {
      method: 'GET',
      credentials: 'include',
      headers: { accept: 'application/json, text/plain, */*' }
    });
    const text = await response.text();
    let body = null;
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
    return {
      ok: response.ok,
      status: response.status,
      url: url.toString(),
      contentType: response.headers.get('content-type') || '',
      body,
      text: body ? null : text.slice(0, 1000)
    };
  }, { entries: Object.entries(params) });
}

function valueAtPath(root, pathParts) {
  let current = root;
  for (const part of pathParts) {
    if (!current || typeof current !== 'object') return undefined;
    current = current[part];
  }
  return current;
}

function findRows(body) {
  const paths = [
    ['datas'],
    ['data', 'datas'],
    ['data'],
    ['data', 'list'],
    ['data', 'records'],
    ['data', 'rows'],
    ['result'],
    ['result', 'datas'],
    ['result', 'list'],
    ['result', 'records'],
    ['result', 'rows'],
    ['list'],
    ['records'],
    ['rows'],
    ['items']
  ];
  for (const path of paths) {
    const value = valueAtPath(body, path);
    if (Array.isArray(value)) return { path: path.join('.'), rows: value };
  }
  return { path: '', rows: [] };
}

function normalizeColumns(body) {
  const candidates = [
    body?.columns,
    body?.data?.columns,
    body?.showColumns,
    body?.data?.showColumns,
    body?.headers,
    body?.data?.headers
  ].filter(Array.isArray);
  return candidates[0] || [];
}

function totalFromBody(body, rowCount) {
  const candidates = [
    body?.total,
    body?.count,
    body?.data?.total,
    body?.data?.count,
    body?.page?.total
  ];
  const value = candidates.map((item) => Number(item)).find((item) => Number.isFinite(item));
  return value ?? rowCount;
}

function normalizeRow(row, columns) {
  if (!Array.isArray(row)) return row && typeof row === 'object' ? row : { value: row };
  const output = {};
  row.forEach((value, index) => {
    const column = columns[index];
    const key = typeof column === 'string'
      ? column
      : column?.key || column?.dataIndex || column?.field || column?.name || `col${index + 1}`;
    output[key] = value;
  });
  return output;
}

function normalizeBrowserResponse(body) {
  const { path, rows } = findRows(body);
  const columns = normalizeColumns(body);
  const normalizedRows = rows.map((row) => normalizeRow(row, columns));
  return {
    path,
    total: totalFromBody(body, normalizedRows.length),
    rowCount: normalizedRows.length,
    columns,
    rows: normalizedRows
  };
}

function valueFromAliases(row, aliases) {
  for (const alias of aliases) {
    const value = row?.[alias];
    if (value !== undefined && value !== null && String(value) !== '') return value;
  }
  return '';
}

function organizeInventoryRow(row) {
  const fields = {};
  const extraFields = {};
  for (const [key, value] of Object.entries(row || {})) {
    const label = inventoryFieldLabels[key] || inventoryFieldLabels[key.toUpperCase()];
    if (label) fields[label] = value;
    else extraFields[key] = value;
  }
  return {
    materialCode: valueFromAliases(row, organizedFieldAliases.materialCode),
    factoryCode: valueFromAliases(row, organizedFieldAliases.factoryCode),
    stockLocationCode: valueFromAliases(row, organizedFieldAliases.stockLocationCode),
    wbsCode: valueFromAliases(row, organizedFieldAliases.wbsCode),
    batchNumber: valueFromAliases(row, organizedFieldAliases.batchNumber),
    fields,
    extraFields
  };
}

async function runInventoryAttempt({ page, input, workflowId, defaults, config, attemptKind }) {
  const responses = [];
  const rows = [];
  let total = 0;
  let totalPages = 1;
  let failedResponse = null;

  for (let current = 1; current <= input.maxPages; current += 1) {
    const params = buildBrowserDataParams({ input, workflowId, defaults, config, attemptKind, current });
    const fetched = await fetchBrowserData(page, params);
    const normalized = fetched.body ? normalizeBrowserResponse(fetched.body) : {
      path: '',
      total: 0,
      rowCount: 0,
      columns: [],
      rows: []
    };
    responses.push({
      pageNo: current,
      status: fetched.status,
      ok: fetched.ok,
      url: redactUrl(fetched.url),
      contentType: fetched.contentType,
      total: normalized.total,
      rowCount: normalized.rowCount,
      rowPath: normalized.path,
      columns: normalized.columns,
      textSample: fetched.text ? redactText(fetched.text).slice(0, 500) : null
    });

    if (!fetched.ok) {
      failedResponse = responses.at(-1);
      break;
    }

    rows.push(...normalized.rows);
    total = normalized.total;
    totalPages = input.pageSize > 0 ? Math.max(1, Math.ceil(total / input.pageSize)) : 1;
    if (current >= totalPages || normalized.rowCount < input.pageSize) break;
  }

  return {
    kind: attemptKind,
    filters: queryConditionsForAttempt(input, attemptKind),
    ok: !failedResponse,
    failedResponse,
    total,
    totalPages,
    fetchedPageCount: responses.length,
    truncated: responses.length < totalPages,
    rowCount: rows.length,
    rows,
    organizedRows: rows.map(organizeInventoryRow),
    responses
  };
}

function stockQueryBody(input) {
  const lgortList = input.stockLocationCode
    ? [input.stockLocationCode]
    : DEFAULT_STOCK_LOCATIONS;
  return {
    matnrList: [input.materialCode].filter(Boolean),
    werksList: input.factoryCode ? [input.factoryCode] : [],
    lgortList,
    sobkzList: input.wbsCode ? ['Q'] : ['', 'Q']
  };
}

function stockQueryFailed(body) {
  return body?.api_status === '0'
    || body?.api_status === 0
    || body?.api_status === false
    || body?.status === false
    || body?.status === '0';
}

async function runStockQueryAttempt({ page, input }) {
  const requestBody = stockQueryBody(input);
  if (!requestBody.matnrList.length) {
    return null;
  }

  const fetched = await page.evaluate(async ({ body }) => {
    const response = await fetch('/api/ps/fhd/stockQuery', {
      method: 'POST',
      credentials: 'include',
      headers: {
        accept: 'application/json, text/plain, */*',
        'content-type': 'application/json;charset=UTF-8'
      },
      body: JSON.stringify(body)
    });
    const text = await response.text();
    let parsed = null;
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
    return {
      ok: response.ok,
      status: response.status,
      url: new URL('/api/ps/fhd/stockQuery', window.location.origin).toString(),
      contentType: response.headers.get('content-type') || '',
      body: parsed,
      text: parsed ? null : text.slice(0, 1000)
    };
  }, { body: requestBody });

  const normalized = fetched.body ? normalizeBrowserResponse(fetched.body) : {
    path: '',
    total: 0,
    rowCount: 0,
    columns: [],
    rows: []
  };
  const failed = !fetched.ok || stockQueryFailed(fetched.body);
  return {
    kind: 'stock-query',
    filters: requestBody,
    ok: !failed,
    failedResponse: failed ? {
      status: fetched.status,
      ok: fetched.ok,
      url: redactUrl(fetched.url),
      contentType: fetched.contentType,
      msg: fetched.body?.msg,
      api_status: fetched.body?.api_status ?? fetched.body?.status,
      textSample: fetched.text ? redactText(fetched.text).slice(0, 500) : null
    } : null,
    total: normalized.total,
    totalPages: 1,
    fetchedPageCount: 1,
    truncated: false,
    rowCount: normalized.rowCount,
    rows: normalized.rows,
    organizedRows: normalized.rows.map(organizeInventoryRow),
    responses: [{
      pageNo: 1,
      status: fetched.status,
      ok: fetched.ok,
      url: redactUrl(fetched.url),
      contentType: fetched.contentType,
      total: normalized.total,
      rowCount: normalized.rowCount,
      rowPath: normalized.path,
      columns: normalized.columns,
      msg: fetched.body?.msg,
      api_status: fetched.body?.api_status ?? fetched.body?.status,
      textSample: fetched.text ? redactText(fetched.text).slice(0, 500) : null
    }]
  };
}

function attemptPlan(input) {
  if (input.preferWbs && input.wbsCode) {
    const attempts = [baseAttemptKind(input, true)];
    if (input.fallbackWarehouse) attempts.push(baseAttemptKind(input, false));
    return [...new Set(attempts)];
  }
  return [baseAttemptKind(input, false)];
}

function summarizeAttempts(attempts) {
  return attempts.map((attempt) => ({
    kind: attempt.kind,
    filters: attempt.filters,
    ok: attempt.ok,
    total: attempt.total,
    rowCount: attempt.rowCount,
    fetchedPageCount: attempt.fetchedPageCount,
    truncated: attempt.truncated,
    failedResponse: attempt.failedResponse
  }));
}

export async function queryOaInventory(input = {}) {
  const normalized = normalizeInput(input);
  validateQueryInput(normalized);
  const pageConfig = resolveOaPage({
    pageId: normalized.pageId || DEFAULT_PAGE_ID,
    workflowId: normalized.workflowId || undefined,
    url: normalized.url
  });
  const workflowId = normalizeText(normalized.workflowId || pageConfig.workflowId || workflowIdFromUrl(pageConfig.url) || DEFAULT_WORKFLOW_ID);
  const defaults = workflowInventoryDefaults[workflowId] || workflowInventoryDefaults[DEFAULT_WORKFLOW_ID];
  const entryUrl = normalized.url || pageConfig.url;
  let page = null;
  try {
    page = await edgeSession.newPage();
    const { inventoryConfig, sourceUrl } = await gotoAndCaptureInventoryConfig(page, entryUrl);

    let login = await detectLoginPage(page);
    if (login.requiresLogin && normalized.loginTimeoutMs > 0) {
      const stillRequiresLogin = await waitForLoginRecovery(page, normalized.loginTimeoutMs);
      login = await detectLoginPage(page);
      if (stillRequiresLogin || login.requiresLogin) {
        const screenshot = await edgeSession.captureLoginScreenshot(page, 'oa-inventory-login');
        return {
          page: pageConfig,
          entryUrl: redactUrl(entryUrl),
          requiresLogin: true,
          login,
          screenshotUrl: screenshot.url,
          rows: [],
          organizedRows: []
        };
      }
    } else if (login.requiresLogin) {
      const screenshot = await edgeSession.captureLoginScreenshot(page, 'oa-inventory-login');
      return {
        page: pageConfig,
        entryUrl: redactUrl(entryUrl),
        requiresLogin: true,
        login,
        screenshotUrl: screenshot.url,
        rows: [],
        organizedRows: []
      };
    }

    const attempts = [];
    const stockQueryAttempt = await runStockQueryAttempt({ page, input: normalized });
    if (stockQueryAttempt) {
      attempts.push(stockQueryAttempt);
    }

    if (stockQueryAttempt?.ok && stockQueryAttempt.rowCount > 0) {
      // The top-level OA stock query button uses /api/ps/fhd/stockQuery. Prefer it
      // for material-code-only lookup because it searches inventory across locations.
    } else {
      for (const kind of attemptPlan(normalized)) {
        const attempt = await runInventoryAttempt({
          page,
          input: normalized,
          workflowId,
          defaults,
          config: inventoryConfig,
          attemptKind: kind
        });
        attempts.push(attempt);
        if (attempt.ok && attempt.rowCount > 0) break;
        if (kind === 'warehouse-wbs' && !normalized.fallbackWarehouse) break;
      }
    }

    const selectedAttempt = attempts.find((attempt) => attempt.ok && attempt.rowCount > 0) || attempts.at(-1) || null;
    const fallbackUsed = Boolean(
      attempts.length > 1
        && attemptIncludesWbs(attempts[0]?.kind)
        && !attemptIncludesWbs(selectedAttempt?.kind)
    );

    return {
      ok: true,
      page: {
        id: pageConfig.id,
        workflowId,
        entryUrl: redactUrl(entryUrl),
        currentUrl: redactUrl(page.url())
      },
      requiresLogin: false,
      query: {
        materialCode: normalized.materialCode,
        factoryCode: normalized.factoryCode,
        stockLocationCode: normalized.stockLocationCode,
        wbsCode: normalized.wbsCode,
        pageSize: normalized.pageSize,
        maxPages: normalized.maxPages,
        preferWbs: normalized.preferWbs,
        fallbackWarehouse: normalized.fallbackWarehouse,
        extraConditions: normalized.extraConditions
      },
      browser: {
        type: INVENTORY_BROWSER_TYPE,
        configFound: Boolean(inventoryConfig),
        configSourceUrl: sourceUrl,
        fieldid: String(baseParamsFromConfig(inventoryConfig).fieldid || defaults.fieldid),
        billid: String(baseParamsFromConfig(inventoryConfig).billid || defaults.billid)
      },
      search: {
        fallbackUsed,
        selectedAttemptKind: selectedAttempt?.kind || null,
        total: selectedAttempt?.total || 0,
        fetchedPageCount: selectedAttempt?.fetchedPageCount || 0,
        rowCount: selectedAttempt?.rowCount || 0,
        truncated: Boolean(selectedAttempt?.truncated),
        attempts: summarizeAttempts(attempts)
      },
      rows: selectedAttempt?.rows || [],
      organizedRows: selectedAttempt?.organizedRows || [],
      attempts
    };
  } finally {
    if (normalized.keepPageOpen !== true) {
      await page?.close().catch(() => {});
    }
  }
}
