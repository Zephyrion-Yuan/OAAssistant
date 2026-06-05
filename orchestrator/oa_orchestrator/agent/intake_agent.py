"""P1 — the ReAct intake agent (the agentic *shell*).

A create_react_agent over the read-only tools. It converses with the user,
verifies materials/WBS with tools, and — when the demand is complete — calls
``emit_demand`` to hand a structured ``demandRows`` payload to the deterministic
acquire graph (save=false). It never writes / submits; all its tools are
read-only or assembly. This moves the understanding layer from L1 to L3 without
touching the safety red line.
"""
from __future__ import annotations

from typing import Any, Dict, List

from .tools import get_tool_model, make_emit_tool, make_readonly_tools

_SYSTEM = (
    "你是 MEGA OA 物料下单助手。用户用自然语言描述采购/领用/归还需求,你的目标是组装出"
    "结构化需求行(demandRows),然后调用 emit_demand 交给确定性填单流程(只存草稿,永不提交)。\n"
    "可用的只读工具:query_pdm(按编码或名称核实物料)、query_inventory(查 SAP 库存)、"
    "resolve_wbs(把 WBS 别称/项目名解析成编码)、query_wbs(查 WBS 绑定信息)。\n"
    "工作方式:\n"
    "1) 先用工具核实用户提到的物料(编码或名称)与 WBS(可用别称/项目名)。\n"
    "2) 信息不全(缺物料/数量/单位/WBS/需求工厂)时,直接用中文向用户提问澄清,不要调用 emit_demand。\n"
    "3) 绝不臆造物料编码或数量;拿不准就用 query_pdm 查,或向用户确认。\n"
    "4) 信息齐全后调用 emit_demand(goal: acquire=采购/领用 或 return=归还/退库; demandRows=每物料一行)。\n"
    "5) 你只负责理解与组装,绝不执行任何写操作或提交。"
)


def build_intake_agent(executor, settings, checkpointer=None):
    """Compile the ReAct intake agent (tool-calling model + read-only tools)."""
    from langgraph.prebuilt import create_react_agent
    model = get_tool_model(settings)
    tools = make_readonly_tools(executor) + [make_emit_tool()]
    return create_react_agent(model, tools, prompt=_SYSTEM, checkpointer=checkpointer)


def _last_ai_text(messages: List[Any]) -> str:
    for m in reversed(messages):
        content = getattr(m, "content", None)
        if getattr(m, "type", "") == "ai" and content and not getattr(m, "tool_calls", None):
            return content if isinstance(content, str) else str(content)
    return ""


def run_intake(agent, message: str, thread_id: str) -> Dict[str, Any]:
    """One turn. Returns either {status:'ready', goal, demandRows} when the agent
    assembled the demand, or {status:'clarify', question} when it needs more."""
    config = {"configurable": {"thread_id": thread_id}}
    result = agent.invoke({"messages": [{"role": "user", "content": message}]}, config)
    messages = result.get("messages", []) if isinstance(result, dict) else []

    for m in reversed(messages):
        for tc in (getattr(m, "tool_calls", None) or []):
            if (tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")) == "emit_demand":
                args = (tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})) or {}
                rows = [dict(r) for r in (args.get("demandRows") or []) if r.get("materialCode") or r.get("materialName")]
                return {"status": "ready", "goal": str(args.get("goal") or "acquire"),
                        "demandRows": rows, "reply": _last_ai_text(messages)}

    return {"status": "clarify", "question": _last_ai_text(messages) or "请补充更多信息后继续。"}
