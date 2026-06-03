"""inventory_query node — cross-system read step (peer of pdm_enrich).

For each material plan, ask the executor for OA SAP inventory and classify what
was found into routing-relevant signals. This is the Stage-3b prerequisite the
`route_workflow` decision node consumes; this node only *gathers and classifies*
inventory — it does not decide the workflow (that needs the request's own WBS to
tell "this project's stock" from "another project's stock", which route_workflow
owns).

Stock signals (per the user's inventory-driven routing rules):
  - no available stock                         -> hint "no_stock"     (-> 458 purchase)
  - unrestricted stock, public warehouse (SOBKZ blank) -> hint "public_stock"  (-> 412 outbound)
  - special/project stock (SOBKZ = "Q")        -> hint "project_stock" (-> 89 transfer)
The leftover-return case (-> 414 inbound) is intent-driven, not inferable here.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List

from ..executors.base import ExecutorError
from ..schemas import InventoryQueryRequest
from ._common import append_history


def _to_float(value: Any) -> float:
    try:
        return float(str(value).replace(",", "").strip() or 0)
    except (TypeError, ValueError):
        return 0.0


def _row_fields(row: Dict[str, Any]) -> Dict[str, Any]:
    # organizeInventoryRow puts stock/indicator inside `fields`; tolerate flat too
    fields = row.get("fields")
    return fields if isinstance(fields, dict) else row


def classify_inventory(organized_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pure: reduce one material's organized inventory rows to routing signals."""
    locations: List[Dict[str, Any]] = []
    total_unrestricted = 0.0
    has_public = False
    has_project = False
    project_wbs: List[str] = []

    for row in organized_rows or []:
        fields = _row_fields(row)
        qty = _to_float(fields.get("unrestrictedStock"))
        sobkz = str(fields.get("specialStockIndicator") or "").strip().upper()
        wbs = str(row.get("wbsCode") or fields.get("wbsCode") or "").strip()
        is_project = sobkz == "Q"
        if qty > 0:
            total_unrestricted += qty
            if is_project:
                has_project = True
                if wbs:
                    project_wbs.append(wbs)
            else:
                has_public = True
        locations.append({
            "factoryCode": str(row.get("factoryCode") or fields.get("factoryCode") or ""),
            "stockLocationCode": str(row.get("stockLocationCode") or fields.get("stockLocationCode") or ""),
            "stockLocationName": str(fields.get("stockLocationName") or ""),
            "wbsCode": wbs,
            "unrestrictedStock": qty,
            "specialStockIndicator": sobkz,
            "isProjectStock": is_project,
        })

    if total_unrestricted <= 0:
        hint = "no_stock"
    elif has_public and has_project:
        hint = "mixed"
    elif has_public:
        hint = "public_stock"
    else:
        hint = "project_stock"

    return {
        "hasStock": total_unrestricted > 0,
        "totalUnrestricted": total_unrestricted,
        "hasPublicStock": has_public,
        "hasProjectStock": has_project,
        "projectWbsCodes": sorted(set(project_wbs)),
        "locations": locations,
        "routeHint": hint,
    }


def make_inventory_query(executor) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    def inventory_query_node(state: Dict[str, Any]) -> Dict[str, Any]:
        business = dict(state.get("business_input") or {})
        plans: List[Dict[str, Any]] = list(business.get("materialPlans", []))
        per_material: Dict[str, Any] = {}

        for plan in plans:
            code = plan.get("materialCode")
            if not code:
                continue
            # Query by material code only (all factories/locations), matching the
            # real oaInventoryQuery default (werksList: []). A complete picture of
            # where stock sits lets route_workflow refine by factory/WBS itself —
            # auto-narrowing by demand factory here would hide cross-factory stock.
            request = InventoryQueryRequest(materialCode=code)
            try:
                resp = executor.inventory_query(request)
            except ExecutorError as exc:
                history = append_history(state, {"node": "inventory_query", "ok": False, "error": str(exc)})
                return {"result": {"ok": False, "error": f"inventory query failed: {exc}"}, "history": history}

            if resp.get("requiresLogin"):
                history = append_history(state, {"node": "inventory_query", "ok": False, "requiresLogin": True})
                return {
                    "result": {"ok": False, "needsLogin": True,
                               "error": "OA inventory query requires login."},
                    "history": history,
                }

            organized = resp.get("organizedRows") or []
            summary = classify_inventory(organized)
            summary["rowCount"] = (resp.get("search") or {}).get("rowCount", len(organized))
            per_material[code] = summary

        history = append_history(state, {
            "node": "inventory_query", "ok": True,
            "materials": {c: s["routeHint"] for c, s in per_material.items()},
        })
        return {"inventory": per_material, "history": history}

    return inventory_query_node
