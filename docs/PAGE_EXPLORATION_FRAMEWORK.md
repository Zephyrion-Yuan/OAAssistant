# 页面探索标准框架

## 目标

该框架用于在用户已经登录的 Playwright Edge 中打开 OA/PDM 稳定业务链接，并输出后续自动化开发需要的页面知识：

- 可输入字段。
- 可互动按钮。
- 表格和结果列表。
- XHR/fetch 包装接口摘要。
- 显式安全互动后的字段变化。
- 可追加到后续 agent 开发说明的 Markdown 文档。
- 页面级探索结论需要沉淀到独立子文件夹，便于后续固化脚本和维护。

框架不负责登录，不抓取凭证，不提交表单。

## 模块

- `src/explorer/domainGuard.js`
  - 校验目标 URL 必须是 HTTPS。
  - 目标域名必须在 `config/pages.json` 或 `MEGANT_EXPLORE_ALLOWED_HOSTS` 白名单中。

- `src/explorer/surfaceScanner.js`
  - 扫描字段、按钮、链接、表格、弹窗、分页控件。
  - 识别字段类型、必填、只读、禁用、候选查询/选择字段。
  - 标记按钮意图：`interactive`、`dangerous`、`unknown`。

- `src/explorer/safeNetworkRecorder.js`
  - 只记录 XHR/fetch 的安全摘要。
  - URL 会脱敏。
  - 不记录 cookie、authorization header、localStorage、sessionStorage。
  - JSON 响应只保存结构摘要、列表路径、列表项字段名。

- `src/explorer/actionRunner.js`
  - 执行显式传入的安全互动。
  - 支持 fill、select、check、uncheck、press、click、clickText、wait、waitForSelector、waitForNetworkIdle。
  - 拒绝提交、审批、付款、删除、发布、发送等危险点击。

- `src/explorer/pageExplorer.js`
  - 编排打开页面、等待登录返回、扫描、执行互动、记录接口、生成报告。

- `src/explorer/artifacts.js`
  - 将探索结果写入 `.runtime/exploration/*.json` 和 `.runtime/exploration/*.md`。

## API

```http
POST /api/explore/page
```

输入：

```json
{
  "name": "Human readable name",
  "pageId": "stable-page-id",
  "url": "https://pdm.megarobo.info/masterdata/master-data-material",
  "allowManualLogin": true,
  "loginTimeoutMs": 180000,
  "interactions": []
}
```

输出：

```json
{
  "ok": true,
  "summary": {},
  "artifacts": {},
  "report": {}
}
```

`report` 是安全报告，但可能较大；脚本调用通常读取 `artifacts.markdownPath` 和 `artifacts.jsonPath`。

## CLI

```powershell
npm.cmd run explore:page -- --input config\exploration\page-request.example.json
```

## 探索步骤建议

1. 启动 `npm.cmd run sso:start`，确认 OA/PDM 已在 Playwright Edge 中登录。
2. 对目标 URL 先执行无 interaction 探索，得到字段和按钮候选。
3. 根据报告中的 selector 编写最小 interaction，只触发查询、选择、分页等非提交动作。
4. 再次执行探索，观察：
   - 新增的 XHR/fetch 接口。
   - `listCandidates` 中的列表路径和字段名。
   - `fieldDeltas` 中的自动回填字段。
5. 将确认后的结论整理到独立页面说明文档；如果已存在固化脚本，同步写入脚本命令和参数说明。

## 页面文档归档规范

每个被深入探索并进入固化阶段的页面，都应建立独立文档目录：

```text
docs/explorations/<page-id-or-business-name>/README.md
```

推荐目录名使用稳定页面 id 或业务语义，例如：

```text
docs/explorations/oa-purchase-workflow-458/README.md
```

页面文档至少包含：

- 页面名称、记录日期、稳定入口 URL。
- 一次性参数说明，例如 `_key`、`_rdm`、`timestamp`、`preloadkey` 是否不可固化。
- 安全边界：是否允许保存、是否禁止提交/审批/付款/删除/发布/发送。
- `.runtime/exploration/` 下的 JSON/Markdown 探索产物路径。
- 无 interaction 初扫摘要：字段、按钮、表格、主要包装接口。
- 安全 interaction 结果：查询字段、选择器、接口、结果表字段、自动回填字段。
- 仍需显式填写的字段。
- 已固化脚本的文件路径、package script、常用命令、参数说明、动作顺序。
- 已验证的测试输入、输出报告、附件或其他运行产物路径。
- 维护注意事项：模板变化、DOM 变化、接口变化、安全禁止项。

总览文档 `docs/EXPLORATION_RESULTS.md` 只保留高层结论和独立文档链接，避免同一页面的长篇记录在多个位置重复维护。

## 判断包装接口是否可复用

探索报告会给每个 XHR/fetch 接口标记：

- `dataQueryCandidate`: JSON 响应中包含 list/records/rows/items 等列表结构。
- `independentCandidate`: 请求方法为 GET/POST 且返回列表结构。

该标记只是候选，不代表可以脱离浏览器直接调用。固化为专用 API 前还需要确认：

- 是否依赖当前页面状态。
- 是否依赖 CSRF 字段或一次性参数。
- 是否只依赖浏览器 session。
- 请求体中哪些字段是稳定业务参数。
- 返回分页字段和总数字段。

在未确认前，应通过 Playwright 页面触发接口，而不是在 Node 中直接复用接口。

## OA/PDM 当前理解

- OA 入口以 `https://oa.megarobo.info/wui/index.html?#/main/portal/portal-1-1?...` 为登录有效性基准。
- OA 表单页面是动态工作流表单，字段、必填状态、明细表、附件和保存草稿按钮可能由接口返回并渲染。
- PDM 主数据物料查询入口为 `https://pdm.megarobo.info/masterdata/master-data-material`，旧入口 `https://pdm.megarobo.info/material/material-form` 仅作兼容记录。
- PDM 查询通常需要输入物料编码、物料名称、规格型号、物料组、品牌或物料等级，前端会请求包装接口返回 `data.list` 和 `data.total`；列表支持分页。
- 后续固化自动化时，优先记录“输入字段 -> 查询接口 -> 返回列表字段 -> 选择结果 -> 页面回填字段”的链路。

## 安全约束

- 只探索白名单域名。
- 不保存原始 SSO URL、token、cookie、authorization header。
- 不点击危险按钮。
- 不自动提交。
- 所有最终提交由用户人工复核后完成。

## 已归档页面

- `docs/explorations/oa-outbound-workflow-412/README.md`：OA 物资出库流程 `workflowid=412`，记录长期入口提取、无 interaction 初扫、按钮/表格/包装接口摘要和后续 safe interaction 探索建议。
- `docs/explorations/pdm-master-data-material/README.md`：PDM 主数据物料查询，记录新入口、筛选字段、分页接口、完整返回字段和 `pdm:query` 固化命令。
