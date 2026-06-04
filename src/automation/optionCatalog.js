import fs from 'node:fs';
import path from 'node:path';
import { ensureDir, runtimeDir } from '../config.js';

const CATALOG_PATH = path.join(runtimeDir, 'option-catalog.json');
const CATALOG_VERSION = 1;

const DEFAULT_GROUPS = {
  'oa458.projectType': {
    label: '是否为项目型',
    defaultValue: '是',
    options: [
      { value: '是', label: '是' },
      { value: '否', label: '否' }
    ]
  },
  'oa458.purchaseType': {
    label: '采购类型',
    defaultValue: '项目物资采购申请',
    options: [
      { value: '项目物资采购申请', label: '项目物资采购申请' }
    ]
  },
  'oa458.purchaseDemandType': {
    label: '附件需求类型',
    defaultValue: '02',
    options: [
      { value: '02', label: '02 - 采购申请+预留' }
    ]
  },
  'oa89.movementType': {
    label: '移动类型',
    defaultValue: '普通库存转储至普通库存',
    options: [
      { value: '普通库存转储至普通库存', label: '普通库存转储至普通库存' },
      { value: '普通库存转储至项目库存', label: '普通库存转储至项目库存' },
      { value: '项目库存转储至普通库存', label: '项目库存转储至普通库存' },
      { value: '项目库存转储至项目库存', label: '项目库存转储至项目库存' }
    ]
  },
  'oa412.warehouseType': {
    label: '仓库类型',
    defaultValue: '鲲鹏仓库',
    options: [
      { value: '鲲鹏仓库', label: '鲲鹏仓库' },
      { value: '非鲲鹏仓库', label: '非鲲鹏仓库' }
    ]
  },
  'oa414.inboundType': {
    label: '入库类型',
    defaultValue: '项目退料',
    options: [
      { value: '项目退料', label: '项目退料' },
      { value: '成本中心退料', label: '成本中心退料' },
      { value: '项目副产品入库', label: '项目副产品入库' },
      { value: '内部订单退料', label: '内部订单退料' }
    ]
  }
};

function normalizeText(value) {
  return String(value ?? '').trim();
}

function normalizeOption(option) {
  const value = normalizeText(typeof option === 'object' ? option.value : option);
  const label = normalizeText(typeof option === 'object' ? option.label : option) || value;
  return value ? { value, label } : null;
}

function normalizeGroup(group = {}, defaults = {}) {
  const merged = { ...defaults, ...group };
  const seen = new Set();
  const options = [];
  for (const item of merged.options || []) {
    const option = normalizeOption(item);
    if (!option || seen.has(option.value)) continue;
    seen.add(option.value);
    options.push(option);
  }
  const defaultValue = normalizeText(merged.defaultValue);
  if (defaultValue && !seen.has(defaultValue)) {
    options.unshift({ value: defaultValue, label: defaultValue });
  }
  return {
    label: normalizeText(merged.label),
    defaultValue,
    options
  };
}

function loadRuntimeCatalog() {
  if (!fs.existsSync(CATALOG_PATH)) return {};
  try {
    const parsed = JSON.parse(fs.readFileSync(CATALOG_PATH, 'utf8'));
    return parsed && typeof parsed.groups === 'object' ? parsed.groups : {};
  } catch {
    return {};
  }
}

export function optionCatalog() {
  const runtimeGroups = loadRuntimeCatalog();
  const groups = {};
  const keys = new Set([...Object.keys(DEFAULT_GROUPS), ...Object.keys(runtimeGroups)]);
  for (const key of keys) {
    groups[key] = normalizeGroup(runtimeGroups[key], DEFAULT_GROUPS[key]);
  }
  return {
    ok: true,
    version: CATALOG_VERSION,
    source: fs.existsSync(CATALOG_PATH) ? CATALOG_PATH : null,
    groups
  };
}

export function optionDefault(groupKey, fallback = '') {
  const group = optionCatalog().groups[groupKey];
  return normalizeText(group?.defaultValue) || fallback;
}

export function upsertOptionGroup(input = {}) {
  const key = normalizeText(input.key);
  if (!key) return { ok: false, error: 'key is required.' };
  const current = loadRuntimeCatalog();
  current[key] = normalizeGroup(input, DEFAULT_GROUPS[key]);
  ensureDir(runtimeDir);
  fs.writeFileSync(CATALOG_PATH, JSON.stringify({
    version: CATALOG_VERSION,
    groups: current,
    updatedAt: new Date().toISOString()
  }, null, 2), 'utf8');
  return { ok: true, key, group: current[key], catalog: optionCatalog() };
}
