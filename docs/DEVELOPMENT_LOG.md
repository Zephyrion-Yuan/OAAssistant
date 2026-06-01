# 开发日志

## 2026-04-29

- 初始化本地 Node/Playwright 自动化服务设计。
- 从 PRD 中确认核心目标：PDM 已有物料的采购/出库自动填单、OA 保存草稿、用户最终确认提交。
- 记录 OA workflow 458/412/414/89 和 PDM material-form 页面入口。
- 采用 Edge 持久化 Profile 缓存登录态，支持独立 Profile 与当前系统 Edge Profile 两种模式。
- 根据用户确认，程序内部不做 AI 推理；所有流程使用代码规则、DOM 扫描和配置文件执行。MCP/脚本/人工前端只作为外部调用方。
- 完成服务骨架：`GET /api/session/status`、`POST /api/session/open-login`、`POST /api/oa/scan`、`POST /api/oa/fill`、`POST /api/pdm/query`。
- 完成前端控制台初版：会话状态、登录续期、OA 扫描、OA 填单、PDM 查询。
- 依赖安装与 `npm.cmd run check` 通过。
- 复用系统 Edge Profile 的 `current` 模式会导致 Edge 启动后退出；已增加 `current-profile-dir` 模式并给出明确错误提示。
- 使用 `current-profile-dir` 模式实测：PDM 与 OA 均能打开到登录页并返回二维码/登录截图；当前授权未复用成功或已过期，需要扫码后再跑真实字段扫描。
- 增加 PDM 登录诊断接口 `/api/pdm/login-diagnose`，仅观察自动化 Edge 页面内的跳转、静态资源、请求摘要、可见字段/按钮和 Cookie 名称，不返回 Cookie 值。
- 诊断发现 PDM 登录页停留在 `/auth/login?redirect=...`，页面无二维码和账号输入框，静态 JS 包含 DingTalk JSAPI、企业 SSO 登录、二维码登录路由和账号登录路由。当前更像是需要钉钉容器 authCode 或企业 SSO 入口 URL。
- PDM 查询和诊断支持传入自定义 `url`，用于测试钉钉实际打开的 PDM 入口。
- 根据手动跳转链路确认 PDM 使用 `sso.megarobo.tech` 钉钉 OAuth 到 `pdm.megarobo.info/oauth/callback` 的 SSO 流程。
- 增加 URL 脱敏模块，返回结果中脱敏 `authCode`、`code`、`token`、`ticket` 等参数；前端“打开 PDM 登录/续期”会优先使用“PDM 入口 URL”。
- 明确不做钉钉到 Edge 的 SSO 链接拦截；新增 `npm.cmd run start:current-profile` 和 PDM SSO 登录复用说明，采用“人工 SSO 登录落 Edge Profile -> 关闭 Edge -> 工具复用 Profile”的方式。
- 修正 `start:current-profile` 为 Edge `User Data` 根目录 + `--profile-directory=Default` 的真实 Profile 复用方式。
- PDM 登录复用成功：关闭普通 Edge 和后台 `msedge.exe` 后，工具以 `current` 模式打开 `https://pdm.megarobo.info/material/material-form`，页面标题为“物料查询 - MegaPDM”。
- PDM 物料查询固化结果：
  - 物料编码输入框：`name=materialCode`，placeholder `请输入物料编码`。
  - 物料名称输入框：`name=materialName`，placeholder `请输入物料名称`。
  - 搜索按钮文案：`搜 索`。
  - 查询接口：`GET https://pdm-api.megarobo.info/admin-api/material/query/page?pageNo=1&pageSize=20&materialCode=...` 或 `materialName=...`。
  - 前端会自动携带认证头；直接 `fetch` 不可靠，因此工具改为监听页面自己的 XHR 响应体。
- 验证样例：
  - `materialCode=4000023659` 返回 1 条。
  - `materialName=96孔乳白框透明管PCR板` 模糊查询返回 1 条。
  - 返回字段包括 `materialCode/materialTypeCode/materialName/specifications/description/parameterDescription/materialGroupCode/materialGroupDesc/unit/brandName/oldMaterialCode/stock/docFlagDesc` 等。
- 增加三段脚本：
  - A：`npm.cmd run profile:cache`，缓存系统 Edge `Default` Profile 到 `.runtime/edge-profile-cache`。
  - B：`npm.cmd run profile:test-login`，用缓存 Profile 启动 Playwright Edge，验证 OA/PDM 登录态。
  - C：前端“Profile 缓存”区域按钮调用 `/api/profile/cache` 与 `/api/profile/test-login`，用弹窗提示成功/失败。
- A/B 联调结果：A 缓存成功；B 使用缓存 Profile 验证时 PDM 已带登录态，OA workflow 458 仍跳转钉钉扫码登录，需要用户再完成 OA SSO 后重新缓存。
- OA 入口统一调整为 portal：`https://oa.megarobo.info/wui/index.html?#/main/portal/portal-1-1?menuIds=0,1&menuPathIds=0,1&_key=tcagna`。
- 增加 `/api/session/diagnose` 和前端“诊断 OA 会话”，用于判断 OA 是否仅使用浏览器会话 Cookie。若 OA 关闭 Edge 后必定超时，则应使用“工具托管活会话”模式，而不是离线 Profile 缓存。
- 固定登录流程重构：
  - OA 使用 `/api/oa/login/start` 打开工具托管 Edge 扫码，`/api/oa/login/test-live` 测试活会话。
  - PDM 使用 `/api/pdm/profile/cache` 缓存普通 Edge 登录后的 Profile，`/api/pdm/profile/test` 测试缓存登录态。
  - PDM 查询默认使用 `.runtime/edge-profile-cache`，不再依赖 OA 的活 Edge 会话。
  - 前端重写为“OA 登录流程”和“PDM 登录流程”两个独立面板，并修复中文乱码。
  - 旧别名 `profile:cache/profile:test-login` 已改为 PDM 专用，不再混测 OA。
- 2026-04-29 继续执行探索任务：通过 `/api/oa/login/test-live` 验证 OA portal 工具托管活会话仍有效，标题为 `镁伽OA`，未触发登录页。
- 2026-04-29 完成 OA workflow 458/412/414/89 的字段汇总提取，输出到 `.runtime/oa-field-summary/summary-latest.json`，并新增 `npm.cmd run oa:summarize-summary` 复核命令。
- 2026-04-29 记录 OA 四个流程的必填字段、可编辑字段数量、页面按钮和 workflow API，汇总文档见 `docs/EXPLORATION_RESULTS.md`。
- 2026-04-29 通过 `/api/pdm/query` 验证 PDM 编码查询 `4000023659` 和名称模糊查询 `96孔乳白框透明管PCR板`，均返回目标物料 1 条。
- 2026-04-29 修复 PDM cached profile persistent context 并发启动竞争，避免两个 API 请求同时启动 Edge 时争抢同一 profile 锁。
- 2026-05-06 增加 Docker 运行模式：新增 `Dockerfile`、`docker-compose.yml`、`docker/entrypoint.sh`，容器内运行 Microsoft Edge、Xvfb、x11vnc、noVNC 和 Node 服务。
- 2026-05-06 前端控制台收敛为登录专用页面，仅保留运行状态、OA 打开登录页/检测有效、PDM 打开登录页/检测有效和 noVNC 浏览器入口。
- 2026-05-06 服务端新增 `HOST` 环境变量、`MEGANT_BROWSER_CHANNEL`/`MEGANT_BROWSER_ARGS` 浏览器启动配置，并新增 `/api/pdm/login/start`、`/api/pdm/login/test-live` 以支持 Docker 内 PDM 活会话登录。
- 2026-05-06 暂停 Docker 作为推荐运行方式，改为本机 `.venv` 启动；新增 `scripts/local_venv.py`、`npm run venv:setup`、`npm run venv:start` 和 `docs/LOCAL_VENV.md`。
- 2026-05-06 前端移除 Docker/noVNC 入口和 Docker 状态展示，仅保留本机运行状态、OA 登录/检测、PDM 登录/检测。
- 2026-05-06 按新优先级增加钉钉 SSO 交接模式：新增 `MEGANT_EDGE_PROFILE_MODE=sso-handoff`、`npm run sso:start`，启动系统 Edge User Data 根目录下的专用 Profile `MEGAntBot`，服务启动后自动打开 Playwright 托管 Edge。
- 2026-05-06 新增本地 `/api/sso/open` 和 `npm run sso:relay-url` 兜底交接能力，所有返回 URL 均走脱敏，不保存或打印原始 SSO URL。
- 2026-05-06 新增 `npm run edge:close-all`，用于在启动 SSO 交接模式前强制关闭所有 Microsoft Edge 进程。
- 2026-05-06 修复 `npm run sso:start` 在 8787 已被旧 Node 服务占用时失败的问题：`.venv` 启动脚本会自动停止监听同端口的旧 node 进程后再启动。
- 2026-05-06 修复端口清理 PowerShell 子命令返回非 0 导致 `sso:start` 提前中止的问题：清理步骤改为容错执行并打印 warning，不再阻断启动。
- 2026-05-06 诊断钉钉 SSO 未进入 Playwright Edge：默认浏览器是 Edge 且 `MEGAntBot` profile 已运行，但 Windows/Edge 不保证外部 https 链接投递到 Playwright context。新增 `npm run sso:install-relay` / `sso:uninstall-relay` 注册本地默认浏览器中继器，作为可靠交接方案。
- 2026-05-06 钉钉 SSO Relay 已实测走通，新增 `GUIDE.md` 固化从生成独立 exe、默认应用设置、启动交接模式到验证登录态的 step-by-step 操作手册。
- 2026-05-06 修复 SSO Relay 多窗口兼容：`/api/sso/open` 不再复用第一个已有 page 执行 `goto`，而是每次新建标签页打开 URL，避免替换原标签页。
- 2026-05-09 完成 OA workflow 412（物资出库流程）长期入口提取和无 interaction 探索：稳定入口去除 `_rdm`、`preloadkey`、`timestamp`、`_key`，更新 `config/pages.json` 的 `oa-workflow-412`，探索产物写入 `.runtime/exploration/2026-05-09T09-13-02-288Z-oa-workflow-412-persistent-initial-scan-oa.megarobo.info.*`，页面说明归档到 `docs/explorations/oa-outbound-workflow-412/README.md`。
- 2026-05-11 继续探索 OA workflow 412 项目预留出库链路：确认所属记账主体、成本中心、仓库类型、用途、预留号、物资明细勾选、申请数量和保存草稿接口；新增 `config/oa-workflow-412-outbound.json`、`scripts/outbound_excel.py`、`scripts/oa-outbound-from-excel.js` 和 `npm run oa:outbound-from-excel`，探索归档到 `docs/explorations/oa-outbound-workflow-412/2026-05-11-material-outbound-flow.md`。
- 2026-05-12 总结 OA workflow 458/412 的填单规律并形成 `docs/OA_WORKFLOW_AUTOMATION_PLAYBOOK.md`；继续探索 workflow 414 物资入库流程，确认长期入口、入库类型下拉、项目退料关联出库凭证 `browser.XMTL`、明细库存地点 `browser.KCDD_RK_DT1`、数量字段 `#field7589_<rowIndex>`、项目副产品入库预留号 `browser.ReservedInformationDate581`、内部订单退料关联出库记录 `browser.nbddtl`，更新 `config/pages.json` 的 `oa-workflow-414`，探索归档到 `docs/explorations/oa-inbound-workflow-414/README.md`。
- 2026-05-12 实现 workflow 414 项目退料入库脚本：新增 `config/oa-workflow-414-inbound.json`、`scripts/inbound_excel.py`、`scripts/oa-inbound-from-excel.js` 和 `npm run oa:inbound-from-excel`。脚本默认按 Excel 项目定义检索项目退料出库凭证，按采购表物料需求数量填写入库数量，保存草稿但不提交；多候选或缺失业务选择返回 `needsInput=true`。
- 2026-05-27 探索并固化 PDM 主数据物料查询新入口 `https://pdm.megarobo.info/masterdata/master-data-material`：新增 `scripts/explore-pdm-page.js`、升级 `scripts/query-pdm.js` 和 `src/automation/pdmAutomation.js`，查询通过页面输入与分页按钮触发 PDM 自身 XHR，监听 `/admin-api/master/data/material/page` 响应并整理多页完整结果；验证 `materialCode=4000059295` 精确返回 1 条，`materialName=人力外包` 模糊查询读取 2 页共 24 条。

## 2026-05-29 当前状态总览

本仓库已经形成一套隐私优先的 OA/PDM 自动化工作台。核心原则没有变化：只使用 Playwright 托管的 Microsoft Edge profile，用户手动完成 OA/PDM SSO 登录；自动化只打开白名单域名和稳定业务 URL；不截获或回放钉钉 SSO 一次性链接，不导出 cookie，不读取 token/OAuth code/SAML/password/MFA；不自动点击提交、审批、付款、删除、发布、发送类危险按钮。OA 草稿保存只在专用脚本和用户明确允许的场景下执行。

已实现的底层能力：

- 本地 Node 服务 `src/server.js`，提供 `/api/session/status`、`/api/session/open-login`、`/api/oa/*`、`/api/pdm/*`、`/api/explore/page`、`/api/sso/open` 等入口。
- Edge 会话层：`src/browser/edgeSession.js` 管理工具托管活会话；`src/browser/cachedProfileSession.js` 管理 PDM 缓存 profile。
- SSO Relay：`scripts/install-browser-relay.ps1`、`scripts/relay-url.js` 和 `/api/sso/open` 已支持 Windows 默认应用中继，把钉钉打开的 OA/PDM 链接交给 Playwright 托管 Edge；所有 URL 返回前脱敏。
- 页面探索框架：`src/explorer/*` 已支持域名白名单、页面 surface 扫描、XHR/fetch 安全摘要、受限 interaction、`.runtime/exploration/*.json|*.md` 产物输出。
- 登录和诊断：`/api/oa/login/start`、`/api/oa/login/test-live`、`/api/pdm/profile/cache`、`/api/pdm/profile/test`、`/api/session/diagnose`、`/api/pdm/login-diagnose`、`/api/pdm/auth-probe`。
- 安全脱敏：`src/security/redaction.js` 对 URL 和响应摘要中的 token/code/session/ticket 等敏感字段脱敏。

已固化的 OA 页面和脚本：

- workflow 458 采购申请：`scripts/oa-purchase-from-excel.js`、`scripts/purchase_excel.py`、`docs/explorations/oa-purchase-workflow-458/README.md`。入参是采购 Excel 和用户信息，标准化后填写采购申请并按已确认规则保存草稿，不提交。
- workflow 412 物资出库：`scripts/oa-outbound-from-excel.js`、`scripts/outbound_excel.py`、`config/oa-workflow-412-outbound.json`、`docs/explorations/oa-outbound-workflow-412/`。已掌握所属记账主体、成本中心、仓库类型、用途、预留号、物资明细勾选和申请数量填写链路。
- workflow 414 物资入库：`scripts/oa-inbound-from-excel.js`、`scripts/inbound_excel.py`、`config/oa-workflow-414-inbound.json`、`docs/explorations/oa-inbound-workflow-414/README.md`。默认项目退料，按采购表数量填写入库数量，允许保存草稿；多候选或无法唯一映射时返回 `needsInput=true`。
- workflow 89 库存转储：`scripts/oa-stock-transfer-from-excel.js`、`scripts/stock_transfer_excel.py`、`config/oa-workflow-89-stock-transfer.json`、`docs/explorations/oa-stock-transfer-workflow-89/README.md`。支持移动类型、工厂、物料、数量、转出/转入库存地点和项目库存 WBS 场景；默认不保存，传 `--save` 才保存草稿。
- OA 新表单方法论：`docs/OA_WORKFLOW_AUTOMATION_PLAYBOOK.md` 和 `docs/OA_NEW_FORM_AUTOMATION_STRATEGY.md` 总结了从稳定 URL、无 interaction 探索、browser 弹窗、联动回填、配置化业务规则到脚本固化的流程。

已固化的 PDM 能力：

- PDM 主数据物料查询入口：`https://pdm.megarobo.info/masterdata/master-data-material`，记录在 `config/pages.json`。
- `scripts/query-pdm.js` 和 `src/automation/pdmAutomation.js` 支持物料编码精确查询、编码模糊/前缀查询、物料名称模糊查询、规格型号、物料组编码/描述、品牌、物料等级等筛选。
- 查询通过页面输入和分页按钮触发 PDM 自身 XHR，监听 `/admin-api/master/data/material/page`，整理 `data.list`、`data.total` 和多页完整字段，结果写入 `.runtime/pdm-results/*.json`。
- PDM 探索脚本：`scripts/explore-pdm-page.js` 使用缓存 PDM profile 进行无交互探索，产物写入 `.runtime/exploration/`。
- 完整说明：`docs/explorations/pdm-master-data-material/README.md`。

关键配置和入口：

- 页面入口：`config/pages.json` 记录 OA portal、workflow 458/412/414/89 和 PDM 主数据物料查询。
- OA 业务配置：`config/oa-workflow-412-outbound.json`、`config/oa-workflow-414-inbound.json`、`config/oa-workflow-89-stock-transfer.json`。
- 常用命令：`npm.cmd run sso:start`、`npm.cmd run explore:page`、`npm.cmd run pdm:query`、`npm.cmd run oa:purchase-from-excel`、`npm.cmd run oa:outbound-from-excel`、`npm.cmd run oa:inbound-from-excel`、`npm.cmd run oa:stock-transfer-from-excel`、`npm.cmd run check`。
- 文档入口：`GUIDE.md`、`README.md`、`COMMANDS.md`、`docs/API.md`、`docs/PAGE_EXPLORATION_FRAMEWORK.md`、`docs/EXPLORATION_RESULTS.md`、各 `docs/explorations/*/README.md`。

后续新页面接续方式：

- 新 OA 表单：先提取稳定 URL，不固化 `_rdm`、`preloadkey`、`timestamp`、`_key`；用 `/api/explore/page` 或 `npm.cmd run explore:page` 做无 interaction 扫描；只对查询/选择/分页做安全 interaction；把产物写入 `.runtime/exploration/` 并整理到 `docs/explorations/<page>/README.md` 和 `docs/EXPLORATION_RESULTS.md`。
- 新 PDM 页面：优先用缓存 PDM profile；先用 `pdm:explore` 或探索 API 确认字段、按钮、分页和接口；固化时仍优先让页面自身触发 XHR，再监听响应整理结果。
- 如果脚本遇到多候选、缺少业务规则、明细数量无法唯一映射、库存地点/WBS/预留号无法唯一匹配，应返回 `needsInput=true`，由调用方或用户补充参数后继续。

## 2026-06-01 Python LangGraph 编排层（Stage 1–3）

在确定性 Node/Playwright「手」之上新增一层 Python LangGraph「大脑」（`orchestrator/`）。约束不变：LLM 只做「理解」，Playwright 仍是确定性执行，永不自动提交（最多保存草稿）。集成方式为**服务端 HTTP 封装**——图只与本机 Node 服务通信，不接触 cookie/token；喂给 LLM 的仅业务字段（物料编码/名称/数量/库存地点/WBS/中文请求），绝不喂 SSO URL/token/截图。

- **Stage 1（单流程闭环 89 库存转储）**
  - Node：抽 `src/automation/flows/stockTransfer.js`（`runStockTransfer(input)` + `NeedInputError`，吃**已结构化入参**而非 Excel；浏览器生命周期由调用方持有），CLI `scripts/oa-stock-transfer-from-excel.js` 瘦身为薄壳（仍兼容旧命令行）。
  - Node：新增 `POST /api/oa/stock-transfer`（`src/server.js`，zod 校验 + 进程内互斥锁；`NeedInputError → {ok:false,needsInput:true,input}`）。
  - Python：`intake`(openpyxl 移植 `stock_transfer_excel.py`)→`preflight`→`understand`(LLM)→`check_slot`→`pdm_enrich`(逐物料查 PDM 校验「存在且启用」)→`resolve_params`→`execute`→`verify`→`diagnose`(自愈)→`finalize`；`SqliteSaver` 检查点支持断点续跑。
  - **Excel 解析从 Node 抽离到 Python 输入端**：结构化结果写独立 `business_inputs` SQLite 表 + 进 GraphState，执行端不再处理 Excel。
- **Stage 2（接缝 + 自检）**
  - `run_workflow(thread_id, message, resume)` 前端无关入口（`runner.py`）：命中追问时返回 `needs_input`+问题，前端带 `resume` 续传，不耦合 stdin。
  - `personalize` 节点 + `Profile`：用静态用户画像（默认工厂/WBS/常用库存地点/部门）预填缺槽，减少追问。
  - `workflow_id` 注册表（`workflows.py`）：`check_slot`/`execute` 委托注册表，加流程 = 注册一条 spec，不动图。
  - Executor 契约（`executors/base.py`，`session_status/query_pdm/fill_*`）实现设备无关：`HttpNodeExecutor`（真实 Node 服务，Win/mac 差异封装在此）+ `MockExecutor`（离线测试）。
- **Stage 3（推广四流程）**
  - 412/414/458 同 89 模式抽 flow（`flows/outbound.js|inbound.js|purchase.js`）+ `POST /api/oa/{outbound,inbound,purchase}` + Python `intake_parsers.py`（openpyxl 移植三套 `*_excel.py`）+ 三个 `fill_*` 执行端方法 + mock + 注册 WorkflowSpec。**「插件式加流程」得到验证**：`execute`/`check_slot` 一行未改。
- **对话式前端薄壳**：`python -m oa_orchestrator.chat`（多轮 REPL）与 `python -m oa_orchestrator.serve`（纯 stdlib HTTP `POST /chat`），均坐在 `run_workflow` 上。
- **LLM**：DeepSeek（`deepseek-v4-pro`，思考型模型，结构化抽取改为「JSON-schema 塞进 prompt + 自解析」以兼容；无 key 时 understand/diagnose 自动退回规则兜底）。Key 仅存 `orchestrator/.env`（已 gitignore，不入库）。
- **验证（离线，无需 DeepSeek/Edge/网络）**：`npm run check`、`compileall`、`orchestrator/tests/{smoke,stage2,stage3,chat_demo}.py` 全绿；真实 LLM 见 `tests/llm_live.py`。环境/运行说明见 `orchestrator/README.md`。
- 注意：仓库根 `.venv` 是**旧的 Windows venv（mac 不可用）**；mac 用 `orchestrator/.venv`（python3.12）。

## 2026-06-01 库存查询入口调研（待捕获，Stage 3b 前置）

为支撑「四流程库存驱动决策路由」（无库存→采购 458；有库存·公共仓→出库 412；有库存·别项目专属仓→转储 89；用完有剩→入库 414），需要「按仓/按项目的库存量」数据。调研现有探索记录结论：

- **入口已发现，但从未真正查询/捕获**。OA 表单页（412/414/89）内置三个库存查询入口：顶栏按钮 `库存查询（物料）`、`库存查询（物料+WBS）`，以及浏览字段 `物资库存查询`（414 selector `#field10037span > div:nth-of-type(2) > button`，browser type `browser.SAPInventoryQueryInterface`）。
- 铁证：这些只出现在「无 interaction 扫描」的元素清单里（标 `interactive | no`，从未点击）；`.runtime/exploration/` 中**无任何库存数量**捕获（`现存量/可用量/非限制/LABST/MARD/MCHB` 零命中）；唯一打通的 browser 接口是 `/api/public/browser/data/161`（用于 WBS/工厂/成本中心/预留/库存地点**选择**，非库存查询）。`docs/explorations/oa-outbound-workflow-412/README.md` 第 40/74/75/112 行已将其列为待办。
- 易混淆但都不是「在库量」：预留弹窗（SAP IF031）返回**需求/预留量(BDMNG)**；库存地点选择器（`browser.KCDD_ZC`/`KCDD_RK_DT1`）只返回地点候选（名称/工厂/SAP码），不带数量；PDM 物料页只有主数据，无库存。
- **下一步（需登录态 session）**：用 explorer 框架点开 `物资库存查询`/`库存查询（物料/+WBS）`，捕获弹窗检索字段、查询接口 path/params、结果列（确认含 工厂+库存地点+在库数量）、翻页/点选方式；拿到后固化为执行端 `inventory_query` 方法 + 图的 `route_workflow` 路由节点。
