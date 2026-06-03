# 以下代码是 inventory_query 节点（跨系统读取步骤，与 pdm_enrich 并列）
# 对于每个物料计划，请求执行器查询 OA SAP 库存，并将结果分类为路由相关的信号。
# 这是 Stage-3b 的前置步骤，供 route_workflow 决策节点使用；
# 此节点只负责收集和分类库存信息，不决定工作流（工作流需要请求自身的 WBS 来区分“本项目库存”和“其他项目库存”，由 route_workflow 负责）。
#
# 根据用户库存驱动的路由规则，库存信号包括：
#   - 无可用的库存，提示 "no_stock"    -> 后续执行 458 采购
#   - 非限制库存、公共仓库 (SOBKZ 为空) -> 提示 "public_stock"  -> 后续执行 412 出库
#   - 专用/项目库存 (SOBKZ = "Q")       -> 提示 "project_stock" -> 后续执行 89 移库
# 剩余退货情况（-> 414 入库）由意图驱动，在此无法推断。
from __future__ import annotations  # 允许在类型注解中使用字符串引用（如类名），便于运行时兼容

from typing import Any, Callable, Dict, List  # 导入类型提示模块，用于声明参数和返回值类型

from ..executors.base import ExecutorError  # 引入执行器基本异常类，用于捕获执行错误
from ..schemas import InventoryQueryRequest  # 引入库存查询请求的数据结构（Pydantic模型）
from ._common import append_history  # 引入公共函数：向状态历史中添加记录


def _to_float(value: Any) -> float:  # 辅助函数：将任意值安全转换为浮点数
    try:
        # 尝试将值转为字符串，去除逗号、空格，若为空则转为 "0"，最后转浮点数
        return float(str(value).replace(",", "").strip() or 0)
    except (TypeError, ValueError):  # 若转换失败（如None或非数字字符串），返回0.0
        return 0.0


def _row_fields(row: Dict[str, Any]) -> Dict[str, Any]:  # 辅助函数：从一行库存记录中提取字段字典
    # organizeInventoryRow 接口将存量和指示器放在 'fields' 键下，但也要兼容平面结构（直接放在行内）
    fields = row.get("fields")
    return fields if isinstance(fields, dict) else row  # 如果 fields 是字典则返回它，否则返回整个 row


def classify_inventory(organized_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """纯函数：将某个物料的已整理库存行数据归纳为路由信号。"""
    locations: List[Dict[str, Any]] = []  # 存储每个库存位置详细信息
    total_unrestricted = 0.0  # 累加所有非限制库存数量
    has_public = False  # 标记是否存在公共仓库库存
    has_project = False  # 标记是否存在项目（专用）库存
    project_wbs: List[str] = []  # 收集所有项目库存对应的 WBS 编码

    # 遍历每一行库存数据
    for row in organized_rows or []:
        fields = _row_fields(row)  # 获取该行的关键字段
        qty = _to_float(fields.get("unrestrictedStock"))  # 获取非限制库存数量
        sobkz = str(fields.get("specialStockIndicator") or "").strip().upper()  # 获取特殊库存指示符（如 Q）
        wbs = str(row.get("wbsCode") or fields.get("wbsCode") or "").strip()  # 获取 WBS 编码
        is_project = sobkz == "Q"  # 判断是否为项目库存（SOBKZ = "Q"）
        if qty > 0:  # 仅当库存数量大于0时才统计
            total_unrestricted += qty  # 累加总数
            if is_project:
                has_project = True  # 标记存在项目库存
                if wbs:
                    project_wbs.append(wbs)  # 记录此项目库存的 WBS
            else:
                has_public = True  # 标记存在公共库存
        # 记录当前库存位置的详细信息
        locations.append({
            "factoryCode": str(row.get("factoryCode") or fields.get("factoryCode") or ""),
            "stockLocationCode": str(row.get("stockLocationCode") or fields.get("stockLocationCode") or ""),
            "stockLocationName": str(fields.get("stockLocationName") or ""),
            "wbsCode": wbs,
            "unrestrictedStock": qty,
            "specialStockIndicator": sobkz,
            "isProjectStock": is_project,
        })

    # 根据库存情况决定路由提示（routeHint）
    if total_unrestricted <= 0:
        hint = "no_stock"  # 无可用库存
    elif has_public and has_project:
        hint = "mixed"  # 同时存在公共库存和项目库存（混合情况）
    elif has_public:
        hint = "public_stock"  # 只有公共仓库库存
    else:
        hint = "project_stock"  # 只有项目库存

    # 返回归纳后的库存摘要信息
    return {
        "hasStock": total_unrestricted > 0,  # 是否有库存（总数>0）
        "totalUnrestricted": total_unrestricted,  # 总非限制库存数量
        "hasPublicStock": has_public,  # 是否存在公共库存
        "hasProjectStock": has_project,  # 是否存在项目库存
        "projectWbsCodes": sorted(set(project_wbs)),  # 去重排序后的项目 WBS 编码列表
        "locations": locations,  # 每个库存位置的详细信息
        "routeHint": hint,  # 路由提示，用于后续决策
    }


def make_inventory_query(executor) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """创建一个库存查询节点函数。参数 executor 是执行器对象（封装了 OA 接口调用）。"""
    # 定义实际的节点函数（闭包），接收状态字典，返回更新后的状态字典
    def inventory_query_node(state: Dict[str, Any]) -> Dict[str, Any]:
        business = dict(state.get("business_input") or {})  # 获取业务输入（可能为空）
        plans: List[Dict[str, Any]] = list(business.get("materialPlans", []))  # 获取物料计划列表
        per_material: Dict[str, Any] = {}  # 用于存储每个物料的库存查询结果

        # 遍历每个物料计划
        for plan in plans:
            code = plan.get("materialCode")  # 获取物料编码
            if not code:  # 如果物料编码为空，跳过此计划
                continue
            # 只根据物料编码查询所有工厂/库位的库存（不限定单个工厂），
            # 这符合真实的 oaInventoryQuery 默认行为（werksList: []）。
            # 提供完整的库存分布信息，让 route_workflow 自行根据工厂/WBS 细化决策，
            # 若在此处按需求工厂自动缩小范围，会隐藏跨工厂的库存。
            request = InventoryQueryRequest(materialCode=code)  # 构建查询请求
            try:
                resp = executor.inventory_query(request)  # 调用执行器进行库存查询
            except ExecutorError as exc:  # 若执行器抛出异常（如网络错误）
                # 在状态历史中记录失败信息
                history = append_history(state, {"node": "inventory_query", "ok": False, "error": str(exc)})
                # 返回带有错误信息的结果，终止后续处理
                return {"result": {"ok": False, "error": f"inventory query failed: {exc}"}, "history": history}

            # 检查响应是否要求登录
            if resp.get("requiresLogin"):
                history = append_history(state, {"node": "inventory_query", "ok": False, "requiresLogin": True})
                return {
                    "result": {"ok": False, "needsLogin": True,
                               "error": "OA inventory query requires login."},
                    "history": history,
                }

            organized = resp.get("organizedRows") or []  # 获取已整理的行数据（可能为空）
            summary = classify_inventory(organized)  # 调用纯函数，将行数据归纳为摘要
            # 添加原始查询返回的行数（如果 search 中提供了 rowCount 则使用，否则用实际行数）
            summary["rowCount"] = (resp.get("search") or {}).get("rowCount", len(organized))
            per_material[code] = summary  # 按物料编码保存摘要

        # 所有物料处理完毕，记录历史
        history = append_history(state, {
            "node": "inventory_query", "ok": True,
            "materials": {c: s["routeHint"] for c, s in per_material.items()},  # 仅记录每个物料的 routeHint 便于观察
        })
        # 返回更新的状态：inventory 字段包含所有物料的详细摘要，history 字段包含操作记录
        return {"inventory": per_material, "history": history}

    return inventory_query_node  # 返回闭包函数，作为节点使用