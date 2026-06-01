"""understand node — natural-language request -> Intent (LLM, with heuristic
fallback). This is the natural-language entry point.

Only business fields (the request text + known material codes) are ever sent to
the LLM — never SSO URLs, tokens, or screenshots.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from ..config import get_settings
from ..llm import extract_structured
from ..schemas import Intent
from ._common import append_history

_NAME_RE = re.compile(r"([一-龥A-Za-z0-9]+仓)")
_SAP_RE = re.compile(r"\b([A-Z]\d{3})\b")

_SYSTEM = (
    "你是 OA 库存转储(workflow 89)的意图抽取器。"
    "从用户的自然语言请求中抽取字段：移动类型、工厂代码、转出/转入库存地点(名称或SAP编码)、"
    "WBS、按物料编码的数量覆盖。只抽取明确出现的信息，缺失留空。不要编造。"
)


def _heuristic_intent(request: str, known_codes: List[str]) -> Intent:
    names = _NAME_RE.findall(request or "")
    saps = _SAP_RE.findall(request or "")
    intent = Intent()
    if names:
        intent.transfer_out_stock_location_name = names[0]
        if len(names) > 1:
            intent.transfer_in_stock_location_name = names[1]
    if saps:
        intent.transfer_out_stock_location_sap = saps[0]
        if len(saps) > 1:
            intent.transfer_in_stock_location_sap = saps[1]
    return intent


def _merge(primary: Intent, fallback: Intent) -> Intent:
    data = primary.model_dump()
    fb = fallback.model_dump()
    for key, value in data.items():
        if value in (None, "", {}) and fb.get(key) not in (None, "", {}):
            data[key] = fb[key]
    return Intent.model_validate(data)


def understand_node(state: Dict[str, Any]) -> Dict[str, Any]:
    settings = get_settings()
    request = state.get("request", "") or ""
    answer = state.get("answer")
    if answer:
        request = f"{request}\n补充说明: {answer}"

    business = state.get("business_input") or {}
    known_codes = [p.get("materialCode") for p in business.get("materialPlans", [])]

    heuristic = _heuristic_intent(request, known_codes)
    user = (
        f"请求:\n{request}\n\n"
        f"已知物料编码: {known_codes}\n"
        f"需求工厂代码(来自Excel): {business.get('demandFactoryCode')}\n"
        f"WBS(来自Excel): {business.get('wbsCode')}"
    )
    llm_intent = extract_structured(settings, Intent, _SYSTEM, user)
    intent = _merge(llm_intent, heuristic) if llm_intent else heuristic

    history = append_history(state, {
        "node": "understand",
        "source": "llm" if llm_intent else "heuristic",
        "out_loc": intent.transfer_out_stock_location_name or intent.transfer_out_stock_location_sap,
        "in_loc": intent.transfer_in_stock_location_name or intent.transfer_in_stock_location_sap,
    })
    return {"intent": intent.model_dump(), "request": request, "answer": None, "history": history}
