"""classify_goal node — LLM classifies the request's goal for the router.

  acquire : obtain material for use → fan out to 412 出库 / 89 转储 / 458 采购
  return  : leftover after use, return to the public warehouse → 414 入库

This is an understanding task, so the LLM is required (no heuristic fallback;
a DeepSeek key must be configured, or a test responder registered).
"""
from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, ConfigDict

from ..config import get_settings
from ..llm import require_structured
from ._common import append_history

_SYSTEM = (
    "你是 OA 物料流程意图分类助手。判断用户请求属于:\n"
    "- acquire(获取/采购/领用物料以使用)\n"
    "- return(物料用完后还有剩余,要退还/归还/入库到公共仓)\n"
    "只输出 JSON。含『归还/退库/退回/用完还剩/入库到公共仓』等含义判为 return,否则 acquire。"
)


class GoalClassification(BaseModel):
    model_config = ConfigDict(extra="ignore")

    goal: str = "acquire"   # "acquire" | "return"
    reason: str = ""


def classify_goal_node(state: Dict[str, Any]) -> Dict[str, Any]:
    settings = get_settings()
    request = state.get("request") or ""
    judgment = require_structured(settings, GoalClassification, _SYSTEM, request)
    goal = "return" if str(judgment.goal).strip().lower() == "return" else "acquire"
    history = append_history(state, {"node": "classify_goal", "ok": True, "goal": goal})
    return {"goal": goal, "history": history}
