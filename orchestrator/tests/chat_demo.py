"""Offline scripted test for the conversational frontend (chat.py logic).

No real stdin, no network, no DeepSeek, no Edge — MockExecutor + an in-memory
checkpointer. Simulates a two-turn conversation against the SAME run_workflow
entry the REPL drives:

    turn 1: a request WITHOUT stock locations -> the graph interrupts and asks
            a question (interrupted / needs_input + pending_question).
    turn 2: the operator's answer, fed back via resume -> status=done with a
            requestId.

Run: orchestrator/.venv/bin/python orchestrator/tests/chat_demo.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# make `oa_orchestrator` importable regardless of cwd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["EXECUTOR"] = "mock"            # force the in-memory backend
os.environ["DEEPSEEK_API_KEY"] = ""        # force heuristic (offline gate; empty defeats .env dotenv reload)

from openpyxl import Workbook  # noqa: E402

from oa_orchestrator.chat import ChatSession  # noqa: E402
from oa_orchestrator.config import get_settings  # noqa: E402
from oa_orchestrator.executors.mock import MockExecutor  # noqa: E402
from oa_orchestrator.graph import build_graph, make_checkpointer  # noqa: E402
from oa_orchestrator.state import STATUS_DONE, STATUS_NEEDS_INPUT  # noqa: E402

HEADERS = ["需求工厂代码", "WBS编码", "项目定义", "物料编码", "物料名称",
           "需求数量", "基本计量单位", "MRP控制者"]


def make_workbook(material_code: str = "4000023659") -> str:
    wb = Workbook()
    ws = wb.active
    ws.title = "项目需求填写界面"
    ws.append(HEADERS)                                # row 1: headers
    ws.append(["说明"] * len(HEADERS))                 # row 2: instructions
    ws.append(["1000", "C2-0225002.06.01", "C2-0225002",
               material_code, "测试物料", 5, "EA", "M01"])  # row 3: data
    path = Path(tempfile.mkdtemp()) / "req.xlsx"
    wb.save(path)
    return str(path)


def build_session() -> ChatSession:
    """A ChatSession wired to an isolated in-memory runtime (like stage2.py)."""
    settings = get_settings()
    assert settings.executor == "mock", settings.executor
    settings.ensure_runtime_dir()
    executor = MockExecutor()
    graph = build_graph(executor, checkpointer=make_checkpointer(None))  # in-memory
    session = ChatSession.__new__(ChatSession)  # bypass __init__'s build_runtime
    session.settings, session.executor, session.graph = settings, executor, graph
    session.thread_id = "chat-demo-1"
    session.pending = False
    session.attached_excel = None
    session.save = True  # request a real (mock) draft so requestId is returned
    return session


def main() -> int:
    xlsx = make_workbook()
    session = build_session()
    session.attached_excel = xlsx

    # turn 1: request WITHOUT stock locations -> conversation pauses with a question
    res1 = session.send("帮我做一个库存转储")
    session.render(res1)
    assert res1["interrupted"] is True, res1
    assert res1["status"] == STATUS_NEEDS_INPUT, res1["status"]
    assert res1["pending_question"], res1
    assert session.pending is True, "session should be awaiting an answer"
    print("PASS turn 1 -> interrupted/needs_input with pending_question")

    # turn 2: answer the question via resume -> done with a requestId
    res2 = session.send("设备零件仓 D002 成品仓 A001")
    session.render(res2)
    assert res2["status"] == STATUS_DONE, res2["status"]
    assert res2["requestId"] == "MOCK-89-0001", res2
    assert session.pending is False, "session should be cleared after a done turn"
    print("PASS turn 2 -> resume with answer -> status=done, requestId="
          f"{res2['requestId']}")

    print("\nALL CHAT DEMO TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
