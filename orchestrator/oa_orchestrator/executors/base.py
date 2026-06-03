"""The Executor contract the graph depends on (platform-neutral)."""
from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, runtime_checkable

from ..schemas import (ExecutionResult, FillRequest, InboundFillRequest,
                       InventoryQueryRequest, OutboundFillRequest,
                       PurchaseFillRequest)


class ExecutorError(RuntimeError):
    """Raised for transport/backend failures (network, 5xx). The diagnose node
    classifies these as transient/login rather than business errors."""


@runtime_checkable
class Executor(Protocol):
    """OA/PDM contract the graph depends on. One fill_* method per workflow."""

    name: str

    def session_status(self) -> Dict[str, Any]:
        """Return the backend's OA/PDM login/session status."""
        ...

    def query_pdm(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """Query PDM master-data material; return the Node response shape."""
        ...

    def inventory_query(self, request: InventoryQueryRequest) -> Dict[str, Any]:
        """Query OA SAP inventory by material code (optionally narrowed by
        factory/stock-location/WBS). Read-only; never fills or submits. Returns
        the Node /api/oa/inventory-query response shape (organizedRows + search).
        Feeds the Stage-3b route_workflow decision."""
        ...

    def query_wbs(self, wbs_code: str) -> Optional[Dict[str, Any]]:
        """Look up a WBS code in the Node-owned WBS registry. Returns the record
        dict (factory/cost center/purchaser/stock location/…) or None if unknown.
        The prepare node uses this to auto-fill each draft's bound fields."""
        ...

    def resolve_wbs(self, query: str) -> Dict[str, Any]:
        """Resolve a free-text/alias/code reference to a WBS. Returns
        {matched: record|None, matchType, candidates: [...]}. The resolve_wbs node
        uses this so users can fill the WBS field (or instruct) with a nickname."""
        ...

    def fill_stock_transfer(self, request: FillRequest) -> ExecutionResult:
        """Drive OA workflow 89 to a (optionally saved) draft. Never submits."""
        ...

    def fill_outbound(self, request: OutboundFillRequest) -> ExecutionResult:
        """Drive OA workflow 412 (物资出库) to a (optionally saved) draft."""
        ...

    def fill_inbound(self, request: InboundFillRequest) -> ExecutionResult:
        """Drive OA workflow 414 (物资入库) to a (optionally saved) draft."""
        ...

    def fill_purchase(self, request: PurchaseFillRequest) -> ExecutionResult:
        """Drive OA workflow 458 (采购申请) to a (optionally saved) draft."""
        ...
