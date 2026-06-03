"""Offline test: query_wbs executor capability + WbsRecord schema.

No network, no DeepSeek, no Edge. Run:
    orchestrator/.venv/bin/python orchestrator/tests/wbs.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["EXECUTOR"] = "mock"
os.environ["DEEPSEEK_API_KEY"] = ""  # offline gate

from oa_orchestrator.executors.base import Executor  # noqa: E402
from oa_orchestrator.executors.http_node import HttpNodeExecutor  # noqa: E402
from oa_orchestrator.executors.mock import MockExecutor  # noqa: E402
from oa_orchestrator.schemas import WbsRecord  # noqa: E402


def main() -> int:
    mock = MockExecutor()

    # 1) known WBS -> full bound record
    rec = mock.query_wbs("C2-0225002.06.01")
    assert rec is not None, "known WBS must resolve"
    model = WbsRecord.model_validate(rec)
    assert model.demandFactoryCode == "1010", model
    assert model.costCenter == "CC-1010-01", model
    assert model.purchaser == "demo-buyer", model
    assert model.stockLocationSapCode == "H001", model
    assert model.demandDateOffsetDays == 5, model
    print("PASS known WBS C2-0225002.06.01 -> factory/cost-center/purchaser/stock/offset bound")

    # 2) unknown WBS -> None (prepare will needs_input)
    assert mock.query_wbs("ZZ-NOPE") is None
    assert mock.query_wbs("") is None
    print("PASS unknown WBS -> None")

    # 3) alias resolver: code / exact alias / fuzzy / ambiguous / none
    assert mock.resolve_wbs("C2-0225002.06.01")["matchType"] == "code"
    r = mock.resolve_wbs("SA探针")
    assert r["matchType"] == "alias" and r["matched"]["wbsCode"] == "C2-0225002.06.01", r
    r = mock.resolve_wbs("传感器")  # fuzzy substring of alias '传感器项目'
    assert r["matchType"] == "fuzzy" and r["matched"]["wbsCode"] == "C2-0225002.06.01", r
    r = mock.resolve_wbs("项目")  # matches both aliases -> ambiguous, no single match
    assert r["matched"] is None and len(r["candidates"]) == 2, r
    assert mock.resolve_wbs("nope-xyz")["matchType"] == "none"
    print("PASS resolve_wbs: code / alias / fuzzy / ambiguous / none")

    # 4) both executors satisfy the (extended) Executor Protocol
    for ex in (mock, HttpNodeExecutor("http://127.0.0.1:8787")):
        assert hasattr(ex, "query_wbs") and hasattr(ex, "resolve_wbs")
        assert isinstance(ex, Executor), f"{ex.name} does not satisfy Executor Protocol"
    print("PASS Mock + HttpNode satisfy Executor Protocol (incl. query_wbs / resolve_wbs)")

    print("\nALL WBS OFFLINE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
