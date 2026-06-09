import fs from 'node:fs';
import path from 'node:path';
import { ensureDir, runtimeDir } from '../config.js';

const CATALOG_PATH = path.join(runtimeDir, 'option-catalog.json');
const CATALOG_VERSION = 1;

const STOCK_LOCATIONS = [
  ['D002', '设备零件仓'],
  ['A001', '成品仓'],
  ['B001', '原材料仓'],
  ['C001', '电子件仓'],
  ['D001', '辅料仓'],
  ['E001', '公共仓'],
  ['F001', '客户仓'],
  ['G001', '不良品仓'],
  ['H001', '实验室仓'],
  ['J001', '待处置仓'],
  ['K001', '借用料仓'],
  ['S001', '生产中转仓'],
  ['Z001', '苏州深圳仓']
];

const PURCHASE_GROUPS = [
  ['A01', '钣金'],
  ['A02', '机加件'],
  ['A03', '标准件1'],
  ['A04', '标准件2'],
  ['A05', '标准件3'],
  ['A06', '标准件4'],
  ['A07', '电子料'],
  ['A08', '产品线定制设备'],
  ['A09', '机器人及附件'],
  ['A10', '仪器仪表/设备'],
  ['A11', '视觉/光学'],
  ['A12', '试剂耗材'],
  ['A13', '服务'],
  ['A14', '标准件5'],
  ['B01', '固定资产']
];

const MRP_CONTROLLERS = [
  ['P01', 'PAS PDT'],
  ['P02', 'ILP PDT'],
  ['P03', '自动化耗材 PDT（禁用）'],
  ['P04', 'ILS PDT'],
  ['P05', 'MOMC PDT（禁用）'],
  ['P06', '3D细胞培养 PDT（禁用）'],
  ['P07', '晶圆切割 PDT'],
  ['P08', '激光加工 PDT'],
  ['P09', '晶圆检测 PDT'],
  ['P10', '封装检测 PDT（禁用）'],
  ['P11', '半导体材料 PDT'],
  ['P12', '显示面板 PDT（禁用）'],
  ['P13', '锂电 PDT'],
  ['P14', '零售自动化 PDT'],
  ['P15', '原PABU生命健康苏州-禁用'],
  ['P16', 'DAS PDT'],
  ['P17', '原PABU智能制造-禁用'],
  ['P18', '原PABU智慧工厂-禁用'],
  ['P19', '数字化工厂 PDT'],
  ['P20', '自动化三部-禁用'],
  ['P21', 'CMS研发组'],
  ['P22', 'ACRO'],
  ['P23', '电测系统 PDT'],
  ['P24', 'BPA PDT'],
  ['P25', 'IAAS PDT(禁用）'],
  ['P29', '视觉检测 PDT'],
  ['P30', '细胞成像 PDT'],
  ['P83', 'MEPC'],
  ['P84', 'SCBU-研发管理部'],
  ['P85', 'SCBU-电测技术TDT'],
  ['P86', 'SCBU-显微成像TDT'],
  ['P87', 'SCBU-轩辕实验室'],
  ['P88', '营销业务中心'],
  ['P89', 'SCBU-产品部'],
  ['P91', '数字化中心MRP'],
  ['P92', '工程项目MRP'],
  ['P93', '承影研究院-ADAT'],
  ['P94', '承影研究院-AIDD'],
  ['P95', '承影研究院-Biolauto ST'],
  ['P96', '承影研究院-NITD'],
  ['P97', 'RDC-光谱色谱TDT'],
  ['P98', 'RDC-产品技术开发部'],
  ['P99', 'MAPP'],
  ['PP1', '原料MRP控制者'],
  ['PP2', '辅料MRP控制者'],
  ['PP3', '成品/半成品MRP控制者'],
  ['P28', 'MEPC-无损检测产品线']
];

const MATERIAL_GROUPS = [
  ['101001', '成品-试剂'],
  ['102001', '成品-耗材'],
  ['103001', '成品-仪器设备'],
  ['104001', '成品-解决方案'],
  ['201001', '服务-软件'],
  ['202001', '服务-实验室服务'],
  ['202002', '服务-售后服务'],
  ['203001', '服务-知识产品'],
  ['301001', '半成品-PCBA半成品'],
  ['302001', '半成品-部装组件'],
  ['401001', '机械标准件-气动件'],
  ['401002', '机械标准件-电机及附件'],
  ['401003', '机械标准件-机械传动件'],
  ['401004', '机械标准件-机器人及附件'],
  ['401005', '机械标准件-电动夹爪'],
  ['401006', '机械标准件-传感器'],
  ['401007', '机械标准件-紧固件'],
  ['401008', '机械标准件-密封件'],
  ['401009', '机械标准件-弹簧'],
  ['401010', '机械标准件-散热件'],
  ['401011', '机械标准件-液压配件'],
  ['401012', '机械标准件-结构配件'],
  ['402001', '电气标准件-电气控制类'],
  ['402002', '电气标准件-低压电气件'],
  ['402003', '电气标准件-电源'],
  ['402004', '电气标准件-连接器'],
  ['402005', '电气标准件-电气控制模块'],
  ['402006', '电气标准件-电气通讯'],
  ['402007', '电气标准件-线束类'],
  ['402008', '电气标准件-灯'],
  ['402009', '电气标准件-电气辅料'],
  ['403001', '电子件-电阻'],
  ['403002', '电子件-电容'],
  ['403003', '电子件-电感'],
  ['403004', '电子件-二极管'],
  ['403005', '电子件-晶体管'],
  ['403006', '电子件-运算放大器'],
  ['403007', '电子件-时钟管理'],
  ['403008', '电子件-传感器电子元件'],
  ['403009', '电子件-电源管理'],
  ['403010', '电子件-功能集成电路'],
  ['403011', '电子件-电子集成模块'],
  ['403012', '电子件-发声器件'],
  ['403013', '电子件-保险丝'],
  ['403014', '电子件-信号继电器'],
  ['403015', '电子件-编码元件'],
  ['403016', '电子件-接插件'],
  ['403017', '电子件-开关'],
  ['403018', '电子件-显示模块'],
  ['403019', '电子件-PCB'],
  ['403020', '电子件-变压器'],
  ['404001', '电池'],
  ['405001', '视觉-相机'],
  ['405002', '视觉-镜头及附件'],
  ['405003', '视觉-视觉控制器'],
  ['405004', '视觉-图像采集卡'],
  ['405005', '视觉-光源'],
  ['405006', '视觉-光源控制器'],
  ['405007', '视觉-视觉线缆'],
  ['406001', '光学'],
  ['407001', '试剂耗材'],
  ['407002', '实验用品'],
  ['408001', '仪器仪表'],
  ['409001', '设备'],
  ['410001', '定制设备'],
  ['410002', '定制治具'],
  ['411001', '生产耗材'],
  ['412001', '标签标识'],
  ['412002', '定制铭牌'],
  ['413001', '工具'],
  ['413002', '量具'],
  ['414001', '包装材料'],
  ['415001', '劳保用品-项目'],
  ['416001', '电脑及周边-项目'],
  ['501001', '加工件-机加件'],
  ['501002', '加工件-钣金件'],
  ['501003', '加工件-机架'],
  ['501004', '加工件-冲压件'],
  ['501005', '加工件-注塑件'],
  ['601001', '费用-技术服务'],
  ['601002', '费用-加工件返修服务'],
  ['601003', '费用-物料加工'],
  ['601004', '费用-修理维护'],
  ['601005', '费用-检测检验'],
  ['601006', '费用-人力外包服务-整机外包'],
  ['601007', '费用-人力外包服务-工时外包'],
  ['601008', '费用-软件外包服务'],
  ['601009', '费用-租赁服务-设备租赁'],
  ['601010', '费用-租赁服务-场地租赁'],
  ['601011', '费用-租赁服务-其他租赁'],
  ['601012', '费用-仓储费用-外仓租赁'],
  ['601013', '费用-仓储费用-其他'],
  ['601014', '费用-物流服务'],
  ['601015', '费用-劳动保护'],
  ['601016', '费用-低值易耗品'],
  ['701001', '固资-实验室设备及仪器'],
  ['701002', '固资-生产设备及仪器'],
  ['701003', '固资-研发设备及仪器'],
  ['701004', '固资-生产及研发用器具及工具'],
  ['701005', '固资-其它'],
  ['701006', '固资-无形资产'],
  ['702001', '行政固资-家具用品'],
  ['702002', '行政固资-办公设备'],
  ['702003', '行政固资-电子设备'],
  ['702004', '行政固资-交通工具'],
  ['703001', '固资-房屋建筑物'],
  ['801001', '研发测试']
];

function codeNameOptions(rows) {
  return rows.map(([value, name]) => ({ value, label: `${value} - ${name}` }));
}

function nameCodeOptions(rows) {
  return rows.map(([value, name]) => ({ value: name, label: `${name} - ${value}` }));
}

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
  'oa.stockLocationSapCode': {
    label: '库存地点SAP',
    defaultValue: '',
    options: codeNameOptions(STOCK_LOCATIONS)
  },
  'oa.stockLocationName': {
    label: '库存地点名称',
    defaultValue: '',
    options: nameCodeOptions(STOCK_LOCATIONS)
  },
  'oa.mrpController': {
    label: 'MRP控制者',
    defaultValue: '',
    options: codeNameOptions(MRP_CONTROLLERS)
  },
  'oa.purchaseGroup': {
    label: '采购组',
    defaultValue: '',
    options: codeNameOptions(PURCHASE_GROUPS)
  },
  'oa.materialGroup': {
    label: '物料组',
    defaultValue: '',
    options: codeNameOptions(MATERIAL_GROUPS)
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
  const seen = new Set();
  const options = [];
  const defaultOptions = Array.isArray(defaults.options) ? defaults.options : [];
  const runtimeOptions = Array.isArray(group.options) ? group.options : [];
  for (const item of [...defaultOptions, ...runtimeOptions]) {
    const option = normalizeOption(item);
    if (!option || seen.has(option.value)) continue;
    seen.add(option.value);
    options.push(option);
  }
  const defaultValue = normalizeText(group.defaultValue ?? defaults.defaultValue);
  if (defaultValue && !seen.has(defaultValue)) {
    options.unshift({ value: defaultValue, label: defaultValue });
  }
  return {
    label: normalizeText(group.label ?? defaults.label),
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
