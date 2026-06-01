"""finalize node — assemble the two-level audit (graph-node history + the Node
report's Playwright-step actions) and write it to
.runtime/orchestrator/<thread>/run.json.
"""
from __future__ import annotations

import json
from typing import Any, Dict

from ..config import get_settings
from ..state import STATUS_DONE, STATUS_FAILED, STATUS_RUNNING
from ._common import append_history


def finalize_node(state: Dict[str, Any]) -> Dict[str, Any]:
    settings = get_settings()
    result = state.get("result") or {}
    status = state.get("status", STATUS_RUNNING)
    if status == STATUS_RUNNING:
        status = STATUS_DONE if result.get("ok") else STATUS_FAILED

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
        "pending_question": state.get("pending_question"),
        "graph_history": state.get("history", []),
        "playwright_actions": result.get("actions", []),
        "requestUrl": result.get("requestUrl"),
    }
    audit_path = out_dir / "run.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")

    history = append_history(state, {"node": "finalize", "status": status, "audit": str(audit_path)})
    return {"status": status, "audit_path": str(audit_path), "history": history}
