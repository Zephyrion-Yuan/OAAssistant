"""Offline test: P3 adaptive PDM lookup — a missed material code re-queries by
name and auto-applies a unique match (remapping plans + demand rows). No network
/ DeepSeek. Run:
    orchestrator/.venv/bin/python orchestrator/tests/adaptive.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from oa_orchestrator.executors.mock import MockExecutor  # noqa: E402
from oa_orchestrator.nodes.pdm_enrich import make_pdm_enrich  # noqa: E402


def _state(plans, rows):
    return {"business_input": {"materialPlans": plans, "demandRows": rows}}


def main() -> int:
    node = make_pdm_enrich(MockExecutor())

    # 1) bad code + a name that uniquely matches PDM -> auto-resolve + remap
    out = node(_state(
        [{"materialCode": "9999999999", "materialName": "传感器", "quantity": "2", "unit": "EA"}],
        [{"materialCode": "9999999999", "materialName": "传感器", "quantity": "2", "unit": "EA", "wbsCode": "C2-A"}],
    ))
    assert (out.get("pdm") or {}).get("valid") is True, out
    plans = out["business_input"]["materialPlans"]
    rows = out["business_input"]["demandRows"]
    assert plans[0]["materialCode"] == "4000059295", plans     # name '传感器' -> 传感器模组
    assert rows[0]["materialCode"] == "4000059295", rows        # demand row remapped too
    assert any("按名称" in n for n in out.get("correction_summary", [])), out.get("correction_summary")
    print("PASS P3: bad code + unique name '传感器' -> auto-resolved to 4000059295 (plans+rows remapped)")

    # 2) bad code with no usable name -> still a clean needs_input material gate
    out2 = node(_state(
        [{"materialCode": "9999999999", "materialName": "", "quantity": "1", "unit": "EA"}],
        [{"materialCode": "9999999999", "quantity": "1", "unit": "EA", "wbsCode": "C2-A"}],
    ))
    res2 = out2.get("result") or {}
    assert res2.get("needsInput") and res2["input"]["kind"] == "material", out2
    assert "9999999999" in res2["input"]["badCodes"], res2
    print("PASS P3: bad code with no name -> needs_input material (unchanged gate)")

    print("\nALL ADAPTIVE (P3) TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
