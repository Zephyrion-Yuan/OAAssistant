"""check_slot node — pure function computing missing required slots.

Delegates the per-workflow "what's required" logic to the workflow registry so
this node stays workflow-agnostic. Material existence is validated separately by
pdm_enrich.
"""
from __future__ import annotations

from typing import Any, Dict

from ..workflows import get_workflow_spec
from ._common import append_history


def check_slot_node(state: Dict[str, Any]) -> Dict[str, Any]:
    spec = get_workflow_spec(state.get("workflow_id", "89"))
    missing = spec.required_slots(state.get("intent") or {}, state.get("business_input") or {})
    history = append_history(state, {"node": "check_slot", "workflow": spec.workflow_id, "missing": missing})
    return {"missing": missing, "history": history}
