import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { z } from 'zod';
import { edgeSession } from './browser/edgeSession.js';
import { cachedProfileSession } from './browser/cachedProfileSession.js';
import { openLoginPage, scanOaPage, fillOaPage } from './automation/oaAutomation.js';
import { queryOaInventory } from './automation/oaInventoryQuery.js';
import { listWbs, getWbs, upsertWbs, archiveWbs, deleteWbs, resolveWbs } from './automation/wbsRegistry.js';
import { queryPdmMaterial } from './automation/pdmAutomation.js';
import { runStockTransfer, NeedInputError } from './automation/flows/stockTransfer.js';
import { runOutbound, NeedInputError as OutboundNeedInputError } from './automation/flows/outbound.js';
import { runInbound, NeedInputError as InboundNeedInputError } from './automation/flows/inbound.js';
import { runPurchase, NeedInputError as PurchaseNeedInputError } from './automation/flows/purchase.js';
import { diagnosePdmLogin, probePdmAuth } from './automation/loginDiagnostics.js';
import { diagnoseSystemSession } from './automation/sessionDiagnostics.js';
import { explorePage } from './explorer/pageExplorer.js';
import { ensureDir, pagesConfig, repoRoot, runtimeDir } from './config.js';
import { cacheEdgeProfile, closeEdgeBackgroundProcesses, profileCacheStatus } from './profile/profileCache.js';
import { testCachedProfileLogin, testOaLiveSession, testPdmCachedProfileLogin, testPdmLiveSession } from './profile/testLogin.js';
import { redactText, redactUrl } from './security/redaction.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const publicDir = path.join(repoRoot, 'public');
const port = Number(process.env.PORT || 8787);
const host = process.env.HOST || '127.0.0.1';
const defaultSsoAllowedHosts = [
  'oa.megarobo.info',
  'pdm.megarobo.info',
  'pdm-api.megarobo.info',
  'sso.megarobo.tech',
  'megarobo.tech',
  'megarobo.info'
];

ensureDir(runtimeDir);

const mimeTypes = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon'
};

function sendJson(response, statusCode, payload) {
  response.writeHead(statusCode, {
    'Content-Type': 'application/json; charset=utf-8',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'content-type',
    'Access-Control-Allow-Methods': 'GET,POST,OPTIONS'
  });
  response.end(JSON.stringify(payload, null, 2));
}

function sendFile(response, filePath) {
  const extension = path.extname(filePath).toLowerCase();
  response.writeHead(200, { 'Content-Type': mimeTypes[extension] || 'application/octet-stream' });
  fs.createReadStream(filePath).pipe(response);
}

function safeStaticPath(root, requestPath) {
  const decoded = decodeURIComponent(requestPath);
  const filePath = path.resolve(root, `.${decoded}`);
  if (!filePath.startsWith(path.resolve(root))) return null;
  return filePath;
}

async function readBody(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  const text = Buffer.concat(chunks).toString('utf8');
  if (!text.trim()) return {};
  return JSON.parse(text);
}

function ssoAllowedHosts() {
  return (process.env.MEGANT_SSO_ALLOWED_HOSTS || defaultSsoAllowedHosts.join(','))
    .split(',')
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
}

function isAllowedHost(hostname, allowedHosts) {
  const host = hostname.toLowerCase();
  return allowedHosts.some((allowed) => host === allowed || host.endsWith(`.${allowed}`));
}

function validateSsoHandoffUrl(rawUrl) {
  if (!rawUrl) throw new Error('Missing url');
  const target = new URL(rawUrl);
  if (!['https:', 'http:'].includes(target.protocol)) {
    throw new Error('Only http/https handoff URLs are allowed.');
  }
  const allowedHosts = ssoAllowedHosts();
  if (!isAllowedHost(target.hostname, allowedHosts)) {
    throw new Error(`Blocked handoff URL host: ${target.hostname}`);
  }
  return target.toString();
}

async function openUrlInManagedEdge(rawUrl) {
  const targetUrl = validateSsoHandoffUrl(rawUrl);
  const context = await edgeSession.getContext();
  const page = await context.newPage();
  await page.bringToFront();
  await page.goto(targetUrl, { waitUntil: 'domcontentloaded' });
  return {
    ok: true,
    redactedUrl: redactUrl(targetUrl),
    currentUrl: redactUrl(page.url()),
    openedAt: new Date().toISOString()
  };
}

async function autoLaunchManagedEdge() {
  if (process.env.MEGANT_AUTO_LAUNCH_EDGE !== '1') return;
  const startupUrl = process.env.MEGANT_STARTUP_URL || `http://127.0.0.1:${port}/`;
  try {
    const context = await edgeSession.getContext();
    const page = context.pages().find((item) => !item.isClosed()) || await context.newPage();
    await page.bringToFront();
    await page.goto(startupUrl, { waitUntil: 'domcontentloaded' });
    console.log(`Managed Edge launched: ${redactUrl(startupUrl)}`);
  } catch (error) {
    console.error(redactText(error.message));
  }
}

const stockTransferSchema = z.object({
  structured: z.object({
    projectDefinition: z.string().optional(),
    wbsCode: z.string().optional(),
    demandFactoryCode: z.string().optional(),
    mrpController: z.string().optional(),
    materialPlans: z.array(z.object({
      materialCode: z.string().min(1),
      materialName: z.string().optional(),
      quantity: z.union([z.string(), z.number()]),
      unit: z.string().optional()
    })).min(1)
  }).passthrough(),
  url: z.string().optional(),
  userInfo: z.record(z.string(), z.any()).optional(),
  userDepartment: z.string().optional(),
  movementType: z.string().optional(),
  warehouseType: z.string().nullish(),
  factoryCode: z.string().optional(),
  stockLocationName: z.string().optional(),
  stockLocationSapCode: z.string().optional(),
  transferOutStockLocationName: z.string().optional(),
  transferOutStockLocationSapCode: z.string().optional(),
  transferInStockLocationName: z.string().optional(),
  transferInStockLocationSapCode: z.string().optional(),
  wbs: z.string().optional(),
  transferOutWbs: z.string().optional(),
  transferInWbs: z.string().optional(),
  quantityRule: z.string().optional(),
  quantityOverrides: z.record(z.string(), z.union([z.string(), z.number()])).optional(),
  loginTimeoutMs: z.number().optional(),
  save: z.boolean().optional()
}).passthrough();

// OA forms are single-page and stateful; serialize fill requests so two never
// drive the same managed Edge page concurrently.
let oaFillLock = Promise.resolve();
function withOaFillLock(task) {
  const run = oaFillLock.then(() => task());
  oaFillLock = run.then(() => {}, () => {});
  return run;
}

async function handleStockTransfer(rawBody) {
  const parsed = stockTransferSchema.safeParse(rawBody);
  if (!parsed.success) {
    return { ok: false, error: 'Invalid /api/oa/stock-transfer request body.', issues: parsed.error.issues };
  }
  return withOaFillLock(async () => {
    try {
      return await runStockTransfer(parsed.data);
    } catch (error) {
      if (error instanceof NeedInputError) {
        return {
          ok: false,
          needsInput: true,
          input: error.payload,
          error: error.message,
          artifact: error.artifact || null
        };
      }
      return { ok: false, error: error.message, artifact: error.artifact || null };
    }
  });
}

// ----- Workflow 412 (outbound / 物资出库) ------------------------------------
const outboundSchema = z.object({
  structured: z.object({
    projectDefinition: z.string().optional(),
    wbsCode: z.string().optional(),
    demandFactoryCode: z.string().optional(),
    mrpController: z.string().optional(),
    mrpDescription: z.string().optional(),
    costCenter: z.object({
      costCenterCode: z.string().optional(),
      searchName: z.string().optional()
    }).passthrough(),
    materialRows: z.array(z.record(z.string(), z.any())).optional()
  }).passthrough(),
  url: z.string().optional(),
  userInfo: z.record(z.string(), z.any()).optional(),
  userJson: z.string().optional(),
  userDepartment: z.string().optional(),
  warehouseType: z.string().nullish(),
  loginTimeoutMs: z.number().optional(),
  save: z.boolean().optional()
}).passthrough();

async function handleOutbound(rawBody) {
  const parsed = outboundSchema.safeParse(rawBody);
  if (!parsed.success) {
    return { ok: false, error: 'Invalid /api/oa/outbound request body.', issues: parsed.error.issues };
  }
  return withOaFillLock(async () => {
    try {
      return await runOutbound(parsed.data);
    } catch (error) {
      if (error instanceof OutboundNeedInputError) {
        return { ok: false, needsInput: true, input: error.payload, error: error.message, artifact: error.artifact || null };
      }
      return { ok: false, error: error.message, artifact: error.artifact || null };
    }
  });
}

// ----- Workflow 414 (inbound / 物资入库) -------------------------------------
const inboundSchema = z.object({
  structured: z.object({
    projectDefinition: z.string().optional(),
    wbsCode: z.string().optional(),
    demandFactoryCode: z.string().optional(),
    mrpController: z.string().optional(),
    materialRows: z.array(z.record(z.string(), z.any())).optional(),
    quantityByMaterialCode: z.record(z.string(), z.union([z.string(), z.number()]))
  }).passthrough(),
  url: z.string().optional(),
  userInfo: z.record(z.string(), z.any()).optional(),
  userJson: z.string().optional(),
  userDepartment: z.string().optional(),
  inboundType: z.string().optional(),
  warehouseType: z.string().nullish(),
  voucherSearchBy: z.string().optional(),
  projectCode: z.string().optional(),
  voucherNumber: z.string().optional(),
  stockLocationName: z.string().optional(),
  stockLocationSapCode: z.string().optional(),
  quantityRule: z.string().optional(),
  quantityOverrides: z.record(z.string(), z.union([z.string(), z.number()])).optional(),
  loginTimeoutMs: z.number().optional(),
  save: z.boolean().optional()
}).passthrough();

async function handleInbound(rawBody) {
  const parsed = inboundSchema.safeParse(rawBody);
  if (!parsed.success) {
    return { ok: false, error: 'Invalid /api/oa/inbound request body.', issues: parsed.error.issues };
  }
  return withOaFillLock(async () => {
    try {
      return await runInbound(parsed.data);
    } catch (error) {
      if (error instanceof InboundNeedInputError) {
        return { ok: false, needsInput: true, input: error.payload, error: error.message, artifact: error.artifact || null };
      }
      return { ok: false, error: error.message, artifact: error.artifact || null };
    }
  });
}

// ----- Workflow 458 (purchase / 采购申请) ------------------------------------
const purchaseSchema = z.object({
  structured: z.object({
    projectDefinition: z.string().optional(),
    wbsCode: z.string().optional(),
    demandFactoryCode: z.string().optional(),
    demandCompanyName: z.string().nullish(),
    targetDemandDate: z.string().optional(),
    normalizedPath: z.string().min(1)
  }).passthrough(),
  url: z.string().optional(),
  purchaseType: z.string().optional(),
  projectType: z.string().optional(),
  loginTimeoutMs: z.number().optional(),
  save: z.boolean().optional()
}).passthrough();

async function handlePurchase(rawBody) {
  const parsed = purchaseSchema.safeParse(rawBody);
  if (!parsed.success) {
    return { ok: false, error: 'Invalid /api/oa/purchase request body.', issues: parsed.error.issues };
  }
  return withOaFillLock(async () => {
    try {
      return await runPurchase(parsed.data);
    } catch (error) {
      if (error instanceof PurchaseNeedInputError) {
        return { ok: false, needsInput: true, input: error.payload, error: error.message, artifact: error.artifact || null };
      }
      return { ok: false, error: error.message, artifact: error.artifact || null };
    }
  });
}

// ----- WBS registry (user-managed business master data) ----------------------
const wbsUpsertSchema = z.object({
  wbsCode: z.string().min(1),
  alias: z.string().optional(),
  projectDefinition: z.string().optional(),
  demandFactoryCode: z.string().optional(),
  costCenter: z.string().optional(),
  purchaser: z.string().optional(),
  mrpController: z.string().optional(),
  stockLocationName: z.string().optional(),
  stockLocationSapCode: z.string().optional(),
  deliveryAddress: z.string().optional(),
  demandDateOffsetDays: z.union([z.string(), z.number()]).nullish(),
  remark: z.string().optional(),
  status: z.enum(['active', 'archived']).optional()
}).passthrough();

const wbsKeySchema = z.object({ wbsCode: z.string().min(1) }).passthrough();

function handleWbsUpsert(rawBody) {
  const parsed = wbsUpsertSchema.safeParse(rawBody);
  if (!parsed.success) {
    return { ok: false, error: 'Invalid /api/wbs/upsert request body.', issues: parsed.error.issues };
  }
  return upsertWbs(parsed.data);
}

function handleWbsKey(rawBody, fn, label) {
  const parsed = wbsKeySchema.safeParse(rawBody);
  if (!parsed.success) {
    return { ok: false, error: `Invalid ${label} request body.`, issues: parsed.error.issues };
  }
  return fn(parsed.data);
}

async function handleApi(request, response, url) {
  if (request.method === 'OPTIONS') {
    sendJson(response, 200, {});
    return;
  }

  if (request.method === 'GET' && url.pathname === '/api/health') {
    sendJson(response, 200, { ok: true, pages: pagesConfig });
    return;
  }
  if (request.method === 'GET' && url.pathname === '/api/session/status') {
    sendJson(response, 200, {
      oaLiveSession: edgeSession.status(),
      pdmCachedSession: cachedProfileSession.status(),
      docker: {
        enabled: process.env.MEGANT_DOCKER === '1',
        noVncPort: Number(process.env.NOVNC_PORT || 7900)
      }
    });
    return;
  }
  if (request.method === 'GET' && url.pathname === '/api/profile/status') {
    sendJson(response, 200, profileCacheStatus());
    return;
  }
  if (request.method === 'GET' && url.pathname === '/api/wbs/list') {
    const includeArchived = ['1', 'true', 'yes'].includes((url.searchParams.get('includeArchived') || '').toLowerCase());
    sendJson(response, 200, listWbs({ includeArchived }));
    return;
  }

  if (request.method !== 'POST') {
    sendJson(response, 405, { error: 'Method not allowed' });
    return;
  }

  const body = await readBody(request);
  if (url.pathname === '/api/session/open-login') {
    sendJson(response, 200, await openLoginPage(body));
    return;
  }
  if (url.pathname === '/api/oa/login/start') {
    sendJson(response, 200, await openLoginPage({ system: 'oa', pageId: 'oa-portal' }));
    return;
  }
  if (url.pathname === '/api/oa/login/test-live') {
    const context = await edgeSession.getContext();
    sendJson(response, 200, await testOaLiveSession(context));
    return;
  }
  if (url.pathname === '/api/pdm/login/start') {
    sendJson(response, 200, await openLoginPage({ system: 'pdm' }));
    return;
  }
  if (url.pathname === '/api/pdm/login/test-live') {
    const context = await edgeSession.getContext();
    sendJson(response, 200, await testPdmLiveSession(context));
    return;
  }
  if (url.pathname === '/api/sso/open') {
    sendJson(response, 200, await openUrlInManagedEdge(body.url));
    return;
  }
  if (url.pathname === '/api/oa/scan') {
    sendJson(response, 200, await scanOaPage(body));
    return;
  }
  if (url.pathname === '/api/oa/fill') {
    sendJson(response, 200, await fillOaPage(body));
    return;
  }
  if (url.pathname === '/api/oa/inventory-query') {
    sendJson(response, 200, await queryOaInventory(body));
    return;
  }
  if (url.pathname === '/api/oa/stock-transfer') {
    sendJson(response, 200, await handleStockTransfer(body));
    return;
  }
  if (url.pathname === '/api/oa/outbound') {
    sendJson(response, 200, await handleOutbound(body));
    return;
  }
  if (url.pathname === '/api/oa/inbound') {
    sendJson(response, 200, await handleInbound(body));
    return;
  }
  if (url.pathname === '/api/oa/purchase') {
    sendJson(response, 200, await handlePurchase(body));
    return;
  }
  if (url.pathname === '/api/pdm/query') {
    sendJson(response, 200, await queryPdmMaterial(body));
    return;
  }
  if (url.pathname === '/api/wbs/get') {
    sendJson(response, 200, handleWbsKey(body, getWbs, '/api/wbs/get'));
    return;
  }
  if (url.pathname === '/api/wbs/upsert') {
    sendJson(response, 200, handleWbsUpsert(body));
    return;
  }
  if (url.pathname === '/api/wbs/archive') {
    sendJson(response, 200, handleWbsKey(body, archiveWbs, '/api/wbs/archive'));
    return;
  }
  if (url.pathname === '/api/wbs/delete') {
    sendJson(response, 200, handleWbsKey(body, deleteWbs, '/api/wbs/delete'));
    return;
  }
  if (url.pathname === '/api/wbs/resolve') {
    sendJson(response, 200, resolveWbs(body));
    return;
  }
  if (url.pathname === '/api/pdm/login-diagnose') {
    sendJson(response, 200, await diagnosePdmLogin(body));
    return;
  }
  if (url.pathname === '/api/pdm/auth-probe') {
    sendJson(response, 200, await probePdmAuth(body));
    return;
  }
  if (url.pathname === '/api/profile/cache') {
    await cachedProfileSession.close();
    sendJson(response, 200, cacheEdgeProfile({ force: body.force !== false }));
    return;
  }
  if (url.pathname === '/api/pdm/profile/cache') {
    await cachedProfileSession.close();
    sendJson(response, 200, cacheEdgeProfile({ force: body.force !== false }));
    return;
  }
  if (url.pathname === '/api/profile/close-edge-background') {
    sendJson(response, 200, closeEdgeBackgroundProcesses());
    return;
  }
  if (url.pathname === '/api/profile/test-login') {
    sendJson(response, 200, await testCachedProfileLogin());
    return;
  }
  if (url.pathname === '/api/pdm/profile/test') {
    await cachedProfileSession.close();
    sendJson(response, 200, await testPdmCachedProfileLogin());
    return;
  }
  if (url.pathname === '/api/session/diagnose') {
    sendJson(response, 200, await diagnoseSystemSession(body));
    return;
  }
  if (url.pathname === '/api/explore/page') {
    sendJson(response, 200, await explorePage(body));
    return;
  }

  sendJson(response, 404, { error: 'API route not found' });
}

const server = http.createServer(async (request, response) => {
  const url = new URL(request.url, `http://${request.headers.host || '127.0.0.1'}`);
  try {
    if (url.pathname.startsWith('/api/')) {
      await handleApi(request, response, url);
      return;
    }

    if (url.pathname.startsWith('/runtime/')) {
      const relative = url.pathname.slice('/runtime/'.length);
      const filePath = safeStaticPath(runtimeDir, `/${relative}`);
      if (!filePath || !fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
        response.writeHead(404);
        response.end('Not found');
        return;
      }
      sendFile(response, filePath);
      return;
    }

    const requestPath = url.pathname === '/' ? '/index.html' : url.pathname;
    const filePath = safeStaticPath(publicDir, requestPath);
    if (filePath && fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
      sendFile(response, filePath);
      return;
    }
    sendFile(response, path.join(publicDir, 'index.html'));
  } catch (error) {
    sendJson(response, 500, {
      error: error.message,
      stack: process.env.NODE_ENV === 'production' ? undefined : error.stack
    });
  }
});

server.listen(port, host, () => {
  console.log(`MEGAnt OA/PDM agent listening on http://${host}:${port}`);
  console.log(`Edge profile mode: ${edgeSession.profile.mode}`);
  console.log(`Edge user data dir: ${edgeSession.profile.userDataDir}`);
  console.log(`Edge profile name: ${edgeSession.profile.profileName || '(persistent root)'}`);
  setTimeout(autoLaunchManagedEdge, 500);
});

process.on('SIGINT', async () => {
  await edgeSession.close();
  process.exit(0);
});
