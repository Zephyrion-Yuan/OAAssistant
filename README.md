# MEGAnt OA/PDM Automation

这是一个本地运行的 Edge/Playwright 自动化服务。程序内部不使用 AI 推理，所有动作都由显式命令、JSON 输入、白名单域名、页面扫描结果和配置规则决定。

当前重点能力：

- 启动 Playwright 托管的 Microsoft Edge。
- 用户在该 Edge 中手动完成 OA/PDM 登录。
- 通过钉钉 SSO Relay 将钉钉工作台链接导入托管 Edge。
- 对已登录业务页面进行字段、按钮、表格、包装接口探索。
- 输出探索报告，供后续脚本或 agent 固化自动化逻辑。
- 已固化 OA workflow 458/412/414/89 的 Excel 驱动填单脚本。
- 已固化 PDM 主数据物料查询，支持物料编码精确查询、名称模糊查询和多页完整结果整理。

安全边界：

- 不抓取或回放 DingTalk SSO 一次性链接。
- 不导出 cookie。
- 不读取 token、OAuth code、SAML、密码或 MFA。
- 不自动提交、审批、付款、删除、发布或发送。

## 本地启动

首次准备：

```powershell
npm.cmd install
npm.cmd run venv:setup
```

启动普通本地服务：

```powershell
npm.cmd run venv:start
```

打开：

```text
http://127.0.0.1:8787
```

## 钉钉 SSO 交接模式

如果希望“程序启动后自动打开 Playwright 托管 Edge，钉钉点击 OA/PDM 后进入这个 Edge”，使用：

```powershell
npm.cmd run edge:close-all
npm.cmd run sso:start
```

如果还没有安装本地默认浏览器中继器：

```powershell
npm.cmd run sso:install-relay
```

然后在 Windows 默认应用设置中，把 `HTTP` 和 `HTTPS` 关联到 `MEGAnt SSO Relay`。

测试结束后如需恢复：

```powershell
npm.cmd run sso:uninstall-relay
```

完整步骤见 [GUIDE.md](GUIDE.md) 和 [docs/SSO_HANDOFF.md](docs/SSO_HANDOFF.md)。

## 已实现业务能力

OA：

- `npm.cmd run oa:purchase-from-excel`：采购申请 workflow 458。
- `npm.cmd run oa:outbound-from-excel`：物资出库 workflow 412。
- `npm.cmd run oa:inbound-from-excel`：物资入库 workflow 414。
- `npm.cmd run oa:stock-transfer-from-excel`：库存转储 workflow 89。

PDM：

- `npm.cmd run pdm:query -- --material-code 4000059295 --max-pages 2`
- `npm.cmd run pdm:query -- --material-name "传感器" --max-pages 5`
- `npm.cmd run pdm:explore -- --url "https://pdm.megarobo.info/masterdata/master-data-material" --full`

主要文档：

- **[系统架构与进度](docs/ARCHITECTURE.md)** ⭐ 先看这个:三层架构、图拓扑、关键文件、进度、debug 锦囊
- **[测试全流程(mock + 真机)](docs/TESTING_GUIDE.md)** ⭐ step-by-step
- [前端测试台报告](docs/frontend-report.html)
- [开发日志](docs/DEVELOPMENT_LOG.md)
- [探索结果总览](docs/EXPLORATION_RESULTS.md)
- [页面探索框架](docs/PAGE_EXPLORATION_FRAMEWORK.md)
- [OA workflow 自动化操作知识](docs/OA_WORKFLOW_AUTOMATION_PLAYBOOK.md)
- [OA 新表单自动化策略](docs/OA_NEW_FORM_AUTOMATION_STRATEGY.md)
- [PDM 主数据物料查询](docs/explorations/pdm-master-data-material/README.md)

## 新 Session 探索新页面

在新的 Codex/session 中，如果你希望继续探索一个新的系统内页面，可以直接发送以下指令：

```text
请按照 D:\Desktop\MEGAnt\AGENTS.md 和 COMMANDS.md 的规则执行。
当前 cwd 是 D:\Desktop\MEGAnt。
我已经通过 Playwright Edge 登录好了系统。
请探索这个新页面：

<这里粘贴页面 URL>

要求：
1. 使用现有 /api/explore/page 或 npm run explore:page 框架。
2. 先做无 interaction 探索，输出字段、按钮、表格、包装接口摘要。
3. 不要点击提交/审批/付款/删除/发布/发送等危险按钮。
4. 探索产物写入 .runtime/exploration/。
5. 根据结果整理/追加页面说明到 docs/EXPLORATION_RESULTS.md 或新建对应文档。
```

如果页面需要输入测试值触发查询，可以补充：

```text
页面上需要用以下测试值触发查询：
字段含义：物料编码
测试值：4000023659

请先根据无 interaction 探索结果判断 selector，再执行安全 interaction：
- 填入测试值
- 点击/触发查询
- 等待返回列表
- 记录查询接口、返回字段、分页方式、点选后回填字段
```

最短可用指令：

```text
在 D:\Desktop\MEGAnt 中，按 COMMANDS.md 使用现有探索框架探索这个页面：<URL>。
我已经登录。先无 interaction 扫描，再根据页面安全地触发查询。不要提交表单，输出并整理探索文档。
```

关键是说明三件事：

- 当前目录是 `D:\Desktop\MEGAnt`。
- 已经在 Playwright Edge 中登录。
- 目标页面 URL。

## 页面探索命令

使用请求文件：

```powershell
npm.cmd run explore:page -- --input config\exploration\page-request.example.json
```

直接传入链接：

```powershell
npm.cmd run explore:page -- --name "OA workflow 458" --page-id oa-workflow-458 --url "https://oa.megarobo.info/spa/workflow/static4form/index.html?_rdm=1777431863391#/main/workflow/req?iscreate=1&workflowid=458"
```

输出完整安全报告：

```powershell
npm.cmd run explore:page -- --input config\exploration\page-request.example.json --full
```

探索产物会写入：

```text
.runtime/exploration/<artifactId>.json
.runtime/exploration/<artifactId>.md
```

详细协议见 [COMMANDS.md](COMMANDS.md) 和 [docs/PAGE_EXPLORATION_FRAMEWORK.md](docs/PAGE_EXPLORATION_FRAMEWORK.md)。

## 页面探索 API

```http
POST http://127.0.0.1:8787/api/explore/page
Content-Type: application/json
```

最小输入：

```json
{
  "name": "PDM material query page",
  "pageId": "pdm-material-form",
  "url": "https://pdm.megarobo.info/masterdata/master-data-material",
  "allowManualLogin": true
}
```

带安全互动：

```json
{
  "name": "PDM material query page",
  "pageId": "pdm-material-form",
  "url": "https://pdm.megarobo.info/masterdata/master-data-material",
  "allowManualLogin": true,
  "interactions": [
    {
      "name": "Fill material keyword",
      "type": "fill",
      "selector": "input",
      "value": "4000023659"
    },
    {
      "name": "Press Enter to query",
      "type": "press",
      "key": "Enter"
    },
    {
      "name": "Wait for result APIs",
      "type": "waitForNetworkIdle",
      "timeoutMs": 30000
    }
  ]
}
```

## 关键 API

- `GET /api/session/status`
- `POST /api/oa/login/start`
- `POST /api/oa/login/test-live`
- `POST /api/pdm/login/start`
- `POST /api/pdm/login/test-live`
- `POST /api/sso/open`
- `POST /api/explore/page`
- `POST /api/oa/scan`
- `POST /api/oa/fill`
- `POST /api/pdm/query`

## 检查

```powershell
npm.cmd run check
```

## Python LangGraph 编排层（`orchestrator/`）

在上面这套确定性服务**之上**的一层 Python「大脑」（LangGraph）。它把一条自然语言请求 + Excel 变成 OA 草稿：先用 PDM 校验物料，再由确定性脚本填单。**LLM 只做理解（意图抽取 / 缺槽追问 / 失败诊断），Playwright 仍是确定性的手，永不自动提交。**

- 集成方式：服务端 HTTP 封装。编排层只调本机 Node 的 `POST /api/oa/{stock-transfer,outbound,inbound,purchase}` 与 `/api/pdm/query`，不接触 cookie/token。
- 设备无关：图只依赖 Executor 契约（`HttpNodeExecutor` 真实后端 / `MockExecutor` 离线）；Win/mac 差异封装在执行端。
- 四个 OA 工作流（89/412/414/458）以插件式 WorkflowSpec 注册；对话式入口 `python -m oa_orchestrator.chat`。
- 状态机带 `SqliteSaver` 检查点，崩溃可断点续跑；离线测试不需 DeepSeek/Edge/网络。

环境准备、命令与设计说明见 [`orchestrator/README.md`](orchestrator/README.md) 与 [`COMMANDS.md`](COMMANDS.md) 第 7 节；开发记录见 [`docs/DEVELOPMENT_LOG.md`](docs/DEVELOPMENT_LOG.md)。

> 注意：仓库根 `.venv` 是旧的 Windows venv，mac 不可用；编排层在 mac 上用独立的 `orchestrator/.venv`（python3.12）。`orchestrator/.env`（含 DeepSeek key）不入库。
