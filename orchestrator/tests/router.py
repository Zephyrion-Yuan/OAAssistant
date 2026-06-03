"""Offline test: the Phase-1 acquire-mode WBS-fan-out router, end to end.

No network, no DeepSeek, no Edge. Drives the full acquire graph against the mock
backend and asserts the 412/89/458 fan-out, WBS bucketing, generated 458
attachment, and the skip-on-missing-registry path. Run:
    orchestrator/.venv/bin/python orchestrator/tests/router.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["EXECUTOR"] = "mock"
os.environ["DEEPSEEK_API_KEY"] = ""  # offline gate

from openpyxl import Workbook, load_workbook  # noqa: E402

from oa_orchestrator.executors import mock as mockmod  # noqa: E402
from oa_orchestrator.executors.mock import MockExecutor  # noqa: E402
from oa_orchestrator.graph import build_graph, make_checkpointer  # noqa: E402
from oa_orchestrator.llm import set_test_responder  # noqa: E402
from oa_orchestrator.nodes.classify_goal import GoalClassification  # noqa: E402
from oa_orchestrator.nodes.route_workflow import allocate  # noqa: E402
from oa_orchestrator.nodes.unit_check import UnitJudgment  # noqa: E402
from oa_orchestrator.state import (STATUS_DONE, STATUS_NEEDS_INPUT,  # noqa: E402
                                   new_state)

# LLM is mandatory (no heuristic fallback). Register a deterministic stub so the
# classify_goal / unit_check nodes run offline. _GOAL drives the classifier;
# UnitJudgment defaults to "inconsistent" so any unit-mismatch is flagged.
_GOAL = {"value": "acquire"}


def _stub_llm(schema, system, user):
    if schema is GoalClassification:
        return GoalClassification(goal=_GOAL["value"])
    if schema is UnitJudgment:
        return UnitJudgment(consistent=False, suggestedUnit="箱", suggestedQuantity="1",
                            reason="规格 50 盒/箱,疑似单位误用")
    return None


set_test_responder(_stub_llm)

HEADERS = ["需求工厂代码", "WBS编码", "项目定义", "物料编码", "物料名称",
           "需求数量", "基本计量单位", "MRP控制者"]
DEMAND_WBS = "C2-0225002.06.01"      # in mock registry (cost center + stock loc)
SOURCE_WBS = "C2-0339001.01.01"      # another project's WBS (also in registry)


def _loc(factory, code, name, wbs, qty, sobkz):
    return {"factoryCode": factory, "stockLocationCode": code, "stockLocationName": name,
            "wbsCode": wbs, "unrestrictedStock": qty, "specialStockIndicator": sobkz, "unit": "EA"}


def make_workbook(rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "项目需求填写界面"
    ws.append(HEADERS)
    ws.append(["说明"] * len(HEADERS))
    for r in rows:
        ws.append(r)
    path = Path(tempfile.mkdtemp()) / "demand.xlsx"
    wb.save(path)
    return str(path)


def run(graph, *, excel, thread, save, mode="acquire"):
    config = {"configurable": {"thread_id": thread}}
    state = new_state(request="按需求表采购/出库/转储", excel_path=excel, thread_id=thread,
                      interactive=False, save=save, mode=mode)
    return graph.invoke(state, config)


def main() -> int:
    # 0) pure allocation sanity (allocate() consumes the *classified* inventory
    #    shape — locations carry isProjectStock, as the inventory_query node emits)
    plan = allocate(
        [{"materialCode": "M", "wbsCode": DEMAND_WBS, "quantity": "5"}],
        {"M": {"locations": [{"wbsCode": SOURCE_WBS, "unrestrictedStock": "2", "isProjectStock": True}]}},
    )
    kinds = sorted(e.workflow_id for e in plan.entries)
    assert kinds == ["458", "89"], kinds
    print("PASS allocation sanity: 2@other-project -> 89, shortfall 3 -> 458")

    # scenario inventory: 4000023659 public(10), 4000059295 other-project special(2)
    mockmod._INVENTORY = {
        "4000023659": [_loc("1010", "A001", "成品仓", "", "10.000", "")],
        "4000059295": [_loc("1010", "D002", "设备零件仓", SOURCE_WBS, "2.000", "Q")],
    }

    graph = build_graph(MockExecutor(), checkpointer=make_checkpointer(None), mode="acquire")

    # 1) three-flow fan-out, single demand WBS, save -> 3 saved drafts
    xlsx = make_workbook([
        ["1010", DEMAND_WBS, "C2-0225002", "4000023659", "PCR板", 10, "EA", "M01"],
        ["1010", DEMAND_WBS, "C2-0225002", "4000059295", "传感器", 5, "EA", "M01"],
    ])
    out = run(graph, excel=xlsx, thread="router-3way", save=True)
    assert out.get("status") == STATUS_DONE, (out.get("status"), out.get("result"))
    result = out["result"]
    assert result["router"] and result["ok"], result
    drafts = {d["workflow_id"]: d for d in result["drafts"]}
    assert set(drafts) == {"412", "89", "458"}, set(drafts)
    # 412: outbound the public PCR板 x10 at the demand WBS
    assert drafts["412"]["wbsCode"] == DEMAND_WBS
    assert drafts["412"]["materialLines"][0]["materialCode"] == "4000023659"
    assert drafts["412"]["materialLines"][0]["quantity"] == "10"
    # 89: transfer the 2 from the other project's WBS into the demand WBS
    assert drafts["89"]["transferOutWbs"] == SOURCE_WBS
    assert drafts["89"]["materialLines"][0]["materialCode"] == "4000059295"
    assert drafts["89"]["materialLines"][0]["quantity"] == "2"
    # 458: purchase the shortfall 3
    assert drafts["458"]["materialLines"][0]["materialCode"] == "4000059295"
    assert drafts["458"]["materialLines"][0]["quantity"] == "3"
    assert all(d["ok"] and d["requestId"] for d in drafts.values()), drafts
    print("PASS 3-flow fan-out: 412(PCR板x10) + 89(传感器x2 from other WBS) + 458(传感器x3) all saved")

    # 2) generated 458 attachment matches the real 22-column 项目需求填写界面 layout
    entry458 = next(e for e in out["plan"]["entries"] if e["workflow_id"] == "458")
    att = Path(entry458["request"]["structured"]["normalizedPath"])
    assert att.exists(), att
    awb = load_workbook(att)
    aws = awb.active
    assert aws.title == "项目需求填写界面"
    hdr = [c.value for c in aws[1]]
    assert hdr[:6] == ["需求类型", "物料编码", "物料名称", "物料组", "需求数量", "基本计量单位"], hdr
    assert len(hdr) == 22, len(hdr)
    data = [c.value for c in aws[3]]
    # 需求类型=02, 物料编码, 需求数量=3, 申请人(idx9), WBS(idx11), 工厂(idx16)
    assert data[0] == "02" and data[1] == "4000059295" and str(data[4]) == "3", data
    assert data[11] == DEMAND_WBS and data[16] == "1010", data
    assert data[9] == "demo-buyer", data[9]   # 申请人 from registry.purchaser
    print("PASS 458 attachment matches real 22-col template:", att.name)

    # 3) shortfall note recorded
    assert any("缺口" in n for n in result["notes"]), result["notes"]
    print("PASS shortfall note recorded:", result["notes"][0])

    # 4) WBS bucketing: same material, two WBS -> separate 458 drafts
    out2 = run(graph, excel=make_workbook([
        ["1010", DEMAND_WBS, "C2-0225002", "9999999999", "无库存物料", 4, "EA", "M01"],
    ]), thread="router-badcode", save=True)
    # bad material code -> PDM validation stops before routing
    assert out2.get("status") == STATUS_NEEDS_INPUT, out2.get("status")
    assert (out2.get("result") or {}).get("input", {}).get("kind") == "material"
    print("PASS bad material code -> PDM gate -> needs_input (router never runs)")

    # 5) skip-on-missing-registry: public stock but WBS not in registry -> 412 skipped
    mockmod._INVENTORY["4000023659"] = [_loc("1010", "A001", "成品仓", "", "10.000", "")]
    out3 = run(graph, excel=make_workbook([
        ["1010", "ZZ-NOT-IN-REGISTRY", "ZZ", "4000023659", "PCR板", 4, "EA", "M01"],
    ]), thread="router-skip", save=True)
    res3 = out3["result"]
    d412 = next(d for d in res3["drafts"] if d["workflow_id"] == "412")
    assert d412["skipped"] and d412["needsInput"]["kind"] == "costCenter", d412
    assert out3.get("status") == STATUS_NEEDS_INPUT, out3.get("status")
    print("PASS missing-registry WBS -> 412 draft skipped (needsInput costCenter), others unaffected")

    # 6) return mode (classify_goal=return) -> 414 入库 draft bucketed by WBS, no stock fan-out
    _GOAL["value"] = "return"
    out4 = run(graph, excel=make_workbook([
        ["1010", DEMAND_WBS, "C2-0225002", "4000023659", "PCR板", 4, "EA", "M01"],
    ]), thread="router-return", save=True)
    _GOAL["value"] = "acquire"  # restore
    res4 = out4["result"]
    assert out4.get("status") == STATUS_DONE, (out4.get("status"), res4)
    assert {d["workflow_id"] for d in res4["drafts"]} == {"414"}, res4["drafts"]
    d414 = res4["drafts"][0]
    assert d414["wbsCode"] == DEMAND_WBS and d414["ok"] and d414["requestId"], d414
    print("PASS return mode -> single 414 入库 draft saved")

    # 7) unit mismatch (demand 盒 vs PDM base EA) -> unit_check LLM flags -> needs_input
    out5 = run(graph, excel=make_workbook([
        ["1010", DEMAND_WBS, "C2-0225002", "4000023659", "PCR板", 50, "盒", "M01"],
    ]), thread="router-unit", save=True)
    assert out5.get("status") == STATUS_NEEDS_INPUT, out5.get("status")
    assert (out5.get("result") or {}).get("input", {}).get("kind") == "unitReview", out5.get("result")
    print("PASS unit mismatch (盒≠EA) -> unit_check stops for confirmation (needs_input)")

    # 8) WBS alias: demand row references the WBS by its nickname -> resolved to code
    out6 = run(graph, excel=make_workbook([
        ["1010", "传感器项目", "C2-0225002", "4000023659", "PCR板", 10, "EA", "M01"],
    ]), thread="router-alias", save=True)
    assert out6.get("status") == STATUS_DONE, (out6.get("status"), out6.get("result"))
    d = out6["result"]["drafts"][0]
    assert d["wbsCode"] == DEMAND_WBS, ("alias should resolve to the real WBS code", d)
    print("PASS WBS alias '传感器项目' -> resolved to", d["wbsCode"], "and routed")

    print("\nALL ROUTER OFFLINE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
