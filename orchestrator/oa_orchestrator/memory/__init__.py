"""Memory subsystem package (④⑤) — interface-only scaffold.

Wiring entry points (kept dormant until a real store is configured):
- `get_memory()` — factory, env `MEGANT_MEMORY` (default `null` = no-op).
- `recall_context(memory, business)` — the hook a node (e.g. unit_check / prepare)
  would call to fetch prior-episode context + learned heuristics for the current
  materials/WBS. Returns {} for NullMemory, so behavior is unchanged by default.
- `MemoryStore.link_reverse(outbound)` — ⑤: derive a 414 from a prior 412.

To go live later: implement JsonlMemory/SqliteMemory/VectorMemory behind the same
`MemoryStore` protocol, point `MEGANT_MEMORY` at it, and call `recall_context` from
the chosen node(s). No graph topology change is required.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List

from .base import (EpisodeQuery, LearnedHeuristic, MemoryStore, PurchaseEpisode,
                   RetrievedEpisode, ReturnDraft, reverse_outbound)
from .mock import MockMemory
from .null import NullMemory

__all__ = [
    "MemoryStore", "PurchaseEpisode", "EpisodeQuery", "RetrievedEpisode",
    "LearnedHeuristic", "ReturnDraft", "reverse_outbound",
    "NullMemory", "MockMemory", "get_memory", "recall_context",
]


def get_memory(kind: str | None = None) -> MemoryStore:
    """Resolve the configured memory store. Default `null` = no-op (today's
    behavior). `mock` = in-memory reference impl. Real stores plug in here."""
    kind = (kind or os.environ.get("MEGANT_MEMORY") or "null").strip().lower()
    if kind == "mock":
        return MockMemory()
    # "jsonl" / "sqlite" / "vector" -> add here once the record format is known
    return NullMemory()


def recall_context(memory: MemoryStore, business: Dict[str, Any],
                   *, workflow_id: str = "", k: int = 5) -> Dict[str, Any]:
    """The node-side hook: given the current BusinessInput, fetch similar past
    episodes + learned heuristics. Returns {} for NullMemory (dormant)."""
    if memory is None or getattr(memory, "name", "null") == "null":
        return {}
    plans = (business or {}).get("materialPlans") or []
    codes = [str(p.get("materialCode")) for p in plans if p.get("materialCode")]
    query = EpisodeQuery(materialCodes=codes, wbsCode=str((business or {}).get("wbsCode") or ""),
                         workflowId=workflow_id)
    episodes = memory.retrieve(query, k=k)
    heuristics: List[LearnedHeuristic] = []
    for code in codes:
        heuristics.extend(memory.summarize(scope=f"material:{code}"))
    return {
        "episodes": [e.model_dump() for e in episodes],
        "heuristics": [h.model_dump() for h in heuristics],
    }
