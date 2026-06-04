"""finalize node — assemble the two-level audit (graph-node history + the Node
report's Playwright-step actions) and write it to
.runtime/orchestrator/<thread>/run.json.
"""
from __future__ import annotations

import json
from typing import Any, Dict

from ..config import get_settings
from ..state import (STATUS_DONE, STATUS_FAILED, STATUS_NEEDS_INPUT,
                    STATUS_NEEDS_LOGIN, STATUS_RUNNING)
from ._common import append_history


def finalize_node(state: Dict[str, Any]) -> Dict[str, Any]:
    settings = get_settings()
    result = state.get("result") or {}
    status = state.get("status", STATUS_RUNNING)
    if status == STATUS_RUNNING:
        # an upstream node may have stopped with a resumable signal without a
        # diagnose pass (e.g. the acquire router); map it here.
        if result.get("needsInput"):
            status = STATUS_NEEDS_INPUT
        elif result.get("needsLogin"):
            status = STATUS_NEEDS_LOGIN
        else:
            status = STATUS_DONE if result.get("ok") else STATUS_FAILED

    pending_input = result.get("input") if result.get("needsInput") else state.get("pending_input")
    pending_question = state.get("pending_question")
    if status == STATUS_NEEDS_INPUT and not pending_question:
        pending_question = (pending_input or {}).get("question") or result.get("error")

    thread = state.get("thread_id", "default")
    out_dir = settings.runtime_dir / thread
    out_dir.mkdir(parents=True, exist_ok=True)
    audit = {
        "thread_id": thread,
        "status": status,
        "request": state.get("request"),
        "save": state.get("save"),
        "intent": state.get("intent"),
        "missing": state.get("missing"),
        "pdm": state.get("pdm"),
        "resolved": state.get("resolved"),
        "result": result,
        "diagnosis": state.get("diagnosis"),
        "pending_question": pending_question,
        "pending_input": pending_input,
        "correction_history": state.get("correction_history", []),
        "graph_history": state.get("history", []),
        "playwright_actions": result.get("actions", []),
        "requestUrl": result.get("requestUrl"),
        # acquire-mode router: per-draft fan-out audit
        "plan_results": state.get("plan_results"),
        "plan_notes": (state.get("plan") or {}).get("notes"),
    }
    audit_path = out_dir / "run.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")

    history = append_history(state, {"node": "finalize", "status": status, "audit": str(audit_path)})
    return {
        "status": status,
        "audit_path": str(audit_path),
        "pending_input": pending_input,
        "pending_question": pending_question,
        "history": history,
    }
