"""Offline test: the FastAPI BFF gateway (profile + SSE chat) via TestClient.

No network, no DeepSeek, no Edge, no Node. The LLM is stubbed; the chat runs the
acquire router against MockWithRealWbs (query_wbs falls back to the mock registry
when Node is unreachable). Node-proxy endpoints (session/wbs) need a live Node and
are not exercised here. Run:
    orchestrator/.venv/bin/python orchestrator/tests/bff.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["DEEPSEEK_API_KEY"] = ""  # offline gate (LLM stubbed below)

from fastapi.testclient import TestClient  # noqa: E402

import re  # noqa: E402

from oa_orchestrator.llm import set_test_responder  # noqa: E402
from oa_orchestrator.nodes.apply_corrections import (CorrectionPatch,  # noqa: E402
                                                     MaterialEdit, WbsEdit)
from oa_orchestrator.nodes.classify_goal import GoalClassification  # noqa: E402
from oa_orchestrator.nodes.unit_check import UnitJudgment  # noqa: E402


def _emulate_correction(user: str) -> CorrectionPatch:
    """Stand in for the DeepSeek CorrectionPatch extraction in offline tests:
    emulate what the model would return for the phrasings the tests send."""
    text = user.split("用户回复:")[-1].strip()
    pair = re.search(r"(\d{8,12})\s*(?:改成|换成|替换为|->)\s*(\d{8,12})", text)
    if pair:
        return CorrectionPatch(actionable=True,
                               materialEdits=[MaterialEdit(materialCode=pair.group(1),
                                                           newMaterialCode=pair.group(2))])
    qty = re.search(r"改成\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z一-鿿]{1,8})?", text)
    if qty:
        code = re.search(r"(\d{8,12})", text)
        return CorrectionPatch(actionable=True, materialEdits=[MaterialEdit(
            materialCode=code.group(1) if code else "",
            quantity=qty.group(1), unit=(qty.group(2) or "").strip())])
    if re.search(r"按.*建议|采用建议|使用建议|确认|同意", text):
        return CorrectionPatch(actionable=True, materialEdits=[MaterialEdit(useSuggestion=True)])
    cc = re.search(r"成本中心\s*([A-Za-z0-9_.-]+)", text)
    if cc:
        return CorrectionPatch(actionable=True, wbsEdits=[WbsEdit(costCenter=cc.group(1))])
    return CorrectionPatch(actionable=False)


def _stub(schema, system, user):
    if schema is GoalClassification:
        return GoalClassification(goal="acquire")
    if schema is UnitJudgment:
        return UnitJudgment(consistent=False, reason="stub")
    if schema is CorrectionPatch:
        return _emulate_correction(user)
    return None


set_test_responder(_stub)

from oa_orchestrator import bff  # noqa: E402  (import after stub so runtime sees it)

client = TestClient(bff.app)
WBS = "C2-0225002.06.01"   # in the mock WBS registry (cost center + stock loc)


def _parse_sse(text):
    events = []
    for block in text.split("\n\n"):
        block = block.strip()
        if block.startswith("data:"):
            events.append(json.loads(block[len("data:"):].strip()))
    return events


def main() -> int:
    # 1) health
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    print("PASS /api/health")

    # 2) profile save + get round-trip
    prof = {"user_id": "tester", "department": "研发", "default_factory_code": "1010"}
    r = client.post("/api/profile", json=prof)
    assert r.status_code == 200 and r.json()["ok"], r.text
    r = client.get("/api/profile/tester")
    body = r.json()
    assert body["found"] and body["profile"]["default_factory_code"] == "1010", body
    print("PASS profile save/get round-trip")

    # 3) chat SSE: acquire router, public stock -> 412 draft.
    # userId=tester supplies the department the 412 flow needs for cost-center match.
    r = client.post("/api/chat", json={
        "message": "采购 PCR板",
        "executor": "mock",
        "save": False,
        "userId": "tester",
        "demandRows": [
            {"materialCode": "4000023659", "materialName": "PCR板", "quantity": "10",
             "unit": "EA", "wbsCode": WBS, "demandFactoryCode": "1000"},
        ],
    })
    assert r.status_code == 200, r.text
    events = _parse_sse(r.text)
    types = [e["type"] for e in events]
    assert types[0] == "start", types
    assert "node" in types, types
    final = next(e for e in events if e["type"] in ("final", "needs_input"))
    assert final["type"] == "final", final
    assert final["status"] == "done", final
    flows = {d["workflow_id"] for d in final["drafts"]}
    assert "412" in flows, final["drafts"]
    print("PASS chat SSE -> node events + final draft (412):", sorted(flows))

    # 4) chat needs_input: WBS not in registry -> 412 skipped (needsInput costCenter)
    r = client.post("/api/chat", json={
        "message": "采购",
        "executor": "mock",
        "save": False,
        "demandRows": [
            {"materialCode": "4000023659", "materialName": "PCR板", "quantity": "4",
             "unit": "EA", "wbsCode": "ZZ-NOT-IN-REGISTRY", "demandFactoryCode": "1000"},
        ],
    })
    events = _parse_sse(r.text)
    final = next(e for e in events if e["type"] in ("final", "needs_input"))
    assert final["type"] == "needs_input", final
    print("PASS chat SSE -> needs_input when WBS missing from registry")

    # 5) continuation: unit mismatch stops with details; follow-up patches the
    # same thread in place instead of starting a new request.
    r = client.post("/api/chat", json={
        "message": "采购",
        "executor": "mock",
        "save": False,
        "userId": "tester",
        "demandRows": [
            {"materialCode": "4000023659", "materialName": "PCR板", "quantity": "4",
             "unit": "盒", "wbsCode": WBS, "demandFactoryCode": "1000"},
        ],
    })
    events = _parse_sse(r.text)
    need = next(e for e in events if e["type"] == "needs_input")
    assert need["kind"] == "unitReview", need
    assert need["detail"]["items"][0]["materialCode"] == "4000023659", need
    thread_id = need["threadId"]

    r = client.post("/api/chat", json={
        "message": "4000023659 改成 4 EA",
        "executor": "mock",
        "save": False,
        "userId": "tester",
        "threadId": thread_id,
        "continueThread": True,
    })
    events = _parse_sse(r.text)
    final = next(e for e in events if e["type"] in ("final", "needs_input"))
    assert final["type"] == "final", final
    assert final["status"] == "done", final
    assert any(e.get("node") == "apply_corrections" for e in events if e["type"] == "node"), events
    print("PASS chat continuation -> unit correction resumes same thread to final")

    # 6) agent-chat (P1): stub the ReAct runner (real one needs a tool-calling LLM).
    # clarify first, then a 'ready' demand -> demand event + acquire-graph drafts.
    def _fake_intake(agent, message, thread_id):
        if "WBS" not in message:   # vague -> clarify
            return {"status": "clarify", "question": "请补充 WBS 和数量。"}
        return {"status": "ready", "goal": "acquire", "reply": "已为你整理需求。", "demandRows": [
            {"materialCode": "4000023659", "materialName": "PCR板", "quantity": "4",
             "unit": "EA", "wbsCode": WBS, "demandFactoryCode": "1010"}]}
    bff.set_intake_runner(_fake_intake)
    try:
        r = client.post("/api/agent-chat", json={"message": "领用一些传感器", "executor": "mock", "userId": "tester"})
        ev = _parse_sse(r.text)
        assert any(e["type"] == "clarify" for e in ev), ev
        print("PASS agent-chat: vague request -> clarify")

        r = client.post("/api/agent-chat", json={
            "message": "采购4个PCR板，WBS " + WBS + "，工厂1010", "executor": "mock", "userId": "tester"})
        ev = _parse_sse(r.text)
        demand = next((e for e in ev if e["type"] == "demand"), None)
        assert demand and demand["demandRows"][0]["materialCode"] == "4000023659", demand
        final = next(e for e in ev if e["type"] in ("final", "needs_input"))
        assert final["type"] == "final" and final["status"] == "done", final
        flows = {d["workflow_id"] for d in final["drafts"]}
        assert "412" in flows, final["drafts"]
        print("PASS agent-chat: ready demand -> demand event + acquire-graph drafts", sorted(flows))
    finally:
        bff.set_intake_runner(bff._run_intake_impl)

    print("\nALL BFF OFFLINE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
