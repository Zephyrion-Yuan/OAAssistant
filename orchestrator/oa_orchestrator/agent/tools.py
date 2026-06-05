"""Read-only tools for the P1/P2 agent layer.

Every tool here is READ-ONLY or assembly — query PDM / inventory / WBS, or emit
the assembled structured demand. The agent NEVER touches the write path: the
deterministic acquire graph (which itself never submits) does the actual filling.
This is the safety guarantee that lets the front-end be a real ReAct agent.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..config import Settings


def get_tool_model(settings: Settings):
    """A tool-calling-capable chat model for the agent layer. Defaults to
    deepseek-chat (function calling), independent of DEEPSEEK_MODEL which may be a
    reasoning model that rejects forced tool_choice."""
    from langchain_deepseek import ChatDeepSeek
    if not settings.deepseek_api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is required for the agent layer.")
    return ChatDeepSeek(
        model=settings.deepseek_tool_model,
        api_key=settings.deepseek_api_key,
        api_base=settings.deepseek_base_url,
        temperature=0,
        max_retries=2,
    )


def _rows(resp: Dict[str, Any]) -> List[Dict[str, Any]]:
    return resp.get("rows") or resp.get("organizedRows") or []


# --- emit_demand args (the terminal "produce structured demand" tool) ---------
class DemandRowArg(BaseModel):
    materialCode: str = ""
    materialName: str = ""
    quantity: str = ""
    unit: str = "EA"
    wbsCode: str = ""              # may be an alias/project name; resolved downstream
    demandFactoryCode: str = ""


class EmitDemandArgs(BaseModel):
    goal: str = Field(default="acquire", description="acquire(采购/领用) | return(归还/退库)")
    demandRows: List[DemandRowArg] = Field(default_factory=list)


def make_readonly_tools(executor) -> List[StructuredTool]:
    def query_pdm(materialCode: str = "", materialName: str = "") -> str:
        """按物料编码(精确)或物料名称(模糊)查询 PDM 主数据。返回匹配物料的编码/名称/单位/规格/状态。只读。"""
        filters: Dict[str, Any] = {"maxPages": 1}
        if materialCode:
            filters["materialCode"] = materialCode
            filters["exactMaterialCode"] = True
        if materialName:
            filters["materialName"] = materialName
        if len(filters) == 1:
            return json.dumps({"error": "materialCode 或 materialName 至少给一个"}, ensure_ascii=False)
        try:
            resp = executor.query_pdm(filters)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": str(exc)}, ensure_ascii=False)
        out = [{
            "materialCode": str(r.get("materialCode")),
            "materialName": r.get("materialName"),
            "unit": r.get("unit") or (r.get("fields") or {}).get("unit"),
            "specificationModel": r.get("specificationModel"),
            "status": r.get("status") or (r.get("fields") or {}).get("状态文本"),
        } for r in _rows(resp)[:10]]
        return json.dumps(out, ensure_ascii=False)

    def query_inventory(materialCode: str, factoryCode: str = "", wbsCode: str = "") -> str:
        """查询某物料的 SAP 库存(可选按工厂/WBS过滤)。返回各库存地点的可用量、是否项目库存、所属 WBS。只读。"""
        from ..schemas import InventoryQueryRequest
        try:
            req = InventoryQueryRequest(materialCode=materialCode,
                                        factoryCode=factoryCode or None, wbsCode=wbsCode or None)
            resp = executor.inventory_query(req)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": str(exc)}, ensure_ascii=False)
        locs = []
        for r in (resp.get("organizedRows") or [])[:20]:
            f = r.get("fields") or {}
            locs.append({
                "stockLocationName": f.get("stockLocationName") or r.get("stockLocationName"),
                "wbsCode": r.get("wbsCode") or f.get("wbsCode"),
                "unrestrictedStock": f.get("unrestrictedStock"),
                "specialStockIndicator": f.get("specialStockIndicator"),  # "Q"=项目库存, 空=公共仓
            })
        return json.dumps(locs, ensure_ascii=False)

    def resolve_wbs(query: str) -> str:
        """把 WBS 别称/项目名/编码解析成真实 WBS 编码。只读。"""
        try:
            res = executor.resolve_wbs(query) or {}
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": str(exc)}, ensure_ascii=False)
        m = res.get("matched") or {}
        return json.dumps({"matched": m.get("wbsCode"), "matchType": res.get("matchType"),
                           "candidates": [c.get("wbsCode") for c in (res.get("candidates") or [])]},
                          ensure_ascii=False)

    def query_wbs(wbsCode: str) -> str:
        """查询某 WBS 的绑定信息(需求工厂/成本中心/库存地点/采购人/项目定义等)。只读。"""
        try:
            rec = executor.query_wbs(wbsCode) or {}
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": str(exc)}, ensure_ascii=False)
        keep = ("wbsCode", "alias", "projectDefinition", "demandFactoryCode", "costCenter",
                "mrpController", "stockLocationName", "stockLocationSapCode")
        return json.dumps({k: rec.get(k) for k in keep if rec.get(k)}, ensure_ascii=False)

    return [
        StructuredTool.from_function(query_pdm, name="query_pdm", description=query_pdm.__doc__),
        StructuredTool.from_function(query_inventory, name="query_inventory", description=query_inventory.__doc__),
        StructuredTool.from_function(resolve_wbs, name="resolve_wbs", description=resolve_wbs.__doc__),
        StructuredTool.from_function(query_wbs, name="query_wbs", description=query_wbs.__doc__),
    ]


def make_emit_tool() -> StructuredTool:
    """The terminal 'produce structured demand' tool. Calling it signals the agent
    has assembled the demand; the runner intercepts its args (no side effect)."""
    def emit_demand(goal: str = "acquire", demandRows: List[Dict[str, Any]] = None) -> str:
        n = len(demandRows or [])
        return json.dumps({"ok": True, "goal": goal, "rowCount": n,
                           "note": "已提交结构化需求,交由确定性填单流程(仅存草稿)。"}, ensure_ascii=False)
    return StructuredTool.from_function(
        emit_demand, name="emit_demand", args_schema=EmitDemandArgs,
        description=("当物料编码、数量、单位、WBS、需求工厂都明确后,调用本工具提交结构化需求。"
                     "goal=acquire(采购/领用) 或 return(归还/退库)。每行 = 一个物料的需求。"),
    )
