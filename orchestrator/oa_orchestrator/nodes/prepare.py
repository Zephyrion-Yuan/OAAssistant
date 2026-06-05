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
from typing import Any, Callable, Dict, List

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
# 458 attachment 需求类型: "02" = 采购申请+预留.
DEFAULT_PURCHASE_DEMAND_TYPE = "02"
# 458 OA main form defaults.
DEFAULT_OA_PURCHASE_TYPE = "项目物资采购申请"
DEFAULT_OA_PROJECT_TYPE = "是"
# Acquire-mode 89 always moves another project's special stock into the demand
# project's special stock, so the movement type is fixed.
MOVEMENT_TYPE_ACQUIRE_89 = "项目库存转储至项目库存"


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _material_codes(entry: Dict[str, Any]) -> List[str]:
    codes: List[str] = []
    for line in entry.get("materialLines", []) or []:
        code = _clean(line.get("materialCode"))
        if code and code not in codes:
            codes.append(code)
    return codes


def _material_text(entry: Dict[str, Any]) -> str:
    codes = _material_codes(entry)
    return "、".join(codes) if codes else "未识别到物料"


def _project_from_wbs(wbs_code: str) -> str:
    code = _clean(wbs_code)
    return code.split(".")[0] if code else ""


def _skip(entry: Dict[str, Any], kind: str, reason: str,
          extra: Dict[str, Any] | None = None) -> Dict[str, Any]:
    entry["skipped"] = True
    entry["skipReason"] = reason
    pending = {
        "kind": kind,
        "question": reason,
        "wbsCode": entry.get("wbsCode"),
        "workflow": entry.get("workflow_id"),
        "workflow_id": entry.get("workflow_id"),
        "materialCodes": _material_codes(entry),
        "preserveQuestion": True,
    }
    if extra:
        pending.update(extra)
    entry["needsInput"] = pending
    entry["request"] = None
    return entry


def _missing_wbs_question(entry: Dict[str, Any], label: str) -> str:
    return (
        f"流程 {entry.get('workflow_id')} 缺少 {label}，当前无法继续填单。"
        f"涉及物料：{_material_text(entry)}。请在需求行中补充 WBS 编码，"
        "或直接回复“WBS 改成 C2-0225002.06.01”。"
    )


def _stock_location_question(entry: Dict[str, Any], missing: List[Dict[str, str]]) -> str:
    parts = []
    for item in missing:
        parts.append(f"{item['label']} {item['wbsCode']} 缺默认库存地点")
    return (
        f"流程 89 项目库存转储至项目库存卡住：{'；'.join(parts)}。"
        f"涉及物料：{_material_text(entry)}。请在配置 -> WBS 管理中维护对应 WBS 的"
        "默认库存地点名称或 SAP 编码（例如 设备零件仓/D002），"
        "也可以直接回复“C2-0225002.06.01 库存地点 D002”。"
    )


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
                                 target_date_text: str, purchase_type: str, out_dir,
                                 material_defaults: Dict[str, Dict[str, Any]] | None = None) -> str:
    wb = Workbook()
    ws = wb.active
    ws.title = "项目需求填写界面"
    ws.append(PURCHASE_ATTACHMENT_HEADERS)                       # row 1 headers
    ws.append([""] * len(PURCHASE_ATTACHMENT_HEADERS))          # row 2 instruction (importer skips)
    ctx = {
        "purchaseType": purchase_type,
        "targetDate": target_date_text,
        "purchaser": bound.get("purchaser", ""),
        "projectDefinition": (
            entry.get("projectDefinition")
            or bound.get("projectDefinition")
            or _project_from_wbs(entry.get("wbsCode", ""))
        ),
        "wbsCode": entry.get("wbsCode", ""),
        "costCenter": bound.get("costCenter", ""),
        "mrpController": entry.get("mrpController") or bound.get("mrpController", ""),
        "factory": factory,
        "deliveryAddress": bound.get("deliveryAddress", ""),
        "remark": bound.get("remark", ""),
    }
    for line in entry.get("materialLines", []):                  # row 3+ data
        row = dict(line)
        defaults = (material_defaults or {}).get(str(row.get("materialCode") or ""), {})
        if not row.get("materialName") and defaults.get("materialName"):
            row["materialName"] = defaults.get("materialName")
        if not row.get("unit") and defaults.get("unit"):
            row["unit"] = defaults.get("unit")
        ws.append(_purchase_row(row, ctx))
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
        wbs_overrides = state.get("wbs_overrides") or {}
        profile = state.get("profile") or {}
        user_department = _clean(
            (profile.get("department") if isinstance(profile, dict) else "")
            or state.get("user_department")
        )
        material_defaults = {
            str(plan.get("materialCode") or ""): dict(plan)
            for plan in (state.get("business_input") or {}).get("materialPlans", [])
            if plan.get("materialCode")
        }

        prepared = []
        skipped = 0
        for raw in entries:
            entry = dict(raw)
            wf = entry.get("workflow_id")
            wbs_code = _clean(entry.get("wbsCode"))
            transfer_out_wbs = _clean(entry.get("transferOutWbs"))
            bound = executor.query_wbs(wbs_code) or {}
            bound = {**bound, **dict(wbs_overrides.get(wbs_code, {}))}
            entry["bound"] = bound
            factory = _factory(entry, bound)
            proj = entry.get("projectDefinition") or bound.get("projectDefinition") or _project_from_wbs(wbs_code)
            mrp = entry.get("mrpController") or bound.get("mrpController", "")
            try:
                if wf == "412":
                    if not wbs_code:
                        entry = _skip(entry, "wbs", _missing_wbs_question(entry, "出库 WBS 编码"),
                                      {"missingWbs": [""]})
                    else:
                        cost_center = bound.get("costCenter")
                        if not cost_center:
                            entry = _skip(entry, "costCenter", f"WBS {wbs_code} 未维护成本中心")
                        elif not user_department:
                            entry = _skip(
                                entry,
                                "userDepartment",
                                (
                                    "流程 412 物资出库需要用户部门用于成本中心匹配。"
                                    f"当前 WBS：{wbs_code}；涉及物料：{_material_text(entry)}。"
                                    "请回复“我的部门是研发三组”或在配置 -> 用户设置中维护部门。"
                                ),
                                {"userDepartment": ""},
                            )
                        else:
                            warehouse_type = entry.get("warehouseType") or bound.get("warehouseType") or None
                            structured = {
                                "projectDefinition": proj, "wbsCode": entry.get("wbsCode"),
                                "demandFactoryCode": factory, "mrpController": mrp,
                                "costCenter": {"costCenterCode": cost_center, "searchName": cost_center},
                                "materialRows": _outbound_lines(entry),
                            }
                            entry["request"] = OutboundFillRequest(
                                structured=structured, save=save,
                                userDepartment=user_department,
                                warehouseType=warehouse_type).model_dump(exclude_none=True)
                elif wf == "89":
                    if not wbs_code:
                        entry = _skip(
                            entry,
                            "transferInWbs",
                            (
                                "流程 89 项目库存转储缺少转入/需求 WBS，无法填写转入 WBS 和转入库存地点。"
                                f"当前转出 WBS: {transfer_out_wbs or '未提供'}；涉及物料：{_material_text(entry)}。"
                                "请在需求行中补充转入/需求 WBS，或直接回复“WBS 改成 C2-0225002.06.01”。"
                            ),
                            {
                                "transferInWbs": "",
                                "transferOutWbs": transfer_out_wbs,
                                "missingWbs": [""],
                            },
                        )
                    elif entry.get("sourceKind") == "public":
                        # 公共仓 → 项目仓 转储: source is a public warehouse location
                        # (no WBS, carried on the entry by route_workflow); transfer-in
                        # location comes from the demand WBS registry.
                        in_name, in_sap = bound.get("stockLocationName"), bound.get("stockLocationSapCode")
                        out_name = entry.get("transferOutStockLocationName")
                        out_sap = entry.get("transferOutStockLocationSapCode")
                        if not (in_name or in_sap):
                            entry = _skip(
                                entry, "stockLocation",
                                (f"流程 89 公共仓→项目仓转储卡住：转入/需求 WBS {wbs_code} 未维护默认库存地点。"
                                 f"涉及物料：{_material_text(entry)}。请在配置 -> WBS 管理中维护该 WBS 的"
                                 "默认库存地点名称或 SAP 编码，或直接回复“"
                                 f"{wbs_code} 库存地点 D002”。"),
                                {"transferInWbs": wbs_code, "missingStockLocationSides": ["in"], "missingWbs": [wbs_code]},
                            )
                        elif not (out_name or out_sap):
                            entry = _skip(
                                entry, "stockLocation",
                                (f"流程 89 公共仓→项目仓转储缺少公共仓来源库存地点。涉及物料：{_material_text(entry)}。"),
                                {"transferInWbs": wbs_code, "missingStockLocationSides": ["out"]},
                            )
                        else:
                            structured = {
                                "projectDefinition": proj, "wbsCode": entry.get("wbsCode"),
                                "demandFactoryCode": factory, "mrpController": mrp,
                                "materialPlans": _transfer_plans(entry),
                            }
                            entry["request"] = FillRequest(
                                structured=structured, save=save,
                                movementType=entry.get("movementType") or "普通库存转储至项目库存",
                                factoryCode=factory, transferInWbs=wbs_code,
                                transferOutStockLocationName=out_name, transferOutStockLocationSapCode=out_sap,
                                transferInStockLocationName=in_name, transferInStockLocationSapCode=in_sap,
                            ).model_dump(exclude_none=True)
                    elif not transfer_out_wbs:
                        entry = _skip(
                            entry,
                            "transferOutWbs",
                            (
                                f"流程 89 项目库存转储缺少转出 WBS，当前转入/需求 WBS: {wbs_code}。"
                                f"涉及物料：{_material_text(entry)}。请提供库存来源 WBS。"
                            ),
                            {
                                "transferInWbs": wbs_code,
                                "transferOutWbs": "",
                            },
                        )
                    else:
                        src = executor.query_wbs(transfer_out_wbs) or {}
                        src = {**src, **dict(wbs_overrides.get(transfer_out_wbs, {}))}
                        in_name, in_sap = bound.get("stockLocationName"), bound.get("stockLocationSapCode")
                        out_name, out_sap = src.get("stockLocationName"), src.get("stockLocationSapCode")
                        missing_locations: List[Dict[str, str]] = []
                        if not (out_name or out_sap):
                            missing_locations.append({
                                "side": "out",
                                "label": "转出 WBS",
                                "wbsCode": transfer_out_wbs,
                            })
                        if not (in_name or in_sap):
                            missing_locations.append({
                                "side": "in",
                                "label": "转入/需求 WBS",
                                "wbsCode": wbs_code,
                            })
                        if missing_locations:
                            entry = _skip(
                                entry,
                                "stockLocation",
                                _stock_location_question(entry, missing_locations),
                                {
                                    "transferInWbs": wbs_code,
                                    "transferOutWbs": transfer_out_wbs,
                                    "missingStockLocationSides": [m["side"] for m in missing_locations],
                                    "missingWbs": [m["wbsCode"] for m in missing_locations],
                                },
                            )
                        else:
                            structured = {
                                "projectDefinition": proj, "wbsCode": entry.get("wbsCode"),
                                "demandFactoryCode": factory, "mrpController": mrp,
                                "materialPlans": _transfer_plans(entry),
                            }
                            entry["request"] = FillRequest(
                                structured=structured, save=save,
                                movementType=MOVEMENT_TYPE_ACQUIRE_89, factoryCode=factory,
                                transferOutWbs=transfer_out_wbs, transferInWbs=wbs_code,
                                transferOutStockLocationName=out_name, transferOutStockLocationSapCode=out_sap,
                                transferInStockLocationName=in_name, transferInStockLocationSapCode=in_sap,
                            ).model_dump(exclude_none=True)
                elif wf == "458":
                    if not wbs_code:
                        entry = _skip(entry, "wbs", _missing_wbs_question(entry, "采购申请 WBS 编码"),
                                      {"missingWbs": [""]})
                    else:
                        offset = bound.get("demandDateOffsetDays")
                        offset = int(offset) if offset not in (None, "") else 5
                        target_text = (date.today() + timedelta(days=offset)).strftime("%Y%m%d")
                        demand_type = (
                            entry.get("purchaseDemandType")
                            or bound.get("purchaseDemandType")
                            or DEFAULT_PURCHASE_DEMAND_TYPE
                        )
                        oa_purchase_type = (
                            entry.get("purchaseType")
                            or bound.get("purchaseType")
                            or DEFAULT_OA_PURCHASE_TYPE
                        )
                        project_type = (
                            entry.get("projectType")
                            or bound.get("projectType")
                            or DEFAULT_OA_PROJECT_TYPE
                        )
                        path = generate_purchase_attachment(
                            entry, bound, factory, target_text, demand_type, attach_dir, material_defaults
                        )
                        structured = {
                            "projectDefinition": proj, "wbsCode": entry.get("wbsCode"),
                            "demandFactoryCode": factory,
                            "demandCompanyName": FACTORY_COMPANY_NAMES.get(factory),
                            "targetDemandDate": target_text, "normalizedPath": path,
                        }
                        entry["request"] = PurchaseFillRequest(
                            structured=structured, save=save,
                            purchaseType=oa_purchase_type, projectType=project_type,
                        ).model_dump(exclude_none=True)
                elif wf == "414":
                    if not wbs_code:
                        entry = _skip(entry, "wbs", _missing_wbs_question(entry, "入库 WBS 编码"),
                                      {"missingWbs": [""]})
                    else:
                        in_name, in_sap = bound.get("stockLocationName"), bound.get("stockLocationSapCode")
                        if not (in_name or in_sap):
                            entry = _skip(
                                entry,
                                "stockLocation",
                                (
                                    f"流程 414 项目退料入库卡住：WBS {wbs_code} 未维护默认入库库存地点。"
                                    f"涉及物料：{_material_text(entry)}。请在配置 -> WBS 管理中维护该 WBS 的"
                                    "默认库存地点名称或 SAP 编码，或直接回复“库存地点 D002”。"
                                ),
                                {
                                    "transferInWbs": wbs_code,
                                    "missingStockLocationSides": ["in"],
                                    "missingWbs": [wbs_code],
                                },
                            )
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
