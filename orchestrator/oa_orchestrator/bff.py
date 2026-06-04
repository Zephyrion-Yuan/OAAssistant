"""FastAPI BFF gateway — the single HTTP surface the test frontend (and any
future Agent platform) talks to. The frontend NEVER touches the Node service or
the graph directly; it only calls this API.

Responsibilities:
- proxy session / login / sso / WBS to the Node deterministic service (:8787)
- profile (user-settings) CRUD over the orchestrator store (no HTTP before)
- POST /api/chat: run the acquire-mode WBS-fan-out router, streamed as SSE

Executor toggle (per /api/chat request):
- "mock":      MockExecutor for OA/PDM/inventory, but query_wbs reads the REAL
               Node registry, so WBS the user edits in the UI is honored offline.
- "http-node": the real Node service end to end (needs a logged-in Edge).

Note: the LLM (classify_goal / unit_check) is a required dependency either way —
configure DEEPSEEK_API_KEY (orchestrator/.env). Run:
    PYTHONPATH=orchestrator orchestrator/.venv/bin/uvicorn oa_orchestrator.bff:app --port 8788
"""
from __future__ import annotations

import asyncio
import json
import queue
import threading
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import store
from .config import get_settings
from .executors.http_node import HttpNodeExecutor
from .executors.mock import MockExecutor
from .runner import build_runtime, run_workflow
from .schemas import BusinessInput, DemandRow, MaterialPlan, Profile

settings = get_settings()
settings.ensure_runtime_dir()
NODE = settings.node_base_url

app = FastAPI(title="OAAssistant BFF", version="1.0",
              description="Front-end-facing gateway: Node proxy + profile + acquire-router SSE chat.")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Executor + compiled-graph cache (one runtime per executor flavour)
# --------------------------------------------------------------------------- #
class MockWithRealWbs:
    """MockExecutor for OA/PDM/inventory, but query_wbs delegates to the real
    Node WBS registry (falling back to the mock registry if Node is down), so
    the WBS records the user manages in the UI drive offline chat runs too."""

    name = "mock+wbs"

    def __init__(self, node_base_url: str):
        self._mock = MockExecutor()
        self._node = HttpNodeExecutor(node_base_url)

    def __getattr__(self, name):  # delegate everything else to the mock
        return getattr(self._mock, name)

    def query_wbs(self, wbs_code: str):
        try:
            record = self._node.query_wbs(wbs_code)
            return record if record is not None else self._mock.query_wbs(wbs_code)
        except Exception:  # noqa: BLE001 — Node unreachable → mock registry
            return self._mock.query_wbs(wbs_code)


_runtimes: Dict[str, Any] = {}


def _runtime(executor_key: str):
    if executor_key not in _runtimes:
        executor = MockWithRealWbs(NODE) if executor_key == "mock" else HttpNodeExecutor(NODE)
        _runtimes[executor_key] = build_runtime(executor=executor, settings=settings, mode="acquire")
    return _runtimes[executor_key]


# --------------------------------------------------------------------------- #
# Node proxy
# --------------------------------------------------------------------------- #
async def _proxy(method: str, path: str, **kwargs) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.request(method, f"{NODE}{path}", **kwargs)
            return resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Node service unreachable: {exc}") from exc


@app.get("/api/health")
async def health():
    return {"ok": True, "node": NODE, "executors": ["mock", "http-node"]}


@app.get("/api/session/status")
async def session_status():
    return await _proxy("GET", "/api/session/status")


@app.post("/api/session/login/{system}/{action}")
async def login(system: str, action: str):
    if system not in {"oa", "pdm"} or action not in {"start", "test-live"}:
        raise HTTPException(status_code=400, detail="login route must be /{oa|pdm}/{start|test-live}")
    return await _proxy("POST", f"/api/{system}/login/{action}", json={})


class SsoBody(BaseModel):
    url: str


@app.post("/api/sso/open")
async def sso_open(body: SsoBody):
    return await _proxy("POST", "/api/sso/open", json=body.model_dump())


@app.get("/api/wbs/list")
async def wbs_list(includeArchived: bool = False):  # noqa: N803 (query param name)
    return await _proxy("GET", f"/api/wbs/list?includeArchived={'1' if includeArchived else '0'}")


@app.get("/api/options/catalog")
async def options_catalog():
    return await _proxy("GET", "/api/options/catalog")


@app.post("/api/options/catalog")
async def options_catalog_upsert(body: Dict[str, Any]):
    return await _proxy("POST", "/api/options/catalog", json=body)


@app.post("/api/wbs/upsert")
async def wbs_upsert(body: Dict[str, Any]):
    return await _proxy("POST", "/api/wbs/upsert", json=body)


@app.post("/api/wbs/archive")
async def wbs_archive(body: Dict[str, Any]):
    return await _proxy("POST", "/api/wbs/archive", json=body)


@app.post("/api/wbs/delete")
async def wbs_delete(body: Dict[str, Any]):
    return await _proxy("POST", "/api/wbs/delete", json=body)


@app.post("/api/wbs/resolve")
async def wbs_resolve(body: Dict[str, Any]):
    return await _proxy("POST", "/api/wbs/resolve", json=body)


# --------------------------------------------------------------------------- #
# Profile (user settings) — orchestrator store, exposed over HTTP here
# --------------------------------------------------------------------------- #
@app.get("/api/profile/{user_id}")
async def get_profile(user_id: str):
    profile = store.get_profile(settings.store_path, user_id)
    return {"ok": True, "found": profile is not None,
            "profile": profile.model_dump() if profile else None}


@app.post("/api/profile")
async def save_profile(body: Dict[str, Any]):
    if not body.get("user_id"):
        raise HTTPException(status_code=400, detail="user_id is required")
    profile = Profile.model_validate(body)
    store.save_profile(settings.store_path, profile)
    return {"ok": True, "profile": profile.model_dump()}


# --------------------------------------------------------------------------- #
# Chat — acquire-mode router, streamed as Server-Sent Events
# --------------------------------------------------------------------------- #
class ChatRequest(BaseModel):
    message: str = ""
    threadId: Optional[str] = None
    demandRows: List[Dict[str, Any]] = []
    save: bool = False
    executor: str = "mock"   # "mock" | "http-node"
    userId: Optional[str] = None
    continueThread: bool = False


def _business_from_demand_rows(rows: List[Dict[str, Any]]) -> BusinessInput:
    """Build a BusinessInput (per-row demand + per-material aggregate) from the
    frontend's table — seeded into the store so intake skips Excel parsing."""
    demand = [DemandRow.model_validate(r) for r in rows]
    totals: Dict[str, Decimal] = {}
    names: Dict[str, str] = {}
    units: Dict[str, str] = {}
    for row in demand:
        try:
            qty = Decimal(str(row.quantity or "0"))
        except (InvalidOperation, ValueError):
            qty = Decimal(0)
        totals[row.materialCode] = totals.get(row.materialCode, Decimal(0)) + qty
        names.setdefault(row.materialCode, row.materialName)
        units.setdefault(row.materialCode, row.unit)
    plans = [MaterialPlan(materialCode=c, materialName=names.get(c, ""),
                          quantity=str(totals[c]), unit=units.get(c, ""))
             for c in totals]
    first = demand[0] if demand else None
    return BusinessInput(
        projectDefinition=(first.projectDefinition if first else None),
        wbsCode=(first.wbsCode if first else None),
        demandFactoryCode=(first.demandFactoryCode if first else None),
        mrpController=(first.mrpController if first else None),
        materialPlans=plans, demandRows=demand,
    )


def _sse(event_type: str, **data) -> str:
    return f"data: {json.dumps({'type': event_type, **data}, ensure_ascii=False)}\n\n"


def _summarize(delta: Any) -> str:
    if not isinstance(delta, dict):
        return str(delta)
    bits = []
    for key, value in delta.items():
        if key == "history":
            continue
        bits.append(f"{key}=<{type(value).__name__}>" if isinstance(value, (dict, list)) else f"{key}={value}")
    return ", ".join(bits) or "(history)"


@app.post("/api/chat")
async def chat(req: ChatRequest):
    executor_key = "http-node" if req.executor == "http-node" else "mock"
    rt_settings, executor, graph = _runtime(executor_key)
    continuation = bool(req.continueThread and req.threadId)
    thread_id = req.threadId if continuation else (req.threadId or f"chat-{uuid.uuid4().hex[:8]}")

    profile = None
    if req.userId:
        stored = store.get_profile(settings.store_path, req.userId)
        profile = stored.model_dump() if stored else None
    if req.demandRows and not continuation:
        store.save_business_input(settings.store_path, thread_id,
                                  _business_from_demand_rows(req.demandRows), None)

    events: "queue.Queue" = queue.Queue()
    sentinel = object()

    def worker():
        def on_update(chunk: Dict[str, Any]) -> None:
            for node, delta in chunk.items():
                if node == "__interrupt__":
                    continue
                events.put(_sse("node", node=node, summary=_summarize(delta)))
        try:
            kwargs = {
                "thread_id": thread_id,
                "save": req.save,
                "mode": "acquire",
                "profile": profile,
                "graph": graph,
                "executor": executor,
                "settings": rt_settings,
                "on_update": on_update,
            }
            if continuation:
                kwargs["correction"] = req.message
            else:
                kwargs["request"] = req.message or "采购申请"
            res = run_workflow(
                **kwargs,
            )
            result = res.get("result") or {}
            if result.get("needsInput") or res.get("status") == "needs_input":
                inp = result.get("input") or res.get("pending_input") or {}
                events.put(_sse("needs_input", threadId=thread_id, status=res.get("status"),
                                kind=inp.get("kind"), question=inp.get("question") or "需要补充输入",
                                detail=inp, drafts=result.get("drafts") or [],
                                correctionSummary=res.get("correction_summary") or []))
            else:
                events.put(_sse("final", threadId=thread_id, status=res.get("status"),
                                ok=result.get("ok"), drafts=result.get("drafts") or [],
                                notes=result.get("notes") or [],
                                correctionSummary=res.get("correction_summary") or [],
                                auditPath=res.get("audit_path")))
        except Exception as exc:  # noqa: BLE001
            events.put(_sse("error", error=str(exc)))
        finally:
            events.put(sentinel)

    threading.Thread(target=worker, daemon=True).start()

    async def stream():
        yield _sse("start", threadId=thread_id, executor=executor_key, continuation=continuation)
        while True:
            item = await asyncio.to_thread(events.get)
            if item is sentinel:
                break
            yield item

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
