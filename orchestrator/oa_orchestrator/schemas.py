"""Pydantic data contracts shared across nodes and the Executor boundary.

Wire-facing models (BusinessInput, MaterialPlan, FillRequest) use camelCase
field names to match the Node /api/oa/stock-transfer contract 1:1. Internal
reasoning models (Intent, Diagnosis) use snake_case.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# --------------------------------------------------------------------------- #
# Wire-facing (mirror the Node structured contract)
# --------------------------------------------------------------------------- #
class MaterialPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    materialCode: str
    materialName: Optional[str] = None
    quantity: str = "0"
    unit: Optional[str] = None

    @field_validator("quantity", mode="before")
    @classmethod
    def _coerce_quantity(cls, v):  # noqa: N805
        return "" if v is None else str(v)


class BusinessInput(BaseModel):
    """Structured Excel content (replaces passing a file path to Node)."""

    model_config = ConfigDict(extra="ignore")

    projectDefinition: Optional[str] = None
    wbsCode: Optional[str] = None
    demandFactoryCode: Optional[str] = None
    mrpController: Optional[str] = None
    materialPlans: List[MaterialPlan] = Field(default_factory=list)
    quantityByMaterialCode: Dict[str, str] = Field(default_factory=dict)
    sourceFile: Optional[str] = None
    # Stage 3: the full per-workflow structured dict (the shape each Node
    # endpoint's `structured` field expects). Workflow 89 leaves this None and
    # relies on the flat fields above; 412/414/458 carry their own shape here
    # (cost center, material rows, normalized attachment path, etc.) so their
    # build_request can reconstruct the exact Node payload.
    structured: Optional[Dict[str, Any]] = None


# --------------------------------------------------------------------------- #
# Personalization (static per-user defaults; the personalize node prefills slots)
# --------------------------------------------------------------------------- #
class Profile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: str
    department: Optional[str] = None
    default_factory_code: Optional[str] = None
    default_movement_type: Optional[str] = None
    default_wbs: Optional[str] = None
    default_transfer_out_stock_location_name: Optional[str] = None
    default_transfer_out_stock_location_sap: Optional[str] = None
    default_transfer_in_stock_location_name: Optional[str] = None
    default_transfer_in_stock_location_sap: Optional[str] = None


# --------------------------------------------------------------------------- #
# Understanding layer (LLM output)
# --------------------------------------------------------------------------- #
class Intent(BaseModel):
    """What the LLM extracts from the natural-language request for workflow 89."""

    model_config = ConfigDict(extra="ignore")

    workflow_id: str = "89"
    movement_type: Optional[str] = None
    factory_code: Optional[str] = None
    warehouse_type: Optional[str] = None
    transfer_out_stock_location_name: Optional[str] = None
    transfer_out_stock_location_sap: Optional[str] = None
    transfer_in_stock_location_name: Optional[str] = None
    transfer_in_stock_location_sap: Optional[str] = None
    wbs: Optional[str] = None
    transfer_out_wbs: Optional[str] = None
    transfer_in_wbs: Optional[str] = None
    quantity_overrides: Dict[str, str] = Field(default_factory=dict)
    notes: Optional[str] = None


class FillRequest(BaseModel):
    """Payload sent to executor.fill_stock_transfer — mirrors Node's zod schema."""

    model_config = ConfigDict(extra="ignore")

    structured: BusinessInput
    url: Optional[str] = None
    movementType: Optional[str] = None
    warehouseType: Optional[str] = None
    factoryCode: Optional[str] = None
    stockLocationName: Optional[str] = None
    stockLocationSapCode: Optional[str] = None
    transferOutStockLocationName: Optional[str] = None
    transferOutStockLocationSapCode: Optional[str] = None
    transferInStockLocationName: Optional[str] = None
    transferInStockLocationSapCode: Optional[str] = None
    wbs: Optional[str] = None
    transferOutWbs: Optional[str] = None
    transferInWbs: Optional[str] = None
    quantityOverrides: Dict[str, str] = Field(default_factory=dict)
    loginTimeoutMs: Optional[int] = None
    save: bool = False


class OutboundFillRequest(BaseModel):
    """Payload for executor.fill_outbound — mirrors Node POST /api/oa/outbound.

    The per-workflow `structured` dict (cost center, material rows, MRP info) is
    passed through verbatim; extra keys are kept (extra="allow") because the
    structured shape differs from workflow 89.
    """

    model_config = ConfigDict(extra="allow")

    structured: Dict[str, Any]
    url: Optional[str] = None
    userDepartment: Optional[str] = None
    warehouseType: Optional[str] = None
    loginTimeoutMs: Optional[int] = None
    save: bool = False


class InboundFillRequest(BaseModel):
    """Payload for executor.fill_inbound — mirrors Node POST /api/oa/inbound."""

    model_config = ConfigDict(extra="allow")

    structured: Dict[str, Any]
    url: Optional[str] = None
    userDepartment: Optional[str] = None
    inboundType: Optional[str] = None
    warehouseType: Optional[str] = None
    voucherSearchBy: Optional[str] = None
    projectCode: Optional[str] = None
    voucherNumber: Optional[str] = None
    stockLocationName: Optional[str] = None
    stockLocationSapCode: Optional[str] = None
    quantityRule: Optional[str] = None
    quantityOverrides: Dict[str, str] = Field(default_factory=dict)
    loginTimeoutMs: Optional[int] = None
    save: bool = False


class PurchaseFillRequest(BaseModel):
    """Payload for executor.fill_purchase — mirrors Node POST /api/oa/purchase.

    `structured.normalizedPath` is the normalized attachment the Node endpoint
    uploads; intake (parse_purchase) writes it.
    """

    model_config = ConfigDict(extra="allow")

    structured: Dict[str, Any]
    url: Optional[str] = None
    purchaseType: Optional[str] = None
    projectType: Optional[str] = None
    loginTimeoutMs: Optional[int] = None
    save: bool = False


# --------------------------------------------------------------------------- #
# Execution + self-check
# --------------------------------------------------------------------------- #
class ExecutionResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    ok: bool = False
    requestId: Optional[str] = None
    requestUrl: Optional[str] = None
    reportPath: Optional[str] = None
    summary: Optional[dict] = None
    actions: List[dict] = Field(default_factory=list)
    needsInput: bool = False
    input: Optional[dict] = None  # NeedInputError payload {kind, question, options}
    error: Optional[str] = None
    artifact: Optional[dict] = None


class FailureCategory(str, Enum):
    TRANSIENT = "transient"        # network / load timeout -> deterministic retry
    INPUT = "input"               # missing/wrong slot -> back to ask / needs_input
    STRUCTURAL = "structural"     # selector drift / DOM change -> record + escalate
    LOGIN = "login"               # session expired -> wait for re-login
    UNKNOWN = "unknown"


class DiagnosisAction(str, Enum):
    RETRY = "retry"
    BACK_TO_ASK = "back_to_ask"
    RESOLVE_AGAIN = "resolve_again"
    NEEDS_INPUT = "needs_input"
    WAIT_LOGIN = "wait_login"
    ABORT = "abort"


class Diagnosis(BaseModel):
    model_config = ConfigDict(extra="ignore")

    category: FailureCategory = FailureCategory.UNKNOWN
    action: DiagnosisAction = DiagnosisAction.ABORT
    reason: str = ""
    confidence: float = 0.5
