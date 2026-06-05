"""MockMemory — a tiny in-memory reference store for tests and offline demos.

Deliberately simple (keyword/material overlap scoring, count-based heuristics) so
the contract can be exercised without real data or a vector DB. A future
JsonlMemory / SqliteMemory / VectorMemory drops in behind the same MemoryStore
protocol once the real 4000-record format is known.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

from .base import (EpisodeQuery, LearnedHeuristic, MemoryStore, PurchaseEpisode,
                   RetrievedEpisode, ReturnDraft, reverse_outbound)


class MockMemory:
    name = "mock"

    def __init__(self, episodes: Iterable[PurchaseEpisode] | None = None):
        self._episodes: List[PurchaseEpisode] = []
        if episodes:
            self.ingest(episodes)

    def ingest(self, episodes: Iterable[PurchaseEpisode]) -> Dict[str, Any]:
        added = 0
        for ep in episodes:
            self._episodes.append(ep if isinstance(ep, PurchaseEpisode)
                                  else PurchaseEpisode.model_validate(ep))
            added += 1
        return {"ingested": added, "total": len(self._episodes), "store": self.name}

    def _score(self, ep: PurchaseEpisode, query: EpisodeQuery) -> float:
        score = 0.0
        codes = {str(c) for c in query.materialCodes}
        ep_codes = {str(m.get("materialCode")) for m in ep.materials}
        score += 3.0 * len(codes & ep_codes)
        if query.wbsCode and query.wbsCode == ep.wbsCode:
            score += 2.0
        if query.workflowId and query.workflowId == ep.workflowId:
            score += 1.0
        if query.text and ep.requestText and query.text in ep.requestText:
            score += 0.5
        return score

    def retrieve(self, query: EpisodeQuery, k: int = 5) -> List[RetrievedEpisode]:
        scored = [(self._score(ep, query), ep) for ep in self._episodes]
        scored = [(s, ep) for s, ep in scored if s > 0]
        scored.sort(key=lambda t: t[0], reverse=True)
        return [RetrievedEpisode(episode=ep, score=s,
                                 why=f"匹配分 {s}（物料/WBS/流程重叠）")
                for s, ep in scored[:k]]

    def summarize(self, scope: str = "") -> List[LearnedHeuristic]:
        # Count how often each material was historically corrected to a given unit.
        by_unit: Dict[tuple, int] = {}
        for ep in self._episodes:
            for m in ep.materials:
                code = str(m.get("materialCode") or "")
                unit = str(m.get("unit") or "")
                if code and unit:
                    by_unit[(code, unit)] = by_unit.get((code, unit), 0) + 1
        out: List[LearnedHeuristic] = []
        for (code, unit), n in sorted(by_unit.items(), key=lambda kv: kv[1], reverse=True):
            if scope and scope != f"material:{code}":
                continue
            out.append(LearnedHeuristic(scope=f"material:{code}",
                                        advice=f"历史上 {code} 多以单位『{unit}』填报", support=n))
        return out

    def link_reverse(self, outbound: PurchaseEpisode) -> ReturnDraft:
        return reverse_outbound(outbound)


_: MemoryStore = MockMemory()
