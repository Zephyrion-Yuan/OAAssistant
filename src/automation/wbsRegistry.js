// WBS registry — user-managed business master data (Node-owned source of truth).
//
// Each WBS code binds the surrounding info the OA workflows need (project def,
// factory, cost center, purchaser, MRP controller, default stock location,
// demand-date offset, remark). The LangGraph orchestrator only READS this via
// the Executor contract (query_wbs over HTTP); all editing happens here through
// the control panel. JSON-file backed (small dataset, zero new dependency);
// swap to node:sqlite later if real SQL is wanted.
//
// This is local, read-only-natured business master data: it holds no SSO URLs,
// cookies, tokens, passwords, or MFA — only fields the user types in.
import fs from 'node:fs';
import path from 'node:path';
import { ensureDir, runtimeDir } from '../config.js';

const REGISTRY_PATH = path.join(runtimeDir, 'wbs-registry.json');
const REGISTRY_VERSION = 1;
const STATUS_VALUES = new Set(['active', 'archived']);

// field -> normalizer; wbsCode is the primary key.
const TEXT_FIELDS = [
  'wbsCode',
  'alias',              // 别称: comma/;-separated nicknames for fuzzy/NL reference
  'projectDefinition',
  'demandFactoryCode',
  'costCenter',
  'purchaser',          // 458 申请人, in 工号-姓名 format (e.g. ZN092-张三)
  'mrpController',
  'stockLocationName',
  'stockLocationSapCode',
  'deliveryAddress',    // 458 送货地址 (per-project fixed address)
  'remark'
];

function nowIso() {
  return new Date().toISOString();
}

function normalizeText(value) {
  return String(value ?? '').trim();
}

function normalizeOffset(value) {
  if (value === null || value === undefined || value === '') return null;
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

function emptyRegistry() {
  return { version: REGISTRY_VERSION, records: {} };
}

function loadRegistry() {
  if (!fs.existsSync(REGISTRY_PATH)) return emptyRegistry();
  try {
    const parsed = JSON.parse(fs.readFileSync(REGISTRY_PATH, 'utf8'));
    if (!parsed || typeof parsed !== 'object' || typeof parsed.records !== 'object') {
      return emptyRegistry();
    }
    return { version: parsed.version || REGISTRY_VERSION, records: parsed.records || {} };
  } catch {
    return emptyRegistry();
  }
}

function saveRegistry(registry) {
  ensureDir(runtimeDir);
  const tmp = `${REGISTRY_PATH}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(registry, null, 2), 'utf8');
  fs.renameSync(tmp, REGISTRY_PATH); // atomic replace
}

function emptyRecordShape() {
  return Object.fromEntries(TEXT_FIELDS.map((field) => [field, '']));
}

export function listWbs({ includeArchived = false } = {}) {
  const { records } = loadRegistry();
  const rows = Object.values(records)
    .filter((record) => includeArchived || record.status !== 'archived')
    .sort((a, b) => String(a.wbsCode).localeCompare(String(b.wbsCode)));
  return { ok: true, count: rows.length, records: rows };
}

export function getWbs(input = {}) {
  const wbsCode = normalizeText(input.wbsCode);
  if (!wbsCode) return { ok: false, error: 'wbsCode is required.' };
  const { records } = loadRegistry();
  const record = records[wbsCode] || null;
  return { ok: true, found: Boolean(record), record };
}

// Merge-upsert: only fields present in `input` overwrite; unspecified fields on
// an existing record are preserved (partial updates are safe). The control panel
// sends the full record, so it gets a full write either way.
export function upsertWbs(input = {}) {
  const wbsCode = normalizeText(input.wbsCode);
  if (!wbsCode) return { ok: false, error: 'wbsCode is required.' };
  const registry = loadRegistry();
  const existing = registry.records[wbsCode];
  const record = existing ? { ...existing } : emptyRecordShape();

  for (const field of TEXT_FIELDS) {
    if (input[field] !== undefined) record[field] = normalizeText(input[field]);
  }
  record.wbsCode = wbsCode;
  if (input.demandDateOffsetDays !== undefined) {
    record.demandDateOffsetDays = normalizeOffset(input.demandDateOffsetDays);
  } else if (record.demandDateOffsetDays === undefined) {
    record.demandDateOffsetDays = null;
  }
  if (input.status !== undefined) {
    const status = normalizeText(input.status).toLowerCase();
    record.status = STATUS_VALUES.has(status) ? status : 'active';
  } else if (!record.status) {
    record.status = 'active';
  }
  record.createdAt = existing?.createdAt || nowIso();
  record.updatedAt = nowIso();

  registry.records[wbsCode] = record;
  saveRegistry(registry);
  return { ok: true, created: !existing, record };
}

export function archiveWbs(input = {}) {
  const wbsCode = normalizeText(input.wbsCode);
  if (!wbsCode) return { ok: false, error: 'wbsCode is required.' };
  const registry = loadRegistry();
  const record = registry.records[wbsCode];
  if (!record) return { ok: false, error: `Unknown WBS: ${wbsCode}` };
  record.status = 'archived';
  record.updatedAt = nowIso();
  saveRegistry(registry);
  return { ok: true, record };
}

export function deleteWbs(input = {}) {
  const wbsCode = normalizeText(input.wbsCode);
  if (!wbsCode) return { ok: false, error: 'wbsCode is required.' };
  const registry = loadRegistry();
  if (!registry.records[wbsCode]) return { ok: false, error: `Unknown WBS: ${wbsCode}` };
  delete registry.records[wbsCode];
  saveRegistry(registry);
  return { ok: true, deleted: wbsCode };
}

function aliasList(record) {
  return String(record.alias || '').split(/[,;，；]/).map((s) => s.trim()).filter(Boolean);
}

// Resolve a free-text/alias/code reference to a single WBS record. Deterministic,
// case-insensitive: exact wbsCode → exact alias → fuzzy substring on
// alias/projectDefinition/wbsCode. matched is set only on a single confident hit;
// otherwise candidates lists the near-misses (the caller can ask the user).
export function resolveWbs(input = {}) {
  const query = normalizeText(input.query ?? input.wbs ?? input.alias ?? '');
  if (!query) return { ok: false, error: 'query is required.' };
  const q = query.toLowerCase();
  const active = Object.values(loadRegistry().records).filter((r) => r.status !== 'archived');

  const byCode = active.find((r) => String(r.wbsCode).toLowerCase() === q);
  if (byCode) return { ok: true, query, matched: byCode, matchType: 'code', candidates: [] };

  const byAlias = active.filter((r) => aliasList(r).some((a) => a.toLowerCase() === q));
  if (byAlias.length === 1) return { ok: true, query, matched: byAlias[0], matchType: 'alias', candidates: [] };
  if (byAlias.length > 1) return { ok: true, query, matched: null, matchType: 'alias-ambiguous', candidates: byAlias };

  const fuzzy = active.filter((r) => {
    const hay = [String(r.wbsCode), String(r.projectDefinition), ...aliasList(r)].map((s) => s.toLowerCase());
    return hay.some((h) => h && (h.includes(q) || q.includes(h)));
  });
  if (fuzzy.length === 1) return { ok: true, query, matched: fuzzy[0], matchType: 'fuzzy', candidates: [] };
  return { ok: true, query, matched: null, matchType: fuzzy.length ? 'fuzzy-ambiguous' : 'none', candidates: fuzzy };
}

export const wbsRegistryPath = REGISTRY_PATH;
