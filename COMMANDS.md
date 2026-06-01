# MEGAnt 自动化调用指令

本文件是后续脚本或 agent 调用本项目的入口说明。项目内部不使用 AI 推理，所有动作都来自显式命令、JSON 输入、白名单域名和 Playwright 规则。

## 1. 启动认证浏览器

```powershell
npm.cmd run edge:close-all
npm.cmd run sso:start
```

效果：

- 启动本地服务 `http://127.0.0.1:8787`。
- 自动打开 Playwright 托管的 Microsoft Edge。
- 用户在该 Edge 中手动完成 OA/PDM 登录。
- 钉钉 SSO Relay 已安装并设置为 HTTP/HTTPS 默认应用时，钉钉工作台链接会进入该 Edge。

安全边界：

- 不抓取 SSO 链接。
- 不导出 cookie。
- 不读取 token、OAuth code、SAML、密码或 MFA。
- 不自动提交、审批、付款、删除、发布或发送。

## 2. 探索页面 HTTP API

接口：

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

带安全互动的输入：

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

输出：

```json
{
  "ok": true,
  "summary": {
    "fieldCount": 10,
    "requiredFieldCount": 2,
    "buttonCount": 8,
    "tableCount": 1,
    "apiCallCount": 12,
    "listApiCount": 1,
    "fieldDeltaCount": 3
  },
  "artifacts": {
    "artifactId": "...",
    "jsonPath": "...",
    "markdownPath": "...",
    "jsonUrl": "/runtime/exploration/....json",
    "markdownUrl": "/runtime/exploration/....md"
  }
}
```

探索产物固定写入：

```text
.runtime/exploration/<artifactId>.json
.runtime/exploration/<artifactId>.md
```

## 3. 探索页面命令行

使用 JSON 请求文件：

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

## 4. interaction 动作协议

支持动作：

```json
{ "type": "fill", "selector": "input[name='xxx']", "value": "text" }
{ "type": "select", "selector": "select[name='xxx']", "value": "option-value" }
{ "type": "check", "selector": "input[type='checkbox']" }
{ "type": "uncheck", "selector": "input[type='checkbox']" }
{ "type": "press", "selector": "input[name='xxx']", "key": "Enter" }
{ "type": "click", "selector": "button:has-text(\"查询\")" }
{ "type": "clickText", "text": "查询" }
{ "type": "waitForSelector", "selector": ".ant-table-row", "timeoutMs": 30000 }
{ "type": "wait", "ms": 1000 }
{ "type": "waitForNetworkIdle", "timeoutMs": 30000 }
```

限制：

- `click/clickText` 会拒绝点击包含提交、审批、付款、删除、发布、发送等含义的控件。
- `fill/select` 会拒绝操作看起来像 password、token、secret、mfa、cookie、authorization 的字段。
- 自动分页、点选结果行、弹窗选择等行为先用显式 interaction 描述；探索报告会记录字段变化和接口变化，后续再固化为专用任务。

## 5. 后续开发记录要求

每次对 OA/PDM 新页面完成探索后，将 `.runtime/exploration/*.md` 中确认过的信息整理追加到：

```text
docs/PAGE_EXPLORATION_FRAMEWORK.md
docs/EXPLORATION_RESULTS.md
docs/DEVELOPMENT_LOG.md
```

记录重点：

- 页面用途和入口 URL。
- 必填字段、选填字段、只读字段、自动回填字段。
- 需要输入后查询的包装接口。
- 包装接口返回的列表字段、分页方式、点选方式。
- 点选后会回填哪些页面字段。
- 附件上传入口和保存草稿入口，但不要自动提交。

## 6. 已固化任务命令

PDM：

```powershell
npm.cmd run pdm:query -- --material-code 4000059295 --max-pages 2
npm.cmd run pdm:query -- --material-name "传感器" --max-pages 5
npm.cmd run pdm:explore -- --url "https://pdm.megarobo.info/masterdata/master-data-material" --full
```

OA：

```powershell
npm.cmd run oa:purchase-from-excel -- --help
npm.cmd run oa:outbound-from-excel -- --help
npm.cmd run oa:inbound-from-excel -- --help
npm.cmd run oa:stock-transfer-from-excel -- --help
```

安全边界仍然适用：脚本不得自动提交、审批、付款、删除、发布或发送。保存草稿仅限已固化且用户明确允许的流程。

## 7. Python LangGraph 编排层（`orchestrator/`）

在上面的确定性 Node 服务**之上**的 Python「大脑」层。LLM 只做理解，Playwright 仍是确定性执行，永不自动提交。完整说明见 `orchestrator/README.md`。

新增 Node 端点（编排层经 HTTP 调用，入参为**已结构化数据**，非 Excel 文件）：

```
POST /api/oa/stock-transfer   # workflow 89
POST /api/oa/outbound         # workflow 412
POST /api/oa/inbound          # workflow 414
POST /api/oa/purchase         # workflow 458
```

mac 首次准备（不要复用仓库根 `.venv`，那是旧 Windows venv）：

```bash
python3.12 -m venv orchestrator/.venv
orchestrator/.venv/bin/pip install -r orchestrator/requirements.txt
cp orchestrator/.env.example orchestrator/.env   # 填 DEEPSEEK_API_KEY 才用真 LLM
```

离线自测（无需 DeepSeek/Edge/网络）：

```bash
orchestrator/.venv/bin/python orchestrator/tests/smoke.py     # 89 闭环
orchestrator/.venv/bin/python orchestrator/tests/stage2.py    # 画像/追问/续跑
orchestrator/.venv/bin/python orchestrator/tests/stage3.py    # 412/414/458
orchestrator/.venv/bin/python orchestrator/tests/chat_demo.py # 对话前端
```

运行（默认 `--dry-run` 只填不存；真机需先 `MEGANT_EDGE_PROFILE_MODE=sso-handoff npm start` 并登录）：

```bash
# CLI（--executor mock 走离线假后端）
PYTHONPATH=orchestrator orchestrator/.venv/bin/python -m oa_orchestrator.run \
  --executor mock --excel <xlsx> --request "从设备零件仓 D002 转到成品仓 A001" --save

# 对话式前端 / HTTP 前端（同一个 run_workflow 入口）
PYTHONPATH=orchestrator orchestrator/.venv/bin/python -m oa_orchestrator.chat
PYTHONPATH=orchestrator orchestrator/.venv/bin/python -m oa_orchestrator.serve   # POST /chat
```

CLI 参数：`--request --excel --thread --resume --save --dry-run --interactive --executor`。缺必填槽时：交互模式追问，无人值守进 `needs_input` 可恢复终态（`--resume --thread <id>` 续跑）。
