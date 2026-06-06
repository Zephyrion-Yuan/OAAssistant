# OAAssistant — 系统架构与进度

> 给另一终端 / 另一份 repo / 接手的人:**快速理解整套系统 + 知道去哪 debug**。
> 当前测试步骤见 [`TESTING_GUIDE.md`](TESTING_GUIDE.md)。本文反映 2026-06-06 的状态。
>
> **架构定位(重要)**:理解/规划层现在是**真正的 agentic 外壳(L3)**——前端左侧「AI 下单」走一个 ReAct intake agent(`create_react_agent` + 只读工具),自主澄清/查 PDM/查库存/解析 WBS/拆分复合目标,组装出结构化需求;**执行/业务规则/安全仍是确定性内核**,永不提交。即「agentic 外壳 + 确定性内核」。设计评估见 [`graph-design-review.html`](graph-design-review.html)。

---

## 0. 一句话 & 心智模型

把一条「采购物料」的诉求,自动判断每个物料该走 **采购/出库/转储/入库** 哪条 OA 流程,按 WBS 分桶填成 OA 草稿(**永不提交**)。三层:

| 层 | 角色 | 技术 | 进程 |
|---|---|---|---|
| **Node「手」** | 确定性执行:登录托管 Edge、查 PDM、查库存、填单、WBS 主数据 | Node.js,零框架 `http` | `npm start` → :8787 |
| **Agent 外壳(L3)** | ReAct intake agent:自由自然语言 → 自主调**只读工具**(query_pdm/inventory/resolve_wbs/query_wbs)澄清+组装需求(P1);复合请求按目标拆组(P2)。**只读/装配,绝不写/提交** | `create_react_agent` + `deepseek-chat`(tool-calling) | 同 :8788(`/api/agent-chat`) |
| **编排层「脑」** | LangGraph 状态机:意图理解、库存驱动路由、补全、自检、原位纠错。**LLM 只做理解,永不操作浏览器、永不提交** | Python + LangGraph + DeepSeek | `uvicorn …bff:app` → :8788 |
| **前端「壳」** | 测试台:对话(左,含「AI 下单」)+ 填表(右)+ 配置抽屉 | Vue3(CDN)+ deep-chat | 任意静态服务器 → :5500 |

**硬约束**:Node 执行路径内不用 AI(确定性);全程只存草稿、零提交/审批;不碰 cookie/token/SSO 一次性链接;喂 LLM 只给业务字段。

---

## 1. 仓库布局

```
src/                     Node「手」
  server.js              零框架 HTTP 服务(:8787),所有 /api/* 路由
  browser/               edgeSession(托管 Edge)/ cachedProfileSession(PDM 缓存)/ browserLaunch
  automation/
    domScanner.js        确定性 DOM 扫描(字段/按钮/表格/登录检测)
    oaAutomation.js      通用扫描 + 模糊字段匹配 + 填值(只点存草稿)
    pdmAutomation.js     PDM 物料查询(读 XHR 响应,非爬表)
    oaInventoryQuery.js  OA 库存查询(/api/ps/fhd/stockQuery,降级 SAPInventoryQueryInterface)
    wbsRegistry.js       WBS 主数据(JSON 文件 .runtime/wbs-registry.json)+ 别称模糊解析
    flows/               固化 4 流:stockTransfer(89)/outbound(412)/inbound(414)/purchase(458)
  explorer/              通用页面探索框架 + 安全闸(domainGuard/actionRunner)
  security/redaction.js  URL/正文脱敏
  profile/               Edge profile 缓存(Windows 重,mac/linux no-op)
scripts/                 CLI:oa-*-from-excel.js / oa-inventory-query.js / query-pdm / explore-page / *_excel.py(openpyxl 解析,CLI 向后兼容)
config/
  pages.json             OA workflow URL + PDM URL(唯一来源)
  oa-workflow-*.json     412/414/89 的 selector 映射 + 业务查表
public/                  旧控制面板(Node 自带,简单运维页;非测试台)
orchestrator/            编排层「脑」(独立 mac venv:orchestrator/.venv,python3.12)
  oa_orchestrator/
    bff.py               FastAPI 网关(:8788)—— 前端唯一连的面
    graph.py             build_graph(executor, checkpointer, mode) —— single | acquire
    runner.py            run_workflow(...) 前端无关入口;run.py CLI
    chat.py              CLI 对话 REPL(终端版前端)
    schemas.py           Pydantic 数据契约(BusinessInput/DemandRow/AllocationPlan/WbsRecord/…)
    state.py             GraphState(TypedDict)
    store.py             SQLite:business_inputs + profiles 表
    workflows.py         WorkflowSpec 注册表(单流程模式用)
    llm.py               DeepSeek 工厂 + require_structured(必需,无 fallback) + 测试 stub
    intake_parsers.py    412/414/458 的 Excel 解析(openpyxl)+ FACTORY_COMPANY_NAMES
    config.py            Settings:含 deepseek_tool_model(agent 层用 deepseek-chat)
    agent/               【P1/P2 agentic 外壳】tools.py(只读工具 + emit_demand + tool-model 工厂)/ intake_agent.py(create_react_agent + run_intake)
    memory/              【④⑤ 记忆脚手架,接口态/默认休眠】base.py(MemoryStore 协议 + episode/ReturnDraft schema + reverse_outbound)/ null.py / mock.py;get_memory()/recall_context()
    executors/           契约:base.py(Protocol) / http_node.py(真机) / mock.py(离线)
    nodes/               图节点(逐个见 §4)
  tests/                 离线测试(smoke/stage2/stage3/chat_demo/inventory/wbs/router/idempotency/assist/memory/adaptive/bff)+ llm_live(真 LLM)
  archive/serve.py       已归档(被 bff.py 取代)
frontend/                测试台(Vue3 + deep-chat),纯 fetch/SSE 只连 BFF
docs/                    本文 + TESTING_GUIDE + 各 Node 层运维/探索文档;archive/ 是历史
.runtime/                所有产物(gitignored):wbs-registry.json / store.sqlite / checkpoints.sqlite / 各任务报告 / 探索产物 / 登录截图 / Edge profile 缓存
```

---

## 2. 三进程 + 端口 + 数据流

```
[ frontend :5500 ]  ──fetch/SSE(只连一个面)──►  [ BFF FastAPI :8788 ]
                                                    ├─ httpx 代理 ─►  [ Node :8787 ]  会话/登录/SSO/WBS/inventory/填单
                                                    ├─ store.py     画像(profiles 表)
                                                    └─ /api/chat(SSE) ─► run_workflow(mode=acquire)
                                                                          executor = mock | http-node(→Node)
```

- **mock 模式**:聊天用 `MockExecutor`(假 OA/PDM/库存),但 `query_wbs` 仍走真实 Node registry(`bff.MockWithRealWbs` 薄包装)→ 你在配置抽屉改的 WBS 能被聊天用上。**离线但 LLM 仍是真的**(classify_goal 必调 DeepSeek)。
- **http-node 模式**:全真机,需先登录托管 Edge。
- 前端从不直连 Node、从不 import 后端;只认 BFF 这一份契约(FastAPI 自带 `/docs` OpenAPI)。

---

## 3. Node「手」层(`src/server.js` :8787)

零框架 `http` 服务,所有路由在 `handleApi` 的 if 链。要点端点:

| 端点 | 作用 |
|---|---|
| `GET /api/session/status` | 托管 Edge / PDM 缓存会话状态 |
| `POST /api/oa/login/{start,test-live}` · `/api/pdm/login/{start,test-live}` · `/api/sso/open` | 登录/检测/SSO 交接 |
| `POST /api/pdm/query` | PDM 物料主数据查询(读 XHR) |
| `POST /api/oa/inventory-query` | OA 库存查询(material code 即可;返回工厂/库存地点/WBS/在库量/SOBKZ) |
| `POST /api/oa/{stock-transfer,outbound,inbound,purchase}` | 固化 4 流填单(zod 校验 + 进程内互斥;入参为**已结构化**数据) |
| `GET /api/wbs/list` · `POST /api/wbs/{get,upsert,archive,delete,resolve}` | WBS 主数据 CRUD + **别称模糊解析** |
| `POST /api/explore/page` | 通用页面探索(安全闸:HTTPS+白名单,拒点提交/审批/删除) |

- **两个浏览器会话(单例)**:`edgeSession`(`chromium.launchPersistentContext(channel:'msedge')`,profile 模式由 `MEGANT_EDGE_PROFILE_MODE` 控:`sso-handoff`/`isolated`/`current`/…);`cachedProfileSession`(PDM 用真实 Edge profile 的副本)。
- **固化流**(`flows/*.js`):硬编码 selector + 模态/browser-field 交互序列,参数化自 `config/oa-workflow-*.json`;只点 `保存`(存草稿),正则硬拦 提交/审批/付款/删除/发布/发送。失败落 `.runtime/<task>-requests/` 报告+截图。
- **库存语义(关键)**:`oaInventoryQuery` 返回 organizedRows,每行含 `unrestrictedStock`、`specialStockIndicator`(**SOBKZ**)、`wbsCode`。`SOBKZ="Q"` = 项目/专属仓库存;空 = 公共仓通用库存。**这是路由判定的依据**。
- **WBS registry**(`wbsRegistry.js`):JSON 文件 `.runtime/wbs-registry.json`,合并式 upsert(部分更新不抹其它字段)。字段:`wbsCode/alias/projectDefinition/demandFactoryCode/costCenter/purchaser(458 申请人)/mrpController/stockLocationName/stockLocationSapCode/projectType/purchaseType/purchaseDemandType/deliveryAddress/demandDateOffsetDays/remark/status`。`projectType/purchaseType/purchaseDemandType` 来自后端选项目录。`resolveWbs(query)`:精确码 → 精确别称 → 别称/项目/码 模糊子串。

---

## 4. 编排层「脑」(`orchestrator/`)

### 4.1 图拓扑(`graph.py`,两种模式)

**single 模式**(单流程,旧;`run_workflow(mode="single")`,workflow_id ∈ 89/412/414/458):
```
intake → preflight → understand → personalize → check_slot →(missing? ask)→ pdm_enrich
   → resolve_params → execute → verify →(fail? diagnose →retry/…)→ finalize
```
按 `workflows.WORKFLOWS` 注册表 delegate(`get_workflow_spec`)。

**acquire 模式(主力,库存驱动 WBS-fan-out router;`run_workflow(mode="acquire")`)**:
```
START → apply_corrections → intake(parse_demand) → preflight → resolve_wbs → classify_goal
   → pdm_enrich → unit_check
   ├─[goal=acquire]→ inventory_query → route_workflow(412/89/458)
   └─[goal=return ]───────────────────→ route_workflow(414, 按WBS)
   ⇒ prepare → execute_plan ─(ok)→ finalize
任一上游「阻塞结果」(物料码错 / 单位需审核 / 未登录 / 缺字段 / 硬错)─► assist ─►
   · 瞬时错 → 有界自动重试(回 prepare→execute_plan;saved_buckets 幂等不重复存草稿)
   · info/action → finalize(needs_input + 引导话术,可恢复)
   · 残差/结构漂移 → finalize(FAILED 人工转交)
```
- **`apply_corrections`(对话节点,START 后第一站)**:`needs_input` 后用户的下一句话当成**原位修正**而非新需求 —— LLM 抽 `CorrectionPatch`(物料码/数量/单位/成本中心/库存地点/WBS 替换 + `userReportsActionDone`),喂确定性 appliers;改完清下游、从 intake 重跑。识别不出 → 原地追问。`resumeMode=action/mixed` 且用户回「已处理/已登录」→ 不改数据、重跑**重新校验**(信任+复核)。
- **`assist`(分诊+引导节点,阻塞统一入口)**:确定性先筛(login/transient/已结构化 needs_input),LLM 只啃残差并**撰写面向用户的引导话术**(把「可自行处理」与「需人工」分开);LLM 永不改动作/重试预算(沿用 single-mode diagnose 安全立场)。checkpoint 里的 `diagnosis`+`pending_input` 即「临时 cache」。

### 4.2 节点清单(`nodes/`)

| 节点 | 作用 | LLM? |
|---|---|---|
| `intake` | Excel/需求行 → BusinessInput(openpyxl);存 store。acquire 用 `parse_demand`(保留每行 WBS) | 否 |
| `preflight` | 校验后端会话/登录 | 否 |
| `resolve_wbs` | 把需求行里写的**别称**解析成真实 WBS 码(executor.resolve_wbs;唯一命中才改) | 否 |
| `classify_goal` | 分意图 acquire / return | **是(必需)** |
| `pdm_enrich` | 逐物料 PDM 校验「存在且启用」+ 补名称/单位/规格;坏码→needs_input | 否 |
| `unit_check` | 需求单位≠基本单位时,LLM 判断是否包装误用(如 50 盒 vs 50 箱)→ 需确认则停 | **是(单位不一致时必需)** |
| `inventory_query` | 逐物料查库存 + `classify_inventory` 算路由信号(公共/项目/无) | 否 |
| `route_workflow` | **分配算法**:每物料 412>89>458 + 共享池跨行扣减;按 (流, WBS) 分桶(89 另按源 WBS);return 走 (414, WBS) | 否 |
| `prepare` | 逐草稿 `query_wbs` 补全 + **生成 458 附件**(openpyxl,真实 22 列);缺关键字段→skip+note | 否 |
| `execute_plan` | 串行逐草稿调 executor 填单;某张失败/缺输入不挡其余;汇总。**save 模式按 bucket key 复用已保存草稿**(纠错重跑不重复存) | 否 |
| `apply_corrections` | `needs_input` 后把用户回复当原位修正:LLM 抽 `CorrectionPatch` → 确定性 appliers;或「已处理」→ 重跑重校验 | **是(必需)** |
| `assist` | 阻塞分诊:确定性先筛 + LLM 写引导话术(可自行处理 vs 需人工);transient 自动重试、info/action 引导停、残差转人工 | LLM 仅润色引导(可无 key 兜底) |
| `finalize` | 写 `.runtime/orchestrator/<thread>/run.json`(两级审计 + 多草稿) | 否 |
| (single) `understand/check_slot/ask/resolve_params/execute/verify/diagnose/personalize` | 单流程模式专用 | understand/diagnose 用 LLM(有启发式兜底) |

### 4.3 分配算法(`route_workflow.allocate`)
每物料,需求量 Q,按库存行 SOBKZ + WBS 分桶,优先级 **412 > 89 > 458**:
- `a412 = min(Q, 公共仓 + 本项目专属仓(SOBKZ=Q 且 WBS==需求WBS))` → 草稿 **(412, 需求WBS)**
- 对每个别项目源 WBS:`a89 = min(剩余, 该源量)` → 草稿 **(89, 转出=源WBS, 转入=需求WBS)**,移动类型恒 `项目库存转储至项目库存`
- `a458 = 剩余缺口` → 草稿 **(458, 需求WBS)**
- 同物料跨行扣减同一库存池(不重复占用);跨物料同键合并物料行 → 每桶一张草稿。

### 4.4 Executor 契约(`executors/base.py`,设备无关)
`session_status / query_pdm / inventory_query / query_wbs / resolve_wbs / fill_stock_transfer / fill_outbound / fill_inbound / fill_purchase`。
- `HttpNodeExecutor`(http_node.py):全部经 HTTP 调 Node。
- `MockExecutor`(mock.py):内存假后端 + 内置目录/库存/WBS(含别称),离线跑全图。
- `bff.MockWithRealWbs`:mock + `query_wbs/resolve_wbs` 走真实 Node registry。

### 4.5 LLM(`llm.py`)
DeepSeek(`orchestrator/.env` 的 `DEEPSEEK_API_KEY`;模型 `deepseek-v4-pro` 是 thinking 模型,用 JSON-schema-in-prompt 自解析)。`require_structured` = **必需,无 fallback**(classify_goal / unit_check 用它)。`set_test_responder()` 是离线测试的 stub 接缝。single 模式的 understand/diagnose 仍有启发式兜底(旧测试用 key="" 走启发式)。

### 4.6 持久化
`store.sqlite`(business_inputs + profiles 表);`checkpoints.sqlite`(LangGraph SqliteSaver,断点续跑);`.runtime/orchestrator/<thread>/run.json`(审计 + 多草稿)。

### 4.7 Agent 外壳(P1/P2,`agent/`)—— 真正的 L3
**它在确定性图之外、之上**:把自由自然语言变成结构化 `demandRows`,再交给上面的 acquire 图(`save=false`),图与安全边界一行不改。

- **工具(`agent/tools.py`,全只读/装配)**:`query_pdm` / `query_inventory` / `resolve_wbs` / `query_wbs` + 终结工具 `emit_demand`。模型用 `deepseek-chat`(`deepseek_tool_model`)——thinking 模型不支持强制 tool_choice,故 agent 层单独走 chat 模型。
- **intake agent(`agent/intake_agent.py`)**:`create_react_agent(model, tools)`。`run_intake(agent, msg, thread)` 跑一轮 → 信息不全返回 `{status:'clarify', question}`(多轮靠 checkpointer 记忆);齐了对**每个目标**调一次 `emit_demand`,收集成 `groups`(P2 复合:采购 + 归还)。
- **入口**:`POST /api/agent-chat`(SSE)。每个 group 用 `forced_goal`(透传 `run_workflow→new_state→classify_goal`,跳过整句意图分类)跑一遍 acquire 图,草稿聚合;单 group = P1。前端左侧「AI 下单」开关默认开,表单/配置面板保留不变。
- **安全**:agent 能调的全是只读/可回退;写操作仍只走「哑」确定性管线、永不提交。AI-native 度 L1→L3,红线一条没碰。

### 4.8 自适应采集(P3)+ 记忆脚手架(④⑤)
- **P3(`pdm_enrich`)**:物料码查无 → **按名称自适应重查**;唯一启用匹配自动改码(plans+demandRows 同步重映射)、多匹配surface候选。库存查询本就按物料码**全工厂/全库位**拉(`werksList:[]`),已是完整画像,无需再按维度重拉。
- **④⑤(`memory/`,默认休眠)**:`MemoryStore` 协议 + `PurchaseEpisode`/`ReturnDraft` schema + `NullMemory`(默认 no-op)/`MockMemory`;`get_memory()` 工厂、`recall_context()` 入口钩子;`link_reverse` = 412 出库→414 入库退料反向派生。**接口态**:待 4000 条历史记录格式确定后接 `Jsonl/Sqlite/Vector` 实现并 `MEGANT_MEMORY` 指向即可,图拓扑不动。

---

## 5. BFF + 前端

- **BFF**(`bff.py` :8788,FastAPI + CORS):代理 Node 的 session/login/sso/wbs;`/api/profile`(store);`POST /api/chat`(SSE,工作线程跑 run_workflow,`on_update` 推逐节点事件,终态发草稿/needs_input);executor 开关。前端表格 demandRows → 拼 BusinessInput 存 store → intake 跳过 Excel。
- **前端**(`frontend/`):Vue3 壳 + **deep-chat**(MIT Web Component,CDN)。双栏:左对话(进度 chips + 彩色草稿卡,html 消息在 shadow DOM,**草稿卡用内联样式**)、右采购需求表;配置(初始化/用户设置/WBS)收进右滑抽屉。

---

## 6. 进度状态

| 模块 | 状态 |
|---|---|
| Node 固化 4 流(89/412/414/458)+ PDM 查询 + 探索框架 | ✅ 早已固化 |
| OA 库存查询(Q 项目库存路径)| ✅ 真机验证过(material 4000059295) |
| 编排层 single 模式(workflow 89 闭环)+ 412/414/458 抽 flow | ✅ 离线测试 |
| WBS registry + Executor query_wbs/resolve_wbs + 别称 | ✅ 离线 + 浏览器 |
| acquire router(412/89/458 分配 + WBS 分桶)+ 458 附件(真实 22 列)+ unit_check + return 414 | ✅ 离线(tests/router.py)+ 浏览器(真 DeepSeek + mock 后端) |
| BFF 网关 + Vue3/deep-chat 双栏前端 | ✅ 浏览器端到端跑通 |
| 离线测试套件 | ✅ smoke/stage2/stage3/chat_demo/inventory/wbs/router/bff 全绿 + `npm run check` |
| **真机 acquire dry-run(HttpNodeExecutor + 登录态 OA)** | ⏳ **未验证** —— 需登录 Edge + 公司网 |
| OA 458 导入是否需要附件的 5 个参考页签 | ⏳ 待真机确认(当前只生成数据主表;`prepare` 留了模板化空间) |
| 公共仓 / 无库存分支的真实 SOBKZ 语义 | ⏳ 只验过 Q(项目库存);空/无库存仅在 mock |
| 真 DeepSeek 在规模下的 classify_goal/unit_check 质量 | ⏳ 单次验过,未压测 |

---

## 7. 安全边界(贯穿,enforced)
- 全程只存草稿:`flows/*` never click 提交;`actionRunner`/`oaAutomation` 正则硬拦 提交/审批/付款/删除/发布/发送;acquire 图无提交路径。
- 不抓/回放 SSO 一次性链接,不导出 cookie,不读 token/SAML/OAuth-code/密码/MFA。
- BFF 只代理 + 编排,不碰凭据;喂 LLM 只业务字段(物料/数量/WBS/库存地点/规格),绝不喂 SSO URL/token/截图。
- 域名白名单(explorer/domainGuard + server SSO host 白名单);redaction 脱敏每条出站 URL/正文/日志。

---

## 8. Debug 锦囊(症状 → 看哪里)

| 症状 | 看这里 |
|---|---|
| 聊天报 `LLM understanding required…` / classify_goal 抛错 | `DEEPSEEK_API_KEY` 没配。`orchestrator/.env`;mock 模式也需要(LLM 必需)。 |
| BFF 502 `Node service unreachable` | Node(:8787)没起,或 `NODE_BASE_URL` 不对。代理类端点(session/wbs)都需 Node。 |
| 起 Node 报 `EADDRINUSE :8787` | 有残留 `node src/server.js`。`pkill -f src/server.js`。两个进程不能同时持有同一 Edge profile。 |
| 草稿被「跳过(needsInput costCenter / stockLocation)」 | 该 WBS 在 registry 里缺成本中心/库存地点。配置抽屉 → WBS 管理补全(真机走 Node registry;mock 也读 Node registry)。 |
| WBS 别称没解析 | `resolve_wbs` 返回多候选(歧义)或无命中 → 看 run.json 的 resolve_wbs note;别称要能唯一命中。 |
| 路由结果不对(该走 89 却走 412 等) | 看库存 SOBKZ:`Q`=项目库存(别项目→89),空=公共仓(→412)。`inventory_query`/`classify_inventory` 的 locations。真机库存数据是源头。 |
| 458 草稿缺附件 / 列对不上 | `prepare.PURCHASE_ATTACHMENT_HEADERS`(真实 22 列);申请人=registry.purchaser,送货地址=registry.deliveryAddress。真机若导入要 5 个参考页签,改模板化生成。 |
| 离线测试突然变慢(40-60s) | 误打真 LLM。测试应 `set_test_responder` 或 `DEEPSEEK_API_KEY=""`(走启发式/stub)。 |
| 前端 deep-chat 不渲染/不提交 | 看浏览器 console;deep-chat 是 CDN 异步 upgrade,配置在 `customElements.whenDefined` 后;草稿卡须内联样式(shadow DOM)。 |
| run.json 在哪 | `.runtime/orchestrator/<thread_id>/run.json`(两级审计 + plan_results 多草稿)。 |
| Windows vs mac 差异 | Edge profile/relay/SSO 在 `profileCache.js`/`edgeSession.js` 的平台分支里;mac 无 relay,手动在托管 Edge 登录一次。仓库根 `.venv` 是旧 Windows venv,**别用**;编排层用 `orchestrator/.venv`。 |

---

## 9. 关键环境变量
`MEGANT_EDGE_PROFILE_MODE`(`sso-handoff`|`isolated`|`current`|…)、`MEGANT_AUTO_LAUNCH_EDGE`、`MEGANT_STARTUP_URL`、`MEGANT_BROWSER_CHANNEL`、`MEGANT_SSO_ALLOWED_HOSTS`、`MEGANT_EXPLORE_ALLOWED_HOSTS`、`PORT`/`HOST`(Node);`NODE_BASE_URL`、`EXECUTOR`、`DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL`、`DEEPSEEK_TOOL_MODEL`(P1/P2 agent 层,默认 `deepseek-chat`)、`DEEPSEEK_BASE_URL`、`MEGANT_MEMORY`(④⑤,默认 `null`=休眠;`mock` 起参考实现)(编排层)。

测试全流程见 [`TESTING_GUIDE.md`](TESTING_GUIDE.md)。
