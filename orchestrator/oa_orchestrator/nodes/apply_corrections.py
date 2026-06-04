"""Apply a user's follow-up answer to the existing graph state.

The web chat treats a message after ``needs_input`` as a correction, not a new
business request. This node makes that behavior explicit and auditable.

Interpretation is an *understanding* task, so it is delegated to the LLM (same
mandatory-LLM contract as classify_goal / unit_check — no heuristic fallback by
design): ``_interpret`` asks the model for a structured ``CorrectionPatch``, and
the deterministic appliers below (``_set_material_fields`` / ``_replace_wbs`` /
the WBS-override patch) mutate the structured BusinessInput or run-local WBS
overrides. Downstream state is then cleared so the graph reruns from the
corrected data. Offline tests register a ``set_test_responder`` stub so this
node runs without a DeepSeek key.
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .. import store
from ..config import get_settings
from ..llm import require_structured
from ..schemas import BusinessInput
from ..state import STATUS_NEEDS_INPUT, STATUS_RUNNING
from ._common import RESUME_ACTION, RESUME_MIXED, append_history

# Notes emitted by the appliers that mean "a change actually landed". Used to
# decide whether the correction was applied (continue) or not (re-ask).
_APPLIED_MARKERS = ("已更新", "已改为", "本次运行补充")


# --------------------------------------------------------------------------- #
# LLM contract: the structured patch the understanding layer must produce.
# --------------------------------------------------------------------------- #
class MaterialEdit(BaseModel):
    model_config = ConfigDict(extra="ignore")

    materialCode: str = ""        # existing code to target ("" => sole candidate)
    newMaterialCode: str = ""     # replacement code (material fix)
    quantity: str = ""            # new quantity
    unit: str = ""                # new unit
    useSuggestion: bool = False   # unitReview: accept the PDM-suggested qty/unit


class WbsEdit(BaseModel):
    model_config = ConfigDict(extra="ignore")

    wbsCode: str = ""             # target WBS ("" => sole candidate)
    newWbsCode: str = ""          # replacement WBS
    costCenter: str = ""
    stockLocationName: str = ""
    stockLocationSapCode: str = ""


class CorrectionPatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    actionable: bool = False
    materialEdits: List[MaterialEdit] = Field(default_factory=list)
    wbsEdits: List[WbsEdit] = Field(default_factory=list)
    userReportsActionDone: bool = False   # user did an external action (logged in / fixed master data) and wants to continue
    summary: str = ""


_SYSTEM = (
    "你是 OA 填单纠错解析助手。用户上一步在某个 OA 草稿环节卡住(needs_input),"
    "现在用一句自然语言来补充或修正信息。请把这句话解析成结构化补丁,只输出 JSON。\n"
    "规则:\n"
    "- 物料编码替换(如『9999999999 改成 4000023659』): "
    "materialEdits=[{materialCode:旧码, newMaterialCode:新码}]。\n"
    "- 数量/单位修改(如『数量改成5』『4000023659 改成 4 EA』): "
    "materialEdits=[{materialCode:目标码, quantity:'5', unit:'EA'}]。\n"
    "- 单位复核时用户表示采用建议(『按建议修改/采用建议/确认/同意』): "
    "materialEdits=[{materialCode:目标码, useSuggestion:true}]。\n"
    "- 成本中心(如『成本中心 CC-1010-01』): "
    "wbsEdits=[{wbsCode:目标WBS, costCenter:'CC-1010-01'}]。\n"
    "- 库存地点(如『库存地点 H001』『库存地点名称 实验室仓』): "
    "wbsEdits=[{wbsCode:目标WBS, stockLocationSapCode 或 stockLocationName}]。\n"
    "- WBS 替换(如『WBS 改成 C2-0339001.01.01』): "
    "wbsEdits=[{wbsCode:旧WBS, newWbsCode:新WBS}]。\n"
    "- 只填明确出现的字段;目标物料/WBS 只有一个候选时可以把对应编码留空。\n"
    "- 若用户表示已在外部系统完成了某项操作(如『已登录/已处理/WBS已改好/好了/弄好了』)"
    "且没有给出新的数据值, 设 userReportsActionDone=true(此时可不带任何 edits)。\n"
    "- 不要编造编码或数量。完全无法解析出任何修正且没有完成操作的表态时 actionable=false,"
    "识别到任意一处修正则 actionable=true。"
)


def _pending(state: Dict[str, Any]) -> Dict[str, Any]:
    result = state.get("result") or {}
    return dict(state.get("pending_input") or result.get("input") or {})


def _pending_items(pending: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = pending.get("items")
    if isinstance(items, list):
        return [dict(item) for item in items if isinstance(item, dict)]
    return [pending] if pending else []


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


# --------------------------------------------------------------------------- #
# Target inference + structured-patch application.
# --------------------------------------------------------------------------- #
def _material_codes(business: Dict[str, Any]) -> List[str]:
    seen: List[str] = []
    for source in (business.get("demandRows") or [], business.get("materialPlans") or []):
        for item in source:
            code = str(item.get("materialCode") or "").strip()
            if code and code not in seen:
                seen.append(code)
    return seen


def _single_material_target(business: Dict[str, Any], pending: Dict[str, Any]) -> str:
    item_codes = [str(it.get("materialCode") or "").strip() for it in _pending_items(pending)]
    item_codes = [c for c in item_codes if c]
    if len(item_codes) == 1:
        return item_codes[0]
    codes = _material_codes(business)
    return codes[0] if len(codes) == 1 else ""


def _suggestion_for(pending: Dict[str, Any], code: str) -> Dict[str, Any]:
    items = _pending_items(pending)
    for item in items:
        if str(item.get("materialCode") or "").strip() == code:
            return item
    return items[0] if len(items) == 1 else {}


def _apply_patch(
    business: Dict[str, Any],
    overrides: Dict[str, Dict[str, Any]],
    pending: Dict[str, Any],
    patch: CorrectionPatch,
) -> List[str]:
    notes: List[str] = []

    for edit in patch.materialEdits:
        code = (edit.materialCode or "").strip() or _single_material_target(business, pending)
        if not code:
            notes.append("未能确定要修改的物料编码")
            continue
        if edit.useSuggestion:
            sug = _suggestion_for(pending, code)
            qty = str(sug.get("suggestedQuantity") or "").strip() or None
            unit = str(sug.get("suggestedUnit") or "").strip() or None
            if not qty and not unit:
                notes.append(f"{code} 没有可用的建议数量/单位")
                continue
            notes.extend(_set_material_fields(business, code, quantity=qty, unit=unit))
            continue
        new_code = (edit.newMaterialCode or "").strip() or None
        qty = (edit.quantity or "").strip() or None
        unit = (edit.unit or "").strip() or None
        if not (new_code or qty or unit):
            continue
        notes.extend(_set_material_fields(business, code, new_code=new_code, quantity=qty, unit=unit))

    for edit in patch.wbsEdits:
        wbs = (edit.wbsCode or "").strip() or str(business.get("wbsCode") or "")
        new_wbs = (edit.newWbsCode or "").strip()
        if new_wbs and wbs:
            notes.extend(_replace_wbs(business, wbs, new_wbs))
            wbs = new_wbs
        if not wbs:
            wbs = new_wbs
        if not wbs:
            continue
        patch_fields = overrides.setdefault(wbs, {})
        cost_center = (edit.costCenter or "").strip()
        loc_name = (edit.stockLocationName or "").strip()
        loc_sap = (edit.stockLocationSapCode or "").strip()
        if cost_center:
            patch_fields["costCenter"] = cost_center
            notes.append(f"WBS {wbs} 本次运行补充成本中心 {cost_center}")
        if loc_name:
            patch_fields["stockLocationName"] = loc_name
            notes.append(f"WBS {wbs} 本次运行补充库存地点名称 {loc_name}")
        if loc_sap:
            patch_fields["stockLocationSapCode"] = loc_sap
            notes.append(f"WBS {wbs} 本次运行补充库存地点 SAP {loc_sap}")

    return notes


def _interpret(pending: Dict[str, Any], business: Dict[str, Any], text: str) -> CorrectionPatch:
    """Ask the LLM to turn the free-text answer into a structured CorrectionPatch.

    Grounds the model with the pending question + the current materials/WBS so it
    can resolve "the material" / "the WBS" without inventing codes. Mandatory LLM
    (require_structured): raises if no key and no test responder is configured.
    """
    settings = get_settings()
    items = _pending_items(pending)
    candidate_keys = ("materialCode", "demandQuantity", "demandUnit", "baseUnit",
                      "suggestedQuantity", "suggestedUnit", "wbsCode")
    context = {
        "kind": pending.get("kind"),
        "question": pending.get("question"),
        "badCodes": pending.get("badCodes"),
        "candidates": [
            {k: it.get(k) for k in candidate_keys if it.get(k) not in (None, "")}
            for it in items
        ],
        "currentMaterials": [
            {"materialCode": p.get("materialCode"), "quantity": p.get("quantity"), "unit": p.get("unit")}
            for p in (business.get("materialPlans") or [])
        ],
        "currentWbs": sorted({str(r.get("wbsCode")) for r in (business.get("demandRows") or []) if r.get("wbsCode")})
        or ([str(business.get("wbsCode"))] if business.get("wbsCode") else []),
    }
    user = ("待补充上下文(JSON):\n" + json.dumps(context, ensure_ascii=False)
            + "\n\n用户回复:\n" + text)
    return require_structured(settings, CorrectionPatch, _SYSTEM, user)


def _clear_for_rerun(notes: List[str]) -> Dict[str, Any]:
    # Note: saved_buckets is intentionally NOT cleared — already-saved drafts are
    # preserved across a correction rerun so execute_plan can skip them (see
    # execute_plan._bucket_key), avoiding duplicate OA drafts in save mode.
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


def _reask(
    state: Dict[str, Any],
    pending: Dict[str, Any],
    kind: str,
    notes: List[str],
    *,
    history: Optional[List[Dict[str, Any]]] = None,
    correction_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Stay parked at needs_input, appending why the answer wasn't applied."""
    original_question = pending.get("question") or "请补充更明确的修正信息。"
    examples = {
        "unitReview": "示例: “按建议修改” 或 “4000023659 改成 4 EA”。",
        "material": "示例: “9999999999 改成 4000023659”。",
        "costCenter": "示例: “成本中心 CC-1010-01”。",
        "stockLocation": "示例: “库存地点 H001” 或 “库存地点名称 实验室仓”。",
        "draftReview": "示例: “成本中心 CC-1010-01” 或 “库存地点 H001”。",
    }
    parked = dict(pending)
    parked["question"] = (
        f"{original_question}\n\n"
        f"我仍停在当前卡壳环节，没有把这句话当成新需求。"
        f"但我没有识别到可应用的修正: {'；'.join(notes)}\n"
        f"{examples.get(kind, '请明确要修改的字段和值。')}"
    )
    out: Dict[str, Any] = {
        "status": STATUS_NEEDS_INPUT,
        "pending_input": parked,
        "pending_question": parked["question"],
        "result": {
            "ok": False,
            "needsInput": True,
            "input": parked,
            "error": "无法从追问中提取可应用的修正: " + "；".join(notes),
        },
        "correction": None,
    }
    if history is not None:
        out["history"] = history
    if correction_history is not None:
        out["correction_history"] = correction_history
    return out


def apply_corrections_node(state: Dict[str, Any]) -> Dict[str, Any]:
    text = str(state.get("correction") or state.get("answer") or "").strip()
    if not text:
        return {}

    pending = _pending(state)
    business = dict(state.get("business_input") or {})
    overrides = {k: dict(v) for k, v in (state.get("wbs_overrides") or {}).items()}
    kind = str(pending.get("kind") or "")

    if not pending:
        return _reask(state, {}, kind, ["当前线程没有待补充问题，这条输入没有作为修正应用"])
    if not business:
        return _reask(state, pending, kind, ["当前线程缺少可修正的结构化需求，请重新发起需求"])

    try:
        patch = _interpret(pending, business, text)
    except Exception as exc:  # noqa: BLE001 — LLM unavailable/failed: stay parked, keep thread resumable
        return _reask(state, pending, kind,
                      [f"理解服务暂时不可用，请稍后重试或换种更明确的说法（{exc}）"])

    notes = _apply_patch(business, overrides, pending, patch) if patch.actionable else []
    applied = [note for note in notes if any(marker in note for marker in _APPLIED_MARKERS)]

    # "I've done it" — the user performed an external action (logged in / fixed
    # master data) for an action-resumable block. Trust + rerun: no data change,
    # the rerun re-validates (re-checks login/WBS/PDM) and re-guides if still stuck.
    resume_mode = str(pending.get("resumeMode") or "")
    action_done = (bool(patch.userReportsActionDone) and not applied
                   and resume_mode in {RESUME_ACTION, RESUME_MIXED})
    if action_done:
        notes = notes + ["用户确认已完成外部操作，重新校验并继续"]

    did_something = bool(applied) or action_done
    history = append_history(state, {
        "node": "apply_corrections",
        "ok": did_something,
        "kind": kind,
        "actionDone": action_done,
        "summary": patch.summary,
        "notes": notes,
    })
    correction_history = list(state.get("correction_history") or [])
    correction_history.append({"kind": kind, "answer": text, "summary": patch.summary,
                               "notes": notes, "applied": bool(applied), "actionDone": action_done})

    if not did_something:
        fallback = notes or ["没有从这句话里识别到可应用的修正"]
        return _reask(state, pending, kind, fallback,
                      history=history, correction_history=correction_history)

    if applied:
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
    updates.update({"history": history, "correction_history": correction_history})
    if applied:
        # only persist edited data; an action-done rerun keeps the existing input
        updates.update({"business_input": business, "wbs_overrides": overrides})
    return updates
