# orchestrator/archive

归档的、已被取代的编排层代码。**不在 `oa_orchestrator` 包内**,不会被导入或运行。

- `serve.py` — 早期极简 stdlib `http.server`,只暴露 `POST /chat` + `GET /health`,用于验证 `run_workflow` 的 HTTP 接缝。已被 `oa_orchestrator/bff.py`(FastAPI 网关:代理 Node + 画像 + executor 开关 + SSE 流式聊天)完全取代。
