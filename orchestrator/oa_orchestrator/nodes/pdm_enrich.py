"""pdm_enrich node — cross-system step. Validate each material code against PDM
master data ("exists and 启用") and backfill name/unit/spec into the business
input. Bad codes are surfaced as a needs-input result for the diagnose node.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List

from ..executors.base import ExecutorError
from ._common import append_history


def _row_enabled(row: Dict[str, Any]) -> bool:
    status = row.get("status")
    if status in (1, "1"):
        return True
    fields = row.get("fields") or {}
    return fields.get("状态文本") == "启用"


def _match_row(resp: Dict[str, Any], code: str) -> Dict[str, Any]:
    for row in resp.get("rows", []) or []:
        if str(row.get("materialCode")) == str(code):
            return row
    # mock/organized fallback
    for row in resp.get("organizedRows", []) or []:
        if str(row.get("materialCode")) == str(code):
            return row
    return {}


def make_pdm_enrich(executor) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    def pdm_enrich_node(state: Dict[str, Any]) -> Dict[str, Any]:
        business = dict(state.get("business_input") or {})
        plans: List[Dict[str, Any]] = [dict(p) for p in business.get("materialPlans", [])]
        enriched: Dict[str, Any] = {}
        bad_codes: List[str] = []

        for plan in plans:
            code = plan.get("materialCode")
            try:
                resp = executor.query_pdm({
                    "materialCode": code,
                    "maxPages": 1,
                    "exactMaterialCode": True,
                })
            except ExecutorError as exc:
                history = append_history(state, {"node": "pdm_enrich", "ok": False, "error": str(exc)})
                return {"result": {"ok": False, "error": f"pdm query failed: {exc}"}, "history": history}

            row = _match_row(resp, code)
            total = (resp.get("search") or {}).get("total", 0)
            if not row or total == 0:
                bad_codes.append(code)
                continue
            if not _row_enabled(row):
                bad_codes.append(code)
                continue
            # backfill missing fields from PDM
            if not plan.get("materialName") and row.get("materialName"):
                plan["materialName"] = row.get("materialName")
            if not plan.get("unit") and row.get("unit"):
                plan["unit"] = row.get("unit")
            enriched[code] = {
                "materialName": row.get("materialName"),
                "unit": row.get("unit"),
                "specificationModel": row.get("specificationModel"),
                "materialGroupCode": row.get("materialGroupCode"),
            }

        if bad_codes:
            history = append_history(state, {"node": "pdm_enrich", "ok": False, "badCodes": bad_codes})
            return {
                "pdm": {"valid": False, "enriched": enriched, "badCodes": bad_codes},
                "result": {
                    "ok": False,
                    "needsInput": True,
                    "input": {
                        "kind": "material",
                        "question": "以下物料编码在 PDM 中不存在或未启用。请回复替换后的物料编码，例如“4000000000 改成 4000023659”。",
                        "badCodes": bad_codes,
                    },
                    "error": f"PDM validation failed for: {bad_codes}",
                },
                "history": history,
            }

        business["materialPlans"] = plans
        history = append_history(state, {"node": "pdm_enrich", "ok": True, "validated": len(plans)})
        return {
            "business_input": business,
            "pdm": {"valid": True, "enriched": enriched, "badCodes": []},
            "history": history,
        }

    return pdm_enrich_node
