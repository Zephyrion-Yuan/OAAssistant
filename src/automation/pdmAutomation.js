import { edgeSession } from '../browser/edgeSession.js';
import { cachedProfileSession } from '../browser/cachedProfileSession.js';
import { resolvePdmPage } from '../config.js';
import { redactUrl } from '../security/redaction.js';
import { detectLoginPage, waitForSettledPage } from './domScanner.js';
import { attachSafeNetworkRecorder } from '../explorer/safeNetworkRecorder.js';
import { scanPageSurface } from '../explorer/surfaceScanner.js';

const MATERIAL_PAGE_API_PATH = '/admin-api/master/data/material/page';
const DEFAULT_MAX_PAGES = 5;

const textFilterFields = [
  'materialCode',
  'materialName',
  'specificationModel',
  'materialGroupCode',
  'materialGroupDesc',
  'brand',
  'materialLevel'
];

const fieldAliases = {
  code: 'materialCode',
  materialCode: 'materialCode',
  materialCodeLike: 'materialCodeLike',
  name: 'materialName',
  materialName: 'materialName',
  specification: 'specificationModel',
  specificationModel: 'specificationModel',
  groupCode: 'materialGroupCode',
  materialGroupCode: 'materialGroupCode',
  groupDesc: 'materialGroupDesc',
  materialGroupDesc: 'materialGroupDesc',
  brand: 'brand',
  level: 'materialLevel',
  materialLevel: 'materialLevel'
};

const materialFieldLabels = {
  id: 'ID',
  materialCode: '物料编码',
  materialName: '物料名称',
  specificationModel: '规格型号',
  materialType: '物料类型',
  materialGroupCode: '物料组编码',
  materialGroupDesc: '物料组',
  machineType: '机加类型',
  materialDesc: '物料描述',
  unit: '基本计量单位编码',
  unitDesc: '基本计量单位',
  brand: '品牌',
  brandCode: '品牌编码',
  packaged: '封装',
  material: '材质',
  surfaceTreatment: '表面处理',
  transportationTemperature: '运输温度',
  productRecordNumber: '产品注册证号/备案号',
  materialLevel: '物料等级',
  supplierModelName: '供应商型号名称',
  status: '状态',
  freezeType: '冻结类型',
  parameterDescription: '参数描述(长文本)',
  enableGsp: '是否医疗器械经营',
  productCompany: '生产企业',
  productLicenseNo: '生产许可证号/备案号',
  shippingUnit: '运输单位',
  cbbFlag: 'CBB标识',
  keyAssemblyMaterialCode: '关键组装物料编码',
  keyTraceMaterialCode: '关键追溯物料编码',
  keyAssemblyMaterialDesc: '关键组装物料描述',
  keyTraceMaterialDesc: '关键追溯物料描述'
};

const statusLabels = {
  0: '禁用',
  1: '启用'
};

function normalizeText(value) {
  return String(value ?? '').trim();
}

function positiveInt(value, fallback) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function buildFilters(input = {}) {
  const filters = {};

  for (const field of textFilterFields) {
    const value = normalizeText(input[field]);
    if (value) filters[field] = value;
  }

  const codeLike = normalizeText(input.materialCodeLike);
  if (codeLike) filters.materialCode = codeLike;

  const queryType = fieldAliases[normalizeText(input.queryType)] || null;
  const keyword = normalizeText(input.keyword);
  if (queryType && keyword) {
    filters[queryType === 'materialCodeLike' ? 'materialCode' : queryType] = keyword;
  } else if (keyword && !Object.keys(filters).length) {
    filters[/^\d+$/.test(keyword) ? 'materialCode' : 'materialName'] = keyword;
  }

  return filters;
}

function apiPagePayload(body) {
  const data = body?.data || {};
  const list = Array.isArray(data.list) ? data.list : [];
  const total = Number(data.total ?? list.length);
  return { list, total };
}

function materialApiResponse(response) {
  try {
    return new URL(response.url()).pathname.endsWith(MATERIAL_PAGE_API_PATH) && response.status() === 200;
  } catch {
    return false;
  }
}

function responsePageNo(response) {
  try {
    return positiveInt(new URL(response.url()).searchParams.get('pageNo'), 1);
  } catch {
    return 1;
  }
}

function responsePageSize(response, listLength) {
  try {
    return positiveInt(new URL(response.url()).searchParams.get('pageSize'), listLength || 20);
  } catch {
    return listLength || 20;
  }
}

async function readMaterialResponse(response) {
  const body = await response.json();
  const { list, total } = apiPagePayload(body);
  return {
    url: redactUrl(response.url()),
    pageNo: responsePageNo(response),
    pageSize: responsePageSize(response, list.length),
    total,
    rowCount: list.length,
    rows: list
  };
}

async function fillTextFilter(page, fieldName, value) {
  const locator = page.locator(`input[name="${fieldName}"]:visible`).first();
  await locator.waitFor({ timeout: 15000 });
  await locator.scrollIntoViewIfNeeded();
  await locator.fill(String(value));
}

async function clickSearch(page) {
  const candidates = [
    page.locator('form button').filter({ hasText: /搜\s*索/ }).first(),
    page.getByRole('button', { name: /搜\s*索|搜索/ }).first()
  ];
  for (const locator of candidates) {
    if (await locator.count().catch(() => 0)) {
      await locator.scrollIntoViewIfNeeded();
      await locator.click();
      return true;
    }
  }
  await page.keyboard.press('Enter');
  return false;
}

async function submitSearch(page, filters) {
  for (const fieldName of textFilterFields) {
    if (filters[fieldName] !== undefined) {
      await fillTextFilter(page, fieldName, filters[fieldName]);
    }
  }

  const responsePromise = page.waitForResponse((response) => {
    if (!materialApiResponse(response)) return false;
    return responsePageNo(response) === 1;
  }, { timeout: 30000 });

  const clickedSearch = await clickSearch(page);
  const response = await responsePromise;
  return {
    clickedSearch,
    ...(await readMaterialResponse(response))
  };
}

async function clickNextPage(page) {
  const locators = [
    page.getByRole('button', { name: /下一页/ }).first(),
    page.locator('button[aria-label*="下一页"],button[title*="下一页"]').first(),
    page.locator('button').filter({ hasText: /下一页/ }).first()
  ];

  for (const locator of locators) {
    if (!(await locator.count().catch(() => 0))) continue;
    const disabled = await locator.evaluate((element) => (
      element.disabled ||
      element.getAttribute('aria-disabled') === 'true' ||
      element.className?.toString().includes('disabled')
    )).catch(() => true);
    if (disabled) return false;
    await locator.scrollIntoViewIfNeeded();
    await locator.click();
    return true;
  }
  return false;
}

async function readNextPage(page, nextPageNo) {
  const responsePromise = page.waitForResponse((response) => {
    if (!materialApiResponse(response)) return false;
    return responsePageNo(response) === nextPageNo;
  }, { timeout: 30000 });

  const clicked = await clickNextPage(page);
  if (!clicked) return null;
  const response = await responsePromise;
  return readMaterialResponse(response);
}

function exactMaterialCode(input, filters) {
  if (input.exactMaterialCode === false || input.exact === false) return false;
  return Boolean(filters.materialCode && !input.materialCodeLike && input.queryType !== 'materialCodeLike');
}

function organizeMaterialRow(row) {
  const labeled = {};
  const extra = {};
  for (const [key, value] of Object.entries(row || {})) {
    if (key in materialFieldLabels) labeled[materialFieldLabels[key]] = value;
    else extra[key] = value;
  }
  if (row?.status !== undefined) labeled['状态文本'] = statusLabels[String(row.status)] || String(row.status);
  return {
    materialCode: row?.materialCode || '',
    materialName: row?.materialName || '',
    fields: labeled,
    extraFields: extra
  };
}

function uniqueRows(rows) {
  const seen = new Set();
  const output = [];
  for (const row of rows) {
    const key = row?.id ?? row?.materialCode ?? JSON.stringify(row);
    if (seen.has(key)) continue;
    seen.add(key);
    output.push(row);
  }
  return output;
}

async function gotoPdmPage(page, url) {
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  await waitForSettledPage(page);
}

export async function queryPdmMaterial(input = {}) {
  const pageConfig = resolvePdmPage();
  const session = input.useLiveSession ? edgeSession : cachedProfileSession;
  let page = null;
  try {
    page = await session.newPage();
    const recorder = attachSafeNetworkRecorder(page);
    const entryUrl = input.url || pageConfig.url;
    const maxPages = positiveInt(input.maxPages, DEFAULT_MAX_PAGES);
    const filters = buildFilters(input);
    if (!Object.keys(filters).length) {
      throw new Error('At least one PDM material query filter is required.');
    }
    if (input.status !== undefined) {
      throw new Error('Status filter is not automated yet; supported filters: materialCode, materialName, specificationModel, materialGroupCode, materialGroupDesc, brand, materialLevel.');
    }

    await gotoPdmPage(page, entryUrl);
    const login = await detectLoginPage(page);
    if (login.requiresLogin) {
      const screenshot = input.useLiveSession
        ? await edgeSession.captureLoginScreenshot(page, 'pdm-login')
        : null;
      return {
        page: pageConfig,
        entryUrl: redactUrl(entryUrl),
        requiresLogin: true,
        login,
        screenshotUrl: screenshot?.url || null,
        filters,
        rows: [],
        organizedRows: []
      };
    }

    const initialSurface = await scanPageSurface(page);
    const firstPage = await submitSearch(page, filters);
    const materialResponses = [firstPage];
    const totalPages = firstPage.pageSize > 0 ? Math.max(1, Math.ceil(firstPage.total / firstPage.pageSize)) : 1;
    const pagesToRead = Math.min(maxPages, totalPages);

    for (let pageNo = 2; pageNo <= pagesToRead; pageNo += 1) {
      const nextPage = await readNextPage(page, pageNo);
      if (!nextPage) break;
      materialResponses.push(nextPage);
      await waitForSettledPage(page);
    }

    let rows = uniqueRows(materialResponses.flatMap((response) => response.rows || []));
    let exactCodeFilteredOut = 0;
    if (exactMaterialCode(input, filters)) {
      const before = rows.length;
      rows = rows.filter((row) => String(row.materialCode || '') === String(filters.materialCode));
      exactCodeFilteredOut = before - rows.length;
    }

    const finalSurface = await scanPageSurface(page);
    const fetchedPages = materialResponses.map((response) => ({
      pageNo: response.pageNo,
      pageSize: response.pageSize,
      rowCount: response.rowCount,
      url: response.url
    }));

    return {
      page: pageConfig,
      entryUrl: redactUrl(entryUrl),
      currentUrl: redactUrl(page.url()),
      requiresLogin: false,
      query: {
        filters,
        exactMaterialCode: exactMaterialCode(input, filters),
        maxPages
      },
      search: {
        clickedSearch: firstPage.clickedSearch,
        total: firstPage.total,
        totalPages,
        fetchedPageCount: materialResponses.length,
        fetchedPages,
        truncated: materialResponses.length < totalPages,
        exactCodeFilteredOut
      },
      fieldLabels: materialFieldLabels,
      rows,
      organizedRows: rows.map(organizeMaterialRow),
      materialResponses,
      initialSurface,
      finalSurface,
      apiCalls: recorder.calls
    };
  } finally {
    if (input.keepPageOpen !== true) {
      await page?.close().catch(() => {});
    }
  }
}
