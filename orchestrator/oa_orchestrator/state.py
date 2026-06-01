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
    workflow_id: str                    # which workflow (Stage-3 router seam; default "89")
    user_id: Optional[str]              # personalization seam
    profile: Optional[Dict[str, Any]]   # static user defaults (personalize node)

    # accumulated
    business_input: Optional[Dict[str, Any]]   # BusinessInput dump
    intent: Optional[Dict[str, Any]]           # Intent dump
    missing: List[str]                         # missing required slots
    pdm: Optional[Dict[str, Any]]              # per-material enrichment/validation
    resolved: Optional[Dict[str, Any]]         # FillRequest dump (sans structured)
    result: Optional[Dict[str, Any]]           # ExecutionResult dump
    diagnosis: Optional[Dict[str, Any]]        # Diagnosis dump

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
              profile: Optional[Dict[str, Any]] = None) -> GraphState:
    return GraphState(
        request=request,
        excel_path=excel_path,
        thread_id=thread_id,
        interactive=interactive,
        save=save,
        workflow_id=workflow_id,
        user_id=user_id,
        profile=profile,
        business_input=None,
        intent=None,
        missing=[],
        pdm=None,
        resolved=None,
        result=None,
        diagnosis=None,
        status=STATUS_RUNNING,
        retries=0,
        history=[],
        pending_question=None,
        answer=None,
    )
