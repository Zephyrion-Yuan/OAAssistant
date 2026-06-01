"""verify node — confirm the run reached "saved draft" (or a clean dry-run).
Annotates a verdict; routing is decided by the graph edge.
"""
from __future__ import annotations

from typing import Any, Dict

from ._common import append_history


def verify_node(state: Dict[str, Any]) -> Dict[str, Any]:
    result = state.get("result") or {}
    save = bool(state.get("save", False))
    ok = bool(result.get("ok"))
    saved_draft = bool(result.get("requestId"))
    # A dry-run (save=False) is verified by ok alone; a save run also needs a requestId.
    verified = ok and (saved_draft or not save)
    history = append_history(state, {
        "node": "verify",
        "verified": verified,
        "savedDraft": saved_draft,
        "needsInput": bool(result.get("needsInput")),
    })
    return {"history": history}
