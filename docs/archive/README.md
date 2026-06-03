# Archive

过时但保留的文档与产物。内容仍可参考,但**不代表当前状态** —— 当前架构与进度以 [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) 为准。

## reports/(里程碑可视化报告,点状历史)
开发各阶段完成时生成的自包含 HTML 报告。已被 `docs/ARCHITECTURE.md`(综合架构)+ `docs/frontend-report.html`(当前前端)取代,仅作历史留存。

- `stage1-report.html` — Stage 1:LangGraph 编排层最小闭环(workflow 89)。
- `phase0-report.html` — Phase 0:WBS 主数据库(Node registry + Executor query_wbs)。
- `phase1-report.html` — Phase 1:获取模式 WBS-fan-out router(412/89/458)。
- `phase2-report.html` — Phase 2:归还模式(414)+ 真实 458 附件对齐 + LLM 必需化。

## DEVELOPMENT_PLAN.md
最初的「纯确定性 Node 服务」开发计划(程序内不用 AI)。编排层(Python LangGraph 脑)叠加之后,这份计划只描述了 Node「手」层的早期骨架,已被实际架构超越。
