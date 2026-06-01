# OA 物资入库流程 workflowid=414

记录日期：2026-05-12

## 页面入口

长期入口：

```text
https://oa.megarobo.info/spa/workflow/static4form/index.html#/main/workflow/req?iscreate=1&workflowid=414&isagent=0&beagenter=0&f_weaver_belongto_userid=&f_weaver_belongto_usertype=0
```

用户提供链接中的 `_rdm`、`preloadkey`、`timestamp`、`_key` 都是一次性打开参数，不应写入长期配置。`config/pages.json` 已更新 `oa-workflow-414` 为稳定入口。

## 探索产物

- 无 interaction 初扫：`.runtime/exploration/2026-05-12T07-01-01-300Z-oa-workflow-414-inbound-initial-no-interaction-scan-oa.megarobo.info.json`
- 所属记账主体弹窗：`.runtime/exploration/2026-05-12T07-02-46-852Z-oa-workflow-414-company-browser-popup-oa.megarobo.info.json`
- 下拉选项扫描：`.runtime/exploration/2026-05-12T07-03-48-870Z-oa-workflow-414-select-options-scan-oa.megarobo.info.json`
- 成本中心退料关联出库凭证弹窗：`.runtime/exploration/2026-05-12T07-04-45-703Z-oa-workflow-414-cost-center-return-outbound-voucher-popup-oa.megarobo.info.json`
- 项目退料关联出库凭证弹窗：`.runtime/exploration/2026-05-12T07-07-48-583Z-oa-workflow-414-project-return-outbound-voucher-popup-oa.megarobo.info.json`
- 项目退料选择凭证生成明细：`.runtime/exploration/2026-05-12T07-09-00-196Z-oa-workflow-414-select-project-return-voucher-scan-material-rows-oa.megarobo.info.json`
- 项目退料库存地点弹窗：`.runtime/exploration/2026-05-12T07-25-35-464Z-oa-workflow-414-project-return-stock-location-popup-oa.megarobo.info.json`
- 项目退料库存地点和数量干跑：`.runtime/exploration/2026-05-12T07-27-16-458Z-oa-workflow-414-project-return-select-stock-location-and-quantity-dry-run-oa.megarobo.info.json`
- 项目副产品入库模式扫描：`.runtime/exploration/2026-05-12T07-32-15-564Z-oa-workflow-414-project-byproduct-inbound-mode-scan-oa.megarobo.info.json`
- 内部订单退料弹窗扫描：`.runtime/exploration/2026-05-12T07-33-02-366Z-oa-workflow-414-internal-order-return-popup-scan-oa.megarobo.info.json`
- 项目副产品入库预留号弹窗：`.runtime/exploration/2026-05-12T07-33-57-228Z-oa-workflow-414-project-byproduct-reservation-popup-scan-oa.megarobo.info.json`

以上探索均未点击 `提交`、审批、付款、删除、发布或发送类按钮；库存地点和数量干跑未保存。

## 初始页面摘要

- 页面标题：`创建 - 物资入库流程`
- 顶部按钮：`提 交`、`保 存`、`库存查询（物料）`、`库存查询（物料+WBS）`
- 初始可见下拉：
  - `#weaSelect_1 > div > div[role="combobox"]`：仓库类型，默认 `非鲲鹏仓库`，可选 `鲲鹏仓库`、`非鲲鹏仓库`
  - `#weaSelect_2 > div > div[role="combobox"]`：入库类型，默认 `成本中心退料`，可选 `成本中心退料`、`项目退料`、`项目副产品入库`、`内部订单退料`
- 字段汇总：73 个字段，7 个必填字段，31 个可编辑字段。
- 必填字段：
  - `main.field7315` 申请人 `sqr`
  - `main.field7527` 所属记账主体 `szjzzt`
  - `main.field7529` 入库类型 `rklx`
  - `detail_1.field7589` 申请入库(退料)数量 `sqrktlsl`
  - `detail_1.field7592` 库存地点 `kcdd`
  - `detail_2.field8422` 申请入库(退料)数量 `sqrktlsl`
  - `detail_2.field9433` 库存地点 `kcdd2`

## 主表浏览字段

- `所属记账主体`：`#field7527span > div:nth-of-type(2) > button`
  - browser type：`browser.xmcj_gsdm`
  - 结果列：名称 `mc`、编码 `bm`
  - 示例：`1010 -> 苏州镁伽科技有限公司`
- `关联出库物料凭证`，成本中心退料：`#field9638span > div:nth-of-type(2) > button`
  - browser type：`browser.CBZXTL`
  - 结果列：物料凭证号、出库类型、用途、成本中心编号、成本中心名称、申请日期、申请人名称
- `关联出库物料凭证`，项目退料：`#field9637span > div:nth-of-type(2) > button`
  - browser type：`browser.XMTL`
  - 结果列：物料凭证号、出库类型、用途、项目编码、项目名称、申请日期、申请人名称
- `关联出库物料凭证`，内部订单退料：`#field17426span > div:nth-of-type(2) > button`
  - browser type：`browser.nbddtl`
  - 结果列：物料凭证号、出库类型、内部订单编码、成本中心、成本中心编号、申请日期、申请人
- `预留号`，项目副产品入库：`#field8834span > div:nth-of-type(2) > button`
  - browser type：`browser.ReservedInformationDate581`
  - 弹窗标题：`预留信息获取接口_项目副产品入库`
  - 检索字段：工厂必填；结果列包含预留/相关需求的编号、预留项目编号、工厂、物料编号、物料描述、基本计量单位、需求数量、提货数、WBS 编号、存储地点、组件的需求日期、网络号
- `物资库存查询`：`#field10037span > div:nth-of-type(2) > button`，对应 `browser.SAPInventoryQueryInterface`。

## 项目退料链路验证

测试选择 `入库类型=项目退料`，再选择关联出库凭证 `4900119097`。

选中后主表回填：

- 关联出库物料凭证：`4900119097`
- 成本中心：`售后组(视觉检测)`
- 成本中心编码：`102BU05036`
- 用途：`交付项目-售后`
- PDT：`视觉检测 PDT`
- PDT 负责人：`王树平`
- 项目：`C0-0223114`
- 项目名称：`小尺寸全自动绑定粒子压痕检查机`

选中后调用：

```text
POST /api/workflow/linkage/reqDataInputResult
```

响应中 `assignInfo_3675.addDetailRow.detail_1` 生成明细行，包含 `field7586` 物料编码、`field7588` 物料描述、`field8574` 规格型号、`field9431` 出库数量、`field7591` 工厂、`field7628` WBS 编号等。

生成的示例明细：

| 字段 | 值 |
| --- | --- |
| 预留行号 | `0001` |
| 物料编码 | `5000107131` |
| 物料描述 | `挡边固定板#C0-0223114-060-010-028-A` |
| 规格型号 | `C0-0223114-060-010-028-A` |
| 出库数量 | `4.000` |
| 单位 | `PC` |
| 工厂 | `深圳镁伽科技工厂` |
| WBS 编号 | `C0-0223114.99.02` |

## 明细字段

项目退料生成 `detail_1`，明细表为 `#oTable0`：

- 数量输入：`#field7589_<rowIndex>`
- 库存地点按钮：`#field7592_<rowIndex>span > div:nth-of-type(2) > button`
- 网络号输入：`#field7594_<rowIndex>`
- 序列号输入：`#field8261_<rowIndex>`
- 批次编号输入：`#field8729_<rowIndex>`
- 备注输入：`#field7595_<rowIndex>`

库存地点弹窗：

- browser type：`browser.KCDD_RK_DT1`
- 打开接口会带明细工厂参数，例如 `formtable_main_86_dt1_gc_<currenttime>=4`
- 结果列：库存地点 `kcdd`、工厂 `gc`、SAP 编码 `sapbm`
- 示例候选：`设备零件仓/D002`、`1020苏州仓/SZ01`、`成品仓/A001`、`原材料仓/B001`、`电子件仓/C001`

干跑选择 `设备零件仓` 后，明细库存地点回填为 `设备零件仓`。干跑填写 `#field7589_0=4.000` 成功，未保存。

## 项目副产品入库链路观察

选择 `入库类型=项目副产品入库` 后，页面切换到 `#oTable1` 明细表，表头包括：

```text
序号、预留行号、物料编码、物料描述、规格型号、申请入库(退料)数量、预留需求数量、单位、工厂、工厂按钮、工厂名称、库存地点、库存地点、库存地点名称、WBS编号、网络号、序列号、批次编号、备注
```

该类型显示 `#field8834span > div:nth-of-type(2) > button` 预留号按钮。打开弹窗时调用 `browser.ReservedInformationDate581`，只打开未填工厂时暂无数据；后续固化应按 412 的方式先输入工厂/WBS 或由业务规则确定检索条件。

## 内部订单退料链路观察

选择 `入库类型=内部订单退料` 后，关联出库凭证按钮为 `#field17426span > div:nth-of-type(2) > button`，打开弹窗：

- browser type：`browser.nbddtl`
- 弹窗标题：`物资出库记录-内部订单退料`
- 结果列：物料凭证号、出库类型、内部订单编码、成本中心、成本中心编号、申请日期、申请人
- 示例候选：`4900119191 | 内部订单退料 | 002000000560 | 2026-05-11 | 4408`
- 初始总数：1014 条，分页 102 页

本轮只打开弹窗，未选择内部订单退料记录。

## 可固化脚本的初步流程

已实现一个“项目退料入库”的脚本骨架：

1. 打开 `oa-workflow-414` 稳定入口。
2. 选择仓库类型，默认可保留 `非鲲鹏仓库`，如业务要求可改为 `鲲鹏仓库`。
3. 选择入库类型 `项目退料`。
4. 打开 `#field9637span > div:nth-of-type(2) > button`，按物料凭证号或项目编码检索，选择目标出库凭证。
5. 等待 `#field7589_0` 和 `#field7592_0span` 出现。
6. 对每个明细行选择库存地点。
7. 按业务规则填写 `#field7589_<rowIndex>` 申请入库数量；全量退料可用出库数量，部分退料需要用户或入参提供。
8. 按用户显式参数决定是否保存草稿；不得自动提交。

固化文件：

- 配置：`config/oa-workflow-414-inbound.json`
- Excel helper：`scripts/inbound_excel.py`
- Playwright 脚本：`scripts/oa-inbound-from-excel.js`
- npm 命令：`npm.cmd run oa:inbound-from-excel`

默认测试配置：

- 入库类型：`项目退料`
- 出库物料凭证检索：按项目编码，默认取 Excel 的 `项目定义`
- 数量规则：按采购表 `物料编码 -> 需求数量` 填写对应 OA 明细
- 保存：默认允许保存；使用 `--no-save` 可只干跑填单

示例命令：

```powershell
npm.cmd run oa:inbound-from-excel -- --file "D:\Desktop\采购申请\项目采购申请-SA探针.xlsx" --voucher-number 4900119097 --stock-location-name 设备零件仓
```

如果项目编码命中多个出库凭证、库存地点未提供、OA 明细物料无法从采购表唯一匹配数量，脚本会返回 `needsInput=true` 的 JSON，而不是猜测。

## 待用户确认的业务规则

- 本次入库申请的目标类型是 `项目退料`、`成本中心退料`、`项目副产品入库` 还是 `内部订单退料`。
- 出库凭证检索键：优先用物料凭证号，还是用项目编码/WBS/成本中心组合。
- 库存地点选择规则：按仓库类型、SAP 编码、库存地点名称固定选择，还是由入参提供。
- 申请入库数量规则：默认等于出库数量，还是由 Excel/用户输入指定部分数量。
- 是否需要自动保存草稿。保存是允许的草稿动作，但仍应由用户显式开启。
