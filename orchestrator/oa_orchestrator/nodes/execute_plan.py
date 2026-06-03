"""execute_plan node — drive every AllocationEntry to its own OA draft, serially.

OA forms are single-page and stateful, so drafts are filled one at a time (the
Node side also serializes with a mutex). A draft that returns needsInput (or was
skipped in prepare) is recorded and the loop continues — one draft never blocks
the others. Never submits; at most saves a draft. Produces an aggregate result +
per-draft plan_results that finalize writes into the run audit.
"""
from __future__ import annotations

from typing import Any, Callable, Dict

from ..schemas import (ExecutionResult, FillRequest, InboundFillRequest,
                       OutboundFillRequest, PurchaseFillRequest)
from ._common import append_history

# workflow_id -> (executor method, request model)
_ROUTER = {
    "412": ("fill_outbound", OutboundFillRequest),
    "89": ("fill_stock_transfer", FillRequest),
    "458": ("fill_purchase", PurchaseFillRequest),
    "414": ("fill_inbound", InboundFillRequest),
}


def _draft_summary(entry: Dict[str, Any]) -> Dict[str, Any]:
    result = entry.get("result") or {}
    return {
        "workflow_id": entry.get("workflow_id"),
        "wbsCode": entry.get("wbsCode"),
        "transferOutWbs": entry.get("transferOutWbs"),
        "materialLines": entry.get("materialLines", []),
        "ok": bool(result.get("ok")),
        "requestId": result.get("requestId"),
        "requestUrl": result.get("requestUrl"),
        "needsInput": result.get("needsInput") or entry.get("needsInput"),
        "skipped": bool(entry.get("skipped")),
        "skipReason": entry.get("skipReason"),
    }


def make_execute_plan(executor) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    def execute_plan_node(state: Dict[str, Any]) -> Dict[str, Any]:
        plan = dict(state.get("plan") or {})
        entries = [dict(e) for e in (plan.get("entries", []) or [])]

        for entry in entries:
            if entry.get("skipped") or not entry.get("request"):
                entry["result"] = {"ok": False, "skipped": True, "needsInput": entry.get("needsInput")}
                continue
            wf = entry.get("workflow_id")
            mapping = _ROUTER.get(wf)
            if not mapping:
                entry["result"] = {"ok": False, "error": f"unknown workflow {wf}"}
                continue
            method_name, model_cls = mapping
            try:
                request = model_cls.model_validate(entry["request"])
                result: ExecutionResult = getattr(executor, method_name)(request)
                entry["result"] = result.model_dump()
            except Exception as exc:  # noqa: BLE001
                entry["result"] = {"ok": False, "error": f"execute failed: {exc}"}

        plan["entries"] = entries
        drafts = [_draft_summary(e) for e in entries]
        saved = [d for d in drafts if d["ok"]]
        pending = [d for d in drafts if not d["ok"]]
        all_ok = bool(entries) and all(d["ok"] for d in drafts)

        result = {
            "ok": all_ok,
            "router": True,
            "dryRun": not bool(state.get("save", False)),
            "draftCount": len(drafts),
            "savedCount": len(saved),
            "pendingCount": len(pending),
            "needsInput": (not all_ok) and any(d.get("needsInput") or d.get("skipped") for d in pending),
            "drafts": drafts,
            "notes": (plan.get("notes") or []),
        }
        history = append_history(state, {"node": "execute_plan", "ok": all_ok,
                                         "drafts": len(drafts), "saved": len(saved),
                                         "pending": len(pending)})
        return {"plan": plan, "plan_results": drafts, "result": result, "history": history}

    return execute_plan_node
