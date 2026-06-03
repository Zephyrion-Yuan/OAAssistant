"""route_workflow node — the inventory-driven WBS-fan-out allocator.

Per demand row (material + WBS + quantity), allocate against that material's SAP
inventory with priority 412 > 89 > 458:

    a412 = min(Q, public + own-project stock at this WBS)   -> 412 outbound
    a89  = min(remaining, other-project stock per source WBS) -> 89 transfer
    a458 = remaining shortfall                              -> 458 purchase

A per-material stock pool is depleted across rows (two rows for the same
material don't double-count stock). Allocations are then bucketed into drafts
keyed by (flow, WBS) — 89 additionally by source WBS — so each AllocationEntry
becomes exactly one OA draft. Pure + deterministic; no LLM, no executor.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List

from ..schemas import AllocationEntry, AllocationPlan, MaterialLine
from ._common import append_history


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value).strip() or "0")
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _fmt(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal(1)))
    return format(normalized, "f")


def _build_pools(inventory: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """material -> {public: Decimal, project: {wbs: Decimal}} from classify_inventory."""
    pools: Dict[str, Dict[str, Any]] = {}
    for material, inv in (inventory or {}).items():
        public = Decimal("0")
        project: Dict[str, Decimal] = {}
        for loc in (inv or {}).get("locations", []) or []:
            qty = _dec(loc.get("unrestrictedStock"))
            if qty <= 0:
                continue
            if loc.get("isProjectStock"):
                wbs = str(loc.get("wbsCode") or "")
                project[wbs] = project.get(wbs, Decimal("0")) + qty
            else:
                public += qty
        pools[material] = {"public": public, "project": project}
    return pools


def _add_line(bucket: Dict[str, Any], material: str, name: str, qty: Decimal, unit: str, meta: Dict[str, str]):
    if bucket["meta"] is None:
        bucket["meta"] = meta
    line = bucket["lines"].setdefault(material, {"name": name, "unit": unit, "qty": Decimal("0")})
    line["qty"] += qty


def allocate(demand_rows: List[Dict[str, Any]], inventory: Dict[str, Any]) -> AllocationPlan:
    pools = _build_pools(inventory)
    buckets: Dict[tuple, Dict[str, Any]] = {}
    notes: List[str] = []

    def bucket(key: tuple, workflow_id: str, wbs: str, src_wbs: str | None = None) -> Dict[str, Any]:
        if key not in buckets:
            buckets[key] = {"workflow_id": workflow_id, "wbsCode": wbs,
                            "transferOutWbs": src_wbs, "lines": {}, "meta": None}
        return buckets[key]

    for row in demand_rows or []:
        material = str(row.get("materialCode") or "")
        if not material:
            continue
        need = _dec(row.get("quantity"))
        wbs = str(row.get("wbsCode") or "")
        meta = {"demandFactoryCode": str(row.get("demandFactoryCode") or ""),
                "projectDefinition": str(row.get("projectDefinition") or ""),
                "mrpController": str(row.get("mrpController") or "")}
        name = str(row.get("materialName") or "")
        unit = str(row.get("unit") or "")
        pool = pools.setdefault(material, {"public": Decimal("0"), "project": {}})

        # 412: own-project stock at this WBS + public warehouse
        own = pool["project"].get(wbs, Decimal("0"))
        a412 = min(need, own + pool["public"])
        take_own = min(a412, own)
        pool["project"][wbs] = own - take_own
        pool["public"] -= (a412 - take_own)
        if a412 > 0:
            _add_line(bucket(("412", wbs), "412", wbs), material, name, a412, unit, meta)
        remaining = need - a412

        # 89: other projects' special stock, largest source first; one draft per source WBS
        others = sorted(
            [(w, q) for w, q in pool["project"].items() if w != wbs and q > 0],
            key=lambda kv: kv[1], reverse=True,
        )
        for src_wbs, avail in others:
            if remaining <= 0:
                break
            a89 = min(remaining, avail)
            pool["project"][src_wbs] = avail - a89
            remaining -= a89
            if a89 > 0:
                _add_line(bucket(("89", wbs, src_wbs), "89", wbs, src_wbs), material, name, a89, unit, meta)

        # 458: purchase the shortfall
        if remaining > 0:
            _add_line(bucket(("458", wbs), "458", wbs), material, name, remaining, unit, meta)
            notes.append(f"{material} @ {wbs or '(无WBS)'}: 缺口 {_fmt(remaining)} → 458 采购")

    entries: List[AllocationEntry] = []
    for b in buckets.values():
        meta = b["meta"] or {}
        lines = [MaterialLine(materialCode=code, materialName=v["name"], quantity=_fmt(v["qty"]), unit=v["unit"])
                 for code, v in b["lines"].items()]
        entries.append(AllocationEntry(
            workflow_id=b["workflow_id"],
            wbsCode=b["wbsCode"],
            transferOutWbs=b.get("transferOutWbs"),
            demandFactoryCode=meta.get("demandFactoryCode", ""),
            projectDefinition=meta.get("projectDefinition", ""),
            mrpController=meta.get("mrpController", ""),
            materialLines=lines,
        ))

    order = {"412": 0, "89": 1, "458": 2}
    entries.sort(key=lambda e: (order.get(e.workflow_id, 9), e.wbsCode, e.transferOutWbs or ""))
    return AllocationPlan(entries=entries, notes=notes)


def allocate_return(demand_rows: List[Dict[str, Any]]) -> AllocationPlan:
    """Return mode: every demand row becomes a 414 入库 line, bucketed by WBS.
    No stock fan-out — the quantity is what's being returned to the warehouse."""
    buckets: Dict[tuple, Dict[str, Any]] = {}
    for row in demand_rows or []:
        material = str(row.get("materialCode") or "")
        if not material:
            continue
        wbs = str(row.get("wbsCode") or "")
        meta = {"demandFactoryCode": str(row.get("demandFactoryCode") or ""),
                "projectDefinition": str(row.get("projectDefinition") or ""),
                "mrpController": str(row.get("mrpController") or "")}
        key = ("414", wbs)
        if key not in buckets:
            buckets[key] = {"workflow_id": "414", "wbsCode": wbs, "transferOutWbs": None,
                            "lines": {}, "meta": None}
        _add_line(buckets[key], material, str(row.get("materialName") or ""),
                  _dec(row.get("quantity")), str(row.get("unit") or ""), meta)

    entries: List[AllocationEntry] = []
    for b in buckets.values():
        meta = b["meta"] or {}
        lines = [MaterialLine(materialCode=code, materialName=v["name"], quantity=_fmt(v["qty"]), unit=v["unit"])
                 for code, v in b["lines"].items()]
        entries.append(AllocationEntry(
            workflow_id="414", wbsCode=b["wbsCode"],
            demandFactoryCode=meta.get("demandFactoryCode", ""),
            projectDefinition=meta.get("projectDefinition", ""),
            mrpController=meta.get("mrpController", ""), materialLines=lines))
    entries.sort(key=lambda e: e.wbsCode)
    return AllocationPlan(entries=entries, notes=["归还模式:按 WBS 生成 414 入库草稿"])


def route_workflow_node(state: Dict[str, Any]) -> Dict[str, Any]:
    business = dict(state.get("business_input") or {})
    demand_rows = business.get("demandRows") or []
    if state.get("goal") == "return":
        plan = allocate_return(demand_rows)
    else:
        plan = allocate(demand_rows, state.get("inventory") or {})

    summary = {wf: 0 for wf in ("412", "89", "458")}
    for entry in plan.entries:
        summary[entry.workflow_id] = summary.get(entry.workflow_id, 0) + 1
    history = append_history(state, {"node": "route_workflow", "ok": True,
                                     "draftCount": len(plan.entries), "byFlow": summary,
                                     "notes": len(plan.notes)})
    if not plan.entries:
        return {"plan": plan.model_dump(),
                "result": {"ok": False, "error": "路由未产出任何草稿(无需求行或无可分配量)。"},
                "history": history}
    return {"plan": plan.model_dump(), "history": history}
