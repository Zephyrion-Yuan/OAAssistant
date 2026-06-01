"""Conversational REPL frontend over the workflow-89 orchestrator.

A thin, multi-turn chat loop that drives the SAME frontend-agnostic entry point
(`run_workflow`) every other frontend uses (CLI, HTTP, MCP). It never blocks the
graph on stdin: when the graph raises an interactive ask interrupt, run_workflow
returns `interrupted=True` + a `pending_question`; this loop prints the question,
reads the operator's next line, and feeds it back as `resume=<answer>` on the
SAME thread. This file is the reference for how a conversational/agent frontend
drives the graph.

Run:
    orchestrator/.venv/bin/python -m oa_orchestrator.chat

Meta commands (type these instead of a request):
    /new                start a fresh conversation thread
    /excel <path>       attach a workbook for the NEXT request
    /save               toggle save (real draft) vs dry-run
    /quit               exit
    /help               show this help
"""
from __future__ import annotations

import os
import sys
import uuid
from typing import Any, Dict, Optional

from .runner import build_runtime, run_workflow
from .state import (STATUS_DONE, STATUS_ESCALATED, STATUS_FAILED,
                    STATUS_NEEDS_INPUT, STATUS_NEEDS_LOGIN)

HELP = """\
Commands:
  /new            start a fresh conversation thread
  /excel <path>   attach a workbook for the NEXT request
  /save           toggle save (real draft) vs dry-run
  /quit           exit
  /help           show this help
Anything else is sent as a request (or, if the agent just asked a question,
as your answer to it)."""


def _new_thread_id() -> str:
    return f"chat-{uuid.uuid4().hex[:8]}"


def _print_node(chunk: Dict[str, Any]) -> None:
    """on_update callback: print one '· <node>' line per graph node update."""
    for node in chunk:
        if node.startswith("__"):
            continue
        print(f"· {node}")


class ChatSession:
    """Holds the runtime (built once) plus the current thread + UI toggles.

    The runtime — settings, executor, compiled graph — is created a single time
    and reused across every turn, so the checkpointer (and thus thread history)
    persists for the life of the session.
    """

    def __init__(self, executor=None, settings=None) -> None:
        self.settings, self.executor, self.graph = build_runtime(
            executor=executor, settings=settings
        )
        self.thread_id: str = _new_thread_id()
        self.pending: bool = False     # True when the agent is awaiting an answer
        self.attached_excel: Optional[str] = None
        self.save: bool = False        # dry-run by default (safe demo)

    # -- turn drivers -------------------------------------------------------

    def start(self, request: str) -> Dict[str, Any]:
        """Begin a new request on the current thread."""
        excel = self.attached_excel
        self.attached_excel = None  # consumed by this request
        return run_workflow(
            request=request,
            excel_path=excel,
            thread_id=self.thread_id,
            save=self.save,
            interactive=True,
            graph=self.graph,
            executor=self.executor,
            settings=self.settings,
            on_update=_print_node,
        )

    def answer(self, reply: str) -> Dict[str, Any]:
        """Resume the current thread with the operator's answer to an ask."""
        return run_workflow(
            thread_id=self.thread_id,
            resume=reply,
            interactive=True,
            graph=self.graph,
            executor=self.executor,
            settings=self.settings,
            on_update=_print_node,
        )

    def send(self, line: str) -> Dict[str, Any]:
        """Route one user line: a pending question gets an answer, else a request."""
        if self.pending:
            return self.answer(line)
        return self.start(line)

    # -- presentation -------------------------------------------------------

    def render(self, res: Dict[str, Any]) -> None:
        """Print the outcome of a turn and update the pending flag."""
        status = res.get("status")

        if res.get("interrupted") or status == STATUS_NEEDS_INPUT:
            self.pending = True
            question = res.get("pending_question") or "(the agent needs more information)"
            print(f"\nagent> {question}")
            return

        # Any terminal status clears the pending flag.
        self.pending = False

        if status == STATUS_DONE:
            req_id = res.get("requestId")
            req_url = res.get("requestUrl")
            audit = res.get("audit_path")
            mode = "saved draft" if self.save else "dry-run (not saved)"
            print(f"\nagent> done ({mode}).")
            if req_id:
                print(f"       requestId : {req_id}")
            if req_url:
                print(f"       requestUrl: {req_url}")
            if audit:
                print(f"       audit     : {audit}")
        elif status == STATUS_NEEDS_LOGIN:
            print("\nagent> needs login: please log into the managed Edge browser, "
                  "then resend your request.")
        elif status == STATUS_ESCALATED:
            print("\nagent> escalated to a human (structural drift detected). "
                  "See the audit log for details.")
        elif status == STATUS_FAILED:
            result = res.get("result") or {}
            err = result.get("error") or "unknown error"
            print(f"\nagent> failed: {err}")
        else:
            print(f"\nagent> finished with status={status!r}.")

    # -- meta commands ------------------------------------------------------

    def handle_meta(self, line: str) -> bool:
        """Handle a /command. Returns True if the line was a meta command."""
        if not line.startswith("/"):
            return False
        parts = line.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("/help", "/?"):
            print(HELP)
        elif cmd == "/new":
            self.thread_id = _new_thread_id()
            self.pending = False
            self.attached_excel = None
            print(f"(new thread {self.thread_id})")
        elif cmd == "/excel":
            if not arg:
                print("(usage: /excel <path>)")
            elif not os.path.exists(arg):
                print(f"(no such file: {arg})")
            else:
                self.attached_excel = arg
                print(f"(attached workbook for next request: {arg})")
        elif cmd == "/save":
            self.save = not self.save
            print(f"(save is now {'ON — real draft' if self.save else 'OFF — dry-run'})")
        elif cmd in ("/quit", "/exit", "/q"):
            raise EOFError  # let the loop exit cleanly
        else:
            print(f"(unknown command {cmd}; type /help)")
        return True


def main(argv: Optional[list] = None) -> int:
    # Default to the mock executor for a safe, offline demo unless overridden.
    os.environ.setdefault("EXECUTOR", "mock")

    session = ChatSession()
    print("OA Assistant chat (workflow 89). Type /help for commands, /quit to exit.")
    print(f"executor={session.executor.name}  thread={session.thread_id}  "
          f"save={'ON' if session.save else 'OFF (dry-run)'}")

    while True:
        prompt = "answer> " if session.pending else "you> "
        try:
            line = input(prompt)
        except (EOFError, KeyboardInterrupt):
            print("\nbye.")
            return 0

        line = line.strip()
        if not line:
            continue

        try:
            if session.handle_meta(line):
                continue
        except EOFError:
            print("bye.")
            return 0

        try:
            res = session.send(line)
        except Exception as exc:  # keep the REPL alive on a single bad turn
            print(f"agent> error: {exc}", file=sys.stderr)
            session.pending = False
            continue
        session.render(res)


if __name__ == "__main__":
    raise SystemExit(main())
