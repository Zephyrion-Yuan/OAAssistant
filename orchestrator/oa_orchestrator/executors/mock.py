"""In-memory fake OA/PDM backend for offline tests and CI.

No real system, no network, no browser. Mirrors the relevant response shapes of
the Node service closely enough to exercise the whole graph (happy path +
needs-input branches) without DeepSeek or a logged-in Edge.
"""
from __future__ import annotations

from typing import Any, Dict, List

from ..schemas import (ExecutionResult, FillRequest, InboundFillRequest,
                       OutboundFillRequest, PurchaseFillRequest)

# materialCode -> master data (status 1 = 启用)
_CATALOG: Dict[str, Dict[str, Any]] = {
    "4000023659": {
        "materialName": "96孔乳白框透明管PCR板（全裙边）",
        "specificationModel": "96孔",
        "materialGroupCode": "407001",
        "materialGroupDesc": "耗材",
        "unit": "EA",
        "unitDesc": "个",
        "materialLevel": "A",
        "status": 1,
    },
    "4000059295": {
        "materialName": "传感器模组",
        "specificationModel": "S-200",
        "materialGroupCode": "407002",
        "materialGroupDesc": "电子元件",
        "unit": "EA",
        "unitDesc": "个",
        "materialLevel": "B",
        "status": 1,
    },
}

# Known stock locations (name -> sap)
_STOCK_LOCATIONS = {
    "设备零件仓": "D002",
    "成品仓": "A001",
}


class MockExecutor:
    name = "mock"

    def session_status(self) -> Dict[str, Any]:
        return {
            "oaLiveSession": {"browser": "running", "requiresLogin": False},
            "pdmCachedSession": {"browser": "running", "requiresLogin": False},
            "mock": True,
        }

    def query_pdm(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        code = str(filters.get("materialCode") or "").strip()
        name = str(filters.get("materialName") or filters.get("keyword") or "").strip()
        rows: List[Dict[str, Any]] = []
        for c, data in _CATALOG.items():
            if code and c == code:
                rows.append({"materialCode": c, **data})
            elif name and name in data["materialName"]:
                rows.append({"materialCode": c, **data})
        organized = [
            {
                "materialCode": r["materialCode"],
                "materialName": r["materialName"],
                "fields": {"状态文本": "启用" if r.get("status") == 1 else "禁用"},
            }
            for r in rows
        ]
        return {
            "requiresLogin": False,
            "query": {"filters": filters},
            "search": {"total": len(rows), "totalPages": 1, "fetchedPageCount": 1},
            "rows": rows,
            "organizedRows": organized,
            "mock": True,
        }

    def fill_stock_transfer(self, request: FillRequest) -> ExecutionResult:
        plans = request.structured.materialPlans
        # 1) validate materials against the catalog (mirrors NeedInputError kind=material)
        for plan in plans:
            if plan.materialCode not in _CATALOG:
                return ExecutionResult(
                    ok=False,
                    needsInput=True,
                    input={
                        "kind": "material",
                        "question": "物料主数据查询没有返回结果，请确认物料编码。",
                        "materialCode": plan.materialCode,
                    },
                    error=f"No material was found for materialCode={plan.materialCode}.",
                )
        # 2) require stock locations (mirrors NeedInputError kind=transfer*StockLocation)
        out_loc = request.transferOutStockLocationName or request.transferOutStockLocationSapCode \
            or request.stockLocationName or request.stockLocationSapCode
        in_loc = request.transferInStockLocationName or request.transferInStockLocationSapCode \
            or request.stockLocationName or request.stockLocationSapCode
        if not out_loc:
            return ExecutionResult(
                ok=False, needsInput=True,
                input={"kind": "transferOutStockLocation",
                       "question": "请提供转出库存地点名称或 SAP 编码。",
                       "options": [{"stockLocationName": n, "sapCode": s} for n, s in _STOCK_LOCATIONS.items()]},
                error="Transfer-out stock location is required.",
            )
        if not in_loc:
            return ExecutionResult(
                ok=False, needsInput=True,
                input={"kind": "transferInStockLocation",
                       "question": "请提供转入库存地点名称或 SAP 编码。",
                       "options": [{"stockLocationName": n, "sapCode": s} for n, s in _STOCK_LOCATIONS.items()]},
                error="Transfer-in stock location is required.",
            )
        # 3) success
        request_id = "MOCK-89-0001" if request.save else None
        actions = [{"name": f"Select material row {i + 1} {p.materialCode}", "ok": True}
                   for i, p in enumerate(plans)]
        actions.append({"name": "Click 保存" if request.save else "Dry-run (no save)", "ok": True})
        return ExecutionResult(
            ok=True,
            requestId=request_id,
            requestUrl=(f"https://oa.megarobo.info/spa/workflow/static4form/index.html"
                        f"#/main/workflow/req?requestid={request_id}") if request_id else None,
            summary={
                "movementType": request.movementType,
                "factoryCode": request.factoryCode or request.structured.demandFactoryCode,
                "transferRowCount": len(plans),
                "saved": request.save,
            },
            actions=actions,
        )

    # --------------------------------------------------------------------- #
    # Workflow 412 — outbound (物资出库)
    # --------------------------------------------------------------------- #
    def fill_outbound(self, request: OutboundFillRequest) -> ExecutionResult:
        structured = request.structured or {}
        cost_center = structured.get("costCenter") or {}
        # needs_input branch: no cost center resolved (mirrors a Node failure to
        # uniquely match 成本中心 from the workbook).
        if not (cost_center.get("searchName") or cost_center.get("costCenterCode")):
            return ExecutionResult(
                ok=False, needsInput=True,
                input={"kind": "costCenter",
                       "question": "无法唯一确定成本中心，请提供成本中心名称或编码。",
                       "demandFactoryCode": structured.get("demandFactoryCode")},
                error="Cost center could not be resolved.",
            )
        request_id = "MOCK-412-0001" if request.save else None
        return self._ok_result(
            request_id,
            summary={
                "demandFactoryCode": structured.get("demandFactoryCode"),
                "wbsCode": structured.get("wbsCode"),
                "costCenterName": cost_center.get("searchName"),
                "warehouseType": request.warehouseType,
                "materialRowCount": len(structured.get("materialRows") or []),
                "saved": request.save,
            },
        )

    # --------------------------------------------------------------------- #
    # Workflow 414 — inbound (物资入库)
    # --------------------------------------------------------------------- #
    def fill_inbound(self, request: InboundFillRequest) -> ExecutionResult:
        structured = request.structured or {}
        # needs_input branch: no stock location supplied (mirrors Node
        # NeedInputError kind=stockLocation before saving workflow 414).
        if not (request.stockLocationName or request.stockLocationSapCode):
            return ExecutionResult(
                ok=False, needsInput=True,
                input={"kind": "stockLocation",
                       "question": "请提供库存地点名称或 SAP 编码后继续。",
                       "options": [{"stockLocationName": n, "sapCode": s} for n, s in _STOCK_LOCATIONS.items()]},
                error="Stock location is required.",
            )
        request_id = "MOCK-414-0001" if request.save else None
        return self._ok_result(
            request_id,
            summary={
                "demandFactoryCode": structured.get("demandFactoryCode"),
                "wbsCode": structured.get("wbsCode"),
                "inboundType": request.inboundType,
                "projectCode": request.projectCode or structured.get("projectDefinition"),
                "materialRowCount": len(structured.get("materialRows") or []),
                "saved": request.save,
            },
        )

    # --------------------------------------------------------------------- #
    # Workflow 458 — purchase (采购申请)
    # --------------------------------------------------------------------- #
    def fill_purchase(self, request: PurchaseFillRequest) -> ExecutionResult:
        structured = request.structured or {}
        # needs_input branch: no normalized attachment to upload.
        if not structured.get("normalizedPath"):
            return ExecutionResult(
                ok=False, needsInput=True,
                input={"kind": "attachment",
                       "question": "缺少归一化后的采购附件 normalizedPath，请先生成附件。"},
                error="normalizedPath attachment is required.",
            )
        request_id = "MOCK-458-0001" if request.save else None
        return self._ok_result(
            request_id,
            summary={
                "demandFactoryCode": structured.get("demandFactoryCode"),
                "wbsCode": structured.get("wbsCode"),
                "purchaseType": request.purchaseType,
                "projectType": request.projectType,
                "targetDemandDate": structured.get("targetDemandDate"),
                "saved": request.save,
            },
        )

    @staticmethod
    def _ok_result(request_id, *, summary: Dict[str, Any]) -> ExecutionResult:
        return ExecutionResult(
            ok=True,
            requestId=request_id,
            requestUrl=(f"https://oa.megarobo.info/spa/workflow/static4form/index.html"
                        f"#/main/workflow/req?requestid={request_id}") if request_id else None,
            summary=summary,
            actions=[{"name": "Click 保存" if request_id else "Dry-run (no save)", "ok": True}],
        )
