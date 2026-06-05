"""assist node — triage a blocked/failed acquire run, then either auto-retry a
transient fault, guide the user (supply info OR perform an external action) and
stop for a reply, or hand off to a human.

Deterministic-first (the safety backbone): the *category, routing, retry budget
and resumeMode* are decided by the rules below. The LLM only **composes the
user-facing guidance text** — and, for an otherwise-unclassifiable hard error,
may classify it info/action/unsupported. The LLM can never widen the action or
bypass the retry budget (mirrors the single-mode diagnose philosophy). With no
DEEPSEEK_API_KEY the guidance falls back to the deterministic question, so the
offline tests run unchanged.

The user's "temp cache to search" is the checkpointed state itself: the enriched
``pending_input`` + ``diagnosis`` + ``correction_history`` persist per thread via
the SqliteSaver, and the dialogue node reads them on the next message.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict

from ..config import get_settings
from ..llm import extract_structured
from ..schemas import Diagnosis, DiagnosisAction, FailureCategory
from ..state import (STATUS_FAILED, STATUS_NEEDS_INPUT, STATUS_NEEDS_LOGIN,
                     STATUS_RUNNING)
from ._common import (RESUME_ACTION, RESUME_CORRECT, RESUME_MIXED,
                      append_history)

_LOGIN_HINTS = ("requires login", "still requires login", "未登录", "需要登录", "login", "session")
_TRANSIENT_HINTS = ("network", "timeout", "timed out", "econnrefused", "etimedout",
                    "backend unreachable", "socket", "temporarily", "503", "502")
# A Playwright selector/locator timeout looks transient ("timeout") but is really
# structural drift — retrying just fails again. These hints veto transient.
_STRUCTURAL_HINTS = ("locator", "selector", "waiting for", "not found",
                     "no element", "no node", "strict mode")

# Known structured needs_input kinds -> (category, resumeMode). 'action' kinds
# expect the user to do something externally (then report done); 'input'/data
# kinds expect a value; 'mixed' accepts either (e.g. type the cost center OR go
# maintain it in the WBS/master data).
_KIND_TRIAGE = {
    "material": ("input", RESUME_MIXED),                 # give a valid code OR fix PDM master data
    "unitReview": ("input", RESUME_CORRECT),
    "wbs": ("input", RESUME_CORRECT),
    "transferOutWbs": ("input", RESUME_CORRECT),
    "transferInWbs": ("input", RESUME_CORRECT),
    "userDepartment": ("input", RESUME_CORRECT),
    "costCenter": ("input", RESUME_MIXED),
    "stockLocation": ("input", RESUME_MIXED),
    "transferOutStockLocation": ("input", RESUME_MIXED),
    "transferInStockLocation": ("input", RESUME_MIXED),
    "attachment": ("input", RESUME_CORRECT),
    "wbsAutofill": ("action", RESUME_ACTION),            # go check the WBS / project type in OA
    "draftReview": ("input", RESUME_MIXED),
    "prepareError": ("input", RESUME_MIXED),
    "login": ("login", RESUME_ACTION),
    "session": ("login", RESUME_ACTION),
}


class AssistGuidance(BaseModel):
    model_config = ConfigDict(extra="ignore")

    userMessage: str = ""
    # Only consulted for the residual (deterministically-unclassifiable) branch:
    category: Optional[str] = None   # "info" | "action" | "unsupported"


_SYSTEM = (
    "你是 OA 自动化的纠错引导助手。给定一次卡住/失败的结构化信息(类别、待补充问题、涉及的物料/WBS、原始错误),"
    "请用中文写一段简洁、可执行的引导话术(userMessage),告诉用户如何补充信息、或在 OA/主数据中完成某项操作来解除阻塞。"
    "若存在多个问题,请分点列出,并把『用户可自行补充/处理』与『需要人工/管理员处理』分开。"
    "当给定 category 为 unknown 时,请判断该错误能否由用户补充信息(info)、由用户在外部系统操作(action)解决,否则标记 unsupported。"
    "只输出 JSON。不要建议任何自动提交/审批/付款/删除动作,不要编造错误信息中没有的细节。"
)


def _failure_category(cat: str) -> FailureCategory:
    if cat == "login":
        return FailureCategory.LOGIN
    if cat in {"unsupported", "structural"}:
        return FailureCategory.STRUCTURAL
    return FailureCategory.INPUT


def _items(pending: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = pending.get("items")
    if isinstance(items, list):
        return [it for it in items if isinstance(it, dict)]
    return [pending] if pending else []


def _compose_guidance(settings, state: Dict[str, Any], pending: Dict[str, Any],
                      kind: str, category: str, det_question: str,
                      result: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    """LLM-compose the user-facing guidance; deterministic fallback = det_question."""
    if pending.get("preserveQuestion"):
        return det_question, None
    business = state.get("business_input") or {}
    keep = ("materialCode", "workflow_id", "wbsCode", "demandUnit", "baseUnit",
            "suggestedUnit", "suggestedQuantity", "error", "skipReason", "question")
    keep_extra = ("workflow", "transferInWbs", "transferOutWbs", "missingWbs",
                  "missingStockLocationSides", "materialCodes")
    keep = keep + keep_extra
    context = {
        "category": category,
        "kind": kind,
        "question": det_question,
        "badCodes": pending.get("badCodes"),
        "items": [{k: it.get(k) for k in keep if it.get(k) not in (None, "")}
                  for it in _items(pending)][:8],
        "error": result.get("error"),
        "materials": [p.get("materialCode") for p in (business.get("materialPlans") or [])][:10],
    }
    guidance = extract_structured(settings, AssistGuidance, _SYSTEM,
                                  json.dumps(context, ensure_ascii=False))
    if guidance and (guidance.userMessage or "").strip():
        return guidance.userMessage.strip(), (guidance.category or None)
    return det_question, None


def assist_node(state: Dict[str, Any]) -> Dict[str, Any]:
    settings = get_settings()
    result = dict(state.get("result") or {})
    err = str(result.get("error") or "").lower()
    status_in = state.get("status")
    retries = int(state.get("retries", 0))
    pending = dict(result.get("input") or state.get("pending_input") or {})
    kind = str(pending.get("kind") or "")

    is_login = (status_in == STATUS_NEEDS_LOGIN or kind in {"login", "session"}
                or any(h in err for h in _LOGIN_HINTS))
    is_structural = any(h in err for h in _STRUCTURAL_HINTS)
    is_transient = (not pending) and (not is_login) and (not is_structural) \
        and any(h in err for h in _TRANSIENT_HINTS)

    # 1) transient -> bounded auto-retry (loop back to prepare -> execute_plan;
    #    saved_buckets keeps it idempotent so no duplicate drafts).
    if is_transient and retries < settings.max_retries:
        retries += 1
        diagnosis = Diagnosis(category=FailureCategory.TRANSIENT, action=DiagnosisAction.RETRY,
                              reason=f"瞬时后端错误,自动重试 {retries}/{settings.max_retries}。")
        history = append_history(state, {"node": "assist", "category": "transient",
                                         "action": "retry", "retries": retries})
        return {"diagnosis": diagnosis.model_dump(), "status": STATUS_RUNNING,
                "retries": retries, "result": None, "history": history}

    # 2) deterministic category + resumeMode
    if is_login:
        category, resume = "login", RESUME_ACTION
        det_question = "OA 会话已失效或未登录,请在托管 Edge 中重新登录,然后回复『已登录』继续。"
        det_action = DiagnosisAction.NEEDS_INPUT
    elif pending:
        category, resume = _KIND_TRIAGE.get(kind, ("input", RESUME_MIXED))
        det_question = pending.get("question") or "需要补充信息后才能继续。"
        det_action = DiagnosisAction.NEEDS_INPUT
    elif err:
        category, resume = "unknown", RESUME_ACTION   # residual: let the LLM classify
        det_question = f"执行时发生未归类的错误,可能需要人工排查:{result.get('error')}"
        det_action = DiagnosisAction.NEEDS_INPUT
    else:
        diagnosis = Diagnosis(category=FailureCategory.UNKNOWN, action=DiagnosisAction.ABORT,
                              reason="无可操作的结果。")
        history = append_history(state, {"node": "assist", "category": "unknown", "action": "abort"})
        return {"diagnosis": diagnosis.model_dump(), "status": STATUS_FAILED, "history": history}

    # 3) LLM composes the guidance text (+ classifies a residual error)
    guidance, llm_category = _compose_guidance(settings, state, pending, kind, category, det_question, result)
    if category == "unknown":
        # residual: deterministic handoff unless the LLM says the user can resolve it
        resolved = (llm_category or "").strip().lower()
        if resolved in {"info", "input"}:
            category, resume, det_action = "input", RESUME_CORRECT, DiagnosisAction.NEEDS_INPUT
        elif resolved == "action":
            category, resume, det_action = "action", RESUME_ACTION, DiagnosisAction.NEEDS_INPUT
        else:
            category, resume, det_action = "unsupported", RESUME_ACTION, DiagnosisAction.ABORT

    # 4a) human handoff (no actionable path)
    if det_action == DiagnosisAction.ABORT:
        diagnosis = Diagnosis(category=FailureCategory.STRUCTURAL, action=DiagnosisAction.ABORT, reason=guidance)
        result["guidance"] = guidance
        history = append_history(state, {"node": "assist", "category": category, "action": "abort"})
        return {"result": result, "diagnosis": diagnosis.model_dump(), "status": STATUS_FAILED,
                "pending_question": guidance, "history": history}

    # 4b) needs the user — guide and stop (resumable). Preserve kind/items/drafts.
    enriched = dict(pending)
    enriched.setdefault("kind", kind or category)
    enriched["question"] = guidance
    enriched["guidance"] = guidance
    enriched["resumeMode"] = resume
    enriched["category"] = category
    result["needsInput"] = True
    result["input"] = enriched
    result["guidance"] = guidance
    diagnosis = Diagnosis(category=_failure_category(category), action=DiagnosisAction.NEEDS_INPUT, reason=guidance)
    history = append_history(state, {"node": "assist", "category": category,
                                     "resumeMode": resume, "action": "needs_input"})
    return {"result": result, "diagnosis": diagnosis.model_dump(), "status": STATUS_NEEDS_INPUT,
            "pending_input": enriched, "pending_question": guidance, "history": history}
