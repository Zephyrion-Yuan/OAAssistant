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


def _bucket_key(entry: Dict[str, Any]) -> str:
    """Stable identity for an allocation bucket, content-sensitive.

    Includes the material lines (code:qty:unit) so that a correction which
    *changes* a bucket's contents produces a new key (it re-runs), while an
    untouched, already-saved bucket keeps its key (it is skipped on rerun).
    """
    lines = entry.get("materialLines") or []
    sig = ";".join(sorted(
        f"{l.get('materialCode')}:{l.get('quantity')}:{l.get('unit')}" for l in lines
    ))
    return "|".join([
        str(entry.get("workflow_id") or ""),
        str(entry.get("wbsCode") or ""),
        str(entry.get("transferOutWbs") or ""),
        sig,
    ])


def _draft_summary(entry: Dict[str, Any]) -> Dict[str, Any]:
    result = entry.get("result") or {}
    return {
        "workflow_id": entry.get("workflow_id"),
        "wbsCode": entry.get("wbsCode"),
        "transferInWbs": entry.get("wbsCode"),
        "transferOutWbs": entry.get("transferOutWbs"),
        "materialLines": entry.get("materialLines", []),
        "ok": bool(result.get("ok")),
        "requestId": result.get("requestId"),
        "requestUrl": result.get("requestUrl"),
        "needsInput": result.get("needsInput") or entry.get("needsInput"),
        "skipped": bool(entry.get("skipped")),
        "skipReason": entry.get("skipReason"),
        "reused": bool(entry.get("reused")),
    }


def _pending_item(entry: Dict[str, Any]) -> Dict[str, Any] | None:
    result = entry.get("result") or {}
    need = result.get("input") or entry.get("needsInput")
    if not need:
        return None
    item = dict(need)
    item.update({
        "workflow": entry.get("workflow_id"),
        "workflow_id": entry.get("workflow_id"),
        "wbsCode": entry.get("wbsCode"),
        "transferInWbs": item.get("transferInWbs") or entry.get("wbsCode"),
        "transferOutWbs": entry.get("transferOutWbs"),
        "materialLines": entry.get("materialLines", []),
        "skipReason": entry.get("skipReason"),
        "error": result.get("error") or entry.get("skipReason"),
    })
    return item


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _material_codes(item: Dict[str, Any]) -> list[str]:
    seen: list[str] = []
    for code in item.get("materialCodes") or []:
        text = _clean(code)
        if text and text not in seen:
            seen.append(text)
    for line in item.get("materialLines") or []:
        text = _clean(line.get("materialCode"))
        if text and text not in seen:
            seen.append(text)
    return seen


def _context_text(item: Dict[str, Any]) -> str:
    workflow = _clean(item.get("workflow_id") or item.get("workflow")) or "-"
    parts = [f"流程: {workflow}"]
    if workflow == "89":
        parts.append(f"转入/需求 WBS: {_clean(item.get('transferInWbs') or item.get('wbsCode')) or '未提供'}")
        parts.append(f"转出 WBS: {_clean(item.get('transferOutWbs')) or '未提供'}")
    else:
        parts.append(f"WBS: {_clean(item.get('wbsCode')) or '未提供'}")
    codes = _material_codes(item)
    if codes:
        parts.append("物料: " + "、".join(codes[:8]))
    return "; ".join(parts)


def _input_from_pending(items: list[Dict[str, Any]]) -> Dict[str, Any] | None:
    if not items:
        return None
    if len(items) == 1:
        item = dict(items[0])
        question = item.get("question") or item.get("error") or "该草稿需要补充信息后才能继续。"
        item["question"] = (
            f"{question}\n"
            f"{_context_text(item)}"
        )
        return item
    parts = []
    for item in items:
        parts.append(
            f"{_context_text(item)}: "
            f"{item.get('question') or item.get('error') or item.get('kind') or '需要补充'}"
        )
    return {
        "kind": "draftReview",
        "question": "部分草稿需要补充信息后才能继续:\n" + "\n".join(parts),
        "items": items,
    }


def make_execute_plan(executor) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    def execute_plan_node(state: Dict[str, Any]) -> Dict[str, Any]:
        plan = dict(state.get("plan") or {})
        entries = [dict(e) for e in (plan.get("entries", []) or [])]
        save = bool(state.get("save", False))
        # Preserved across a correction rerun: buckets already saved to OA keep
        # their requestId so we never create a duplicate draft (idempotency).
        # Only meaningful in save mode (dry-run has no real draft to duplicate).
        saved_buckets = dict(state.get("saved_buckets") or {})

        for entry in entries:
            key = _bucket_key(entry)
            if save and key in saved_buckets:
                entry["result"] = dict(saved_buckets[key])
                entry["reused"] = True
                continue
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
            if save and entry["result"].get("ok") and entry["result"].get("requestId"):
                saved_buckets[key] = entry["result"]

        plan["entries"] = entries
        drafts = [_draft_summary(e) for e in entries]
        saved = [d for d in drafts if d["ok"]]
        reused = [d for d in drafts if d["reused"]]
        pending = [d for d in drafts if not d["ok"]]
        pending_items = [item for item in (_pending_item(e) for e in entries) if item]
        pending_input = _input_from_pending(pending_items)
        all_ok = bool(entries) and all(d["ok"] for d in drafts)
        # Surface hard-error buckets (raw exception, no structured input) at the
        # top level so the assist node's residual triage can see them.
        error_msgs = [
            f"{e.get('workflow_id')}/WBS {e.get('wbsCode') or '-'}: {(e.get('result') or {}).get('error')}"
            for e in entries
            if not (e.get("result") or {}).get("ok")
            and not (e.get("result") or {}).get("needsInput")
            and not (e.get("result") or {}).get("skipped")
            and (e.get("result") or {}).get("error")
        ]

        result = {
            "ok": all_ok,
            "router": True,
            "dryRun": not bool(state.get("save", False)),
            "draftCount": len(drafts),
            "savedCount": len(saved),
            "reusedCount": len(reused),
            "pendingCount": len(pending),
            "needsInput": bool(pending_input) or ((not all_ok) and any(d.get("needsInput") or d.get("skipped") for d in pending)),
            "input": pending_input,
            "error": "; ".join(error_msgs) or None,
            "drafts": drafts,
            "notes": (plan.get("notes") or []),
        }
        history = append_history(state, {"node": "execute_plan", "ok": all_ok,
                                         "drafts": len(drafts), "saved": len(saved),
                                         "reused": len(reused), "pending": len(pending)})
        return {"plan": plan, "plan_results": drafts, "result": result,
                "saved_buckets": saved_buckets, "history": history}

    return execute_plan_node
