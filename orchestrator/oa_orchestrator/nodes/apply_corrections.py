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
from ..schemas import BusinessInput, Profile
from ..state import STATUS_NEEDS_INPUT, STATUS_RUNNING
from ._common import RESUME_ACTION, RESUME_MIXED, append_history
from .execute_plan import _bucket_key

# Notes emitted by the appliers that mean "a change actually landed". Used to
# decide whether the correction was applied (continue) or not (re-ask).
_APPLIED_MARKERS = ("已更新", "已改为", "本次运行补充")
_RETRY_HINTS = ("重试", "重新", "再试", "再跑", "继续", "retry", "rerun", "已处理", "处理好了", "好了")


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
    direction: str = ""            # optional side hint: in/out/转入/转出
    costCenter: str = ""
    mrpController: str = ""
    stockLocationName: str = ""
    stockLocationSapCode: str = ""


class RouteOverride(BaseModel):
    model_config = ConfigDict(extra="ignore")

    materialCode: str = ""        # "" => all materials in the routing decision
    action: str = ""              # "purchase" | "transfer"


class CorrectionPatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    actionable: bool = False
    materialEdits: List[MaterialEdit] = Field(default_factory=list)
    wbsEdits: List[WbsEdit] = Field(default_factory=list)
    routeOverrides: List[RouteOverride] = Field(default_factory=list)
    userDepartment: str = ""
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
    "- MRP控制者(如『MRP控制者 P22』『MRP P22』): "
    "wbsEdits=[{wbsCode:目标WBS, mrpController:'P22'}]。\n"
    "- 用户部门(如『我的部门是研发三组』『userDepartment=研发三组』): "
    "userDepartment='研发三组'。\n"
    "- 库存地点(如『库存地点 H001』『库存地点名称 实验室仓』『转出库存地点 D002』『C2-0225002.06.01 库存地点 D002』): "
    "wbsEdits=[{wbsCode:目标WBS, stockLocationSapCode 或 stockLocationName}]。\n"
    "- WBS 替换(如『WBS 改成 C2-0339001.01.01』): "
    "wbsEdits=[{wbsCode:旧WBS, newWbsCode:新WBS}]。\n"
    "- WBS 可以用别称或项目名称(自然语言,如『传感器项目』『适配体项目』)指代,不一定是 C2- 开头的编码。"
    "当 pending 在索要缺失/需要的 WBS(kind 含 wbs / transferInWbs / transferOutWbs)时,"
    "把用户给出的任何 WBS 指代(编码或别称/项目名)放入 wbsEdits[].newWbsCode(target wbsCode 留空);"
    "系统随后会用主数据把别称解析成真实编码。\n"
    "- 只填明确出现的字段;目标物料/WBS 只有一个候选时可以把对应编码留空。\n"
    "- 路由选择(kind=routingChoice,即在其他项目仓发现库存、需在采购与转储间选择): "
    "用户说『确认采购/就采购/走采购』→ routeOverrides=[{materialCode:'', action:'purchase'}](作用于全部待决物料); "
    "用户说『<物料编码> 改走转储/改成转储/走转储』→ routeOverrides=[{materialCode:该物料, action:'transfer'}]。\n"
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


def _wants_retry(text: str, pending: Dict[str, Any]) -> bool:
    if str(pending.get("kind") or "") != "draftReview":
        return False
    lowered = text.lower()
    return any(hint in lowered or hint in text for hint in _RETRY_HINTS)


def _seed_completed_buckets(state: Dict[str, Any]) -> Dict[str, Any]:
    completed = {str(k): dict(v) for k, v in (state.get("completed_buckets") or {}).items()}
    plan = state.get("plan") or {}
    for entry in plan.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        result = entry.get("result") or {}
        if result.get("ok"):
            completed[_bucket_key(entry)] = dict(result)
    for draft in state.get("plan_results") or []:
        if not isinstance(draft, dict) or not draft.get("ok"):
            continue
        completed.setdefault(_bucket_key(draft), {
            "ok": True,
            "requestId": draft.get("requestId"),
            "requestUrl": draft.get("requestUrl"),
            "summary": {},
            "actions": [],
        })
    return completed


def _retry_failed_drafts(state: Dict[str, Any], pending: Dict[str, Any], text: str) -> Dict[str, Any]:
    workflows = sorted({
        str(item.get("workflow_id") or item.get("workflow") or "")
        for item in _pending_items(pending)
        if item.get("workflow_id") or item.get("workflow")
    })
    label = "/".join(workflows) if workflows else "失败"
    notes = [f"用户要求重试 {label} 草稿，保留已成功草稿并重新执行失败 bucket。"]
    history = append_history(state, {
        "node": "apply_corrections",
        "ok": True,
        "kind": pending.get("kind") or "draftReview",
        "actionDone": True,
        "summary": text,
        "notes": notes,
    })
    correction_history = list(state.get("correction_history") or [])
    correction_history.append({
        "kind": pending.get("kind") or "draftReview",
        "answer": text,
        "summary": "retry failed draft",
        "notes": notes,
        "applied": False,
        "actionDone": True,
    })
    updates = _clear_for_rerun(notes)
    updates.update({
        "history": history,
        "correction_history": correction_history,
        "completed_buckets": _seed_completed_buckets(state),
    })
    return updates


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
        name = str(row.get("materialName") or "")
        unit = str(row.get("unit") or "")
        if name and not names.get(code):
            names[code] = name
        if unit and not units.get(code):
            units[code] = unit
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
def _append_unique(target: List[str], value: Any) -> None:
    text = str(value or "").strip()
    if text and text not in target:
        target.append(text)


def _missing_wbs_values(source: Dict[str, Any]) -> List[str]:
    values: List[str] = []
    missing = source.get("missingWbs")
    if isinstance(missing, list):
        for item in missing:
            if isinstance(item, dict):
                _append_unique(values, item.get("wbsCode"))
            else:
                _append_unique(values, item)
    elif missing:
        _append_unique(values, missing)
    return values


def _pending_wbs_values(pending: Dict[str, Any], *, missing_only: bool = False) -> List[str]:
    values: List[str] = []
    for item in _pending_items(pending):
        for wbs in _missing_wbs_values(item):
            _append_unique(values, wbs)
        if missing_only:
            continue
        for key in ("wbsCode", "transferInWbs", "transferOutWbs"):
            _append_unique(values, item.get(key))
    return values


def _business_wbs_values(business: Dict[str, Any]) -> List[str]:
    values: List[str] = []
    _append_unique(values, business.get("wbsCode"))
    for row in business.get("demandRows") or []:
        _append_unique(values, row.get("wbsCode"))
    return values


def _direction(edit: WbsEdit, pending: Dict[str, Any]) -> str:
    raw = f"{edit.direction} {pending.get('kind') or ''}".lower()
    if "out" in raw or "转出" in raw:
        return "out"
    if "in" in raw or "转入" in raw or "入库" in raw:
        return "in"
    return ""


def _directional_wbs(pending: Dict[str, Any], direction: str) -> List[str]:
    values: List[str] = []
    for item in _pending_items(pending):
        if direction == "out":
            _append_unique(values, item.get("transferOutWbs"))
        elif direction == "in":
            _append_unique(values, item.get("transferInWbs") or item.get("wbsCode"))
    return values


def _stock_location_targets(business: Dict[str, Any], pending: Dict[str, Any], edit: WbsEdit) -> List[str]:
    explicit = (edit.wbsCode or "").strip()
    if explicit:
        return [explicit]
    direction = _direction(edit, pending)
    if direction:
        directed = _directional_wbs(pending, direction)
        if directed:
            return directed
    missing = _pending_wbs_values(pending, missing_only=True)
    if len(missing) == 1:
        return missing
    if len(missing) > 1:
        return []
    candidates = _pending_wbs_values(pending) or _business_wbs_values(business)
    return candidates if len(candidates) == 1 else []


def _wbs_replace_target(business: Dict[str, Any], pending: Dict[str, Any], edit: WbsEdit) -> str:
    explicit = (edit.wbsCode or "").strip()
    if explicit:
        return explicit
    has_blank_row = any(not str(row.get("wbsCode") or "").strip() for row in business.get("demandRows") or [])
    if has_blank_row and pending.get("kind") in {"wbs", "transferInWbs"}:
        return ""
    candidates = (
        _pending_wbs_values(pending, missing_only=True)
        or _pending_wbs_values(pending)
        or _business_wbs_values(business)
    )
    if len(candidates) == 1:
        return candidates[0]
    if has_blank_row or pending.get("kind") in {"wbs", "transferInWbs"}:
        return ""
    return ""


def _blocked_bucket_codes(pending: Dict[str, Any]) -> set:
    """materialCodes of the pending items that are actually missing a WBS (so a
    supplied WBS fills the right bucket, not a sibling that already has one)."""
    codes: set = set()
    for item in _pending_items(pending):
        item_wbs = str(item.get("wbsCode") or "").strip()
        if item_wbs and not item.get("missingWbs"):
            continue  # this item already has a WBS — not the blank one
        for code in (item.get("materialCodes") or []):
            if code:
                codes.add(str(code))
    return codes


def _fill_blank_wbs(business: Dict[str, Any], pending: Dict[str, Any], value: str) -> int:
    """Fill blank-WBS demand rows of the blocked bucket with `value`. Scoped by
    the bucket's materialCodes when known so a sibling bucket's row isn't touched.
    Returns rows filled (0 when there were no blank rows — i.e. it's a true
    replace, handled by the caller)."""
    rows = business.get("demandRows") or []
    blanks = [r for r in rows if not str(r.get("wbsCode") or "").strip()]
    if not blanks:
        if not rows and not str(business.get("wbsCode") or "").strip():
            business["wbsCode"] = value
            return 1
        return 0
    codes = _blocked_bucket_codes(pending)
    targets = [r for r in blanks if not codes or str(r.get("materialCode") or "") in codes]
    if not targets:               # codes matched none of the blanks → fill all blanks (best effort)
        targets = blanks
    for row in targets:
        row["wbsCode"] = value
    _rebuild_material_plans(business)
    return len(targets)


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
    business: Dict[str, Any], # 主业务数据，是一个字典，存放着当前业务相关信息（如物料、WBS等）
    overrides: Dict[str, Dict[str, Any]], # 待修改的字段覆盖表，外层键是WBS编码，内层是字段名到值的映射
    pending: Dict[str, Any], # 表示“待处理”状态的数据，通常包含缺失WBS的行或待处理的需求行信息
    patch: CorrectionPatch, # 本次要应用的修正补丁对象，包含了物料编辑列表、WBS编辑列表等
) -> List[str]: # 函数返回一个字符串列表，作为操作过程中的说明或警告（“笔记”）
    notes: List[str] = [] # 初始化为空列表，用来收集所有需要记录的信息

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
        new_wbs = (edit.newWbsCode or "").strip()
        cost_center = (edit.costCenter or "").strip()
        mrp_controller = (edit.mrpController or "").strip()
        loc_name = (edit.stockLocationName or "").strip()
        loc_sap = (edit.stockLocationSapCode or "").strip()

        targets: List[str] = []
        if new_wbs:
            explicit_old = (edit.wbsCode or "").strip()
            # Prefer FILLING the blocked bucket's blank rows (the missing-WBS
            # case). Only fall back to replacing an existing WBS when the user
            # named an old WBS or there are no blank rows to fill — this avoids
            # clobbering a sibling row that already had a WBS (the repeat-ask bug).
            filled = 0 if explicit_old else _fill_blank_wbs(business, pending, new_wbs)
            if filled:
                notes.append(f"缺失的 WBS 已改为 {new_wbs}，影响 {filled} 行")
            else:
                old_wbs = _wbs_replace_target(business, pending, edit)
                replaced = _replace_wbs(business, old_wbs, new_wbs)
                notes.extend(replaced or [f"未找到需要补/改 WBS 的需求行(value={new_wbs})"])
            targets = [new_wbs]
        elif loc_name or loc_sap:
            targets = _stock_location_targets(business, pending, edit)
            if not targets:
                notes.append("存在多个可能的 WBS，请明确库存地点要维护到哪个 WBS")
                continue
        elif cost_center or mrp_controller:
            candidates = _pending_wbs_values(pending, missing_only=True) or _pending_wbs_values(pending) or _business_wbs_values(business)
            targets = candidates if len(candidates) == 1 else []
            if not targets:
                notes.append("存在多个可能的 WBS，请明确要维护到哪个 WBS")
                continue
        else:
            wbs = (edit.wbsCode or "").strip() or str(business.get("wbsCode") or "")
            if wbs:
                targets = [wbs]

        for wbs in targets:
            if not wbs:
                continue
            patch_fields = overrides.setdefault(wbs, {})
            if cost_center:
                patch_fields["costCenter"] = cost_center
                notes.append(f"WBS {wbs} 本次运行补充成本中心 {cost_center}")
            if mrp_controller:
                patch_fields["mrpController"] = mrp_controller
                notes.append(f"WBS {wbs} 本次运行补充 MRP控制者 {mrp_controller}")
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
                      "suggestedQuantity", "suggestedUnit", "wbsCode",
                      "transferInWbs", "transferOutWbs", "missingWbs",
                      "missingStockLocationSides", "mrpController")
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
        "pendingWbs": _pending_wbs_values(pending),
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
        "userDepartment": "示例: “我的部门是研发三组” 或 “userDepartment=研发三组”。",
        "costCenter": "示例: “成本中心 CC-1010-01”。",
        "mrpController": "示例: “MRP控制者 P22” 或 “C2-0225002.06.01 MRP控制者 P22”。",
        "stockLocation": "示例: “库存地点 H001”、“转出库存地点 D002” 或 “C2-0225002.06.01 库存地点 D002”。",
        "transferOutStockLocation": "示例: “转出库存地点 D002” 或 “C2-0339001.01.01 库存地点 D002”。",
        "transferInStockLocation": "示例: “转入库存地点 A001” 或 “C2-0225002.06.01 库存地点 A001”。",
        "wbs": "示例: “WBS 改成 C2-0225002.06.01”。",
        "transferInWbs": "示例: “转入 WBS 改成 C2-0225002.06.01”。",
        "transferOutWbs": "示例: “转出 WBS C2-0339001.01.01”。",
        "draftReview": "示例: “MRP控制者 P22”、“成本中心 CC-1010-01” 或 “C2-0225002.06.01 库存地点 H001”。",
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
    if _wants_retry(text, pending):
        return _retry_failed_drafts(state, pending, text)

    try:
        patch = _interpret(pending, business, text)
    except Exception as exc:  # noqa: BLE001 — LLM unavailable/failed: stay parked, keep thread resumable
        return _reask(state, pending, kind,
                      [f"理解服务暂时不可用，请稍后重试或换种更明确的说法（{exc}）"])

    notes = _apply_patch(business, overrides, pending, patch) if patch.actionable else []
    profile_updated = False
    profile = dict(state.get("profile") or {})
    department = str(patch.userDepartment or "").strip()
    if department:
        profile["department"] = department
        if not profile.get("user_id") and state.get("user_id"):
            profile["user_id"] = str(state.get("user_id") or "")
        notes.append(f"已更新用户部门 {department}")
        profile_updated = True

    # routing decision (other-project stock): purchase(458) vs transfer(89)
    routing_overrides = {str(k): str(v) for k, v in (state.get("routing_overrides") or {}).items()}
    route_changed = False
    if patch.routeOverrides:
        rec_codes = [str(c) for c in (pending.get("materialCodes") or []) if c] \
            or [str(it.get("materialCode")) for it in _pending_items(pending) if it.get("materialCode")]
        for ro in patch.routeOverrides:
            action = (ro.action or "").strip().lower()
            if action not in {"purchase", "transfer"}:
                continue
            codes = [str(ro.materialCode).strip()] if (ro.materialCode or "").strip() else rec_codes
            for code in codes:
                if not code:
                    continue
                routing_overrides[code] = action
                route_changed = True
                notes.append(f"物料 {code} 路由已改为 {'项目间转储(89)' if action == 'transfer' else '采购(458)'}")

    applied = [note for note in notes if any(marker in note for marker in _APPLIED_MARKERS)]

    # "I've done it" — the user performed an external action (logged in / fixed
    # master data) for an action-resumable block. Trust + rerun: no data change,
    # the rerun re-validates (re-checks login/WBS/PDM) and re-guides if still stuck.
    resume_mode = str(pending.get("resumeMode") or "")
    action_done = (bool(patch.userReportsActionDone) and not applied
                   and resume_mode in {RESUME_ACTION, RESUME_MIXED})
    if action_done:
        notes = notes + ["用户确认已完成外部操作，重新校验并继续"]

    did_something = bool(applied) or action_done or route_changed
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
        if profile_updated and profile.get("user_id"):
            try:
                store.save_profile(settings.store_path, Profile.model_validate(profile))
            except Exception:
                # The in-memory profile is enough for this rerun; persistence is best-effort.
                pass

    updates = _clear_for_rerun(notes)
    updates.update({"history": history, "correction_history": correction_history})
    if applied:
        # only persist edited data; an action-done rerun keeps the existing input
        updates.update({"business_input": business, "wbs_overrides": overrides})
    if route_changed:
        updates["routing_overrides"] = routing_overrides
    if profile_updated:
        updates["profile"] = profile
    return updates
