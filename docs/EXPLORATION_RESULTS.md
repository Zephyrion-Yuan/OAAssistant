# OA/PDM 探索结果

更新时间：2026-05-27

## 登录状态

- OA 使用工具托管的 isolated Edge profile：`.runtime/edge-profile`。
- OA 入口统一为 `https://oa.megarobo.info/wui/index.html?#/main/portal/portal-1-1?menuIds=0,1&menuPathIds=0,1&_key=tcagna`。
- OA portal 测试通过，页面标题为 `镁伽OA`，未触发重新登录。
- PDM 使用普通 Edge 登录后缓存的 profile：`.runtime/edge-profile-cache/User Data/Default`。
- PDM 物料查询页面测试通过，未触发重新登录。

## 已固化脚本索引

- PDM 主数据物料查询：`npm.cmd run pdm:query`
- PDM 页面探索（缓存 profile）：`npm.cmd run pdm:explore`
- OA workflow 458 采购申请：`npm.cmd run oa:purchase-from-excel`
- OA workflow 412 物资出库：`npm.cmd run oa:outbound-from-excel`
- OA workflow 414 物资入库：`npm.cmd run oa:inbound-from-excel`
- OA workflow 89 库存转储：`npm.cmd run oa:stock-transfer-from-excel`
- 通用页面探索：`npm.cmd run explore:page`

## OA 字段扫描

原始字段汇总文件：`.runtime/oa-field-summary/summary-latest.json`

可复核命令：

```powershell
npm.cmd run oa:summarize-summary
```

### 采购申请流程（生产和研发物资） workflowid=458

- 字段数：59
- 必填字段：11
- 可编辑字段：26
- 页面按钮：`提 交`、`保 存`、`上传附件`
- 必填字段：
  - `main.field10442` 申请人 `sqr`
  - `main.field10444` 项目经理 `xmjl`
  - `main.field10445` 是否为项目型 `sfwxmx`
  - `main.field10448` PDT `pdt`
  - `main.field10449` BU `bu`
  - `main.field10450` 需求公司 `gs`
  - `main.field10452` 采购类型 `cglx`
  - `detail_1.field10460` 数量 `sl`
  - `detail_1.field10462` 总量 `zl`
  - `detail_1.field10468` 请购原因 `qgyy`
  - `detail_1.field10469` 需求日期 `xqrq`

### 物资出库流程 workflowid=412

- 字段数：100
- 必填字段：13
- 可编辑字段：64
- 页面按钮：`提 交`、`保 存`、`库存查询（物料）`、`库存查询（物料+WBS）`
- 必填字段：
  - `main.field6985` 申请人 `sqr`
  - `main.field7216` 凭证日期 `pzrq`
  - `main.field7245` 所属记账主体 `szjzzt`
  - `main.field7474` 出库类型 `chuklx`
  - `main.field7482` 成本中心 `cbzx`
  - `main.field12742` 用途 `yt`
  - `detail_1.field6998` 单位 `dw`
  - `detail_1.field7219` 申请数量 `sqsl`
  - `detail_1.field7272` 工厂 `gc`
  - `detail_1.field7273` 库存地点 `kcdd`
  - `detail_2.field8315` 申请数量 `sqsl`
  - `detail_2.field8317` 单位 `dw`
  - `detail_2.field9378` 库存地点 `kcdd2`

### 物资入库流程 workflowid=414

- 字段数：73
- 必填字段：7
- 可编辑字段：31
- 页面按钮：`提 交`、`保 存`、`库存查询（物料）`、`库存查询（物料+WBS）`
- 必填字段：
  - `main.field7315` 申请人 `sqr`
  - `main.field7527` 所属记账主体 `szjzzt`
  - `main.field7529` 入库类型 `rklx`
  - `detail_1.field7589` 申请入库(退料)数量 `sqrktlsl`
  - `detail_1.field7592` 库存地点 `kcdd`
  - `detail_2.field8422` 申请入库(退料)数量 `sqrktlsl`
  - `detail_2.field9433` 库存地点 `kcdd2`

### 库存转储流程 workflowid=89

- 字段数：44
- 必填字段：10
- 可编辑字段：30
- 页面按钮：`提 交`、`保 存`、`库存查询（物料）`、`库存查询（物料+WBS）`、`快捷选择人员`
- 必填字段：
  - `main.field8399` 移动类型 `ydlx`
  - `main.field8400` 凭证日期 `pzrq`
  - `main.field8401` 过账日期 `gzrq`
  - `main.field8513` 工厂 `gc`
  - `main.field13563` 仓库类型 `cklx`
  - `detail_1.field8402` 物料编码 `wlbm`
  - `detail_1.field8404` 数量 `sl`
  - `detail_1.field8405` 单位 `dw`
  - `detail_1.field8646` 转出库存地点 `zckcdd`
  - `detail_1.field8647` 转入库存地点 `zrkcdd`

## OA 接口发现

四个流程均出现以下 workflow 接口：

- `POST /api/workflow/reqform/loadForm`
- `POST /api/workflow/layout/getFlowChartInfo`
- `POST /api/workflow/requestAttention/getAttentionTypeSet`
- `POST /api/workflow/reqform/detailData`
- `POST /api/workflow/reqform/rightMenu`
- `POST /api/workflow/reqform/signInput`
- `POST /api/workflow/reqform/getFormTab`
- `POST /api/workflow/linkage/reqFieldSqlResult`
- `POST /api/workflow/linkage/reqDataInputResult`
- `POST /api/workflow/injectDev/loadFormDevFileList`
- `GET /api/workflow/reqform/scripts`
- `GET /api/workflow/forward/getReqWfNodeOperators`

`workflowid=89` 额外出现 `POST /api/workflow/formula/assignValue`。下一步填单脚本应优先复用页面 DOM 触发联动，再根据接口响应补齐自动带出的字段。

## PDM 主数据物料查询

完整探索和固化记录已整理到：

- `docs/explorations/pdm-master-data-material/README.md`

保留在总览中的结论：稳定入口为 `https://pdm.megarobo.info/masterdata/master-data-material`，旧入口 `https://pdm.megarobo.info/material/material-form` 仍作为兼容入口记录。页面标题为 `物料管理 - MegaPDM`，筛选字段包括物料编码、物料名称、规格型号、物料组编码、物料组描述、品牌、物料等级；搜索按钮为 `搜 索`，分页按钮包括 `下一页`。

当前分页接口由页面自身触发，脚本只监听响应，不读取 token/cookie/Authorization header：

`GET https://pdm-api.megarobo.info/admin-api/master/data/material/page?pageNo=<n>&pageSize=20&materialCode=...`

`GET https://pdm-api.megarobo.info/admin-api/master/data/material/page?pageNo=<n>&pageSize=20&materialName=...`

返回结构为 `data.list` 和 `data.total`。已固化 `npm.cmd run pdm:query`，支持 `--material-code` 精确查询、`--material-code-like` 编码模糊/前缀查询、`--material-name` 名称模糊查询，以及规格型号、物料组编码、物料组描述、品牌、物料等级筛选。输出包含 `rows` 原始完整字段和 `organizedRows` 中文字段整理结果。

验证结果：`--material-code 4000059295 --max-pages 2` 返回 1 条 `Octet链霉亲和素SA传感器`；`--material-name "人力外包" --max-pages 2` 返回总数 24 条，自动读取 2 页且未截断。

## 固化结论

- OA 的可持续方案是工具托管 Edge 活会话，失效时由前端打开二维码页面给人工扫码。
- PDM 的可持续方案是人工在普通 Edge 完成 SSO 后缓存 profile，后续查询使用缓存 profile。
- OA 字段填充需要按照 `viewattr=3` 必填、`viewattr=2` 可编辑、`htmltype/detailtype/dbType` 分类型处理。
- 带 `browser.*` 的 OA 字段需要后续单独固化选择器或查询弹窗/API，例如 PDT、需求公司、工厂、库存地点、WBS、物料编码。
- PDM 查询 API 已可作为 OA 自动填单前的物料信息来源。

## 2026-05-09 OA 采购申请流程（生产和研发物资）workflowid=458

该页面的完整探索记录、WBS 回填核对、Excel 附件校验规则、固化脚本命令说明，已独立整理到：

- `docs/explorations/oa-purchase-workflow-458/README.md`

保留在总览中的结论：稳定入口使用 `workflowid=458` 的创建 URL，不固化 `_key`、`_rdm`、`preloadkey`、`timestamp`；WBS 查询只需输入 `WBS编码`；WBS 点选后仍需显式填写 `是否为项目型`、`采购类型`、`需求公司`；固化脚本会点击 `保存`，不会点击 `提交` 或审批/付款/删除/发布/发送类按钮。

## 2026-05-09 OA 物资出库流程 workflowid=412

该页面的长期入口提取和无 interaction 探索记录已独立整理到：

- `docs/explorations/oa-outbound-workflow-412/README.md`

保留在总览中的结论：稳定入口使用 `workflowid=412` 的创建 URL，不固化 `_key`、`_rdm`、`preloadkey`、`timestamp`；本次 `/api/explore/page` 无 interaction 探索未触发提交/保存/查询动作，确认页面已登录、标题为 `创建 - 物资出库流程`、初始加载触发 180 个 XHR/fetch；顶部按钮包含 `提 交`、`保 存`、`库存查询（物料）`、`库存查询（物料+WBS）`。字段全集沿用既有 OA 字段扫描结论：workflowid=412 共 100 个字段、13 个必填字段、64 个可编辑字段。

## 2026-05-11 OA 物资出库流程 workflowid=412 项目预留出库

完整探索和固化记录已整理到：

- `docs/explorations/oa-outbound-workflow-412/2026-05-11-material-outbound-flow.md`

保留在总览中的结论：`所属记账主体` 使用 `browser.xmcj_gsdm`，示例 `1010 -> 苏州镁伽科技有限公司`；`成本中心` 必须在记账主体后使用 `browser.CBZXGLGS` 检索 `成本中心名称`，示例 `产品开发部(ACRO) -> 101BU06015`；`用途` 使用 `browser.yt`，当前固化 `R -> 研发项目-研发领料`、`C -> 交付项目-厂内调试`；`预留号` 使用 `browser.ReservedInformationDate`，检索 `WERKS=1010` 和 `ZYL3=C2-0225002.06.01` 返回示例预留号 `30659`。点选预留号后调用 `GET /api/querySAPActionApi/IF031` 并生成物资明细，脚本勾选 `#oTable1` 可见复选框、按 `LT_DATA[].BDMNG` 填 `#field8315_<rowIndex>`。保存草稿调用 `POST /api/workflow/reqform/requestOperation`，`src=save`，本次探索返回 `requestid=1437117`；全程未点击 `提 交` 或审批/付款/删除/发布/发送类按钮。

## 2026-05-12 OA 物资入库流程 workflowid=414

完整探索记录和入库页固化候选流程已整理到：

- `docs/explorations/oa-inbound-workflow-414/README.md`
- `docs/OA_WORKFLOW_AUTOMATION_PLAYBOOK.md`

保留在总览中的结论：稳定入口使用 `workflowid=414` 的创建 URL，不固化 `_rdm`、`preloadkey`、`timestamp`、`_key`；无 interaction 初扫确认页面标题为 `创建 - 物资入库流程`，顶部按钮包含 `提 交`、`保 存`、`库存查询（物料）`、`库存查询（物料+WBS）`。入库类型下拉包含 `成本中心退料`、`项目退料`、`项目副产品入库`、`内部订单退料`；项目退料时关联出库凭证使用 `browser.XMTL`，选择示例凭证 `4900119097` 后会通过 `POST /api/workflow/linkage/reqDataInputResult` 回填成本中心、用途、PDT、项目和项目名称，并生成 `detail_1` 明细。明细申请入库数量 selector 为 `#field7589_<rowIndex>`，库存地点 selector 为 `#field7592_<rowIndex>span > div:nth-of-type(2) > button`，库存地点弹窗使用 `browser.KCDD_RK_DT1`，返回库存地点、工厂、SAP 编码。项目副产品入库使用 `#oTable1` 和 `browser.ReservedInformationDate581` 预留号弹窗；内部订单退料使用 `browser.nbddtl` 关联出库记录弹窗。已新增 `npm.cmd run oa:inbound-from-excel`，默认按项目编码找项目退料出库凭证、按采购表物料数量填申请入库数量、允许保存草稿；多凭证/库存地点/数量无法唯一确定时返回 `needsInput=true`。

## 2026-05-12 OA 库存转储流程 workflowid=89

完整探索记录和固化脚本说明已整理到：

- `docs/explorations/oa-stock-transfer-workflow-89/README.md`
- `docs/OA_NEW_FORM_AUTOMATION_STRATEGY.md`

保留在总览中的结论：稳定入口使用 `workflowid=89` 的创建 URL，不固化 `_rdm`、`preloadkey`、`timestamp`、`_key`；页面标题为 `创建 - 库存转储流程申请表`，顶部按钮包含 `提 交`、`保 存`、`库存查询（物料）`、`库存查询（物料+WBS）`、`快捷选择人员`。必填字段包括主表移动类型、凭证日期、过账日期、工厂、仓库类型，以及明细物料编码、数量、单位、转出库存地点、转入库存地点。工厂使用 `browser.GC`，示例 `1010 -> 苏州镁伽科技工厂`；物料使用 `browser.materialDate`，查询 input 需用 `#MATNR:visible`，示例物料 `4000059295` 会回填描述、规格和单位；转出/转入库存地点均使用 `browser.KCDD_ZC`，1010 示例候选包含 `设备零件仓/D002`、`成品仓/A001`、`原材料仓/B001`；WBS 使用 `browser.WBSDate`，查询 input 为 `#POSID:visible`。已新增 `npm.cmd run oa:stock-transfer-from-excel`，默认不保存，传 `--save` 才保存草稿；`/api/explore/page` 不保存干跑已验证 `4000059295 / 2.000 / D002 -> A001` 可回显到页面；当前安全固化只支持页面已有明细行，Excel 多物料超过可见行数时返回 `needsInput=true`。

## 2026-06-01 库存查询入口（已发现，待捕获）

OA 表单页（412/414/89）内置三个「库存查询」入口，是后续「库存驱动决策路由」(Stage 3b) 判断「物料是否有库存、在哪个仓」的候选数据源。**目前只完成了入口发现，从未真正点击/捕获查询结果。**

- 顶栏按钮 `库存查询（物料）`、`库存查询（物料+WBS）`：text 定位（`#weareqtop_<rand>...button:nth-of-type(1)/(2)`，前缀含随机串，按文字点更稳）。
- 浏览字段 `物资库存查询`（最稳）：414 上 selector `#field10037span > div:nth-of-type(2) > button`，browser type `browser.SAPInventoryQueryInterface`。

证据（仅发现、未查询）：
- 这些只出现在「无 interaction 扫描」的元素清单（`interactive | no`，未点击）；`.runtime/exploration/` 中无任何库存数量字段被捕获（`现存量/可用量/非限制/LABST/MARD/MCHB` 零命中）。
- 唯一打通的 browser 接口是 `/api/public/browser/data/161`，用途是 WBS/工厂/成本中心/预留/库存地点的**选择**，非库存查询。
- 易混淆但都不是「在库量」：预留弹窗（SAP IF031）= 需求/预留量(BDMNG)；库存地点选择器（`browser.KCDD_ZC`/`KCDD_RK_DT1`）= 地点候选（名称/工厂/SAP码），不带数量；PDM 物料页 = 主数据，无库存。

下一步（需登录态 session，照本节 + 412 README 第 112 行的要求）：点开上述入口之一 → 记录弹窗检索字段、查询接口 path/params、结果列（确认含 工厂 + 库存地点 + 在库数量）、翻页/点选方式 → 固化为执行端 `inventory_query` + 图的 `route_workflow` 决策节点。
