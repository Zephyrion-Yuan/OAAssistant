"""resolve_wbs node — let users reference a WBS by alias / nickname.

For each demand row whose `wbsCode` isn't already an exact registry code, ask the
executor's resolver (alias → fuzzy substring on alias/project/code). A confident
single match rewrites the row's wbsCode to the real code; ambiguous/none is left
untouched (downstream prepare then surfaces a needs-input for that WBS) and noted.
Deterministic — the registry resolver does the matching, not the LLM.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List

from ..executors.base import ExecutorError
from ._common import append_history


def make_resolve_wbs(executor) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    def resolve_wbs_node(state: Dict[str, Any]) -> Dict[str, Any]:
        business = dict(state.get("business_input") or {})
        rows: List[Dict[str, Any]] = [dict(r) for r in (business.get("demandRows") or [])]
        if not rows:
            return {}

        cache: Dict[str, Dict[str, Any]] = {}
        notes: List[str] = []
        changed = False
        for row in rows:
            raw = str(row.get("wbsCode") or "").strip()
            if not raw:
                continue
            if raw not in cache:
                try:
                    cache[raw] = executor.resolve_wbs(raw)
                except ExecutorError:
                    cache[raw] = {"matched": None, "matchType": "error", "candidates": []}
            res = cache[raw] or {}
            matched = res.get("matched")
            if matched and matched.get("wbsCode") and matched["wbsCode"] != raw:
                row["wbsCode"] = matched["wbsCode"]
                # carry registry-bound factory/project onto the row if it lacked them
                if not row.get("demandFactoryCode") and matched.get("demandFactoryCode"):
                    row["demandFactoryCode"] = matched["demandFactoryCode"]
                if not row.get("projectDefinition") and matched.get("projectDefinition"):
                    row["projectDefinition"] = matched["projectDefinition"]
                changed = True
                notes.append(f"WBS 别称『{raw}』→ {matched['wbsCode']}({res.get('matchType')})")
            elif not matched and res.get("matchType") not in (None, "code"):
                cands = ", ".join(c.get("wbsCode", "") for c in (res.get("candidates") or [])) or "无候选"
                notes.append(f"WBS『{raw}』未唯一解析({res.get('matchType')};候选:{cands})")

        history = append_history(state, {"node": "resolve_wbs", "ok": True,
                                         "rewrote": changed, "notes": notes})
        if not changed:
            return {"history": history}
        business["demandRows"] = rows
        return {"business_input": business, "history": history}

    return resolve_wbs_node
