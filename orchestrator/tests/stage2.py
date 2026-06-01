"""Stage 2 offline tests: personalize prefill, interactive interrupt->resume
loop (no stdin), and run_workflow needs_input behavior. MockExecutor only.

Run: orchestrator/.venv/bin/python orchestrator/tests/stage2.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["EXECUTOR"] = "mock"
os.environ["DEEPSEEK_API_KEY"] = ""  # force heuristic (offline gate; empty defeats .env dotenv reload)

from openpyxl import Workbook  # noqa: E402

from oa_orchestrator.config import get_settings  # noqa: E402
from oa_orchestrator.executors.mock import MockExecutor  # noqa: E402
from oa_orchestrator.graph import build_graph, make_checkpointer  # noqa: E402
from oa_orchestrator.runner import run_workflow  # noqa: E402
from oa_orchestrator.state import STATUS_DONE, STATUS_NEEDS_INPUT  # noqa: E402

HEADERS = ["需求工厂代码", "WBS编码", "项目定义", "物料编码", "物料名称",
           "需求数量", "基本计量单位", "MRP控制者"]


def make_workbook(code="4000023659") -> str:
    wb = Workbook(); ws = wb.active; ws.title = "项目需求填写界面"
    ws.append(HEADERS)
    ws.append(["说明"] * len(HEADERS))
    ws.append(["1000", "C2-0225002.06.01", "C2-0225002", code, "测试物料", 5, "EA", "M01"])
    p = Path(tempfile.mkdtemp()) / "req.xlsx"
    wb.save(p)
    return str(p)


def fresh_runtime():
    settings = get_settings()
    settings.ensure_runtime_dir()
    executor = MockExecutor()
    graph = build_graph(executor, checkpointer=make_checkpointer(None))  # in-memory, isolated
    return settings, executor, graph


def main() -> int:
    xlsx = make_workbook()

    # 1) personalize: profile supplies stock locations -> no ask -> done
    settings, executor, graph = fresh_runtime()
    profile = {
        "user_id": "alice",
        "default_transfer_out_stock_location_name": "设备零件仓",
        "default_transfer_in_stock_location_name": "成品仓",
    }
    res = run_workflow(request="帮我做一个库存转储", excel_path=xlsx, thread_id="s2-profile",
                       save=True, profile=profile, graph=graph, executor=executor, settings=settings)
    assert res["status"] == STATUS_DONE, res["status"]
    assert res["requestId"] == "MOCK-89-0001", res
    print("PASS personalize prefill -> no ask, status=done")

    # 2) run_workflow non-interactive: missing slot -> needs_input + question (not an interrupt)
    settings, executor, graph = fresh_runtime()
    res = run_workflow(request="帮我做一个库存转储", excel_path=xlsx, thread_id="s2-unatt",
                       save=True, interactive=False, graph=graph, executor=executor, settings=settings)
    assert res["status"] == STATUS_NEEDS_INPUT, res["status"]
    assert res["interrupted"] is False, res
    assert res["pending_question"], res
    print("PASS unattended missing slot -> needs_input + pending_question")

    # 3) interactive interrupt -> resume loop (no stdin): ask pauses, resume with answer -> done
    settings, executor, graph = fresh_runtime()
    res = run_workflow(request="帮我做一个库存转储", excel_path=xlsx, thread_id="s2-interactive",
                       save=True, interactive=True, graph=graph, executor=executor, settings=settings)
    assert res["interrupted"] is True, res
    assert res["pending_question"], res
    print("  interrupt raised, question:", res["pending_question"].splitlines()[0])
    res2 = run_workflow(thread_id="s2-interactive", resume="设备零件仓 D002 成品仓 A001",
                        interactive=True, graph=graph, executor=executor, settings=settings)
    assert res2["status"] == STATUS_DONE, res2["status"]
    assert res2["requestId"] == "MOCK-89-0001", res2
    print("PASS interactive ask -> resume with answer -> status=done")

    print("\nALL STAGE 2 OFFLINE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
