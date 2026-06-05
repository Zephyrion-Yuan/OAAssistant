"""GraphState — the value threaded through the LangGraph nodes.

Kept as a plain TypedDict of JSON-serializable values (Pydantic models are
dumped to dicts at node boundaries) so the SqliteSaver checkpointer can persist
and resume it cleanly.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


# Terminal/working statuses
STATUS_RUNNING = "running"
STATUS_NEEDS_INPUT = "needs_input"      # resumable: operator supplies a missing slot
STATUS_NEEDS_LOGIN = "needs_login"      # resumable: user logs into managed Edge
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_ESCALATED = "escalated"          # structural drift -> human


class GraphState(TypedDict, total=False):
    # inputs
    request: str                        # natural-language request
    excel_path: Optional[str]
    thread_id: str
    interactive: bool                   # interactive ask-loop vs unattended NEEDS_INPUT
    save: bool                          # save draft after filling (False = dry-run)
    mode: str                           # "single" (one workflow) | "acquire" (Phase-1 router)
    goal: str                           # router intent: "acquire" | "return" (classify_goal)
    forced_goal: str                    # P2: planner-supplied goal that overrides classify_goal
    workflow_id: str                    # which workflow (Stage-3 router seam; default "89")
    user_id: Optional[str]              # personalization seam
    profile: Optional[Dict[str, Any]]   # static user defaults (personalize node)

    # accumulated
    business_input: Optional[Dict[str, Any]]   # BusinessInput dump
    intent: Optional[Dict[str, Any]]           # Intent dump
    missing: List[str]                         # missing required slots
    pdm: Optional[Dict[str, Any]]              # per-material enrichment/validation
    inventory: Optional[Dict[str, Any]]        # per-material SAP stock + route hints (Stage-3b)
    unit_review: Optional[List[Dict[str, Any]]]  # unit_check: suspected unit mismatches
    plan: Optional[Dict[str, Any]]             # AllocationPlan dump (route_workflow)
    plan_results: Optional[List[Dict[str, Any]]]  # per-draft execution results (execute_plan)
    resolved: Optional[Dict[str, Any]]         # FillRequest dump (sans structured)
    result: Optional[Dict[str, Any]]           # ExecutionResult dump
    diagnosis: Optional[Dict[str, Any]]        # Diagnosis dump
    pending_input: Optional[Dict[str, Any]]    # structured continuation request
    correction: Optional[str]                  # user's follow-up for pending_input
    correction_history: List[Dict[str, Any]]   # applied in-place corrections
    correction_summary: List[str]              # last applied correction summary
    wbs_overrides: Dict[str, Dict[str, Any]]   # run-local WBS bound-field patches
    routing_overrides: Dict[str, str]          # material -> "transfer": route other-project stock to 89
    saved_buckets: Dict[str, Any]              # bucketKey -> saved draft result (idempotent rerun)

    # control
    status: str
    retries: int
    history: List[Dict[str, Any]]              # per-node audit records
    pending_question: Optional[str]            # ask node -> user
    answer: Optional[str]                      # user reply (interactive)
    audit_path: Optional[str]                  # finalize -> run.json path


def new_state(request: str, excel_path: Optional[str], thread_id: str,
              interactive: bool, save: bool, workflow_id: str = "89",
              user_id: Optional[str] = None,
              profile: Optional[Dict[str, Any]] = None,
              mode: str = "single", forced_goal: str = "") -> GraphState:
    return GraphState(
        request=request,
        excel_path=excel_path,
        thread_id=thread_id,
        interactive=interactive,
        save=save,
        mode=mode,
        goal="acquire",
        forced_goal=forced_goal or "",
        workflow_id=workflow_id,
        user_id=user_id,
        profile=profile,
        business_input=None,
        intent=None,
        missing=[],
        pdm=None,
        inventory=None,
        unit_review=None,
        plan=None,
        plan_results=None,
        resolved=None,
        result=None,
        diagnosis=None,
        pending_input=None,
        correction=None,
        correction_history=[],
        correction_summary=[],
        wbs_overrides={},
        routing_overrides={},
        saved_buckets={},
        status=STATUS_RUNNING,
        retries=0,
        history=[],
        pending_question=None,
        answer=None,
    )
