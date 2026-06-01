"""resolve_params node — map the extracted Intent into executor fill parameters.

Deterministic for v1 (explicit request/config values win). The LLM tie-break for
genuinely ambiguous multi-candidate cases is a documented Stage-3 extension.
"""
from __future__ import annotations

from typing import Any, Dict

from ._common import DEFAULT_MOVEMENT_TYPE, append_history


def resolve_params_node(state: Dict[str, Any]) -> Dict[str, Any]:
    intent = state.get("intent") or {}
    business = state.get("business_input") or {}

    resolved: Dict[str, Any] = {
        "movementType": intent.get("movement_type") or DEFAULT_MOVEMENT_TYPE,
        "warehouseType": intent.get("warehouse_type"),
        "factoryCode": intent.get("factory_code") or business.get("demandFactoryCode"),
        "transferOutStockLocationName": intent.get("transfer_out_stock_location_name"),
        "transferOutStockLocationSapCode": intent.get("transfer_out_stock_location_sap"),
        "transferInStockLocationName": intent.get("transfer_in_stock_location_name"),
        "transferInStockLocationSapCode": intent.get("transfer_in_stock_location_sap"),
        "wbs": intent.get("wbs"),
        "transferOutWbs": intent.get("transfer_out_wbs"),
        "transferInWbs": intent.get("transfer_in_wbs"),
        "quantityOverrides": intent.get("quantity_overrides") or {},
    }
    # drop None values to keep the executor payload clean
    resolved = {k: v for k, v in resolved.items() if v not in (None, {})}
    history = append_history(state, {"node": "resolve_params", "resolved_keys": sorted(resolved.keys())})
    return {"resolved": resolved, "history": history}
