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
from .agent import build_intake_agent
from .agent import run_intake as _run_intake_impl
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


# P1 ReAct intake agent — one per executor, with its own checkpointer for
# multi-turn clarification. Lazily built (needs a tool-calling DeepSeek key).
_intake_agents: Dict[str, Any] = {}
# Test seam: offline tests inject a fake intake runner (the real one needs a
# tool-calling LLM). Defaults to the real agent run.
_intake_runner = _run_intake_impl


def set_intake_runner(fn) -> None:
    global _intake_runner
    _intake_runner = fn


def _intake_agent(executor_key: str, executor, rt_settings):
    if executor_key not in _intake_agents:
        from langgraph.checkpoint.memory import MemorySaver
        _intake_agents[executor_key] = build_intake_agent(executor, rt_settings, checkpointer=MemorySaver())
    return _intake_agents[executor_key]


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
        if row.materialName and not names.get(row.materialCode):
            names[row.materialCode] = row.materialName
        if row.unit and not units.get(row.materialCode):
            units[row.materialCode] = row.unit
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


def _emit_acquire(events, thread_id, *, request=None, correction=None, save, profile,
                  graph, executor, rt_settings, forced_goal="", terminal=True):
    """Run the acquire graph and push node SSE events. With terminal=True also emit
    the needs_input/final event. Shared by /api/chat (form-driven) and
    /api/agent-chat (the ReAct agent assembled the demand). forced_goal (P2) lets a
    planner pin acquire/return for a demand group."""
    def on_update(chunk: Dict[str, Any]) -> None:
        for node, delta in chunk.items():
            if node == "__interrupt__":
                continue
            events.put(_sse("node", node=node, summary=_summarize(delta)))
    kwargs = {"thread_id": thread_id, "save": save, "mode": "acquire", "profile": profile,
              "graph": graph, "executor": executor, "settings": rt_settings, "on_update": on_update}
    if correction is not None:
        kwargs["correction"] = correction
    else:
        kwargs["request"] = request or "采购申请"
        kwargs["forced_goal"] = forced_goal
    res = run_workflow(**kwargs)
    if not terminal:
        return res
    result = res.get("result") or {}
    if result.get("needsInput") or res.get("status") == "needs_input":
        inp = result.get("input") or res.get("pending_input") or {}
        events.put(_sse("needs_input", threadId=thread_id, status=res.get("status"),
                        kind=inp.get("kind"), question=inp.get("question") or "需要补充输入",
                        resumeMode=inp.get("resumeMode"), category=inp.get("category"),
                        detail=inp, drafts=result.get("drafts") or [],
                        correctionSummary=res.get("correction_summary") or []))
    else:
        events.put(_sse("final", threadId=thread_id, status=res.get("status"),
                        ok=result.get("ok"), drafts=result.get("drafts") or [],
                        notes=result.get("notes") or [],
                        correctionSummary=res.get("correction_summary") or [],
                        auditPath=res.get("audit_path")))
    return res


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
        try:
            _emit_acquire(events, thread_id,
                          request=(None if continuation else (req.message or "采购申请")),
                          correction=(req.message if continuation else None),
                          save=req.save, profile=profile, graph=graph,
                          executor=executor, rt_settings=rt_settings)
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


class AgentChatRequest(BaseModel):
    message: str
    threadId: Optional[str] = None
    save: bool = False
    executor: str = "mock"
    userId: Optional[str] = None


@app.post("/api/agent-chat")
async def agent_chat(req: AgentChatRequest):
    """P1 — the ReAct intake agent drives the left chat. Free natural language →
    the agent clarifies / queries read-only tools / assembles demandRows → hands
    off to the deterministic acquire graph (save=false by default). Multi-turn:
    reuse the same threadId so the agent remembers the conversation."""
    executor_key = "http-node" if req.executor == "http-node" else "mock"
    rt_settings, executor, graph = _runtime(executor_key)
    thread_id = req.threadId or f"agent-{uuid.uuid4().hex[:8]}"

    profile = None
    if req.userId:
        stored = store.get_profile(settings.store_path, req.userId)
        profile = stored.model_dump() if stored else None

    events: "queue.Queue" = queue.Queue()
    sentinel = object()

    def worker():
        try:
            try:
                agent = _intake_agent(executor_key, executor, rt_settings)
            except Exception:  # noqa: BLE001 — no key (offline/stubbed runner doesn't need it)
                agent = None
            intake = _intake_runner(agent, req.message, thread_id)
            if intake.get("status") != "ready":
                events.put(_sse("clarify", threadId=thread_id,
                                question=intake.get("question") or "请补充更多信息后继续。"))
                return
            # P2: one demand group per goal (compound request). Single group = P1.
            groups = intake.get("groups") or [{"goal": intake.get("goal", "acquire"),
                                               "demandRows": intake.get("demandRows") or []}]
            groups = [g for g in groups if g.get("demandRows")]
            if not groups:
                events.put(_sse("clarify", threadId=thread_id,
                                question="未能从描述中组装出需求行，请补充物料 / 数量 / WBS。"))
                return
            single = len(groups) == 1
            all_drafts: List[Dict[str, Any]] = []
            all_notes: List[str] = []
            pending = None
            for i, g in enumerate(groups):
                gt = thread_id if single else f"{thread_id}-g{i}"
                events.put(_sse("demand", threadId=thread_id, group=i, goal=g["goal"],
                                demandRows=g["demandRows"], reply=(intake.get("reply", "") if i == 0 else "")))
                store.save_business_input(settings.store_path, gt,
                                          _business_from_demand_rows(g["demandRows"]), None)
                res = _emit_acquire(events, gt, request=req.message, save=req.save, profile=profile,
                                    graph=graph, executor=executor, rt_settings=rt_settings,
                                    forced_goal=g["goal"], terminal=single)
                result = res.get("result") or {}
                all_drafts += result.get("drafts") or []
                all_notes += result.get("notes") or []
                if not single and pending is None and (result.get("needsInput") or res.get("status") == "needs_input"):
                    pending = (res, result, gt)
            if single:
                return  # _emit_acquire already emitted the terminal event
            if pending:
                res, result, gt = pending
                inp = result.get("input") or res.get("pending_input") or {}
                events.put(_sse("needs_input", threadId=gt, status="needs_input",
                                kind=inp.get("kind"), question=inp.get("question") or "需要补充输入",
                                resumeMode=inp.get("resumeMode"), category=inp.get("category"),
                                detail=inp, drafts=all_drafts, correctionSummary=[]))
            else:
                events.put(_sse("final", threadId=thread_id, status="done", ok=True,
                                drafts=all_drafts, notes=all_notes, correctionSummary=[]))
        except Exception as exc:  # noqa: BLE001
            events.put(_sse("error", error=str(exc)))
        finally:
            events.put(sentinel)

    threading.Thread(target=worker, daemon=True).start()

    async def stream():
        yield _sse("start", threadId=thread_id, executor=executor_key, mode="agent")
        while True:
            item = await asyncio.to_thread(events.get)
            if item is sentinel:
                break
            yield item

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
