"""Shared helpers for nodes."""
from __future__ import annotations

from typing import Any, Dict, List

# Mirrors config/oa-workflow-89-stock-transfer.json "movementType" default.
DEFAULT_MOVEMENT_TYPE = "普通库存转储至普通库存"


def needs_out_wbs(movement_type: str) -> bool:
    return str(movement_type or "").startswith("项目库存转储")


def needs_in_wbs(movement_type: str) -> bool:
    return str(movement_type or "").endswith("至项目库存")


def out_location(intent: Dict[str, Any]) -> str:
    return (intent.get("transfer_out_stock_location_name")
            or intent.get("transfer_out_stock_location_sap") or "")


def in_location(intent: Dict[str, Any]) -> str:
    return (intent.get("transfer_in_stock_location_name")
            or intent.get("transfer_in_stock_location_sap") or "")


def append_history(state: Dict[str, Any], record: Dict[str, Any]) -> List[Dict[str, Any]]:
    history = list(state.get("history", []))
    history.append(record)
    return history
