"""preflight node — verify the executor backend is reachable and (best-effort)
the OA session is logged in before doing any work.
"""
from __future__ import annotations

from typing import Any, Callable, Dict

from ..executors.base import ExecutorError
from ..state import STATUS_NEEDS_LOGIN
from ._common import append_history


def make_preflight(executor) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    def preflight_node(state: Dict[str, Any]) -> Dict[str, Any]:
        try:
            status = executor.session_status()
        except ExecutorError as exc:
            history = append_history(state, {"node": "preflight", "ok": False, "error": str(exc)})
            return {
                "result": {"ok": False, "error": f"backend unreachable: {exc}"},
                "history": history,
            }
        oa = status.get("oaLiveSession") or {}
        requires_login = bool(oa.get("requiresLogin")) or bool(status.get("requiresLogin"))
        if requires_login:
            history = append_history(state, {"node": "preflight", "ok": False, "requiresLogin": True})
            return {
                "status": STATUS_NEEDS_LOGIN,
                "pending_question": "OA 未登录。请在托管 Edge 中完成扫码/SSO 登录后用 --resume 继续。",
                "history": history,
            }
        history = append_history(state, {"node": "preflight", "ok": True})
        return {"history": history}

    return preflight_node
