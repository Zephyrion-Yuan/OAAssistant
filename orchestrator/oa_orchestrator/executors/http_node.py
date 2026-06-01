"""Executor backed by the existing Node OAAssistant HTTP service.

This is where all Windows/mac device differences are absorbed: the same contract
maps to one long-running Node service that owns the managed Edge. The graph is
unaware of platform specifics.
"""
from __future__ import annotations

from typing import Any, Dict

import httpx

from ..schemas import (ExecutionResult, FillRequest, InboundFillRequest,
                       OutboundFillRequest, PurchaseFillRequest)
from .base import ExecutorError


class HttpNodeExecutor:
    name = "http-node"

    def __init__(self, base_url: str, *, timeout: float = 60.0, fill_timeout: float = 600.0):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._fill_timeout = fill_timeout

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    def session_status(self) -> Dict[str, Any]:
        try:
            resp = httpx.get(self._url("/api/session/status"), timeout=self._timeout)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            raise ExecutorError(f"session_status failed: {exc}") from exc

    def query_pdm(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        try:
            resp = httpx.post(self._url("/api/pdm/query"), json=filters, timeout=self._timeout)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            raise ExecutorError(f"query_pdm failed: {exc}") from exc

    def _post_fill(self, path: str, request) -> ExecutionResult:
        payload = request.model_dump(exclude_none=True)
        try:
            resp = httpx.post(self._url(path), json=payload, timeout=self._fill_timeout)
            resp.raise_for_status()
            return ExecutionResult.model_validate(resp.json())
        except httpx.HTTPError as exc:
            # Transport failure -> surface as a (transient) execution result so
            # the diagnose node can decide to retry.
            return ExecutionResult(ok=False, error=f"network: {exc}")

    def fill_stock_transfer(self, request: FillRequest) -> ExecutionResult:
        return self._post_fill("/api/oa/stock-transfer", request)

    def fill_outbound(self, request: OutboundFillRequest) -> ExecutionResult:
        return self._post_fill("/api/oa/outbound", request)

    def fill_inbound(self, request: InboundFillRequest) -> ExecutionResult:
        return self._post_fill("/api/oa/inbound", request)

    def fill_purchase(self, request: PurchaseFillRequest) -> ExecutionResult:
        return self._post_fill("/api/oa/purchase", request)
