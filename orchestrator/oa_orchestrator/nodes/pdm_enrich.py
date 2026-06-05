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


def _enabled_rows(resp: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = list(resp.get("rows") or [])
    if not rows:
        rows = list(resp.get("organizedRows") or [])
    return [r for r in rows if _row_enabled(r)]


def _resolve_by_name(executor, name: str):
    """P3 adaptive lookup: a material code missed, so re-query by name (read-only,
    one bounded re-query). Returns (unique_enabled_row | None, candidate_rows)."""
    name = str(name or "").strip()
    if not name:
        return None, []
    try:
        resp = executor.query_pdm({"materialName": name, "maxPages": 1})
    except Exception:  # noqa: BLE001 — name fallback is best-effort
        return None, []
    rows = _enabled_rows(resp)
    if len(rows) == 1:
        return rows[0], []
    return None, rows[:5]


def make_pdm_enrich(executor) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    def pdm_enrich_node(state: Dict[str, Any]) -> Dict[str, Any]:
        business = dict(state.get("business_input") or {})
        plans: List[Dict[str, Any]] = [dict(p) for p in business.get("materialPlans", [])]
        demand_rows: List[Dict[str, Any]] = [dict(r) for r in business.get("demandRows", [])]
        enriched: Dict[str, Any] = {}
        bad_codes: List[str] = []
        remap: Dict[str, str] = {}            # old code -> name-resolved code (P3)
        name_candidates: Dict[str, Any] = {}  # bad code -> {name, candidates} for ambiguous name lookups
        notes: List[str] = []

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
            if (not row or total == 0) and plan.get("materialName"):
                # P3: the code missed — adaptively re-query by material name.
                alt, cands = _resolve_by_name(executor, plan.get("materialName"))
                if alt and str(alt.get("materialCode") or ""):
                    new_code = str(alt.get("materialCode"))
                    if new_code != str(code):
                        remap[str(code)] = new_code
                        notes.append(f"物料码 {code} 在 PDM 查无，按名称『{plan.get('materialName')}』唯一解析为 {new_code}")
                        plan["materialCode"] = new_code
                        code = new_code
                    row, total = alt, 1
                elif cands:
                    name_candidates[str(code)] = {
                        "materialName": plan.get("materialName"),
                        "candidates": [{"materialCode": str(c.get("materialCode")),
                                        "materialName": c.get("materialName")} for c in cands],
                    }
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
            # Flatten the whole PDM record (top-level + the `fields` bag) so the
            # unit_check LLM can reason over EVERY field — the packaging spec may
            # be missing from 规格型号 or live in a differently-named field.
            all_fields = {k: v for k, v in row.items() if k != "fields"}
            all_fields.update(row.get("fields") or {})
            enriched[code] = {
                "materialName": row.get("materialName"),
                "unit": row.get("unit"),
                "specificationModel": row.get("specificationModel"),
                "materialGroupCode": row.get("materialGroupCode"),
                "fields": all_fields,
            }

        # apply the name-resolved remap to demand rows + quantity map (P3)
        if remap:
            for r in demand_rows:
                rc = str(r.get("materialCode") or "")
                if rc in remap:
                    r["materialCode"] = remap[rc]
            qbm = business.get("quantityByMaterialCode") or {}
            if qbm:
                business["quantityByMaterialCode"] = {remap.get(k, k): v for k, v in qbm.items()}

        if bad_codes:
            cand_hint = ""
            if name_candidates:
                cand_hint = "（部分编码按名称找到多个候选，可回复其中一个编码）"
            history = append_history(state, {"node": "pdm_enrich", "ok": False,
                                             "badCodes": bad_codes, "notes": notes})
            return {
                "pdm": {"valid": False, "enriched": enriched, "badCodes": bad_codes},
                "result": {
                    "ok": False,
                    "needsInput": True,
                    "input": {
                        "kind": "material",
                        "question": ("以下物料编码在 PDM 中不存在或未启用。"
                                     f"请回复替换后的物料编码，例如“4000000000 改成 4000023659”。{cand_hint}"),
                        "badCodes": bad_codes,
                        "candidates": name_candidates,
                    },
                    "error": f"PDM validation failed for: {bad_codes}",
                },
                "history": history,
            }

        business["materialPlans"] = plans
        for row in demand_rows:
            data = enriched.get(str(row.get("materialCode") or ""))
            if not data:
                continue
            if not row.get("materialName") and data.get("materialName"):
                row["materialName"] = data.get("materialName")
            if not row.get("unit") and data.get("unit"):
                row["unit"] = data.get("unit")
        if demand_rows:
            business["demandRows"] = demand_rows
        history = append_history(state, {"node": "pdm_enrich", "ok": True,
                                         "validated": len(plans), "renamed": len(remap), "notes": notes})
        out: Dict[str, Any] = {
            "business_input": business,
            "pdm": {"valid": True, "enriched": enriched, "badCodes": []},
            "history": history,
        }
        if notes:
            out["correction_summary"] = (state.get("correction_summary") or []) + notes
        return out

    return pdm_enrich_node
