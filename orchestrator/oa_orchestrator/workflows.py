"""Workflow registry — the Stage-3 router/extension seam.

Each OA workflow is described by a WorkflowSpec: which executor method drives it,
how to compute its missing required slots, and how to build its executor request.
The graph's check_slot / execute nodes delegate here, so adding workflows
458/412/414 in Stage 3 is plug-in (register a spec) rather than graph surgery.

Today only workflow 89 (stock transfer) is registered.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List

from .schemas import (BusinessInput, FillRequest, InboundFillRequest,
                      OutboundFillRequest, PurchaseFillRequest)
from .nodes._common import (DEFAULT_MOVEMENT_TYPE, in_location, needs_in_wbs,
                            needs_out_wbs, out_location)


@dataclass(frozen=True)
class WorkflowSpec:
    workflow_id: str
    name: str
    executor_method: str                                   # method on the Executor to call
    required_slots: Callable[[Dict[str, Any], Dict[str, Any]], List[str]]
    build_request: Callable[[Dict[str, Any]], Any]         # state -> executor request model


def _stock_transfer_required(intent: Dict[str, Any], business: Dict[str, Any]) -> List[str]:
    movement = intent.get("movement_type") or DEFAULT_MOVEMENT_TYPE
    missing: List[str] = []
    if not out_location(intent):
        missing.append("transferOutStockLocation")
    if not in_location(intent):
        missing.append("transferInStockLocation")
    if needs_out_wbs(movement) and not (intent.get("transfer_out_wbs") or intent.get("wbs") or business.get("wbsCode")):
        missing.append("transferOutWbs")
    if needs_in_wbs(movement) and not (intent.get("transfer_in_wbs") or intent.get("wbs") or business.get("wbsCode")):
        missing.append("transferInWbs")
    return missing


def _stock_transfer_build_request(state: Dict[str, Any]) -> FillRequest:
    business = BusinessInput.model_validate(state.get("business_input") or {})
    resolved = dict(state.get("resolved") or {})
    return FillRequest(structured=business, save=bool(state.get("save", False)), **resolved)


# --------------------------------------------------------------------------- #
# Stage 3 workflows (412 / 414 / 458)
#
# required_slots decision: unlike workflow 89 (which is stock-location driven
# and must collect transfer-out/in locations BEFORE filling), 412/414/458 are
# Excel + config driven. Everything they need is already in the parsed workbook
# (structured dict) + static config (warehouse/inbound/purchase type defaults).
# Their genuinely interactive gaps (e.g. ambiguous 成本中心, multi-voucher
# match, missing 库存地点, missing attachment) only become known once the live
# Node fill queries SAP/OA — they cannot be computed from intent/business_input
# up front. So required_slots returns [] (nothing to ask before execute); those
# gaps surface as needsInput from the executor and are handled by diagnose.
# --------------------------------------------------------------------------- #
def _no_required_slots(intent: Dict[str, Any], business: Dict[str, Any]) -> List[str]:
    return []


def _structured_of(state: Dict[str, Any]) -> Dict[str, Any]:
    business = BusinessInput.model_validate(state.get("business_input") or {})
    return dict(business.structured or {})


def _outbound_build_request(state: Dict[str, Any]) -> OutboundFillRequest:
    resolved = dict(state.get("resolved") or {})
    structured = _structured_of(state)
    return OutboundFillRequest(
        structured=structured,
        save=bool(state.get("save", False)),
        userDepartment=structured.get("userDepartment"),
        warehouseType=resolved.get("warehouseType"),
    )


def _inbound_build_request(state: Dict[str, Any]) -> InboundFillRequest:
    resolved = dict(state.get("resolved") or {})
    structured = _structured_of(state)
    # 414 has a single 库存地点; reuse the generic resolve_params output. The
    # understand heuristic puts a parsed "X仓" name / "A001" SAP code into the
    # transfer-out slot, which we map onto the single stock location here.
    stock_name = resolved.get("stockLocationName") or resolved.get("transferOutStockLocationName")
    stock_sap = resolved.get("stockLocationSapCode") or resolved.get("transferOutStockLocationSapCode")
    return InboundFillRequest(
        structured=structured,
        save=bool(state.get("save", False)),
        warehouseType=resolved.get("warehouseType"),
        stockLocationName=stock_name,
        stockLocationSapCode=stock_sap,
        quantityOverrides=resolved.get("quantityOverrides") or {},
    )


def _purchase_build_request(state: Dict[str, Any]) -> PurchaseFillRequest:
    structured = _structured_of(state)
    return PurchaseFillRequest(
        structured=structured,
        save=bool(state.get("save", False)),
    )


WORKFLOWS: Dict[str, WorkflowSpec] = {
    "89": WorkflowSpec(
        workflow_id="89",
        name="库存转储 (stock transfer)",
        executor_method="fill_stock_transfer",
        required_slots=_stock_transfer_required,
        build_request=_stock_transfer_build_request,
    ),
    "412": WorkflowSpec(
        workflow_id="412",
        name="物资出库 (outbound)",
        executor_method="fill_outbound",
        required_slots=_no_required_slots,
        build_request=_outbound_build_request,
    ),
    "414": WorkflowSpec(
        workflow_id="414",
        name="物资入库 (inbound)",
        executor_method="fill_inbound",
        required_slots=_no_required_slots,
        build_request=_inbound_build_request,
    ),
    "458": WorkflowSpec(
        workflow_id="458",
        name="采购申请 (purchase)",
        executor_method="fill_purchase",
        required_slots=_no_required_slots,
        build_request=_purchase_build_request,
    ),
}


def get_workflow_spec(workflow_id: str) -> WorkflowSpec:
    return WORKFLOWS.get(workflow_id) or WORKFLOWS["89"]
