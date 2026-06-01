"""ask node — slot-filling clarification.

Interactive mode: pause via LangGraph interrupt() and route back to understand
once the operator answers (this is the natural-language追问 loop).
Unattended mode: stop at a resumable NEEDS_INPUT terminal so the operator can
re-invoke with the missing parameter later.
"""
from __future__ import annotations

from typing import Any, Dict

from langgraph.types import interrupt

from ..state import STATUS_NEEDS_INPUT
from ._common import append_history

_SLOT_PROMPTS = {
    "transferOutStockLocation": "请提供转出库存地点名称或 SAP 编码（例如：设备零件仓 / D002）。",
    "transferInStockLocation": "请提供转入库存地点名称或 SAP 编码（例如：成品仓 / A001）。",
    "transferOutWbs": "当前移动类型需要转出 WBS，请提供 WBS 编码。",
    "transferInWbs": "当前移动类型需要转入 WBS，请提供 WBS 编码。",
}


def _compose_question(missing) -> str:
    parts = [_SLOT_PROMPTS.get(slot, f"请补充: {slot}") for slot in missing]
    return "缺少必填信息：\n" + "\n".join(f"- {p}" for p in parts)


def ask_node(state: Dict[str, Any]) -> Dict[str, Any]:
    missing = state.get("missing", [])
    question = _compose_question(missing)

    if not state.get("interactive", False):
        history = append_history(state, {"node": "ask", "mode": "unattended", "missing": missing})
        return {"status": STATUS_NEEDS_INPUT, "pending_question": question, "history": history}

    # Interactive: pause and wait for the operator's reply, then loop to understand.
    answer = interrupt({"question": question, "missing": missing})
    history = append_history(state, {"node": "ask", "mode": "interactive", "missing": missing})
    return {"answer": str(answer), "pending_question": None, "history": history}
