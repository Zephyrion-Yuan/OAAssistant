"""In-memory fake OA/PDM backend for offline tests and CI.

No real system, no network, no browser. Mirrors the relevant response shapes of
the Node service closely enough to exercise the whole graph (happy path +
needs-input branches) without DeepSeek or a logged-in Edge.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from ..schemas import (ExecutionResult, FillRequest, InboundFillRequest,
                       InventoryQueryRequest, OutboundFillRequest,
                       PurchaseFillRequest)

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

# WBS registry (mirrors the Node /api/wbs records). The prepare node reads this
# via query_wbs to auto-fill each draft's bound fields.
_WBS_REGISTRY: Dict[str, Dict[str, Any]] = {
    "C2-0225002.06.01": {
        "wbsCode": "C2-0225002.06.01",
        "alias": "传感器项目, SA探针",
        "projectDefinition": "C2-0225002",
        "demandFactoryCode": "1010",
        "costCenter": "CC-1010-01",
        "purchaser": "demo-buyer",
        "mrpController": "P22",
        "stockLocationName": "实验室仓",
        "stockLocationSapCode": "H001",
        "warehouseType": "鲲鹏仓库",
        "projectType": "是",
        "purchaseType": "项目物资采购申请",
        "purchaseDemandType": "02",
        "deliveryAddress": "苏州工业园区玲珑街88号",
        "demandDateOffsetDays": 5,
        "remark": "紧急",
        "status": "active",
    },
    # a second project's WBS — the source side of an 89 transfer test
    "C2-0339001.01.01": {
        "wbsCode": "C2-0339001.01.01",
        "alias": "适配体项目",
        "projectDefinition": "C2-0339001",
        "demandFactoryCode": "1010",
        "costCenter": "CC-1010-09",
        "purchaser": "demo-buyer-2",
        "mrpController": "M01",
        "stockLocationName": "设备零件仓",
        "stockLocationSapCode": "D002",
        "warehouseType": "鲲鹏仓库",
        "projectType": "是",
        "purchaseType": "项目物资采购申请",
        "purchaseDemandType": "02",
        "demandDateOffsetDays": 5,
        "remark": "",
        "status": "active",
    },
}

# materialCode -> SAP inventory rows (the Node organizeInventoryRow shape).
# Routing-relevant fields (unrestrictedStock, specialStockIndicator) live inside
# `fields`, exactly like the real /api/oa/inventory-query organizedRows, so the
# inventory_query node reads them identically against mock and live backends.
# - 4000059295: project/special stock (SOBKZ=Q) in another project's WBS  -> 89 transfer
# - 4000023659: unrestricted stock in a public warehouse (SOBKZ blank)    -> 412 outbound
# - any other code: no rows                                               -> 458 purchase
_INVENTORY: Dict[str, List[Dict[str, Any]]] = {
    "4000059295": [
        {"factoryCode": "1010", "stockLocationCode": "H001", "stockLocationName": "实验室仓",
         "wbsCode": "C2-0225002.06.01", "batchNumber": "", "unrestrictedStock": "2.000",
         "specialStockIndicator": "Q", "unit": "Z12",
         "materialDescription": "Octet链霉亲和素SA传感器#18-5019"},
    ],
    "4000023659": [
        {"factoryCode": "1000", "stockLocationCode": "A001", "stockLocationName": "成品仓",
         "wbsCode": "", "batchNumber": "", "unrestrictedStock": "10.000",
         "specialStockIndicator": "", "unit": "EA",
         "materialDescription": "96孔乳白框透明管PCR板（全裙边）"},
    ],
}


def _organize_inventory_row(material_code: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    """Mirror Node organizeInventoryRow: top-level identifiers + a `fields` bag."""
    fields = {
        "materialCode": material_code,
        "factoryCode": raw.get("factoryCode", ""),
        "stockLocationCode": raw.get("stockLocationCode", ""),
        "stockLocationName": raw.get("stockLocationName", ""),
        "wbsCode": raw.get("wbsCode", ""),
        "unit": raw.get("unit", ""),
        "unrestrictedStock": raw.get("unrestrictedStock", "0"),
        "specialStockIndicator": raw.get("specialStockIndicator", ""),
        "materialDescription": raw.get("materialDescription", ""),
    }
    return {
        "materialCode": material_code,
        "factoryCode": raw.get("factoryCode", ""),
        "stockLocationCode": raw.get("stockLocationCode", ""),
        "wbsCode": raw.get("wbsCode", ""),
        "batchNumber": raw.get("batchNumber", ""),
        "fields": fields,
        "extraFields": {},
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

    def inventory_query(self, request: InventoryQueryRequest) -> Dict[str, Any]:
        code = str(request.materialCode or "").strip()
        raw_rows = list(_INVENTORY.get(code, []))
        # narrow by factory / stock-location / WBS when supplied
        if request.factoryCode:
            raw_rows = [r for r in raw_rows if r.get("factoryCode") == request.factoryCode]
        if request.stockLocationCode:
            raw_rows = [r for r in raw_rows if r.get("stockLocationCode") == request.stockLocationCode]
        if request.wbsCode:
            raw_rows = [r for r in raw_rows if r.get("wbsCode") == request.wbsCode]
        organized = [_organize_inventory_row(code, r) for r in raw_rows]
        return {
            "ok": True,
            "requiresLogin": False,
            "page": {"workflowId": request.workflowId or "414"},
            "query": {
                "materialCode": code,
                "factoryCode": request.factoryCode or "",
                "stockLocationCode": request.stockLocationCode or "",
                "wbsCode": request.wbsCode or "",
            },
            "search": {
                "selectedAttemptKind": "stock-query",
                "total": len(organized),
                "rowCount": len(organized),
                "fetchedPageCount": 1,
                "truncated": False,
                "fallbackUsed": False,
            },
            "rows": [dict(r) for r in raw_rows],
            "organizedRows": organized,
            "mock": True,
        }

    def query_wbs(self, wbs_code: str) -> Optional[Dict[str, Any]]:
        record = _WBS_REGISTRY.get(str(wbs_code or "").strip())
        return dict(record) if record else None

    def resolve_wbs(self, query: str) -> Dict[str, Any]:
        q = str(query or "").strip().lower()
        if not q:
            return {"ok": False, "error": "query is required."}
        active = [r for r in _WBS_REGISTRY.values() if r.get("status") != "archived"]

        def aliases(r):
            return [a.strip().lower() for a in re.split(r"[,;，；]", str(r.get("alias") or "")) if a.strip()]

        by_code = next((r for r in active if str(r["wbsCode"]).lower() == q), None)
        if by_code:
            return {"ok": True, "query": query, "matched": dict(by_code), "matchType": "code", "candidates": []}
        by_alias = [r for r in active if q in aliases(r)]
        if len(by_alias) == 1:
            return {"ok": True, "query": query, "matched": dict(by_alias[0]), "matchType": "alias", "candidates": []}
        if len(by_alias) > 1:
            return {"ok": True, "query": query, "matched": None, "matchType": "alias-ambiguous",
                    "candidates": [dict(r) for r in by_alias]}
        fuzzy = []
        for r in active:
            hay = [str(r["wbsCode"]).lower(), str(r.get("projectDefinition") or "").lower(), *aliases(r)]
            if any(h and (q in h or h in q) for h in hay):
                fuzzy.append(r)
        if len(fuzzy) == 1:
            return {"ok": True, "query": query, "matched": dict(fuzzy[0]), "matchType": "fuzzy", "candidates": []}
        return {"ok": True, "query": query, "matched": None,
                "matchType": "fuzzy-ambiguous" if fuzzy else "none", "candidates": [dict(r) for r in fuzzy]}

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
