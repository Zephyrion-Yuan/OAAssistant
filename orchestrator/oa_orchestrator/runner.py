"""Frontend-agnostic entry point: run_workflow(...).

Every frontend (CLI, conversational agent, web, MCP, phone) calls this same
function — this is the seam that keeps the graph independent of the UI form
(see 02 架构方案 §2.7). It NEVER blocks on stdin: when the graph hits an
interactive interrupt (ask node), it returns status=needs_input + the question;
the frontend re-calls with `resume=<answer>` to continue.
"""
from __future__ import annotations

import uuid
from typing import Any, Callable, Dict, Optional

from langgraph.types import Command

from .config import Settings, get_settings
from .executors import get_executor
from .graph import build_graph, make_checkpointer
from .state import STATUS_NEEDS_INPUT, new_state


def extract_interrupt(chunk: Dict[str, Any]) -> Optional[str]:
    """Return the pending question if this stream chunk is an interrupt."""
    intr = chunk.get("__interrupt__")
    if not intr:
        return None
    first = intr[0] if isinstance(intr, (list, tuple)) else intr
    value = getattr(first, "value", first)
    if isinstance(value, dict):
        return value.get("question") or str(value)
    return str(value)


def build_runtime(executor=None, settings: Optional[Settings] = None):
    """Build (settings, executor, compiled graph) once; reuse across calls/turns."""
    settings = settings or get_settings()
    settings.ensure_runtime_dir()
    executor = executor or get_executor(settings)
    graph = build_graph(executor, checkpointer=make_checkpointer(settings.checkpoint_path))
    return settings, executor, graph


def run_workflow(
    *,
    request: str = "",
    excel_path: Optional[str] = None,
    thread_id: Optional[str] = None,
    save: bool = False,
    interactive: bool = False,
    user_id: Optional[str] = None,
    profile: Optional[Dict[str, Any]] = None,
    resume: Optional[Any] = None,
    workflow_id: str = "89",
    executor=None,
    graph=None,
    settings: Optional[Settings] = None,
    on_update: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Run (or resume) one workflow thread. Returns a frontend-friendly dict.

    - fresh start: pass `request` (+ `excel_path`).
    - answer an ask: pass `resume=<answer>` with the same `thread_id`.
    - resume after crash: pass only `thread_id` (no request/resume).
    """
    if graph is None or settings is None:
        settings, executor, graph = build_runtime(executor=executor, settings=settings)

    thread_id = thread_id or f"st-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread_id}}

    if resume is not None:
        payload: Any = Command(resume=resume)
    elif request:
        payload = new_state(
            request=request, excel_path=excel_path, thread_id=thread_id,
            interactive=interactive, save=save, workflow_id=workflow_id,
            user_id=user_id, profile=profile,
        )
    else:
        payload = None  # resume from the last checkpoint

    pending_question: Optional[str] = None
    for chunk in graph.stream(payload, config, stream_mode="updates"):
        q = extract_interrupt(chunk)
        if q is not None:
            pending_question = q
            break
        if on_update:
            on_update(chunk)

    final = graph.get_state(config).values
    result = final.get("result") or {}
    status = STATUS_NEEDS_INPUT if pending_question is not None else final.get("status")
    return {
        "thread_id": thread_id,
        "status": status,
        "ok": result.get("ok"),
        "result": result,
        "requestId": result.get("requestId"),
        "requestUrl": result.get("requestUrl"),
        "pending_question": pending_question or final.get("pending_question"),
        "audit_path": final.get("audit_path"),
        "interrupted": pending_question is not None,
        "graph": graph,
        "executor": executor,
        "settings": settings,
    }
