"""Offline smoke test: intake parsing + full graph against MockExecutor.

No network, no DeepSeek, no Edge. Run:
    orchestrator/.venv/bin/python orchestrator/tests/smoke.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# make `oa_orchestrator` importable regardless of cwd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["EXECUTOR"] = "mock"          # force the in-memory backend
os.environ["DEEPSEEK_API_KEY"] = ""  # force heuristic (offline gate; empty defeats .env dotenv reload)

from openpyxl import Workbook  # noqa: E402

from oa_orchestrator.config import get_settings  # noqa: E402
from oa_orchestrator.executors import get_executor  # noqa: E402
from oa_orchestrator.graph import build_graph, make_checkpointer  # noqa: E402
from oa_orchestrator.nodes.intake import parse_workbook  # noqa: E402
from oa_orchestrator.state import (STATUS_DONE, STATUS_NEEDS_INPUT, new_state)  # noqa: E402

HEADERS = ["需求工厂代码", "WBS编码", "项目定义", "物料编码", "物料名称",
           "需求数量", "基本计量单位", "MRP控制者"]


def make_workbook(material_code: str) -> str:
    wb = Workbook()
    ws = wb.active
    ws.title = "项目需求填写界面"
    ws.append(HEADERS)                              # row 1 headers
    ws.append(["说明"] * len(HEADERS))               # row 2 instructions
    ws.append(["1000", "C2-0225002.06.01", "C2-0225002",
               material_code, "测试物料", 5, "EA", "M01"])  # row 3 data
    path = Path(tempfile.mkdtemp()) / "req.xlsx"
    wb.save(path)
    return str(path)


def build():
    settings = get_settings()
    assert settings.executor == "mock", settings.executor
    executor = get_executor(settings)
    assert executor.name == "mock"
    graph = build_graph(executor, checkpointer=make_checkpointer(None))
    return graph


def run(graph, *, request, excel, thread, save):
    config = {"configurable": {"thread_id": thread}}
    state = new_state(request=request, excel_path=excel, thread_id=thread,
                      interactive=False, save=save)
    return graph.invoke(state, config)


def main() -> int:
    # 1) intake parsing
    xlsx = make_workbook("4000023659")
    bi = parse_workbook(xlsx)
    assert bi.demandFactoryCode == "1000", bi.demandFactoryCode
    assert bi.wbsCode == "C2-0225002.06.01"
    assert len(bi.materialPlans) == 1
    assert bi.materialPlans[0].materialCode == "4000023659"
    assert bi.materialPlans[0].quantity == "5", bi.materialPlans[0].quantity
    print("PASS intake parse:", bi.materialPlans[0].model_dump())

    graph = build()

    # 2) happy path: valid material + both stock locations -> saved draft
    out = run(graph, request="从设备零件仓 D002 转到成品仓 A001",
              excel=xlsx, thread="smoke-happy", save=True)
    assert out.get("status") == STATUS_DONE, out.get("status")
    res = out.get("result") or {}
    assert res.get("ok") is True, res
    assert res.get("requestId") == "MOCK-89-0001", res
    assert out.get("audit_path"), "audit_path missing"
    assert Path(out["audit_path"]).exists()
    print("PASS happy path -> status=done requestId=", res.get("requestId"))

    # 3) bad material code -> PDM validation fails -> needs_input
    xlsx_bad = make_workbook("9999999999")
    out = run(graph, request="从设备零件仓 D002 转到成品仓 A001",
              excel=xlsx_bad, thread="smoke-badcode", save=True)
    assert out.get("status") == STATUS_NEEDS_INPUT, out.get("status")
    assert (out.get("result") or {}).get("input", {}).get("kind") == "material"
    print("PASS bad code -> status=needs_input kind=material")

    # 4) missing stock locations (unattended) -> needs_input via ask
    out = run(graph, request="帮我做一个库存转储",
              excel=xlsx, thread="smoke-missing", save=True)
    assert out.get("status") == STATUS_NEEDS_INPUT, out.get("status")
    assert out.get("pending_question"), "expected a pending question"
    assert "transferOutStockLocation" in (out.get("missing") or [])
    print("PASS missing slot -> status=needs_input, asked operator")

    print("\nALL OFFLINE SMOKE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
