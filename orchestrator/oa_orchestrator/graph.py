"""Assemble the workflow-89 StateGraph: nodes + conditional edges + checkpointer.

Topology (unattended draft; interactive slot-filling loop):

  START → intake → preflight → understand → check_slot
                                               │ missing → ask → (interactive: understand / unattended: finalize)
                                               │ complete
                                               ▼
                                          pdm_enrich → (bad codes: diagnose) → resolve_params → execute → verify
                                                                                     ▲                        │
                                                                  diagnose ──retry───┘        ok → finalize → END
                                                                     └ terminal → finalize → END
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

from langgraph.graph import END, START, StateGraph

from .state import (STATUS_FAILED, STATUS_NEEDS_INPUT, STATUS_NEEDS_LOGIN,
                    GraphState)
from .nodes.intake import intake_node
from .nodes.apply_corrections import apply_corrections_node
from .nodes.understand import understand_node
from .nodes.personalize import personalize_node
from .nodes.check_slot import check_slot_node
from .nodes.ask import ask_node
from .nodes.preflight import make_preflight
from .nodes.pdm_enrich import make_pdm_enrich
from .nodes.resolve_params import resolve_params_node
from .nodes.execute import make_execute
from .nodes.verify import verify_node
from .nodes.diagnose import diagnose_node
from .nodes.finalize import finalize_node
# Phase 1/2 router nodes
from .nodes.classify_goal import classify_goal_node
from .nodes.resolve_wbs import make_resolve_wbs
from .nodes.unit_check import unit_check_node
from .nodes.inventory_query import make_inventory_query
from .nodes.route_workflow import route_workflow_node
from .nodes.prepare import make_prepare
from .nodes.execute_plan import make_execute_plan
from .nodes.assist import assist_node


def _result_failed(state: Dict[str, Any]) -> bool:
    result = state.get("result") or {}
    return bool(result) and not result.get("ok")


def _route_after_intake(state: Dict[str, Any]) -> str:
    return "finalize" if state.get("status") == STATUS_FAILED else "preflight"


def _route_after_correction(state: Dict[str, Any]) -> str:
    if state.get("status") == STATUS_NEEDS_INPUT:
        return "finalize"
    return "finalize" if _result_failed(state) else "intake"


def _route_after_preflight(state: Dict[str, Any]) -> str:
    if state.get("status") == STATUS_NEEDS_LOGIN:
        return "finalize"
    if _result_failed(state):
        return "diagnose"
    return "understand"


def _route_after_check_slot(state: Dict[str, Any]) -> str:
    return "ask" if state.get("missing") else "pdm_enrich"


def _route_after_ask(state: Dict[str, Any]) -> str:
    return "finalize" if state.get("status") == STATUS_NEEDS_INPUT else "understand"


def _route_after_pdm(state: Dict[str, Any]) -> str:
    result = state.get("result") or {}
    return "diagnose" if result.get("needsInput") else "resolve_params"


def _route_after_verify(state: Dict[str, Any]) -> str:
    result = state.get("result") or {}
    return "finalize" if result.get("ok") else "diagnose"


def _route_after_diagnose(state: Dict[str, Any]) -> str:
    diagnosis = state.get("diagnosis") or {}
    return "execute" if diagnosis.get("action") == "retry" else "finalize"


def _acquire_gate(next_node: str):
    """Stop at finalize whenever an upstream node set a blocking result
    (bad PDM codes, unit review, login, or no draft); otherwise go on."""
    def gate(state: Dict[str, Any]) -> str:
        return "finalize" if _result_failed(state) else next_node
    return gate


def _route_after_unitcheck(state: Dict[str, Any]) -> str:
    """Blocking result → finalize; return goal skips inventory (no stock decision)."""
    if _result_failed(state):
        return "finalize"
    return "route_workflow" if state.get("goal") == "return" else "inventory_query"


# --- acquire-mode: every blocking point routes through `assist` (triage+guide) --
def _block_gate(next_node: str):
    """A blocking result → assist (triage + user guidance); else continue."""
    def gate(state: Dict[str, Any]) -> str:
        return "assist" if _result_failed(state) else next_node
    return gate


def _route_after_preflight_acq(state: Dict[str, Any]) -> str:
    if state.get("status") == STATUS_NEEDS_LOGIN or _result_failed(state):
        return "assist"
    return "resolve_wbs"


def _route_after_unitcheck_acq(state: Dict[str, Any]) -> str:
    if _result_failed(state):
        return "assist"
    return "route_workflow" if state.get("goal") == "return" else "inventory_query"


def _route_after_assist(state: Dict[str, Any]) -> str:
    """transient → retry (back to prepare→execute_plan); else stop at finalize."""
    diagnosis = state.get("diagnosis") or {}
    return "prepare" if diagnosis.get("action") == "retry" else "finalize"


def build_acquire_graph(executor, checkpointer=None):
    """Phase-1/2 inventory-driven router. classify_goal splits the two goals:

    acquire: intake → preflight → classify_goal → pdm_enrich → unit_check
             → inventory_query → route_workflow(412/89/458) → prepare → execute_plan → finalize
    return:  …→ unit_check → route_workflow(414, bucket by WBS) → prepare → execute_plan → finalize
    Any upstream blocking result short-circuits to finalize (resumable).
    """
    g = StateGraph(GraphState)
    g.add_node("apply_corrections", apply_corrections_node)
    g.add_node("intake", intake_node)
    g.add_node("preflight", make_preflight(executor))
    g.add_node("resolve_wbs", make_resolve_wbs(executor))
    g.add_node("classify_goal", classify_goal_node)
    g.add_node("pdm_enrich", make_pdm_enrich(executor))
    g.add_node("unit_check", unit_check_node)
    g.add_node("inventory_query", make_inventory_query(executor))
    g.add_node("route_workflow", route_workflow_node)
    g.add_node("prepare", make_prepare(executor))
    g.add_node("execute_plan", make_execute_plan(executor))
    g.add_node("assist", assist_node)
    g.add_node("finalize", finalize_node)

    g.add_edge(START, "apply_corrections")
    g.add_conditional_edges("apply_corrections", _route_after_correction,
                            {"finalize": "finalize", "intake": "intake"})
    g.add_conditional_edges("intake", _route_after_intake,
                            {"finalize": "finalize", "preflight": "preflight"})
    g.add_conditional_edges("preflight", _route_after_preflight_acq,
                            {"assist": "assist", "resolve_wbs": "resolve_wbs"})
    g.add_edge("resolve_wbs", "classify_goal")
    g.add_edge("classify_goal", "pdm_enrich")
    g.add_conditional_edges("pdm_enrich", _block_gate("unit_check"),
                            {"assist": "assist", "unit_check": "unit_check"})
    g.add_conditional_edges("unit_check", _route_after_unitcheck_acq,
                            {"assist": "assist", "inventory_query": "inventory_query",
                             "route_workflow": "route_workflow"})
    g.add_conditional_edges("inventory_query", _block_gate("route_workflow"),
                            {"assist": "assist", "route_workflow": "route_workflow"})
    g.add_conditional_edges("route_workflow", _block_gate("prepare"),
                            {"assist": "assist", "prepare": "prepare"})
    g.add_edge("prepare", "execute_plan")
    g.add_conditional_edges("execute_plan", _block_gate("finalize"),
                            {"assist": "assist", "finalize": "finalize"})
    g.add_conditional_edges("assist", _route_after_assist,
                            {"prepare": "prepare", "finalize": "finalize"})
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)


def build_graph(executor, checkpointer=None, mode: str = "single"):
    if mode == "acquire":
        return build_acquire_graph(executor, checkpointer=checkpointer)
    g = StateGraph(GraphState)
    g.add_node("apply_corrections", apply_corrections_node)
    g.add_node("intake", intake_node)
    g.add_node("preflight", make_preflight(executor))
    g.add_node("understand", understand_node)
    g.add_node("personalize", personalize_node)
    g.add_node("check_slot", check_slot_node)
    g.add_node("ask", ask_node)
    g.add_node("pdm_enrich", make_pdm_enrich(executor))
    g.add_node("resolve_params", resolve_params_node)
    g.add_node("execute", make_execute(executor))
    g.add_node("verify", verify_node)
    g.add_node("diagnose", diagnose_node)
    g.add_node("finalize", finalize_node)

    g.add_edge(START, "apply_corrections")
    g.add_conditional_edges("apply_corrections", _route_after_correction,
                            {"finalize": "finalize", "intake": "intake"})
    g.add_conditional_edges("intake", _route_after_intake,
                            {"finalize": "finalize", "preflight": "preflight"})
    g.add_conditional_edges("preflight", _route_after_preflight,
                            {"finalize": "finalize", "diagnose": "diagnose", "understand": "understand"})
    g.add_edge("understand", "personalize")
    g.add_edge("personalize", "check_slot")
    g.add_conditional_edges("check_slot", _route_after_check_slot,
                            {"ask": "ask", "pdm_enrich": "pdm_enrich"})
    g.add_conditional_edges("ask", _route_after_ask,
                            {"finalize": "finalize", "understand": "understand"})
    g.add_conditional_edges("pdm_enrich", _route_after_pdm,
                            {"diagnose": "diagnose", "resolve_params": "resolve_params"})
    g.add_edge("resolve_params", "execute")
    g.add_edge("execute", "verify")
    g.add_conditional_edges("verify", _route_after_verify,
                            {"finalize": "finalize", "diagnose": "diagnose"})
    g.add_conditional_edges("diagnose", _route_after_diagnose,
                            {"execute": "execute", "finalize": "finalize"})
    g.add_edge("finalize", END)

    return g.compile(checkpointer=checkpointer)


def make_checkpointer(path: Optional[Path]):
    """SqliteSaver backed by a file (durable resume) or in-memory (tests)."""
    from langgraph.checkpoint.sqlite import SqliteSaver

    if path is None:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=False)
    return SqliteSaver(conn)
