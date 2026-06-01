"""The Executor contract the graph depends on (platform-neutral)."""
from __future__ import annotations

from typing import Any, Dict, Protocol, runtime_checkable

from ..schemas import (ExecutionResult, FillRequest, InboundFillRequest,
                       OutboundFillRequest, PurchaseFillRequest)


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
