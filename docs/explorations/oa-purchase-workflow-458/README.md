# OA 采购申请流程（生产和研发物资）workflowid=458

记录日期：2026-05-09

## 页面入口

长期有效入口已验证：

```text
https://oa.megarobo.info/spa/workflow/static4form/index.html#/main/workflow/req?iscreate=1&workflowid=458&isagent=0&beagenter=0&f_weaver_belongto_userid=&f_weaver_belongto_usertype=0
```

点击菜单后 URL 中的 `_rdm`、`preloadkey`、`timestamp`、`_key` 均为本次打开相关参数，不应固化。使用上面的稳定 URL 打开后，OA 前端会自行补 `_key`，页面仍进入“采购申请流程（生产和研发物资）”创建页。

配置项：`config/pages.json` 中的 `oa-workflow-458`。

## 安全边界

- 使用项目的 Playwright 托管 Microsoft Edge 专用 profile。
- 用户先在该 profile 内完成人工登录。
- 自动化只打开白名单 OA 域名和稳定业务 URL。
- 自动化只填充已固化字段。
- 当前脚本会点击 `保存`，不会点击 `提交`、审批、付款、删除、发布、发送等危险按钮。

## 探索产物

- 无 interaction 初扫：`.runtime/exploration/2026-05-09T07-11-00-605Z-oa-no-interaction-oa.megarobo.info.json`
- WBS 弹窗初扫：`.runtime/exploration/2026-05-09T07-13-04-596Z-oa-wbs-popup-scan-oa.megarobo.info.json`
- WBS-only 查询：`.runtime/exploration/2026-05-09T07-16-33-830Z-oa-wbs-only-query-c2-0225002.06.01-oa.megarobo.info.json`
- 稳定 URL 验证：`.runtime/exploration/2026-05-09T07-17-11-408Z-oa-stable-url-verification-oa.megarobo.info.json`
- WBS 点选回填专项：`.runtime/exploration/2026-05-09T07-45-39-175Z-oa-wbs-select-result-with-full-rows-c2-0225002.06.01-oa.megarobo.info.json`
- Excel 固化脚本运行报告：`.runtime/purchase-requests/2026-05-09T08-31-18-288Z-oa-purchase-from-excel.json`

## 无 Interaction 初扫

- `requiresLogin=false`
- 标准 DOM 字段识别数量：3。OA 自定义表单字段主要通过 `loadForm` 响应和表格 DOM 暴露。
- 可见按钮数量：34。包含 `提 交`、`保 存`、多个浏览按钮、`上传附件` 以及签字意见富文本工具栏按钮。本阶段未点击提交或保存。
- 可见表格数量：1。主表文本包含：申请单号、申请日期、申请人、申请人部门、是否为项目型、项目编码文本、WBS编码、项目经理、项目名称、子项目经理、BU、PDT、采购类型、需求公司、相关流程、材料上传、价格、备注。
- 初始 XHR/fetch 数量：183。主要接口包括 `POST /api/workflow/reqform/loadForm`、`POST /api/workflow/reqform/detailData`、`POST /api/workflow/reqform/rightMenu`、`POST /api/workflow/reqform/getFormTab`、`POST /api/workflow/linkage/reqFieldSqlResult`、`POST /api/workflow/linkage/reqDataInputResult`、`GET /api/workflow/reqform/scripts`、`GET /api/workflow/forward/getReqWfNodeOperators`。

## 关键字段

- `field21089`：主表 WBS 编码，`htmlType=3`、`detailType=161`、`viewAttr=2`，可编辑浏览字段。
- `field21088`：项目编码文本，只读展示字段。
- `field10446`：项目编码，隐藏或不可编辑浏览字段。
- `field10447`：项目名称，只读字段。
- `field10444`：项目经理，必填浏览字段。
- `field13622`：子项目经理，可编辑浏览字段。
- `field10448`：PDT，必填浏览字段。
- `field10449`：BU，必填浏览字段。
- `field10450`：需求公司，必填浏览字段。
- `field10452`：采购类型，必填选择字段。
- `field10453`：材料上传附件区域。
- `field10454`：备注 textarea。

## WBS 查询与回填

WBS 查询弹窗：

- 打开方式：点击 `#field21089span > div:nth-of-type(2) > button`。
- 弹窗标题：`WBS主数据`。
- 查询字段：`POSID` 为 WBS 编号，`ZID01` 为项目编码，`PRCTR` 为利润中心。
- 实测只输入 WBS 编码即可查询，不需要同时输入项目定义。
- 页面存在重复 id，且 `POSID` 会被安全规则里的 `sid` 误判；脚本优先在弹窗作用域内定位可见输入框和结果行。

WBS-only 查询实测：

- 输入：`C2-0225002.06.01`
- 请求接口：

```text
GET /api/public/browser/data/161?...&POSID=C2-0225002.06.01&type=browser.WBSDate20240118102143&workflowid=458&wfid=458&fieldid=21089&fromModule=workflow...
```

- 返回结构：`total/current/columns/datas/pageSize/type/mobileshowtemplate`。
- 返回 `total=1`，结果表 1 行。
- 表头：WBS编号、项目编码、利润中心、优先级、是否最底层WBS、开票元素、WBS描述、项目经理、公司、子项目经理、下达预算。
- 样例行：`C2-0225002.06.01`、利润中心 `PT22`、是否最底层 WBS `Y`、WBS 描述 `物料采购`、项目经理 `BN997`、公司 `1010`、下达预算 `0`。

点选 WBS 结果后，主表自动回填：

- `项目编码文本`：`C2-0225002`
- `WBS编码`：`C2-0225002.06.01`
- `项目经理`：`陈洁`
- `项目名称`：`合成生物学- 酶筛选`
- `BU`：`ACRO`
- `PDT`：`ACRO`
- `仓库类型`：`非鲲鹏仓库`
- 隐藏/下方辅助字段：`PDT负责人=方攀峰`、`BU编码=BU06`、`一级部门负责人=张琰`、`二级部门负责人=方攀峰`

点选 WBS 后仍未自动填充的关键必填/基础字段：

- `是否为项目型`
- `采购类型`
- `需求公司`

因此固化脚本需要显式填写上述 3 个字段。

联动接口：

- `POST /api/workflow/linkage/reqDataInputResult`，`linkageid=3946`，基于 `field21088=C2-0225002` 回填 `field10444`、`field10447`、`field10448`、`field10449`。
- `POST /api/workflow/linkage/reqDataInputResult`，`linkageid=3944`，基于 `field10448=49` 回填 `field11198`。

## Excel 输入规则

测试文件：

```text
D:\Desktop\采购申请\项目采购申请-SA探针微孔板.xlsx
```

Sheet1 校验和提取规则：

- 仅读取 Sheet1，本次工作表名为 `项目需求填写界面`。
- 表头以当前模板为准；数据行从第 3 行开始，本次有第 3、4 行。
- `需求日期` 统一校正为当前日期 + 5 天。本次运行日期为 2026-05-09，目标日期为 `20260514`。
- `项目定义` 必须唯一，本次为 `C2-0225002`。
- `WBS编码` 必须唯一，并作为页面查询字段，本次为 `C2-0225002.06.01`。
- `需求工厂代码` 必须唯一，本次为 `1010`。
- 工厂代码 `1010` 当前映射页面 `需求公司=苏州镁伽科技有限公司`。
- 规范化附件写入 `.runtime/purchase-requests/attachments/` 后上传。

## 固化脚本

脚本文件：`scripts/oa-purchase-from-excel.js`

package 命令：`oa:purchase-from-excel`

基本用法：

```powershell
npm run oa:purchase-from-excel -- --file "D:\Desktop\采购申请\项目采购申请-SA探针微孔板.xlsx"
```

测试填充但不点击保存：

```powershell
npm run oa:purchase-from-excel -- --file "D:\Desktop\采购申请\项目采购申请-SA探针微孔板.xlsx" --no-save
```

覆盖采购类型：

```powershell
npm run oa:purchase-from-excel -- --file "D:\Desktop\采购申请\项目采购申请-SA探针微孔板.xlsx" --purchase-type "项目物资采购申请"
```

覆盖是否为项目型：

```powershell
npm run oa:purchase-from-excel -- --file "D:\Desktop\采购申请\项目采购申请-SA探针微孔板.xlsx" --project-type "是"
```

指定需求日期偏移天数：

```powershell
npm run oa:purchase-from-excel -- --file "D:\Desktop\采购申请\项目采购申请-SA探针微孔板.xlsx" --days-offset 5
```

常用参数：

- `--file <path>`：必填，采购申请 Excel 文件路径。
- `--purchase-type <text>`：采购类型，默认 `项目物资采购申请`。
- `--project-type <text>`：是否为项目型，默认 `是`。
- `--days-offset <days>`：需求日期校正为当前日期 + N 天，默认 `5`。
- `--url <url>`：临时覆盖 OA 页面入口；通常不需要。
- `--login-timeout-ms <ms>`：如果打开登录页，等待人工登录的时间，默认 `180000`。
- `--wbs-autofill-timeout-ms <ms>`：选择 WBS 后等待 OA 联动回填项目字段的时间，默认 `20000`。
- `--pause-on-error-ms <ms>`：失败后保留浏览器供观察的时间，默认 `120000`。
- `--no-save`：填字段并上传附件，但不点击 `保存`。

脚本动作顺序：

1. 校验 Excel Sheet1，生成规范化附件副本。
2. 打开 `oa-workflow-458` 稳定入口。
3. 填写 `是否为项目型`，默认 `是`。
4. 打开 WBS 浏览框，仅输入 `WBS编码` 查询。
5. 搜索接口返回后立即点选匹配 WBS 行，避免结果表刷新回 `暂无数据` 后点选失败。
6. 等待 OA 基于 WBS 自动回填 `项目编码文本`、`项目经理`、`项目名称`、`PDT`、`BU`。
7. 选择 `采购类型`，默认 `项目物资采购申请`。
8. 打开 `需求公司` 浏览框，按 `需求工厂代码` 点选公司。
9. 上传规范化后的 Excel 附件。
10. 如果未传 `--no-save`，点击 `保存`。

2026-05-09 16:31 验证通过：

- 运行报告：`.runtime/purchase-requests/2026-05-09T08-31-18-288Z-oa-purchase-from-excel.json`
- 规范化附件：`.runtime/purchase-requests/attachments/项目采购申请-SA探针微孔板-normalized-20260509-163049.xlsx`
- 保存后页面生成 `requestid=1435741`。
- 页面摘要确认：`是否为项目型=是`、`项目编码文本=C2-0225002`、`WBS编码=C2-0225002.06.01`、`项目经理=陈洁`、`项目名称=合成生物学- 酶筛选`、`BU=ACRO`、`PDT=ACRO`、`采购类型=项目物资采购申请`、`需求公司=苏州镁伽科技有限公司`，附件已显示在材料上传区域。

## 维护注意

- 若 Excel 模板更新，优先更新 `scripts/purchase_excel.py` 的表头识别和必填规则。
- 若 OA 弹窗 DOM 或查询接口变化，优先检查 WBS 浏览框和需求公司浏览框的选择器。
- WBS 查询返回结果曾出现“条目短暂出现后消失”的现象；当前脚本用接口响应后立即点选匹配行规避。
- 不要固化一次性 `_key`、`_rdm`、`preloadkey`、`timestamp`。
- 不要增加自动提交、审批、付款、删除、发布、发送动作。
