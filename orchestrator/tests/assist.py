"""Offline test: the assist (triage + guide) node and the dialogue node's
"I've done it → carry on" path. No network / DeepSeek / Edge — the assist
guidance falls back to its deterministic question when no LLM is available, and
the dialogue node uses a stubbed CorrectionPatch. Run:
    orchestrator/.venv/bin/python orchestrator/tests/assist.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["DEEPSEEK_API_KEY"] = ""  # offline: assist guidance -> deterministic fallback

from oa_orchestrator.llm import clear_test_responder, set_test_responder  # noqa: E402
from oa_orchestrator.nodes.apply_corrections import (CorrectionPatch, WbsEdit,  # noqa: E402
                                                     apply_corrections_node)
from oa_orchestrator.nodes.assist import assist_node  # noqa: E402
from oa_orchestrator.state import (STATUS_FAILED, STATUS_NEEDS_INPUT,  # noqa: E402
                                   STATUS_NEEDS_LOGIN, STATUS_RUNNING)


def test_login():
    out = assist_node({"status": STATUS_NEEDS_LOGIN,
                       "result": {"ok": False, "error": "OA still requires login"}})
    assert out["status"] == STATUS_NEEDS_INPUT, out
    inp = out["pending_input"]
    assert inp["category"] == "login" and inp["resumeMode"] == "action", inp
    assert out["result"]["needsInput"] is True, out
    print("PASS assist: login -> action guidance (resumeMode=action)")


def test_structured_needs_input_preserved():
    pending = {"kind": "unitReview", "question": "单位不一致",
               "items": [{"materialCode": "4000023659", "baseUnit": "EA"}]}
    out = assist_node({"status": STATUS_RUNNING,
                       "result": {"ok": False, "needsInput": True, "input": pending}})
    assert out["status"] == STATUS_NEEDS_INPUT, out
    inp = out["pending_input"]
    assert inp["kind"] == "unitReview" and inp["resumeMode"] == "correct", inp
    assert inp["items"][0]["materialCode"] == "4000023659", inp  # items preserved
    print("PASS assist: structured needs_input preserves kind/items, sets resumeMode")


def test_wbs_autofill_is_action():
    pending = {"kind": "wbsAutofill", "question": "OA 未回填项目联动字段", "wbsCode": "C2-x"}
    out = assist_node({"status": STATUS_RUNNING,
                       "result": {"ok": False, "needsInput": True, "input": pending}})
    assert out["pending_input"]["resumeMode"] == "action", out  # go check the WBS in OA
    print("PASS assist: wbsAutofill -> action (guide the user to fix the WBS)")


def test_preserve_structured_stock_location_question():
    pending = {
        "kind": "stockLocation",
        "question": "流程 89 卡住：转出 WBS C2-0339001.01.01 缺默认库存地点。",
        "workflow_id": "89",
        "transferInWbs": "C2-0225002.06.01",
        "transferOutWbs": "C2-0339001.01.01",
        "missingWbs": ["C2-0339001.01.01"],
        "preserveQuestion": True,
    }
    out = assist_node({"status": STATUS_RUNNING,
                       "result": {"ok": False, "needsInput": True, "input": pending}})
    assert out["pending_question"].startswith("流程 89 卡住"), out
    assert out["pending_input"]["transferOutWbs"] == "C2-0339001.01.01", out
    print("PASS assist: direction-aware stock-location question is preserved")


def test_residual_handoff():
    out = assist_node({"status": STATUS_RUNNING,
                       "result": {"ok": False, "error": "weird DOM selector drift xyz"}})
    assert out["status"] == STATUS_FAILED, out             # no LLM -> deterministic handoff
    assert (out.get("diagnosis") or {}).get("action") == "abort", out
    print("PASS assist: residual hard error -> human handoff (no LLM)")


def test_transient_retry():
    out = assist_node({"status": STATUS_RUNNING, "retries": 0,
                       "result": {"ok": False, "error": "ECONNREFUSED backend unreachable"}})
    assert out["status"] == STATUS_RUNNING and out["retries"] == 1, out
    assert (out["diagnosis"] or {}).get("action") == "retry", out
    out2 = assist_node({"status": STATUS_RUNNING, "retries": 99,
                        "result": {"ok": False, "error": "timeout"}})
    assert out2["status"] == STATUS_FAILED, out2           # over budget -> handoff
    print("PASS assist: transient -> bounded auto-retry, then handoff over budget")


def test_action_done_carry_on():
    def _stub(schema, system, user):
        return CorrectionPatch(actionable=False, userReportsActionDone=True) if schema is CorrectionPatch else None
    set_test_responder(_stub)
    try:
        out = apply_corrections_node({
            "correction": "已处理好了",
            "business_input": {"materialPlans": [{"materialCode": "4000023659", "quantity": "4", "unit": "EA"}],
                               "demandRows": [{"materialCode": "4000023659", "quantity": "4", "unit": "EA", "wbsCode": "W1"}]},
            "pending_input": {"kind": "wbsAutofill", "question": "请在 OA 核对 WBS", "resumeMode": "action"},
            "thread_id": "t-assist",
        })
        assert out.get("status") == STATUS_RUNNING, out      # cleared for rerun
        assert "business_input" not in out, out              # no data change on action-done
        assert out["correction_history"][-1]["actionDone"] is True, out
        print("PASS dialogue: 'action done' -> clear + rerun (no data change)")
    finally:
        clear_test_responder()


def test_action_done_rejected_for_data_kind():
    def _stub(schema, system, user):
        return CorrectionPatch(actionable=False, userReportsActionDone=True) if schema is CorrectionPatch else None
    set_test_responder(_stub)
    try:
        out = apply_corrections_node({
            "correction": "好了",
            "business_input": {"materialPlans": [{"materialCode": "4000023659", "quantity": "4", "unit": "盒"}]},
            "pending_input": {"kind": "unitReview", "question": "单位不一致", "resumeMode": "correct"},
            "thread_id": "t-assist2",
        })
        assert out.get("status") == STATUS_NEEDS_INPUT, out   # re-ask, not carried on
        print("PASS dialogue: 'done' on a data-only block -> re-ask (not carried on)")
    finally:
        clear_test_responder()


def test_stock_location_correction_targets_pending_wbs():
    def _stub(schema, system, user):
        return CorrectionPatch(
            actionable=True,
            wbsEdits=[WbsEdit(stockLocationSapCode="D002")],
        ) if schema is CorrectionPatch else None
    set_test_responder(_stub)
    try:
        out = apply_corrections_node({
            "correction": "库存地点 D002",
            "business_input": {"materialPlans": [{"materialCode": "4000059295", "quantity": "2", "unit": "EA"}],
                               "demandRows": [{"materialCode": "4000059295", "quantity": "2", "unit": "EA",
                                               "wbsCode": "C2-0225002.06.01"}]},
            "pending_input": {"kind": "stockLocation",
                              "question": "转出 WBS 缺库存地点",
                              "missingWbs": ["C2-0339001.01.01"],
                              "transferInWbs": "C2-0225002.06.01",
                              "transferOutWbs": "C2-0339001.01.01",
                              "resumeMode": "mixed"},
            "thread_id": "t-stockloc",
        })
        assert out.get("status") == STATUS_RUNNING, out
        assert out["wbs_overrides"]["C2-0339001.01.01"]["stockLocationSapCode"] == "D002", out
        print("PASS dialogue: stock-location correction patches pending WBS override")
    finally:
        clear_test_responder()


def test_wbs_correction_fills_blank_demand_rows():
    def _stub(schema, system, user):
        return CorrectionPatch(
            actionable=True,
            wbsEdits=[WbsEdit(newWbsCode="C2-0225002.06.01")],
        ) if schema is CorrectionPatch else None
    set_test_responder(_stub)
    try:
        out = apply_corrections_node({
            "correction": "WBS 改成 C2-0225002.06.01",
            "business_input": {"materialPlans": [{"materialCode": "4000059295", "quantity": "2", "unit": "EA"}],
                               "demandRows": [{"materialCode": "4000059295", "quantity": "2", "unit": "EA",
                                               "wbsCode": ""}]},
            "pending_input": {"kind": "transferInWbs",
                              "question": "缺少转入/需求 WBS",
                              "transferOutWbs": "C2-0339001.01.01",
                              "resumeMode": "correct"},
            "thread_id": "t-wbsblank",
        })
        assert out.get("status") == STATUS_RUNNING, out
        assert out["business_input"]["demandRows"][0]["wbsCode"] == "C2-0225002.06.01", out
        print("PASS dialogue: WBS correction fills blank demand-row WBS in place")
    finally:
        clear_test_responder()


def test_user_department_correction_updates_profile():
    def _stub(schema, system, user):
        return CorrectionPatch(
            actionable=True,
            userDepartment="研发三组",
        ) if schema is CorrectionPatch else None
    set_test_responder(_stub)
    try:
        out = apply_corrections_node({
            "correction": "我的部门是研发三组",
            "user_id": "tester",
            "profile": {"user_id": "tester"},
            "business_input": {"materialPlans": [{"materialCode": "4000054215", "quantity": "1", "unit": "EA"}],
                               "demandRows": [{"materialCode": "4000054215", "quantity": "1", "unit": "EA",
                                               "wbsCode": "C2-0225002.06.01"}]},
            "pending_input": {"kind": "userDepartment",
                              "question": "需要用户部门用于成本中心匹配",
                              "resumeMode": "correct"},
            "thread_id": "t-department",
        })
        assert out.get("status") == STATUS_RUNNING, out
        assert out["profile"]["department"] == "研发三组", out
        print("PASS dialogue: user department correction updates profile in place")
    finally:
        clear_test_responder()


def main() -> int:
    test_login()
    test_structured_needs_input_preserved()
    test_wbs_autofill_is_action()
    test_preserve_structured_stock_location_question()
    test_residual_handoff()
    test_transient_retry()
    test_action_done_carry_on()
    test_action_done_rejected_for_data_kind()
    test_stock_location_correction_targets_pending_wbs()
    test_wbs_correction_fills_blank_demand_rows()
    test_user_department_correction_updates_profile()
    print("\nALL ASSIST OFFLINE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
