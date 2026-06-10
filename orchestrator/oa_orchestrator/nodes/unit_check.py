"""unit_check node — LLM judges whether the demand unit/quantity is sensible vs
the material's PDM base unit + packaging spec, and flags likely unit misuse.

PDM gives a base unit + a free-text 规格型号/封装 but no machine-readable
conversion factor — so this is exactly an understanding task for the LLM. Because
a wrong unit silently inflates purchase/outbound quantity (e.g. 50 盒 ordered as
50 箱), a flagged mismatch stops for human confirmation rather than auto-converting.

The LLM is a required dependency (a DeepSeek key must be configured) — there is
no heuristic fallback. To stay cheap, the LLM is only consulted when the demand
unit differs from the PDM base unit; identical units pass without a call.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from ..config import get_settings
from ..llm import require_structured
from ._common import append_history

_SYSTEM = (
    "你是物料单位换算审核助手。给定物料的需求单位/数量与 PDM 基本计量单位、规格型号/包装描述,"
    "判断需求单位是否合理、是否存在单位误用需要换算。只输出 JSON。"
)


class UnitJudgment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    consistent: bool = False           # True: 单位等价/无需换算
    suggestedUnit: Optional[str] = None
    suggestedQuantity: Optional[str] = None
    reason: str = ""


def _llm_judge(settings, item: Dict[str, Any]) -> UnitJudgment:
    import json
    # Hand the model the FULL PDM record (all fields) — the packaging spec may be
    # absent from 规格型号 or live in a differently-named field; let the LLM find it.
    pdm_fields = item.get("pdmFields") or {}
    user = (
        f"物料编码: {item.get('materialCode')}\n物料名称: {item.get('materialName')}\n"
        f"需求单位: {item.get('demandUnit')}\n需求数量: {item.get('demandQuantity')}\n"
        f"PDM基本计量单位: {item.get('baseUnit')}\n规格型号/包装: {item.get('specificationModel')}\n"
        f"PDM 全部字段(JSON,包装规格可能在其中任意字段或缺失):\n"
        f"{json.dumps(pdm_fields, ensure_ascii=False)}\n"
        "请综合以上所有字段判断需求单位是否与基本计量单位等价(consistent),"
        "若不等价给出建议单位与换算后数量。"
    )
    return require_structured(settings, UnitJudgment, _SYSTEM, user)


def unit_check_node(state: Dict[str, Any]) -> Dict[str, Any]:
    settings = get_settings()
    business = state.get("business_input") or {}
    enriched = (state.get("pdm") or {}).get("enriched") or {}

    # demand quantity per material (aggregate); prefer demandRows-driven plans
    plans = business.get("materialPlans", []) or []
    reviews: List[Dict[str, Any]] = []
    for plan in plans:
        code = plan.get("materialCode")
        demand_unit = str(plan.get("unit") or "").strip()
        base = enriched.get(code) or {}
        base_unit = str(base.get("unit") or "").strip()
        if not demand_unit or not base_unit:
            continue
        if demand_unit.lower() == base_unit.lower():
            continue
        item = {
            "materialCode": code,
            "materialName": base.get("materialName") or plan.get("materialName"),
            "demandUnit": demand_unit,
            "demandQuantity": plan.get("quantity"),
            "baseUnit": base_unit,
            "specificationModel": base.get("specificationModel"),
            "pdmFields": base.get("fields") or {},
        }
        judgment = _llm_judge(settings, item)
        item["suggestedUnit"] = judgment.suggestedUnit
        item["suggestedQuantity"] = judgment.suggestedQuantity
        if judgment.consistent:
            item["reason"] = (
                judgment.reason
                or "需求单位与 PDM 基本计量单位不同，请人工确认是否等价。"
            )
            item["llmConsistent"] = True
        else:
            item["reason"] = judgment.reason
        reviews.append(item)

    if not reviews:
        history = append_history(state, {"node": "unit_check", "ok": True, "reviews": 0})
        return {"history": history}

    history = append_history(state, {"node": "unit_check", "ok": False, "reviews": len(reviews)})
    return {
        "unit_review": reviews,
        "result": {
            "ok": False,
            "needsInput": True,
            "input": {
                "kind": "unitReview",
                "question": "以下物料的需求单位/数量与 PDM 基本计量单位不一致，请确认后继续。可以回复“按建议修改”，或直接说“物料编码 改成 数量 单位”。",
                "items": reviews,
            },
            "error": f"Unit review required for {len(reviews)} material(s).",
        },
        "history": history,
    }
