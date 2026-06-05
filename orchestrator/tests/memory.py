"""Offline test: the memory subsystem scaffold (④⑤). Interface-only — exercises
the contract with NullMemory (dormant) and MockMemory (reference impl), plus the
deterministic outbound→return reversal (⑤). No real data, no network. Run:
    orchestrator/.venv/bin/python orchestrator/tests/memory.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from oa_orchestrator.memory import (EpisodeQuery, MockMemory,  # noqa: E402
                                    NullMemory, PurchaseEpisode, get_memory,
                                    recall_context)

EP1 = PurchaseEpisode(episodeId="E1", workflowId="412", wbsCode="C2-A",
                      demandFactoryCode="1010", projectDefinition="C2",
                      materials=[{"materialCode": "4000023659", "quantity": "10", "unit": "盒"}],
                      finalFields={"costCenter": "CC-1010-01"}, outcome="rejected-corrected")
EP2 = PurchaseEpisode(episodeId="E2", workflowId="458", wbsCode="C2-B",
                      materials=[{"materialCode": "4000023659", "quantity": "3", "unit": "盒"}],
                      outcome="approved")


def main() -> int:
    # 1) NullMemory = dormant (default): no recall, no learning, behavior unchanged
    nm = NullMemory()
    assert nm.ingest([EP1])["ingested"] == 0
    assert nm.retrieve(EpisodeQuery(materialCodes=["4000023659"])) == []
    assert nm.summarize() == []
    assert get_memory().name == "null" and get_memory("mock").name == "mock"
    assert recall_context(nm, {"materialPlans": [{"materialCode": "4000023659"}]}) == {}
    print("PASS NullMemory is a dormant no-op (recall_context -> {})")

    # 2) MockMemory: ingest + material-overlap retrieve + unit heuristic
    mm = MockMemory()
    rep = mm.ingest([EP1, EP2])
    assert rep["ingested"] == 2 and rep["total"] == 2, rep
    hits = mm.retrieve(EpisodeQuery(materialCodes=["4000023659"], workflowId="412"))
    assert hits and hits[0].episode.episodeId == "E1", hits   # 412 + material match scores highest
    heur = mm.summarize(scope="material:4000023659")
    assert heur and heur[0].support == 2 and "盒" in heur[0].advice, heur
    ctx = recall_context(mm, {"materialPlans": [{"materialCode": "4000023659"}], "wbsCode": "C2-A"})
    assert ctx["episodes"] and ctx["heuristics"], ctx
    print("PASS MockMemory ingest/retrieve/summarize + recall_context returns context")

    # 3) ⑤ reverse a 412 outbound into a 414 inbound-return (same content, reversed)
    rd = mm.link_reverse(EP1)
    assert rd.workflowId == "414" and rd.wbsCode == "C2-A" and rd.sourceEpisodeId == "E1", rd
    assert rd.materials[0]["materialCode"] == "4000023659" and rd.materials[0]["quantity"] == "10", rd
    assert "反向生成" in rd.note, rd
    print("PASS link_reverse: 412 出库 E1 -> 414 入库退料 (materials/WBS same, direction reversed)")

    print("\nALL MEMORY SCAFFOLD TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
