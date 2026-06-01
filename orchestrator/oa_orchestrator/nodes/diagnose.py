"""diagnose node — classify a failed/blocked execution and decide the next move,
bounded by a deterministic retry budget (the self-heal brain).

Deterministic backbone (safe + offline-capable). The action, status and retry
budget are chosen *only* by the deterministic logic below. When a DEEPSEEK_API_KEY
is present, an OPTIONAL LLM pass refines the human-readable ``reason`` (and may
confirm the ``category`` / ``confidence``) for nicer escalation messages — but it
can NEVER widen the action, change the status, or bypass max_retries. With no key
the behavior is byte-for-byte unchanged (offline still works).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..config import get_settings
from ..llm import extract_structured, llm_available
from ..schemas import Diagnosis, DiagnosisAction, FailureCategory
from ..state import (STATUS_ESCALATED, STATUS_FAILED, STATUS_NEEDS_INPUT,
                     STATUS_NEEDS_LOGIN, STATUS_RUNNING)
from ._common import append_history

_TRANSIENT_HINTS = ("network", "timeout", "timed out", "econnrefused",
                    "backend unreachable", "socket")
_LOGIN_HINTS = ("requires login", "still requires login", "未登录", "需要登录", "login")

# Categories the LLM is allowed to *confirm/correct* (never expands the action).
_ALLOWED_CATEGORIES = {c.value for c in FailureCategory}

_REFINE_SYSTEM = (
    "你是 OA 自动化的故障诊断助手。给定一次执行失败的错误信息和系统已判定的类别,"
    "请输出一句更清晰、面向运维人员的中文原因说明(reason),并确认故障类别(category)。"
    "类别只能是: transient(网络/超时,可重试)、input(缺失或错误的输入槽位)、"
    "login(会话过期需重新登录)、structural(选择器漂移/页面结构变化,需人工)、unknown。"
    "不要建议任何修复动作,不要编造错误中没有的细节。"
)


class _DiagnosisRefinement(BaseModel):
    """LLM-refinable subset of a Diagnosis. Action is deliberately absent so the
    LLM cannot influence control flow."""

    model_config = ConfigDict(extra="ignore")

    category: Optional[str] = None
    reason: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


def _refine_with_llm(settings, diagnosis: Diagnosis, err: str) -> Diagnosis:
    """Optionally improve the reason/category of an already-decided diagnosis.

    The deterministic ``action`` is preserved verbatim; only ``reason``,
    ``category`` and ``confidence`` may change, and ``category`` may only move to
    another known category (never affects the action/status/retry decision).
    """
    if not llm_available(settings) or not err:
        return diagnosis

    user = (
        f"系统判定类别: {diagnosis.category.value}\n"
        f"系统默认原因: {diagnosis.reason}\n"
        f"原始错误信息: {err}"
    )
    refinement = extract_structured(settings, _DiagnosisRefinement, _REFINE_SYSTEM, user)
    if refinement is None:
        return diagnosis  # LLM unavailable / failed -> keep deterministic text

    category = diagnosis.category
    if refinement.category and refinement.category in _ALLOWED_CATEGORIES:
        category = FailureCategory(refinement.category)

    reason = diagnosis.reason
    if refinement.reason and refinement.reason.strip():
        reason = refinement.reason.strip()

    confidence = diagnosis.confidence
    if refinement.confidence is not None:
        confidence = refinement.confidence

    # action is NEVER taken from the LLM — re-assert the deterministic action.
    return Diagnosis(category=category, action=diagnosis.action,
                     reason=reason, confidence=confidence)


def diagnose_node(state: Dict[str, Any]) -> Dict[str, Any]:
    settings = get_settings()
    result = state.get("result") or {}
    retries = int(state.get("retries", 0))
    err = str(result.get("error") or "").lower()

    if result.get("needsInput"):
        diagnosis = Diagnosis(category=FailureCategory.INPUT, action=DiagnosisAction.NEEDS_INPUT,
                              reason="Executor reported a missing/invalid input slot.")
        status = STATUS_NEEDS_INPUT
    elif any(h in err for h in _LOGIN_HINTS):
        diagnosis = Diagnosis(category=FailureCategory.LOGIN, action=DiagnosisAction.WAIT_LOGIN,
                              reason="OA session requires login.")
        status = STATUS_NEEDS_LOGIN
    elif any(h in err for h in _TRANSIENT_HINTS):
        if retries < settings.max_retries:
            retries += 1
            diagnosis = Diagnosis(category=FailureCategory.TRANSIENT, action=DiagnosisAction.RETRY,
                                  reason=f"Transient backend error; retry {retries}/{settings.max_retries}.")
            status = STATUS_RUNNING
        else:
            diagnosis = Diagnosis(category=FailureCategory.TRANSIENT, action=DiagnosisAction.ABORT,
                                  reason="Transient error exceeded retry budget.")
            status = STATUS_FAILED
    elif err:
        diagnosis = Diagnosis(category=FailureCategory.STRUCTURAL, action=DiagnosisAction.ABORT,
                              reason="Unclassified/structural failure (possible selector drift); escalate to human.")
        status = STATUS_ESCALATED
    else:
        diagnosis = Diagnosis(category=FailureCategory.UNKNOWN, action=DiagnosisAction.ABORT,
                              reason="No actionable result.")
        status = STATUS_FAILED

    # OPTIONAL LLM refinement: improves reason/category text only. The action,
    # status and retries computed above are authoritative and never re-derived.
    deterministic_action = diagnosis.action
    diagnosis = _refine_with_llm(settings, diagnosis, err)
    assert diagnosis.action == deterministic_action, "LLM must not change the action"

    history = append_history(state, {"node": "diagnose", "category": diagnosis.category.value,
                                     "action": diagnosis.action.value, "reason": diagnosis.reason})
    return {"diagnosis": diagnosis.model_dump(), "status": status, "retries": retries, "history": history}
