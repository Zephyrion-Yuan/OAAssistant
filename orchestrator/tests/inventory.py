"""Offline test: inventory_query executor capability + classify + node.

No network, no DeepSeek, no Edge. Run:
    orchestrator/.venv/bin/python orchestrator/tests/inventory.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["EXECUTOR"] = "mock"
os.environ["DEEPSEEK_API_KEY"] = ""  # offline gate

from oa_orchestrator.executors.mock import MockExecutor  # noqa: E402
from oa_orchestrator.nodes.inventory_query import (classify_inventory,  # noqa: E402
                                                   make_inventory_query)
from oa_orchestrator.schemas import InventoryQueryRequest  # noqa: E402


def main() -> int:
    mock = MockExecutor()

    # 1) project/special stock (SOBKZ=Q) -> route hint project_stock (-> 89)
    resp = mock.inventory_query(InventoryQueryRequest(materialCode="4000059295"))
    assert resp["requiresLogin"] is False
    assert resp["search"]["rowCount"] == 1, resp["search"]
    row = resp["organizedRows"][0]
    assert row["fields"]["specialStockIndicator"] == "Q", row
    summary = classify_inventory(resp["organizedRows"])
    assert summary["routeHint"] == "project_stock", summary
    assert summary["hasProjectStock"] and not summary["hasPublicStock"]
    assert summary["projectWbsCodes"] == ["C2-0225002.06.01"], summary
    assert abs(summary["totalUnrestricted"] - 2.0) < 1e-9
    print("PASS project stock 4000059295 -> routeHint=project_stock (->89)")

    # 2) unrestricted public-warehouse stock -> route hint public_stock (-> 412)
    resp = mock.inventory_query(InventoryQueryRequest(materialCode="4000023659"))
    summary = classify_inventory(resp["organizedRows"])
    assert summary["routeHint"] == "public_stock", summary
    assert summary["hasPublicStock"] and not summary["hasProjectStock"]
    print("PASS public stock 4000023659 -> routeHint=public_stock (->412)")

    # 3) unknown material -> no stock -> route hint no_stock (-> 458)
    resp = mock.inventory_query(InventoryQueryRequest(materialCode="9999999999"))
    assert resp["search"]["rowCount"] == 0
    summary = classify_inventory(resp["organizedRows"])
    assert summary["routeHint"] == "no_stock", summary
    assert summary["hasStock"] is False
    print("PASS unknown 9999999999 -> routeHint=no_stock (->458)")

    # 4) narrowing by stockLocationCode filters rows
    resp = mock.inventory_query(InventoryQueryRequest(materialCode="4000059295", stockLocationCode="A001"))
    assert resp["search"]["rowCount"] == 0, "H001 row must be filtered out by LGORT=A001"
    print("PASS narrowing by stockLocationCode filters rows")

    # 5) executor-level narrowing by factory also filters rows
    resp = mock.inventory_query(InventoryQueryRequest(materialCode="4000023659", factoryCode="9999"))
    assert resp["search"]["rowCount"] == 0, "WERKS=9999 must exclude the factory-1000 row"
    print("PASS narrowing by factoryCode filters rows")

    # 6) inventory_query node writes per-material signals into state["inventory"].
    # The node queries material-code-only (all factories) so cross-factory stock
    # is never hidden; route_workflow refines by factory/WBS later.
    node = make_inventory_query(mock)
    state = {
        "business_input": {
            "demandFactoryCode": "1010",
            "materialPlans": [
                {"materialCode": "4000059295", "quantity": "1"},
                {"materialCode": "4000023659", "quantity": "1"},
                {"materialCode": "9999999999", "quantity": "1"},
            ],
        },
        "history": [],
    }
    out = node(state)
    inv = out["inventory"]
    assert inv["4000059295"]["routeHint"] == "project_stock", inv["4000059295"]
    assert inv["4000023659"]["routeHint"] == "public_stock", inv["4000023659"]
    assert inv["9999999999"]["routeHint"] == "no_stock", inv["9999999999"]
    # per-location factory is preserved for route_workflow to refine on
    assert inv["4000023659"]["locations"][0]["factoryCode"] == "1000", inv["4000023659"]
    assert out["history"][-1]["node"] == "inventory_query"
    print("PASS inventory_query node -> per-material route hints in state.inventory")

    print("\nALL INVENTORY OFFLINE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
