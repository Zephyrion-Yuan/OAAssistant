"""Device-agnostic Executor contract + implementations.

The LangGraph brain depends ONLY on the Executor Protocol. All device-/platform-
specific concerns (Windows Edge + SSO relay vs mac Edge + manual login, browser
channel, profile mode) live behind an implementation — the graph never knows
which one it is talking to.
"""
from __future__ import annotations

from .base import Executor, ExecutorError


def get_executor(settings) -> "Executor":
    """Select an executor implementation from settings.executor."""
    kind = (settings.executor or "http-node").lower()
    if kind == "mock":
        from .mock import MockExecutor
        return MockExecutor()
    if kind in {"http-node", "http", "node"}:
        from .http_node import HttpNodeExecutor
        return HttpNodeExecutor(settings.node_base_url)
    raise ValueError(f"Unknown EXECUTOR: {settings.executor!r}")


__all__ = ["Executor", "ExecutorError", "get_executor"]
