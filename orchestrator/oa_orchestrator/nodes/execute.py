"""execute node — drive the chosen OA workflow via the executor. Never submits;
at most saves a draft (save flag). Workflow-agnostic: the registry decides which
executor method to call and how to build the request."""
from __future__ import annotations

from typing import Any, Callable, Dict

from ..workflows import get_workflow_spec
from ._common import append_history


def make_execute(executor) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    def execute_node(state: Dict[str, Any]) -> Dict[str, Any]:
        spec = get_workflow_spec(state.get("workflow_id", "89"))
        request = spec.build_request(state)
        method = getattr(executor, spec.executor_method)
        result = method(request)
        result_dump = result.model_dump()
        history = append_history(state, {
            "node": "execute",
            "workflow": spec.workflow_id,
            "ok": result.ok,
            "needsInput": result.needsInput,
            "requestId": result.requestId,
            "actionCount": len(result.actions or []),
        })
        return {"result": result_dump, "history": history}

    return execute_node
