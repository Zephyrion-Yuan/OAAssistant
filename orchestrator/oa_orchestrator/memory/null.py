"""NullMemory — the default no-op store. With this configured the graph behaves
exactly as today (no recall, no learning); only the deterministic reverse (⑤)
still works since it needs no stored data."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

from .base import (EpisodeQuery, LearnedHeuristic, MemoryStore, PurchaseEpisode,
                   RetrievedEpisode, ReturnDraft, reverse_outbound)


class NullMemory:
    name = "null"

    def ingest(self, episodes: Iterable[PurchaseEpisode]) -> Dict[str, Any]:
        return {"ingested": 0, "store": self.name}

    def retrieve(self, query: EpisodeQuery, k: int = 5) -> List[RetrievedEpisode]:
        return []

    def summarize(self, scope: str = "") -> List[LearnedHeuristic]:
        return []

    def link_reverse(self, outbound: PurchaseEpisode) -> ReturnDraft:
        return reverse_outbound(outbound)


# structural sanity: NullMemory satisfies the MemoryStore protocol
_: MemoryStore = NullMemory()
