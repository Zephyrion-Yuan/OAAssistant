"""prepare node — turn each AllocationEntry into a ready executor request.

For every draft the router produced, look its WBS up in the registry (query_wbs)
and auto-fill the flow's bound fields (factory / cost center / stock location /
demand-date offset). For 458 the purchase attachment is *generated* here (openpyxl)
from the routed material lines + WBS + bound info — that's the workbook the OA 458
form uploads. If a required bound field can't be resolved (e.g. no cost center for
412, no stock location for 89), the draft is marked skipped with a needs-input note
and the others still proceed (execute_plan never blocks on one draft).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict

from openpyxl import Workbook

from ..config import get_settings
from ..intake_parsers import FACTORY_COMPANY_NAMES
from ..schemas import (FillRequest, InboundFillRequest, OutboundFillRequest,
                      PurchaseFillRequest)
from ._common import append_history

# The 458 attachment column layout — the real 项目需求填写界面 sheet (header row 1,
# instruction row 2, data row 3+), aligned 1:1 with docs/example_files. The OA
# importer maps columns by these exact header strings.
PURCHASE_ATTACHMENT_HEADERS = [
    "需求类型", "物料编码", "物料名称", "物料组", "需求数量", "基本计量单位",
    "评估价格（元）", "需求日期", "检验入库时间", "申请人", "项目定义", "WBS编码",
    "网络编码", "网络活动", "成本中心", "MRP控制者", "需求工厂代码", "供应工厂代码",
    "送货地址", "备注", "所需供应商", "OA申请单号",
]
# 需求类型: "02" = 采购申请+预留 (the common project-purchase type).
DEFAULT_PURCHASE_TYPE = "02"
# Acquire-mode 89 always moves another project's special stock into the demand
# project's special stock, so the movement type is fixed.
MOVEMENT_TYPE_ACQUIRE_89 = "项目库存转储至项目库存"


def _skip(entry: Dict[str, Any], kind: str, reason: str) -> Dict[str, Any]:
    entry["skipped"] = True
    entry["skipReason"] = reason
    entry["needsInput"] = {"kind": kind, "question": reason,
                           "wbsCode": entry.get("wbsCode"), "workflow": entry.get("workflow_id")}
    entry["request"] = None
    return entry


def _factory(entry: Dict[str, Any], bound: Dict[str, Any]) -> str:
    return entry.get("demandFactoryCode") or bound.get("demandFactoryCode") or ""


def _purchase_row(line: Dict[str, Any], ctx: Dict[str, str]):
    """One 22-column data row (order matches PURCHASE_ATTACHMENT_HEADERS)."""
    return [
        ctx["purchaseType"],                 # 需求类型
        line.get("materialCode", ""),        # 物料编码
        line.get("materialName", ""),        # 物料名称
        "",                                  # 物料组 (空: 物料编码有值)
        line.get("quantity", "0"),           # 需求数量
        line.get("unit", ""),                # 基本计量单位
        "",                                  # 评估价格（元）
        ctx["targetDate"],                   # 需求日期
        "",                                  # 检验入库时间
        ctx["purchaser"],                    # 申请人 (工号-姓名)
        ctx["projectDefinition"],            # 项目定义
        ctx["wbsCode"],                      # WBS编码
        "",                                  # 网络编码
        "",                                  # 网络活动
        ctx["costCenter"],                   # 成本中心
        ctx["mrpController"],                # MRP控制者
        ctx["factory"],                      # 需求工厂代码
        "",                                  # 供应工厂代码
        ctx["deliveryAddress"],              # 送货地址
        ctx["remark"],                       # 备注
        "",                                  # 所需供应商
        "",                                  # OA申请单号
    ]


def generate_purchase_attachment(entry: Dict[str, Any], bound: Dict[str, Any], factory: str,
                                 target_date_text: str, purchase_type: str, out_dir) -> str:
    wb = Workbook()
    ws = wb.active
    ws.title = "项目需求填写界面"
    ws.append(PURCHASE_ATTACHMENT_HEADERS)                       # row 1 headers
    ws.append([""] * len(PURCHASE_ATTACHMENT_HEADERS))          # row 2 instruction (importer skips)
    ctx = {
        "purchaseType": purchase_type,
        "targetDate": target_date_text,
        "purchaser": bound.get("purchaser", ""),
        "projectDefinition": entry.get("projectDefinition") or bound.get("projectDefinition", ""),
        "wbsCode": entry.get("wbsCode", ""),
        "costCenter": bound.get("costCenter", ""),
        "mrpController": entry.get("mrpController") or bound.get("mrpController", ""),
        "factory": factory,
        "deliveryAddress": bound.get("deliveryAddress", ""),
        "remark": bound.get("remark", ""),
    }
    for line in entry.get("materialLines", []):                  # row 3+ data
        ws.append(_purchase_row(line, ctx))
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    safe_wbs = (entry.get("wbsCode") or "noWBS").replace("/", "_")
    path = out_dir / f"purchase-{safe_wbs}-{stamp}.xlsx"
    wb.save(path)
    return str(path)


def _outbound_lines(entry: Dict[str, Any]):
    return [{"materialCode": l.get("materialCode", ""), "materialName": l.get("materialName", ""),
             "demandQuantity": l.get("quantity", "0"), "unit": l.get("unit", "")}
            for l in entry.get("materialLines", [])]


def _transfer_plans(entry: Dict[str, Any]):
    return [{"materialCode": l.get("materialCode", ""), "materialName": l.get("materialName", ""),
             "quantity": l.get("quantity", "0"), "unit": l.get("unit", "")}
            for l in entry.get("materialLines", [])]


def make_prepare(executor) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    def prepare_node(state: Dict[str, Any]) -> Dict[str, Any]:
        settings = get_settings()
        plan = dict(state.get("plan") or {})
        entries = plan.get("entries", []) or []
        save = bool(state.get("save", False))
        thread = state.get("thread_id", "default")
        attach_dir = settings.runtime_dir / thread / "attachments"

        prepared = []
        skipped = 0
        for raw in entries:
            entry = dict(raw)
            wf = entry.get("workflow_id")
            bound = executor.query_wbs(entry.get("wbsCode", "")) or {}
            entry["bound"] = bound
            factory = _factory(entry, bound)
            proj = entry.get("projectDefinition") or bound.get("projectDefinition", "")
            mrp = entry.get("mrpController") or bound.get("mrpController", "")
            try:
                if wf == "412":
                    cost_center = bound.get("costCenter")
                    if not cost_center:
                        entry = _skip(entry, "costCenter", "成本中心未在 WBS 主数据中维护")
                    else:
                        structured = {
                            "projectDefinition": proj, "wbsCode": entry.get("wbsCode"),
                            "demandFactoryCode": factory, "mrpController": mrp,
                            "costCenter": {"costCenterCode": cost_center, "searchName": cost_center},
                            "materialRows": _outbound_lines(entry),
                        }
                        entry["request"] = OutboundFillRequest(
                            structured=structured, save=save).model_dump(exclude_none=True)
                elif wf == "89":
                    src = executor.query_wbs(entry.get("transferOutWbs", "")) or {}
                    in_name, in_sap = bound.get("stockLocationName"), bound.get("stockLocationSapCode")
                    out_name, out_sap = src.get("stockLocationName"), src.get("stockLocationSapCode")
                    if not (in_name or in_sap) or not (out_name or out_sap):
                        entry = _skip(entry, "stockLocation", "转入/转出库存地点未在 WBS 主数据中维护")
                    else:
                        structured = {
                            "projectDefinition": proj, "wbsCode": entry.get("wbsCode"),
                            "demandFactoryCode": factory, "mrpController": mrp,
                            "materialPlans": _transfer_plans(entry),
                        }
                        entry["request"] = FillRequest(
                            structured=structured, save=save,
                            movementType=MOVEMENT_TYPE_ACQUIRE_89, factoryCode=factory,
                            transferOutWbs=entry.get("transferOutWbs"), transferInWbs=entry.get("wbsCode"),
                            transferOutStockLocationName=out_name, transferOutStockLocationSapCode=out_sap,
                            transferInStockLocationName=in_name, transferInStockLocationSapCode=in_sap,
                        ).model_dump(exclude_none=True)
                elif wf == "458":
                    offset = bound.get("demandDateOffsetDays")
                    offset = int(offset) if offset not in (None, "") else 5
                    target_text = (date.today() + timedelta(days=offset)).strftime("%Y%m%d")
                    purchase_type = entry.get("purchaseType") or DEFAULT_PURCHASE_TYPE
                    path = generate_purchase_attachment(entry, bound, factory, target_text, purchase_type, attach_dir)
                    structured = {
                        "projectDefinition": proj, "wbsCode": entry.get("wbsCode"),
                        "demandFactoryCode": factory,
                        "demandCompanyName": FACTORY_COMPANY_NAMES.get(factory),
                        "targetDemandDate": target_text, "normalizedPath": path,
                    }
                    entry["request"] = PurchaseFillRequest(
                        structured=structured, save=save, purchaseType=purchase_type).model_dump(exclude_none=True)
                elif wf == "414":
                    in_name, in_sap = bound.get("stockLocationName"), bound.get("stockLocationSapCode")
                    if not (in_name or in_sap):
                        entry = _skip(entry, "stockLocation", "入库库存地点未在 WBS 主数据中维护")
                    else:
                        lines = entry.get("materialLines", [])
                        structured = {
                            "projectDefinition": proj, "wbsCode": entry.get("wbsCode"),
                            "demandFactoryCode": factory, "mrpController": mrp,
                            "materialRows": [{"materialCode": l.get("materialCode", ""),
                                              "materialName": l.get("materialName", ""),
                                              "purchaseQuantity": l.get("quantity", "0"),
                                              "unit": l.get("unit", "")} for l in lines],
                            "quantityByMaterialCode": {l.get("materialCode", ""): l.get("quantity", "0") for l in lines},
                        }
                        entry["request"] = InboundFillRequest(
                            structured=structured, save=save,
                            stockLocationName=in_name, stockLocationSapCode=in_sap,
                        ).model_dump(exclude_none=True)
                else:
                    entry = _skip(entry, "unknownWorkflow", f"未知流程 {wf}")
            except Exception as exc:  # noqa: BLE001
                entry = _skip(entry, "prepareError", str(exc))

            if entry.get("skipped"):
                skipped += 1
            prepared.append(entry)

        plan["entries"] = prepared
        history = append_history(state, {"node": "prepare", "ok": True,
                                         "prepared": len(prepared) - skipped, "skipped": skipped})
        return {"plan": plan, "history": history}

    return prepare_node
