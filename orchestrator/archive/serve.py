"""Minimal stdlib HTTP JSON API over the workflow-89 orchestrator.

Proves the frontend-agnostic seam: the SAME `run_workflow` entry that backs the
CLI and the conversational REPL (chat.py) also backs an HTTP frontend — with no
FastAPI/Flask, only `http.server` from the stdlib.

Endpoints:
    POST /chat   body: {message, thread_id?, excel_path?, save?}
                 - no/unknown thread_id      -> start a new run
                 - known thread_id awaiting  -> resume that thread with `message`
                 reply: {thread_id, status, reply|pending_question,
                         requestId, requestUrl, audit_path}
    GET  /health -> {ok: true}

Run:
    orchestrator/.venv/bin/python -m oa_orchestrator.serve
    CHAT_PORT=8799 (default); binds 127.0.0.1.
"""
from __future__ import annotations

import json
import os
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional

from .runner import build_runtime, run_workflow
from .state import (STATUS_DONE, STATUS_ESCALATED, STATUS_FAILED,
                    STATUS_NEEDS_INPUT, STATUS_NEEDS_LOGIN)

# Built once at server start; shared across requests.
_RUNTIME: Dict[str, Any] = {}
# Tiny in-process thread registry: thread_id -> {"pending": bool}.
_THREADS: Dict[str, Dict[str, Any]] = {}


def _new_thread_id() -> str:
    return f"http-{uuid.uuid4().hex[:8]}"


def _terminal_reply(res: Dict[str, Any]) -> str:
    """A short human string for a terminal status."""
    status = res.get("status")
    if status == STATUS_DONE:
        req_id = res.get("requestId")
        return (f"Done. requestId={req_id}." if req_id
                else "Done (dry-run, no draft saved).")
    if status == STATUS_NEEDS_LOGIN:
        return "Needs login: log into the managed Edge browser, then resend."
    if status == STATUS_ESCALATED:
        return "Escalated to a human (structural drift). See the audit log."
    if status == STATUS_FAILED:
        result = res.get("result") or {}
        return f"Failed: {result.get('error') or 'unknown error'}."
    return f"Finished with status={status}."


def handle_chat(body: Dict[str, Any]) -> Dict[str, Any]:
    """Start or resume one thread from a JSON body; return a JSON-able dict."""
    message = body.get("message")
    if not isinstance(message, str) or not message.strip():
        return {"error": "message is required"}

    thread_id = body.get("thread_id")
    excel_path = body.get("excel_path")
    save = bool(body.get("save", False))

    known = isinstance(thread_id, str) and thread_id in _THREADS
    if known and _THREADS[thread_id].get("pending"):
        # Resume: the message is the operator's answer to a pending ask.
        res = run_workflow(
            thread_id=thread_id,
            resume=message,
            interactive=True,
            graph=_RUNTIME["graph"],
            executor=_RUNTIME["executor"],
            settings=_RUNTIME["settings"],
        )
    else:
        # Fresh start (no thread_id, unknown thread_id, or a non-pending one).
        thread_id = thread_id if isinstance(thread_id, str) and thread_id else _new_thread_id()
        res = run_workflow(
            request=message,
            excel_path=excel_path,
            thread_id=thread_id,
            save=save,
            interactive=True,
            graph=_RUNTIME["graph"],
            executor=_RUNTIME["executor"],
            settings=_RUNTIME["settings"],
        )

    tid = res["thread_id"]
    status = res.get("status")
    pending = bool(res.get("interrupted")) or status == STATUS_NEEDS_INPUT
    _THREADS[tid] = {"pending": pending}

    out: Dict[str, Any] = {
        "thread_id": tid,
        "status": status,
        "requestId": res.get("requestId"),
        "requestUrl": res.get("requestUrl"),
        "audit_path": res.get("audit_path"),
    }
    if pending:
        out["pending_question"] = res.get("pending_question")
    else:
        out["reply"] = _terminal_reply(res)
    return out


class ChatHandler(BaseHTTPRequestHandler):
    server_version = "OAChat/1.0"

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        if self.path.rstrip("/") == "/health":
            self._send_json(200, {"ok": True})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 (stdlib naming)
        if self.path.rstrip("/") != "/chat":
            self._send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw or b"{}")
            if not isinstance(body, dict):
                raise ValueError("body must be a JSON object")
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": f"bad JSON: {exc}"})
            return

        try:
            result = handle_chat(body)
        except Exception as exc:  # surface graph errors as 500 JSON
            self._send_json(500, {"error": str(exc)})
            return

        status = 400 if "error" in result and "thread_id" not in result else 200
        self._send_json(status, result)

    def log_message(self, fmt: str, *args: Any) -> None:  # quieter logs
        pass


def serve(host: str = "127.0.0.1", port: Optional[int] = None) -> None:
    os.environ.setdefault("EXECUTOR", "mock")  # safe default for a demo
    settings, executor, graph = build_runtime()
    _RUNTIME.update(settings=settings, executor=executor, graph=graph)

    if port is None:
        port = int(os.getenv("CHAT_PORT", "8799"))
    httpd = ThreadingHTTPServer((host, port), ChatHandler)
    print(f"OA Assistant HTTP chat on http://{host}:{port}  "
          f"(executor={executor.name})")
    print("  POST /chat  {message, thread_id?, excel_path?, save?}")
    print("  GET  /health")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    serve()
