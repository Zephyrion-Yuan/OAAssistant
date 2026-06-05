"""route_workflow node — the inventory-driven WBS-fan-out allocator.

Per demand row (material + demand WBS + quantity), allocate against that
material's SAP inventory by WHERE the stock physically is (confirmed policy):

    own-project stock (Q @ demand WBS)  -> 412 出库
    public-warehouse stock (SOBKZ blank) -> 89 转储(公共仓→项目仓) + 412 出库
    other-project stock (Q @ another WBS) -> 建议 458 采购 (不自动转储;可对话改走 89)
    shortfall (no stock)                 -> 458 采购

The public portion produces TWO drafts: a 89 transfer (普通库存转储至项目库存) moving
it from the public warehouse into the demand project's warehouse, plus the 412
outbound. Other-project stock is NOT auto-transferred — a recommendation note is
surfaced and the user can override per material via the dialogue (routing_overrides
{material: "transfer"}) which then routes it to a project→project 89.

A per-material stock pool is depleted across rows. Pure + deterministic; the LLM
only participates by interpreting the override reply (in apply_corrections).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List

from ..schemas import AllocationEntry, AllocationPlan, MaterialLine
from ._common import append_history

MOVEMENT_PUBLIC_TO_PROJECT = "普通库存转储至项目库存"   # public warehouse -> project stock
MOVEMENT_PROJECT_TO_PROJECT = "项目库存转储至项目库存"  # another project -> this project


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
    """material -> {public: [{code,name,qty}], project: {wbs: qty}}.

    Public locations are kept individually (not summed) because a public→project
    89 transfer needs the *source warehouse location* — which has no WBS and is
    lost if we only keep the aggregate."""
    pools: Dict[str, Dict[str, Any]] = {}
    for material, inv in (inventory or {}).items():
        public: List[Dict[str, Any]] = []
        project: Dict[str, Decimal] = {}
        for loc in (inv or {}).get("locations", []) or []:
            qty = _dec(loc.get("unrestrictedStock"))
            if qty <= 0:
                continue
            if loc.get("isProjectStock"):
                wbs = str(loc.get("wbsCode") or "")
                project[wbs] = project.get(wbs, Decimal("0")) + qty
            else:
                public.append({
                    "code": str(loc.get("stockLocationCode") or ""),
                    "name": str(loc.get("stockLocationName") or ""),
                    "qty": qty,
                })
        pools[material] = {"public": public, "project": project}
    return pools


def _add_line(bucket: Dict[str, Any], material: str, name: str, qty: Decimal, unit: str, meta: Dict[str, str]):
    if bucket["meta"] is None:
        bucket["meta"] = meta
    line = bucket["lines"].setdefault(material, {"name": name, "unit": unit, "qty": Decimal("0")})
    if name and not line.get("name"):
        line["name"] = name
    if unit and not line.get("unit"):
        line["unit"] = unit
    line["qty"] += qty


def allocate(demand_rows: List[Dict[str, Any]], inventory: Dict[str, Any],
             routing_overrides: Dict[str, str] | None = None) -> AllocationPlan:
    pools = _build_pools(inventory)
    overrides = {str(k): str(v) for k, v in (routing_overrides or {}).items()}
    buckets: Dict[tuple, Dict[str, Any]] = {}
    notes: List[str] = []
    recommendations: List[Dict[str, Any]] = []   # other-project stock awaiting a purchase/transfer decision

    def bucket(key: tuple, workflow_id: str, wbs: str, *, src_wbs: str | None = None,
               movement: str | None = None, source_kind: str | None = None,
               out_loc: Dict[str, Any] | None = None) -> Dict[str, Any]:
        if key not in buckets:
            buckets[key] = {
                "workflow_id": workflow_id, "wbsCode": wbs, "transferOutWbs": src_wbs,
                "movementType": movement, "sourceKind": source_kind,
                "transferOutStockLocationName": (out_loc or {}).get("name"),
                "transferOutStockLocationSapCode": (out_loc or {}).get("code"),
                "lines": {}, "meta": None,
            }
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
        pool = pools.setdefault(material, {"public": [], "project": {}})

        # 1) own-project stock @ this WBS -> 412 出库 directly
        own = pool["project"].get(wbs, Decimal("0"))
        a_own = min(need, own)
        pool["project"][wbs] = own - a_own
        out_412 = a_own
        remaining = need - a_own

        # 2) public-warehouse stock -> 89(公共→项目) per source location + 412 出库
        for loc in pool["public"]:
            if remaining <= 0:
                break
            take = min(remaining, loc["qty"])
            if take <= 0:
                continue
            loc["qty"] -= take
            remaining -= take
            out_412 += take
            _add_line(
                bucket(("89pub", wbs, loc["code"] or loc["name"]), "89", wbs,
                       movement=MOVEMENT_PUBLIC_TO_PROJECT, source_kind="public", out_loc=loc),
                material, name, take, unit, meta)
            notes.append(f"{material} @ {wbs or '(无WBS)'}: 公共仓 {loc['name'] or loc['code']} {_fmt(take)} → 89 转储(公共→项目) 后 412 出库")

        # the merged 412 outbound (own-project + transferred-in public)
        if out_412 > 0:
            _add_line(bucket(("412", wbs), "412", wbs), material, name, out_412, unit, meta)

        # 3) other-project stock -> recommend 458 (don't auto-89); user can override
        others = sorted(
            [(w, q) for w, q in pool["project"].items() if w != wbs and q > 0],
            key=lambda kv: kv[1], reverse=True,
        )
        other_total = sum((q for _, q in others), Decimal("0"))
        if remaining > 0 and other_total > 0:
            if overrides.get(material) == "transfer":
                for src_wbs, avail in others:
                    if remaining <= 0:
                        break
                    a89 = min(remaining, avail)
                    pool["project"][src_wbs] = avail - a89
                    remaining -= a89
                    if a89 > 0:
                        _add_line(
                            bucket(("89", wbs, src_wbs), "89", wbs, src_wbs=src_wbs,
                                   movement=MOVEMENT_PROJECT_TO_PROJECT, source_kind="project"),
                            material, name, a89, unit, meta)
                        notes.append(f"{material} @ {wbs or '(无WBS)'}: 已按你的选择从项目仓 {src_wbs} 转储 {_fmt(a89)}(89 项目→项目)")
            elif overrides.get(material) == "purchase":
                pass  # user already confirmed purchase for this material — proceed to 458 silently
            else:
                coverable = min(remaining, other_total)
                src_text = "、".join(f"{w}({_fmt(q)})" for w, q in others)
                notes.append(
                    f"{material} @ {wbs or '(无WBS)'}: 在其他项目仓 {src_text} 发现库存 {_fmt(coverable)}，"
                    f"按建议走采购(458)。如要改为项目间转储，回复『{material} 改走转储』。")
                recommendations.append({
                    "materialCode": material, "wbsCode": wbs,
                    "otherSources": [{"wbsCode": w, "qty": _fmt(q)} for w, q in others],
                    "coverable": _fmt(coverable), "default": "purchase",
                })

        # 4) shortfall (incl. the other-project amount we recommend purchasing) -> 458
        if remaining > 0:
            _add_line(bucket(("458", wbs), "458", wbs), material, name, remaining, unit, meta)
            if not (other_total > 0 and overrides.get(material) != "transfer"):
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
            movementType=b.get("movementType"),
            sourceKind=b.get("sourceKind"),
            transferOutStockLocationName=b.get("transferOutStockLocationName"),
            transferOutStockLocationSapCode=b.get("transferOutStockLocationSapCode"),
            demandFactoryCode=meta.get("demandFactoryCode", ""),
            projectDefinition=meta.get("projectDefinition", ""),
            mrpController=meta.get("mrpController", ""),
            materialLines=lines,
        ))

    order = {"412": 0, "89": 1, "458": 2}
    entries.sort(key=lambda e: (order.get(e.workflow_id, 9), e.wbsCode, e.transferOutWbs or ""))
    return AllocationPlan(entries=entries, notes=notes, recommendations=recommendations)


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
        plan = allocate(demand_rows, state.get("inventory") or {},
                        routing_overrides=state.get("routing_overrides") or {})

    summary = {wf: 0 for wf in ("412", "89", "458")}
    for entry in plan.entries:
        summary[entry.workflow_id] = summary.get(entry.workflow_id, 0) + 1
    history = append_history(state, {"node": "route_workflow", "ok": True,
                                     "draftCount": len(plan.entries), "byFlow": summary,
                                     "notes": len(plan.notes), "recommendations": len(plan.recommendations)})
    if not plan.entries:
        return {"plan": plan.model_dump(),
                "result": {"ok": False, "error": "路由未产出任何草稿(无需求行或无可分配量)。"},
                "history": history}

    # Other-project stock: per the confirmed policy we PROCEED with 458 by default
    # and surface a recommendation (in plan.notes). We do NOT park — the LLM still
    # participates by interpreting a『<物料> 改走转储』override (apply_corrections
    # → routing_overrides), which re-routes that portion to a project→project 89.
    return {"plan": plan.model_dump(), "history": history}
