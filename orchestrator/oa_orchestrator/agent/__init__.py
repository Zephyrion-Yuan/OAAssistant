"""Agent layer (P1/P2) — the agentic shell over the deterministic core.

`build_intake_agent` / `run_intake` give a ReAct intake agent that turns free
natural-language requests into structured `demandRows` using read-only tools,
then hands off to the existing acquire graph. The write path is unchanged and
never reached by the agent.
"""
from __future__ import annotations

from .intake_agent import build_intake_agent, run_intake
from .tools import (EmitDemandArgs, get_tool_model, make_emit_tool,
                    make_readonly_tools)

__all__ = [
    "build_intake_agent", "run_intake", "get_tool_model",
    "make_readonly_tools", "make_emit_tool", "EmitDemandArgs",
]
