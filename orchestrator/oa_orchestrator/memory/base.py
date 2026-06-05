"""Memory subsystem — contract + schemas (interface-only scaffold).

Goal (user's ④⑤): let the agent learn from ~4000 historical human purchase
records (rejected-then-corrected) and use that experience to guide drafting; and
derive an inbound-return (414) from the matching prior outbound (412), same
content with the direction reversed.

This module defines ONLY the contract + data shapes — mirroring the `Executor`
Protocol pattern the repo already uses — so the real ingestion can be plugged in
later once the record format is known. The default `NullMemory` is a no-op, so
nothing in the graph changes until a real store is configured.

Privacy note: historical records may carry supplier/PII fields. An ingester MUST
normalize to the whitelisted business fields below and run them through the
redaction boundary before anything reaches an LLM. Use the *corrected final*
state of a record (not the rejected one) as ground truth.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# Data shapes
# --------------------------------------------------------------------------- #
class PurchaseEpisode(BaseModel):
    """One normalized historical episode (a past draft + its human-corrected
    final state + outcome). The unit the memory store retrieves over."""
    model_config = ConfigDict(extra="ignore")

    episodeId: str = ""
    workflowId: str = ""              # 412 | 89 | 458 | 414
    requestText: str = ""            # NL/context the request came from (optional)
    materials: List[Dict[str, Any]] = Field(default_factory=list)  # [{materialCode, quantity, unit, materialName}]
    wbsCode: str = ""
    demandFactoryCode: str = ""
    projectDefinition: str = ""
    movementType: str = ""
    finalFields: Dict[str, Any] = Field(default_factory=dict)   # the human-corrected field values
    rejectionReason: str = ""
    outcome: str = ""                # "approved" | "rejected-corrected" | ...
    createdAt: str = ""              # ISO; passed in by the ingester (no clock here)


class EpisodeQuery(BaseModel):
    model_config = ConfigDict(extra="ignore")

    materialCodes: List[str] = Field(default_factory=list)
    wbsCode: str = ""
    workflowId: str = ""
    text: str = ""


class RetrievedEpisode(BaseModel):
    model_config = ConfigDict(extra="ignore")

    episode: PurchaseEpisode
    score: float = 0.0
    why: str = ""


class LearnedHeuristic(BaseModel):
    """A distilled rule-of-thumb (e.g. 'material X is usually ordered by 箱')."""
    model_config = ConfigDict(extra="ignore")

    scope: str = ""                  # "material:4000023659" | "wbs:C2-..." | "global"
    advice: str = ""
    support: int = 0                 # episodes backing it (confidence proxy)


class ReturnDraft(BaseModel):
    """A 414 入库退料 derived by reversing a prior 412 outbound episode (⑤)."""
    model_config = ConfigDict(extra="ignore")

    sourceEpisodeId: str = ""
    workflowId: str = "414"
    wbsCode: str = ""
    demandFactoryCode: str = ""
    projectDefinition: str = ""
    materials: List[Dict[str, Any]] = Field(default_factory=list)
    fields: Dict[str, Any] = Field(default_factory=dict)
    note: str = ""


# --------------------------------------------------------------------------- #
# Shared deterministic reversal (⑤) — usable by any store impl
# --------------------------------------------------------------------------- #
def reverse_outbound(outbound: PurchaseEpisode) -> ReturnDraft:
    """Derive a 414 inbound-return from a 412 outbound: same materials / WBS /
    factory, direction reversed. Deterministic — no learning needed."""
    return ReturnDraft(
        sourceEpisodeId=outbound.episodeId,
        workflowId="414",
        wbsCode=outbound.wbsCode,
        demandFactoryCode=outbound.demandFactoryCode,
        projectDefinition=outbound.projectDefinition,
        materials=[dict(m) for m in (outbound.materials or [])],
        fields=dict(outbound.finalFields or {}),
        note=f"由出库(412) {outbound.episodeId or '(无单号)'} 反向生成的入库退料(414)，物料/数量/WBS 相同、方向相反。",
    )


# --------------------------------------------------------------------------- #
# The contract (mirrors the Executor Protocol pattern)
# --------------------------------------------------------------------------- #
@runtime_checkable
class MemoryStore(Protocol):
    name: str

    def ingest(self, episodes: Iterable[PurchaseEpisode]) -> Dict[str, Any]:
        """Load historical episodes; returns a small report ({ingested, ...})."""
        ...

    def retrieve(self, query: EpisodeQuery, k: int = 5) -> List[RetrievedEpisode]:
        """Most-similar past episodes for a new request (RAG / few-shot source)."""
        ...

    def summarize(self, scope: str = "") -> List[LearnedHeuristic]:
        """Distill episodes into rules-of-thumb (offline; optional)."""
        ...

    def link_reverse(self, outbound: PurchaseEpisode) -> ReturnDraft:
        """⑤: derive the inbound-return (414) from a prior outbound (412)."""
        ...
