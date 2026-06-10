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
from oa_orchestrator.nodes.apply_corrections import (CorrectionPatch,  # noqa: E402
                                                     MaterialEdit, RouteOverride, WbsEdit,
                                                     apply_corrections_node)
from oa_orchestrator.nodes.assist import assist_node  # noqa: E402
from oa_orchestrator.nodes.execute_plan import _bucket_key  # noqa: E402
from oa_orchestrator.nodes.unit_check import UnitJudgment, unit_check_node  # noqa: E402
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


def test_unit_check_keeps_every_mismatched_unit_even_if_llm_marks_consistent():
    calls = []

    def _stub(schema, system, user):
        if schema is UnitJudgment:
            calls.append(user)
            return UnitJudgment(
                consistent=True,
                suggestedUnit="EA",
                suggestedQuantity="1",
                reason="maybe equivalent",
            )
        return None

    set_test_responder(_stub)
    try:
        out = unit_check_node({
            "business_input": {"materialPlans": [
                {"materialCode": "MAT-A", "materialName": "A", "quantity": "2", "unit": "BOX"},
                {"materialCode": "MAT-B", "materialName": "B", "quantity": "3", "unit": "PACK"},
            ]},
            "pdm": {"enriched": {
                "MAT-A": {"unit": "EA", "materialName": "A", "fields": {}},
                "MAT-B": {"unit": "EA", "materialName": "B", "fields": {}},
            }},
        })
        items = out["result"]["input"]["items"]
        assert [item["materialCode"] for item in items] == ["MAT-A", "MAT-B"], out
        assert len(calls) == 2, calls
        assert all(item.get("llmConsistent") is True for item in items), items
        print("PASS unit_check: all mismatched units remain visible for review")
    finally:
        clear_test_responder()


def test_unit_review_accepts_all_suggestions_via_llm():
    def _stub(schema, system, user):
        return CorrectionPatch(
            actionable=True,
            materialEdits=[
                MaterialEdit(materialCode="MAT-A", useSuggestion=True),
                MaterialEdit(materialCode="MAT-B", useSuggestion=True),
            ],
        ) if schema is CorrectionPatch else None

    set_test_responder(_stub)
    try:
        out = apply_corrections_node({
            "correction": "按建议修改",
            "business_input": {"materialPlans": [
                {"materialCode": "MAT-A", "quantity": "2", "unit": "BOX"},
                {"materialCode": "MAT-B", "quantity": "3", "unit": "PACK"},
            ], "demandRows": [
                {"materialCode": "MAT-A", "quantity": "2", "unit": "BOX", "wbsCode": "C2-0225002.06.01"},
                {"materialCode": "MAT-B", "quantity": "3", "unit": "PACK", "wbsCode": "C2-0225002.06.01"},
            ]},
            "pending_input": {"kind": "unitReview", "resumeMode": "correct", "items": [
                {"materialCode": "MAT-A", "suggestedQuantity": "20", "suggestedUnit": "EA"},
                {"materialCode": "MAT-B", "suggestedQuantity": "30", "suggestedUnit": "EA"},
            ]},
            "thread_id": "t-unit-all",
        })
        assert out.get("status") == STATUS_RUNNING, out
        rows = {row["materialCode"]: row for row in out["business_input"]["demandRows"]}
        assert rows["MAT-A"]["quantity"] == "20" and rows["MAT-A"]["unit"] == "EA", rows
        assert rows["MAT-B"]["quantity"] == "30" and rows["MAT-B"]["unit"] == "EA", rows
        plans = {plan["materialCode"]: plan for plan in out["business_input"]["materialPlans"]}
        assert plans["MAT-A"]["quantity"] == "20" and plans["MAT-A"]["unit"] == "EA", plans
        assert plans["MAT-B"]["quantity"] == "30" and plans["MAT-B"]["unit"] == "EA", plans
        print("PASS dialogue: LLM patch applies every pending unit suggestion")
    finally:
        clear_test_responder()


def test_plain_wbs_reply_updates_project_code_block_via_llm():
    def _stub(schema, system, user):
        return CorrectionPatch(
            actionable=True,
            wbsEdits=[WbsEdit(newWbsCode="C2-0225002.06.01")],
        ) if schema is CorrectionPatch else None

    set_test_responder(_stub)
    try:
        out = apply_corrections_node({
            "correction": "C2-0225002.06.01",
            "business_input": {"materialPlans": [{"materialCode": "MAT-A", "quantity": "2", "unit": "EA"}],
                               "demandRows": [{"materialCode": "MAT-A", "quantity": "2", "unit": "EA",
                                               "wbsCode": ""}]},
            "pending_input": {"kind": "projectCode",
                              "question": "workflow 412 needs a project code",
                              "resumeMode": "mixed"},
            "thread_id": "t-project-wbs",
        })
        assert out.get("status") == STATUS_RUNNING, out
        assert out["business_input"]["demandRows"][0]["wbsCode"] == "C2-0225002.06.01", out
        print("PASS dialogue: LLM patch refills a project-code block with WBS")
    finally:
        clear_test_responder()


def test_project_code_action_done_via_llm():
    def _stub(schema, system, user):
        return CorrectionPatch(
            actionable=False,
            userReportsActionDone=True,
        ) if schema is CorrectionPatch else None

    set_test_responder(_stub)
    try:
        out = apply_corrections_node({
            "correction": "已处理",
            "business_input": {"materialPlans": [{"materialCode": "MAT-A", "quantity": "2", "unit": "EA"}],
                               "demandRows": [{"materialCode": "MAT-A", "quantity": "2", "unit": "EA",
                                               "wbsCode": "C2-0225002.06.01"}]},
            "pending_input": {"kind": "projectCode",
                              "question": "fix project code in OA",
                              "resumeMode": "mixed"},
            "thread_id": "t-project-done",
        })
        assert out.get("status") == STATUS_RUNNING, out
        assert "business_input" not in out, out
        assert out["correction_history"][-1]["actionDone"] is True, out
        print("PASS dialogue: LLM patch resumes a project-code block after external action")
    finally:
        clear_test_responder()


def test_project_code_value_confirmation_via_llm():
    def _stub(schema, system, user):
        return CorrectionPatch(
            actionable=False,
            userConfirmsPendingValue=True,
        ) if schema is CorrectionPatch else None

    set_test_responder(_stub)
    try:
        out = apply_corrections_node({
            "correction": "确认，WBS号正确",
            "business_input": {"materialPlans": [{"materialCode": "MAT-A", "quantity": "2", "unit": "EA"}],
                               "demandRows": [{"materialCode": "MAT-A", "quantity": "2", "unit": "EA",
                                               "wbsCode": "C2-0225002.06.01"}]},
            "pending_input": {"kind": "projectCode",
                              "question": "请确认 WBS 号是否正确",
                              "wbsCode": "C2-0225002.06.01",
                              "resumeMode": "mixed"},
            "thread_id": "t-project-confirm",
        })
        assert out.get("status") == STATUS_RUNNING, out
        assert "business_input" not in out, out
        assert out["correction_history"][-1]["valueConfirmed"] is True, out
        print("PASS dialogue: LLM value confirmation resumes a WBS/project-code block")
    finally:
        clear_test_responder()


def test_wbs_autofill_is_mixed():
    pending = {"kind": "wbsAutofill", "question": "OA 未回填项目联动字段", "wbsCode": "C2-x"}
    out = assist_node({"status": STATUS_RUNNING,
                       "result": {"ok": False, "needsInput": True, "input": pending}})
    assert out["pending_input"]["resumeMode"] == "mixed", out
    print("PASS assist: wbsAutofill -> mixed (accept WBS reply or external fix)")


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


def test_retry_failed_draft_via_llm():
    def _stub(schema, system, user):
        return CorrectionPatch(retryFailedDrafts=True) if schema is CorrectionPatch else None

    entry_412 = {
        "workflow_id": "412", "wbsCode": "C2-0225002.06.01", "transferOutWbs": None,
        "materialLines": [{"materialCode": "4000059295", "quantity": "2", "unit": "EA"}],
        "request": {"structured": {"wbsCode": "C2-0225002.06.01"}, "save": False},
        "result": {"ok": False, "error": "locator.click: Timeout 15000ms exceeded"},
    }
    entry_458 = {
        "workflow_id": "458", "wbsCode": "C2-0225002.06.01", "transferOutWbs": None,
        "materialLines": [{"materialCode": "4000054215", "quantity": "3", "unit": "EA"}],
        "request": {"structured": {"wbsCode": "C2-0225002.06.01"}, "save": False},
        "result": {"ok": True, "summary": {}, "actions": []},
    }
    set_test_responder(_stub)
    try:
        out = apply_corrections_node({
            "correction": "重试出库流程",
            "business_input": {"materialPlans": [
                {"materialCode": "4000059295", "quantity": "2", "unit": "EA"},
                {"materialCode": "4000054215", "quantity": "3", "unit": "EA"},
            ], "demandRows": [
                {"materialCode": "4000059295", "quantity": "2", "unit": "EA", "wbsCode": "C2-0225002.06.01"},
                {"materialCode": "4000054215", "quantity": "3", "unit": "EA", "wbsCode": "C2-0225002.06.01"},
            ]},
            "pending_input": {"kind": "draftReview", "resumeMode": "mixed", "items": [
                {"workflow_id": "412", "wbsCode": "C2-0225002.06.01",
                 "error": "locator.click: Timeout 15000ms exceeded", "retryable": True},
            ]},
            "plan": {"entries": [entry_412, entry_458]},
            "plan_results": [
                {"workflow_id": "412", "wbsCode": "C2-0225002.06.01",
                 "materialLines": entry_412["materialLines"], "ok": False},
                {"workflow_id": "458", "wbsCode": "C2-0225002.06.01",
                 "materialLines": entry_458["materialLines"], "ok": True},
            ],
            "thread_id": "t-retry-412",
        })
        assert out.get("status") == STATUS_RUNNING, out
        assert out.get("pending_input") is None, out
        completed = out.get("completed_buckets") or {}
        assert _bucket_key(entry_458) in completed, completed
        assert _bucket_key(entry_412) not in completed, completed
        print("PASS dialogue: LLM retry intent -> rerun failed 412 and preserve successful buckets")
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


def test_mrp_controller_correction_targets_pending_wbs():
    def _stub(schema, system, user):
        return CorrectionPatch(
            actionable=True,
            wbsEdits=[WbsEdit(mrpController="P22")],
        ) if schema is CorrectionPatch else None
    set_test_responder(_stub)
    try:
        out = apply_corrections_node({
            "correction": "MRP控制者 P22",
            "business_input": {"materialPlans": [{"materialCode": "4000059295", "quantity": "2", "unit": "EA"}],
                               "demandRows": [{"materialCode": "4000059295", "quantity": "2", "unit": "EA",
                                               "wbsCode": "C2-0225002.06.01"}]},
            "pending_input": {"kind": "mrpController",
                              "question": "流程 458 采购申请需要必填 MRP控制者",
                              "missingWbs": ["C2-0225002.06.01"],
                              "wbsCode": "C2-0225002.06.01",
                              "resumeMode": "mixed"},
            "thread_id": "t-mrp",
        })
        assert out.get("status") == STATUS_RUNNING, out
        assert out["wbs_overrides"]["C2-0225002.06.01"]["mrpController"] == "P22", out
        print("PASS dialogue: MRP controller correction patches pending WBS override")
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


def test_wbs_correction_fills_only_the_blank_bucket():
    """Regression: a multi-bucket plan (one row already has a WBS, one is blank).
    Supplying a WBS must fill the BLANK row, not replace the sibling that already
    had one (the old bug left the blank row blank -> endless re-ask)."""
    def _stub(schema, system, user):
        return CorrectionPatch(
            actionable=True,
            wbsEdits=[WbsEdit(newWbsCode="C2-0225002.06.01")],
        ) if schema is CorrectionPatch else None
    set_test_responder(_stub)
    try:
        out = apply_corrections_node({
            "correction": "C2-0225002.06.01",
            "business_input": {"demandRows": [
                {"materialCode": "A", "quantity": "1", "unit": "EA", "wbsCode": "C2-0339001.01.01"},
                {"materialCode": "B", "quantity": "2", "unit": "EA", "wbsCode": ""}]},
            "pending_input": {"kind": "draftReview", "resumeMode": "correct", "items": [
                {"kind": "costCenter", "wbsCode": "C2-0339001.01.01", "materialCodes": ["A"]},
                {"kind": "wbs", "wbsCode": "", "missingWbs": [""], "materialCodes": ["B"]}]},
            "thread_id": "t-wbsmixed",
        })
        assert out.get("status") == STATUS_RUNNING, out
        rows = {r["materialCode"]: r["wbsCode"] for r in out["business_input"]["demandRows"]}
        assert rows["A"] == "C2-0339001.01.01", rows   # sibling untouched
        assert rows["B"] == "C2-0225002.06.01", rows    # blank bucket filled
        print("PASS dialogue: WBS fills only the blank bucket (mixed plan), not the sibling")
    finally:
        clear_test_responder()


def test_routing_override_to_transfer():
    """Aggressive routing: '<material> 改走转储' sets routing_overrides so the
    rerun re-routes that material's other-project stock to a project→project 89."""
    def _stub(schema, system, user):
        return CorrectionPatch(
            actionable=True,
            routeOverrides=[RouteOverride(materialCode="4000059295", action="transfer")],
        ) if schema is CorrectionPatch else None
    set_test_responder(_stub)
    try:
        out = apply_corrections_node({
            "correction": "4000059295 改走转储",
            "business_input": {"demandRows": [{"materialCode": "4000059295", "quantity": "2",
                                               "unit": "EA", "wbsCode": "C2-0225002.06.01"}]},
            "pending_input": {"kind": "draftReview", "resumeMode": "correct",
                              "materialCodes": ["4000059295"]},
            "routing_overrides": {},
            "thread_id": "t-route",
        })
        assert out.get("status") == STATUS_RUNNING, out
        assert out["routing_overrides"]["4000059295"] == "transfer", out
        print("PASS dialogue: '改走转储' -> routing_overrides[material]=transfer (re-route to 89)")
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
    test_unit_check_keeps_every_mismatched_unit_even_if_llm_marks_consistent()
    test_unit_review_accepts_all_suggestions_via_llm()
    test_plain_wbs_reply_updates_project_code_block_via_llm()
    test_project_code_action_done_via_llm()
    test_project_code_value_confirmation_via_llm()
    test_wbs_autofill_is_mixed()
    test_preserve_structured_stock_location_question()
    test_wbs_correction_fills_only_the_blank_bucket()
    test_routing_override_to_transfer()
    test_residual_handoff()
    test_transient_retry()
    test_action_done_carry_on()
    test_action_done_rejected_for_data_kind()
    test_retry_failed_draft_via_llm()
    test_stock_location_correction_targets_pending_wbs()
    test_mrp_controller_correction_targets_pending_wbs()
    test_wbs_correction_fills_blank_demand_rows()
    test_user_department_correction_updates_profile()
    print("\nALL ASSIST OFFLINE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
