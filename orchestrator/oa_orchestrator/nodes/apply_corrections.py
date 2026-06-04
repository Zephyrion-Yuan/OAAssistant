"""Apply a user's follow-up answer to the existing graph state.

The web chat treats a message after ``needs_input`` as a correction, not a new
business request. This node makes that behavior explicit and auditable: it
patches the structured BusinessInput or run-local WBS overrides, then clears
downstream state so the graph can rerun from the corrected data.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .. import store
from ..config import get_settings
from ..schemas import BusinessInput
from ..state import STATUS_NEEDS_INPUT, STATUS_RUNNING
from ._common import append_history

_MATERIAL_RE = re.compile(r"\b\d{8,12}\b")
_WBS_RE = re.compile(r"\b[A-Z]\d[-A-Z0-9.]{4,}\b", re.I)
_CODEY_RE = re.compile(r"\b[A-Z]{1,4}\d{2,5}\b", re.I)


def _pending(state: Dict[str, Any]) -> Dict[str, Any]:
    result = state.get("result") or {}
    return dict(state.get("pending_input") or result.get("input") or {})


def _clean_text_without_material_codes(text: str) -> str:
    return _MATERIAL_RE.sub(" ", text or "")


def _extract_quantity_unit(text: str) -> Tuple[Optional[str], Optional[str]]:
    rest = _clean_text_without_material_codes(text)
    qty = None
    unit = None
    m = re.search(r"(?:数量|qty|quantity|改成|调整为|设为|=|:|：)\s*([0-9]+(?:\.[0-9]+)?)", rest, re.I)
    if not m:
        m = re.search(r"\b([0-9]+(?:\.[0-9]+)?)\s*(?:个|件|块|盒|箱|EA|PCS|pcs|pc|套|kg|KG)?\b", rest)
    if m:
        qty = m.group(1)

    m = re.search(r"(?:单位|unit)\s*(?:改成|调整为|设为|为|=|:|：)?\s*([A-Za-z0-9\u4e00-\u9fff]+)", rest, re.I)
    if not m:
        m = re.search(r"\b[0-9]+(?:\.[0-9]+)?\s*([A-Za-z\u4e00-\u9fff]{1,8})\b", rest)
    if m:
        candidate = m.group(1).strip(" ，,。.;；")
        if candidate and candidate not in {"数量", "改成", "调整为", "设为"}:
            unit = candidate
    return qty, unit


def _extract_wbs(text: str) -> Optional[str]:
    m = re.search(r"(?:WBS|wbs)\s*(?:改成|调整为|设为|为|=|:|：)?\s*([A-Z0-9_.-]+)", text, re.I)
    if m:
        return m.group(1).strip()
    m = _WBS_RE.search(text or "")
    return m.group(0).strip() if m else None


def _extract_cost_center(text: str) -> Optional[str]:
    m = re.search(r"(?:成本中心|cost\s*center)\s*(?:改成|调整为|设为|为|=|:|：)?\s*([A-Z0-9_.-]+)", text, re.I)
    return m.group(1).strip() if m else None


def _extract_stock_location(text: str) -> Tuple[Optional[str], Optional[str]]:
    sap = None
    name = None
    m = re.search(r"(?:库存地点|库位|stock\s*location)\s*(?:SAP|编码|代码)?\s*(?:改成|调整为|设为|为|=|:|：)?\s*([A-Z]{1,4}\d{2,5})", text, re.I)
    if m:
        sap = m.group(1).strip().upper()
    elif "库存" in text or "库位" in text:
        m = _CODEY_RE.search(text)
        if m:
            sap = m.group(0).strip().upper()

    m = re.search(r"(?:库存地点名称|库位名称)\s*(?:改成|调整为|设为|为|=|:|：)?\s*([\u4e00-\u9fffA-Za-z0-9_-]+)", text, re.I)
    if m:
        name = m.group(1).strip()
    return name, sap


def _as_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value).strip() or "0")
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _fmt_decimal(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal(1)))
    return format(normalized, "f")


def _rebuild_material_plans(business: Dict[str, Any]) -> None:
    rows = business.get("demandRows") or []
    if not rows:
        return
    totals: Dict[str, Decimal] = {}
    names: Dict[str, str] = {}
    units: Dict[str, str] = {}
    for row in rows:
        code = str(row.get("materialCode") or "").strip()
        if not code:
            continue
        totals[code] = totals.get(code, Decimal("0")) + _as_decimal(row.get("quantity"))
        names.setdefault(code, str(row.get("materialName") or ""))
        units.setdefault(code, str(row.get("unit") or ""))
    business["materialPlans"] = [
        {
            "materialCode": code,
            "materialName": names.get(code, ""),
            "quantity": _fmt_decimal(totals[code]),
            "unit": units.get(code, ""),
        }
        for code in sorted(totals)
    ]
    business["quantityByMaterialCode"] = {code: _fmt_decimal(qty) for code, qty in sorted(totals.items())}
    if rows:
        first = rows[0]
        business["wbsCode"] = first.get("wbsCode") or business.get("wbsCode")
        business["demandFactoryCode"] = first.get("demandFactoryCode") or business.get("demandFactoryCode")
        business["projectDefinition"] = first.get("projectDefinition") or business.get("projectDefinition")
        business["mrpController"] = first.get("mrpController") or business.get("mrpController")


def _target_codes(items: Iterable[Dict[str, Any]], text: str) -> List[str]:
    item_codes = [str(item.get("materialCode") or "").strip() for item in items if item.get("materialCode")]
    mentioned = set(_MATERIAL_RE.findall(text or ""))
    targets = [code for code in item_codes if code in mentioned]
    if targets:
        return targets
    return item_codes[:1] if len(item_codes) == 1 else []


def _set_material_fields(
    business: Dict[str, Any],
    material_code: str,
    *,
    new_code: Optional[str] = None,
    quantity: Optional[str] = None,
    unit: Optional[str] = None,
) -> List[str]:
    notes: List[str] = []
    old_code = str(material_code or "").strip()
    target_code = new_code or old_code
    rows = business.get("demandRows") or []
    matching_rows = [row for row in rows if str(row.get("materialCode") or "").strip() == old_code]
    if rows and not matching_rows:
        return [f"未找到物料 {old_code} 对应的需求行"]

    if rows:
        for row in matching_rows:
            if new_code:
                row["materialCode"] = new_code
            if unit:
                row["unit"] = unit
        if quantity is not None and matching_rows:
            matching_rows[0]["quantity"] = quantity
            for extra in matching_rows[1:]:
                extra["quantity"] = "0"
            if len(matching_rows) > 1:
                notes.append(f"{old_code} 有多行需求，数量已写入第一行，其余行置为 0")
        _rebuild_material_plans(business)
        notes.append(f"{old_code} 已更新为 {target_code} {quantity or ''}{unit or ''}".strip())
        return notes

    plans = business.get("materialPlans") or []
    for plan in plans:
        if str(plan.get("materialCode") or "").strip() != old_code:
            continue
        if new_code:
            plan["materialCode"] = new_code
        if quantity is not None:
            plan["quantity"] = quantity
        if unit:
            plan["unit"] = unit
        notes.append(f"{old_code} 已更新为 {target_code} {quantity or plan.get('quantity') or ''}{unit or plan.get('unit') or ''}".strip())
        break
    business["quantityByMaterialCode"] = {
        str(plan.get("materialCode") or ""): str(plan.get("quantity") or "0") for plan in plans
    }
    return notes or [f"未找到物料 {old_code}"]


def _replace_wbs(business: Dict[str, Any], old_wbs: str, new_wbs: str) -> List[str]:
    changed = 0
    for row in business.get("demandRows") or []:
        if str(row.get("wbsCode") or "") == old_wbs:
            row["wbsCode"] = new_wbs
            changed += 1
    if business.get("wbsCode") == old_wbs:
        business["wbsCode"] = new_wbs
        changed += 1
    return [f"WBS {old_wbs or '(空)'} 已改为 {new_wbs}，影响 {changed} 处"] if changed else []


def _pending_items(pending: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = pending.get("items")
    if isinstance(items, list):
        return [dict(item) for item in items if isinstance(item, dict)]
    return [pending] if pending else []


def _apply_unit_review(business: Dict[str, Any], pending: Dict[str, Any], text: str) -> List[str]:
    items = _pending_items(pending)
    targets = _target_codes(items, text)
    use_suggestion = bool(re.search(r"按.*建议|采用建议|使用建议|确认|同意|继续", text or ""))
    qty, unit = _extract_quantity_unit(text)
    if not targets:
        return ["请明确要修正的物料编码，或在只有一条待确认物料时直接回复数量/单位"]
    notes: List[str] = []
    for item in items:
        code = str(item.get("materialCode") or "")
        if code not in targets:
            continue
        next_qty = item.get("suggestedQuantity") if use_suggestion else qty
        next_unit = item.get("suggestedUnit") if use_suggestion else unit
        if not next_qty and not next_unit:
            notes.append(f"{code} 没有识别到新的数量或单位")
            continue
        notes.extend(_set_material_fields(business, code, quantity=next_qty, unit=next_unit))
    return notes


def _apply_material_fix(business: Dict[str, Any], pending: Dict[str, Any], text: str) -> List[str]:
    bad_codes = [str(c) for c in pending.get("badCodes", []) if c]
    if not bad_codes and pending.get("materialCode"):
        bad_codes = [str(pending["materialCode"])]
    codes = _MATERIAL_RE.findall(text or "")
    pairs = re.findall(r"(\d{8,12})\s*(?:->|=>|改成|换成|替换为)\s*(\d{8,12})", text or "")
    mapping = {old: new for old, new in pairs}
    notes: List[str] = []
    for old in bad_codes:
        new = mapping.get(old)
        if not new:
            candidates = [code for code in codes if code != old]
            new = candidates[0] if candidates else (codes[0] if len(bad_codes) == 1 and codes else None)
        if not new:
            notes.append(f"{old} 没有识别到替换后的物料编码")
            continue
        notes.extend(_set_material_fields(business, old, new_code=new))
    return notes


def _apply_bound_field_fix(
    business: Dict[str, Any],
    overrides: Dict[str, Dict[str, Any]],
    pending: Dict[str, Any],
    text: str,
) -> List[str]:
    items = _pending_items(pending)
    notes: List[str] = []
    new_wbs = _extract_wbs(text)
    cost_center = _extract_cost_center(text)
    loc_name, loc_sap = _extract_stock_location(text)
    for item in items:
        wbs = str(item.get("wbsCode") or pending.get("wbsCode") or "")
        if new_wbs and wbs:
            notes.extend(_replace_wbs(business, wbs, new_wbs))
            wbs = new_wbs
        if not wbs:
            wbs = new_wbs or str(business.get("wbsCode") or "")
        if not wbs:
            continue
        patch = overrides.setdefault(wbs, {})
        if cost_center:
            patch["costCenter"] = cost_center
            notes.append(f"WBS {wbs} 本次运行补充成本中心 {cost_center}")
        if loc_name:
            patch["stockLocationName"] = loc_name
            notes.append(f"WBS {wbs} 本次运行补充库存地点名称 {loc_name}")
        if loc_sap:
            patch["stockLocationSapCode"] = loc_sap
            notes.append(f"WBS {wbs} 本次运行补充库存地点 SAP {loc_sap}")
    return notes


def _clear_for_rerun(notes: List[str]) -> Dict[str, Any]:
    return {
        "status": STATUS_RUNNING,
        "result": None,
        "diagnosis": None,
        "pending_input": None,
        "pending_question": None,
        "unit_review": None,
        "pdm": None,
        "inventory": None,
        "plan": None,
        "plan_results": None,
        "correction": None,
        "correction_summary": notes,
    }


def apply_corrections_node(state: Dict[str, Any]) -> Dict[str, Any]:
    text = str(state.get("correction") or state.get("answer") or "").strip()
    if not text:
        return {}

    pending = _pending(state)
    business = dict(state.get("business_input") or {})
    overrides = {k: dict(v) for k, v in (state.get("wbs_overrides") or {}).items()}
    kind = str(pending.get("kind") or "")

    if not pending:
        notes = ["当前线程没有待补充问题，这条输入没有作为修正应用"]
    elif not business:
        notes = ["当前线程缺少可修正的结构化需求，请重新发起需求"]
    elif kind == "unitReview":
        notes = _apply_unit_review(business, pending, text)
    elif kind == "material":
        notes = _apply_material_fix(business, pending, text)
    elif kind in {"costCenter", "stockLocation", "transferOutStockLocation", "transferInStockLocation", "draftReview", "prepareError"}:
        notes = _apply_bound_field_fix(business, overrides, pending, text)
    else:
        notes = (
            _apply_material_fix(business, pending, text)
            + _apply_unit_review(business, pending, text)
            + _apply_bound_field_fix(business, overrides, pending, text)
        )
        notes = [n for n in notes if n]

    applied = [
        note for note in notes
        if not note.startswith("请明确")
        and "没有识别" not in note
        and "缺少" not in note
        and "未找到" not in note
    ]
    history = append_history(state, {
        "node": "apply_corrections",
        "ok": bool(applied),
        "kind": kind,
        "notes": notes,
    })
    correction_history = list(state.get("correction_history") or [])
    correction_history.append({"kind": kind, "answer": text, "notes": notes, "applied": bool(applied)})

    if not applied:
        original_question = pending.get("question") or "请补充更明确的修正信息。"
        examples = {
            "unitReview": "示例: “按建议修改” 或 “4000023659 改成 4 EA”。",
            "material": "示例: “9999999999 改成 4000023659”。",
            "costCenter": "示例: “成本中心 CC-1010-01”。",
            "stockLocation": "示例: “库存地点 H001” 或 “库存地点名称 实验室仓”。",
            "draftReview": "示例: “成本中心 CC-1010-01” 或 “库存地点 H001”。",
        }
        pending = dict(pending)
        pending["question"] = (
            f"{original_question}\n\n"
            f"我仍停在当前卡壳环节，没有把这句话当成新需求。"
            f"但我没有识别到可应用的修正: {'；'.join(notes)}\n"
            f"{examples.get(kind, '请明确要修改的字段和值。')}"
        )
        return {
            "status": STATUS_NEEDS_INPUT,
            "pending_input": pending,
            "pending_question": pending["question"],
            "result": {
                "ok": False,
                "needsInput": True,
                "input": pending,
                "error": "无法从追问中提取可应用的修正: " + "；".join(notes),
            },
            "history": history,
            "correction": None,
            "correction_history": correction_history,
        }

    settings = get_settings()
    try:
        store.save_business_input(
            settings.store_path,
            str(state.get("thread_id") or ""),
            BusinessInput.model_validate(business),
            business.get("sourceFile"),
        )
    except Exception:
        # The graph can still continue with in-memory corrected state.
        pass

    updates = _clear_for_rerun(notes)
    updates.update({
        "business_input": business,
        "wbs_overrides": overrides,
        "history": history,
        "correction_history": correction_history,
    })
    return updates
