# OA 物资出库流程 workflowid=412

记录日期：2026-05-09

## 页面入口

从本次用户提供的一次性 URL 中提取的长期入口：

```text
https://oa.megarobo.info/spa/workflow/static4form/index.html#/main/workflow/req?iscreate=1&workflowid=412&isagent=0&beagenter=0&f_weaver_belongto_userid=&f_weaver_belongto_usertype=0
```

点击菜单或复制浏览器地址时出现的 `_rdm`、`preloadkey`、`timestamp`、`_key` 属于本次打开相关参数，不应固化。使用上面的稳定 URL 打开后，OA 前端会自行补 `_key`，页面仍进入“物资出库流程”创建页。

配置项：`config/pages.json` 中的 `oa-workflow-412`。

## 安全边界

- 使用项目的 Playwright 托管 Microsoft Edge 专用 profile。
- 用户先在该 profile 内完成人工登录。
- 自动化只打开白名单 OA 域名和稳定业务 URL。
- 当前探索未配置 interaction，未点击任何按钮。
- 后续固化可以触发明确记录的查询/选择动作，但不得自动点击 `提交`、审批、付款、删除、发布、发送等危险按钮。

## 探索产物

- 无 interaction 初扫 JSON：`.runtime/exploration/2026-05-09T09-13-02-288Z-oa-workflow-412-persistent-initial-scan-oa.megarobo.info.json`
- 无 interaction 初扫 Markdown：`.runtime/exploration/2026-05-09T09-13-02-288Z-oa-workflow-412-persistent-initial-scan-oa.megarobo.info.md`

## 无 Interaction 初扫

- `requiresLogin=false`
- 页面标题：`创建 - 物资出库流程`
- 目标 URL：稳定入口，不含 `_rdm`、`preloadkey`、`timestamp`、`_key`
- 最终 URL：OA 前端自动追加脱敏后的 `_key`
- 标准 DOM 字段识别数量：3。当前 `/api/explore/page` surface scanner 只识别到 3 个可见 combobox；OA 自定义表单字段主要通过 `loadForm` 响应和表格 DOM 暴露。
- 可见按钮数量：32。顶部业务按钮包含 `提 交`、`保 存`、`库存查询（物料）`、`库存查询（物料+WBS）`；其余主要是浏览字段按钮和签字意见富文本工具栏按钮。
- 可见表格数量：3。主表文本包含申请基本信息、物资信息、物资库存查询；明细表 `#oTable1` 当前 1 行，列包括预留行号、物料编码、物料描述、申请数量、单位、工厂、库存地点、WBS编号、子项目经理、批次编号、序列号、网络号、备注。
- 初始 XHR/fetch 数量：180。
- 本次未发现 list-like 包装接口；库存查询按钮需要后续显式 safe interaction 再探索。

## 可见字段

本次标准 DOM 扫描识别到 3 个可见下拉/combobox：

| 值 | selector | 说明 |
| --- | --- | --- |
| 项目领料 | `#weaSelect_1 > div > div[role="combobox"]` | 出库类型当前值 |
| 非鲲鹏仓库 | `#weaSelect_2 > div > div[role="combobox"]` | 仓库类型当前值 |
| 计划内 | `#weaSelect_3 > div > div[role="combobox"]` | 计划内/计划外当前值 |

字段全集沿用既有 OA 字段扫描结论：workflowid=412 共 100 个字段，13 个必填字段，64 个可编辑字段。

必填字段：

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

## 按钮摘要

- `提 交`：危险按钮，禁止自动点击。
- `保 存`：保存草稿按钮；后续若固化保存动作，必须单独确认并保持不提交。
- `库存查询（物料）`：安全查询候选按钮，尚未在本次无 interaction 扫描中点击。
- `库存查询（物料+WBS）`：安全查询候选按钮，尚未在本次无 interaction 扫描中点击。
- `#field6985span`、`#field7245span`、`#field12742span`、`#field7482span`、`#field8260span`、`#field9722span` 下存在可见浏览按钮，后续需要按字段语义分别探索。

## 初始包装接口

本次页面打开阶段触发的主要 workflow 接口：

```text
POST /api/workflow/reqform/loadForm
POST /api/workflow/layout/getFlowChartInfo
POST /api/workflow/requestAttention/getAttentionTypeSet
POST /api/workflow/reqform/detailData
POST /api/workflow/reqform/rightMenu
POST /api/workflow/reqform/signInput
POST /api/workflow/reqform/getFormTab
POST /api/workflow/linkage/reqFieldSqlResult
POST /api/workflow/linkage/reqDataInputResult
POST /api/workflow/injectDev/loadFormDevFileList
GET /api/workflow/reqform/scripts
GET /api/workflow/forward/getReqWfNodeOperators
```

`POST /api/workflow/reqform/loadForm` 请求体稳定业务参数包括：

```text
iscreate=1
workflowid=412
isagent=0
beagenter=0
f_weaver_belongto_userid=
f_weaver_belongto_usertype=0
```

该接口响应结构包含 `maindata`、`tableInfo`、`params`、`submitParams`、`detailNum`、`linkageCfg`、`cellInfo`、`browserInfo`、`datajson` 等字段，是后续字段固化的主要来源。

## 后续探索建议

- 对 `库存查询（物料）` 和 `库存查询（物料+WBS）` 分别做显式 safe interaction 探索，记录弹窗字段、查询接口、结果表字段和点选后的回填字段。
- 对 `所属记账主体`、`用途`、`成本中心`、`工厂`、`库存地点` 等浏览字段分别确认按钮 selector 和回填联动。
- 固化脚本应先打开长期入口，再填已确认字段，最后显示 review overlay；MVP 不自动提交。
