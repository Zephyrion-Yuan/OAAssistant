# OA 库存转储流程 workflowid=89

记录日期：2026-05-12

## 页面入口

长期入口：

```text
https://oa.megarobo.info/spa/workflow/static4form/index.html#/main/workflow/req?iscreate=1&workflowid=89&isagent=0&beagenter=0&f_weaver_belongto_userid=&f_weaver_belongto_usertype=0
```

用户提供链接中的 `_rdm`、`preloadkey`、`timestamp`、`_key` 均为一次性打开参数，不应写入长期配置。`config/pages.json` 已将 `oa-workflow-89` 改为稳定入口。

## 探索产物

- 初始无 interaction 扫描：`.runtime/exploration/2026-05-12T08-37-31-363Z-oa-workflow-89-stock-transfer-initial-no-interaction-scan-oa.megarobo.info.json`
- 移动类型下拉扫描：`.runtime/exploration/2026-05-12T08-38-38-589Z-oa-workflow-89-movement-type-options-scan-oa.megarobo.info.json`
- 工厂弹窗：`.runtime/exploration/2026-05-12T08-39-17-405Z-oa-workflow-89-factory-browser-popup-oa.megarobo.info.json`
- 物料选择干跑：`.runtime/exploration/2026-05-12T08-48-04-968Z-oa-workflow-89-select-material-4000059295-with-visible-input-oa.megarobo.info.json`
- 转出库存地点弹窗：`.runtime/exploration/2026-05-12T08-49-20-714Z-oa-workflow-89-transfer-out-stock-location-popup-after-material-oa.megarobo.info.json`
- 转入库存地点弹窗：`.runtime/exploration/2026-05-12T08-50-04-926Z-oa-workflow-89-transfer-in-stock-location-popup-after-material-oa.megarobo.info.json`
- 项目库存转入 WBS 弹窗：`.runtime/exploration/2026-05-12T08-51-42-991Z-oa-workflow-89-transfer-in-wbs-popup-for-project-stock-movement-oa.megarobo.info.json`
- 不保存填单干跑：`.runtime/exploration/2026-05-12T09-15-03-048Z-oa-workflow-89-no-save-fill-dry-run-material-quantity-stock-locations-oa.megarobo.info.json`

以上探索未点击 `提交`、审批、付款、删除、发布、发送类按钮；未保存草稿。

## 字段和按钮摘要

- 页面标题：`创建 - 库存转储流程申请表`
- 顶部按钮：`提 交`、`保 存`、`库存查询（物料）`、`库存查询（物料+WBS）`、`快捷选择人员`
- 字段汇总：44 个字段，10 个必填字段，30 个可编辑字段。
- 必填主表字段：移动类型、凭证日期、过账日期、工厂、仓库类型。
- 必填明细字段：物料编码、数量、单位、转出库存地点、转入库存地点。

移动类型选项：`普通库存转储至普通库存`、`普通库存转储至项目库存`、`项目库存转储至普通库存`、`项目库存转储至项目库存`。`普通库存借料至普通库存` 和 `普通库存还料至普通库存` 是已取消选项，不作为默认自动化目标。

## 浏览字段

工厂：

- selector：`#field8513span > div:nth-of-type(2) > button`
- browser type：`browser.GC`
- 结果列：工厂名称、SAP 编码
- 示例：`1010 -> 苏州镁伽科技工厂`
- 选中后调用 `POST /api/workflow/formula/assignValue`，回填明细工厂 `field8406_0`。

物料编码：

- selector：`#field8402_<rowIndex>span > div:nth-of-type(2) > button`
- browser type：`browser.materialDate`
- 查询 input：`#MATNR:visible`
- 示例 `4000059295` 返回 1 条；选中后回填 `#field8403_0` 物料描述、`#field8570_0` 规格型号、`#field8405_0` 单位。

库存地点：

- 转出 selector：`#field8646_<rowIndex>span > div:nth-of-type(2) > button`
- 转入 selector：`#field8647_<rowIndex>span > div:nth-of-type(2) > button`
- browser type：`browser.KCDD_ZC`
- 结果列：库存地点、工厂、SAP 编码
- 1010 示例候选：`设备零件仓/D002`、`成品仓/A001`、`原材料仓/B001`

WBS：

- 转出 selector：`#field8409_<rowIndex>span > div:nth-of-type(2) > button`
- 转入 selector：`#field8412_<rowIndex>span > div:nth-of-type(2) > button`
- browser type：`browser.WBSDate`
- 查询 input：`#POSID:visible`
- 移动类型源为项目库存时填转出 WBS，目标为项目库存时填转入 WBS。

## 已固化脚本

新增文件：

- `config/oa-workflow-89-stock-transfer.json`
- `scripts/stock_transfer_excel.py`
- `scripts/oa-stock-transfer-from-excel.js`

新增命令：

```powershell
npm.cmd run oa:stock-transfer-from-excel
```

脚本入参：

- Excel 采购表：解析需求工厂代码、项目定义、WBS、物料编码、需求数量/采购数量、单位。
- 移动类型：默认 `普通库存转储至普通库存`，可用 `--movement-type` 覆盖。
- 仓库类型：默认保留页面值 `非鲲鹏仓库`，可用 `--warehouse-type` 设置。
- 库存地点：必须由入参提供；可分别传 `--transfer-out-stock-location-sap` 和 `--transfer-in-stock-location-sap`，或用名称参数。
- 数量：默认按采购表同物料编码汇总数量填 `#field8404_<rowIndex>`。
- 保存：默认不保存；只有传 `--save` 才点击 `保 存`。永不点击 `提 交`。

示例不保存命令：

```powershell
npm.cmd run oa:stock-transfer-from-excel -- --file "D:\Desktop\采购申请\项目采购申请-SA探针.xlsx" --transfer-out-stock-location-sap D002 --transfer-in-stock-location-sap A001
```

项目库存示例：

```powershell
npm.cmd run oa:stock-transfer-from-excel -- --file "D:\Desktop\采购申请\项目采购申请-SA探针.xlsx" --movement-type "普通库存转储至项目库存" --transfer-out-stock-location-sap D002 --transfer-in-stock-location-sap A001 --transfer-in-wbs C2-0225002.06.01
```

当前限制：

- 已确认页面初始只有 1 条可见明细行，尚未找到安全可见的新增明细行控件。脚本会先检查可见明细行数量；当 Excel 汇总后物料行数超过页面可见行数时返回 `needsInput=true`。
- 转出/转入项目经理字段不是必填字段，本轮未固化人员选择。
- 现场干跑因当前 Edge `MEGAntBot` profile 被现有浏览器/探索服务占用而未能启动独立脚本进程；需要关闭占用该 profile 的 Edge 后再运行脚本，或后续改造成复用本地服务会话的执行入口。

## 不保存干跑结果

通过 `/api/explore/page` 对示例 Excel 的核心动作做了不保存验证：

- 移动类型：`普通库存转储至普通库存`
- 工厂：`1010`
- 物料：`4000059295`
- 数量：`2`，页面规范化显示为 `2.000`
- 转出库存地点：`设备零件仓/D002`
- 转入库存地点：`成品仓/A001`

最终页面文本包含 `4000059295`、`苏州镁伽科技工厂`、`设备零件仓`、`成品仓`；未点击保存或提交。
