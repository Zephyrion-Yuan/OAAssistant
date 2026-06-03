"""
工作流-89 的 StateGraph 组装：节点 + 条件边 + 检查点。

拓扑结构（无人值守草案；交互式槽填充循环）：

  START → intake → preflight → understand → check_slot
                                               │ missing → ask → (interactive: understand / unattended: finalize)
                                               │ complete
                                               ▼
                                          pdm_enrich → (错误代码：diagnose) → resolve_params → execute → verify
                                                                                     ▲                        │
                                                                  diagnose ──retry───┘        ok → finalize → END
                                                                     └ terminal → finalize → END

以上是英文原拓扑图，中文解释如下：
- START 是开始节点
- intake 节点接收输入
- preflight 节点做预先检查
- understand 节点理解用户意图
- check_slot 检查槽位是否填充完整
  - 缺少信息 → ask 节点询问用户（交互模式会回到 understand，非交互模式直接 finalize）
  - 完整 → pdm_enrich 节点（获取 PDM 数据）
- pdm_enrich 之后：若返回需要输入（错误），则进入 diagnose 诊断
- 正常则进入 resolve_params 解析参数、execute 执行、verify 验证
- 验证成功 → finalize → END
- 验证失败 → diagnose 诊断，根据诊断结果决定重试（回到 execute）或终止 finalize
- diagnose 也处理其他需要登录之类的终止情况
"""

from __future__ import annotations

import sqlite3  # 导入 SQLite 数据库模块，用于持久化状态
from pathlib import Path  # 导入路径处理模块
from typing import Any, Dict, Optional  # 导入类型提示

from langgraph.graph import END, START, StateGraph  # 导入 LangGraph 核心组件
from langgraph.checkpoint.sqlite import SqliteSaver  # 导入 SQLite 检查点保存器（后续用于持久化）


from .state import (STATUS_FAILED, STATUS_NEEDS_INPUT, STATUS_NEEDS_LOGIN,
                    GraphState)  # 导入状态常量（失败、需要输入、需要登录）和状态类

from .nodes.intake import intake_node  # 导入 intake 节点函数
from .nodes.understand import understand_node  # 导入 understand 节点函数
from .nodes.personalize import personalize_node  # 导入 personalize 节点函数
from .nodes.check_slot import check_slot_node  # 导入 check_slot 节点函数
from .nodes.ask import ask_node  # 导入 ask 节点函数
from .nodes.preflight import make_preflight  # 导入 preflight 节点工厂函数
from .nodes.pdm_enrich import make_pdm_enrich  # 导入 pdm_enrich 节点工厂函数
from .nodes.resolve_params import resolve_params_node  # 导入 resolve_params 节点函数
from .nodes.execute import make_execute  # 导入 execute 节点工厂函数
from .nodes.verify import verify_node  # 导入 verify 节点函数
from .nodes.diagnose import diagnose_node  # 导入 diagnose 节点函数
from .nodes.finalize import finalize_node  # 导入 finalize 节点函数

# 以下导入用于第一阶段/第二阶段的流程路由（库存驱动模式）
from .nodes.classify_goal import classify_goal_node  # 目标分类节点
from .nodes.resolve_wbs import make_resolve_wbs  # 工作分解结构解析节点工厂
from .nodes.unit_check import unit_check_node  # 单元检查节点
from .nodes.inventory_query import make_inventory_query  # 库存查询节点工厂
from .nodes.route_workflow import route_workflow_node  # 工作流路由节点
from .nodes.prepare import make_prepare  # 准备阶段节点工厂
from .nodes.execute_plan import make_execute_plan  # 执行计划节点工厂


def _result_failed(state: Dict[str, Any]) -> bool:
    """
    内部辅助函数：判断状态中的结果是否表示失败。
    参数 state: 当前图的状态字典。
    返回 True 如果结果存在且 ok 字段为 False，否则 False。
    """
    result = state.get("result") or {}  # 获取 result 字段，若不存在则用空字典
    return bool(result) and not result.get("ok")  # 有结果且 ok 不为 True 时为失败


def _route_after_intake(state: Dict[str, Any]) -> str:
    """
    intake 节点之后的路由决策函数。
    如果状态为失败，直接进入 finalize；否则进入 preflight。
    """
    return "finalize" if state.get("status") == STATUS_FAILED else "preflight"


def _route_after_preflight(state: Dict[str, Any]) -> str:
    """
    preflight 节点之后的路由决策函数。
    如果状态需要登录（STATUS_NEEDS_LOGIN），则进入 finalize；
    如果结果失败，则进入 diagnose 诊断节点；
    否则进入 understand 理解节点。
    """
    if state.get("status") == STATUS_NEEDS_LOGIN:
        return "finalize"  # 需要登录，无法继续，直接结束
    if _result_failed(state):
        return "diagnose"  # 前置检查失败，进入诊断
    return "understand"  # 正常进入理解阶段


def _route_after_check_slot(state: Dict[str, Any]) -> str:
    """
    check_slot 节点之后的路由决策函数。
    如果 state 中存在 'missing' 字段（表示缺少信息），则进入 ask 询问节点；
    否则进入 pdm_enrich 节点（槽位已填满）。
    """
    return "ask" if state.get("missing") else "pdm_enrich"


def _route_after_ask(state: Dict[str, Any]) -> str:
    """
    ask 节点之后的路由决策函数。
    如果状态为需要输入（STATUS_NEEDS_INPUT），则进入 finalize（无人值守模式）；
    否则回到 understand 继续交互。
    """
    return "finalize" if state.get("status") == STATUS_NEEDS_INPUT else "understand"


def _route_after_pdm(state: Dict[str, Any]) -> str:
    """
    pdm_enrich 节点之后的路由决策函数。
    如果结果中 needsInput 字段为 True，则进入 diagnose 诊断；
    否则进入 resolve_params 解析参数。
    """
    result = state.get("result") or {}
    return "diagnose" if result.get("needsInput") else "resolve_params"


def _route_after_verify(state: Dict[str, Any]) -> str:
    """
    verify 节点之后的路由决策函数。
    如果结果为 ok，则进入 finalize 结束；
    否则进入 diagnose 诊断错误。
    """
    result = state.get("result") or {}
    return "finalize" if result.get("ok") else "diagnose"


def _route_after_diagnose(state: Dict[str, Any]) -> str:
    """
    diagnose 节点之后的路由决策函数。
    如果 diagnosis 中的 action 为 "retry"，则重试执行（回到 execute）；
    否则直接 finalize 结束。
    """
    diagnosis = state.get("diagnosis") or {}
    return "execute" if diagnosis.get("action") == "retry" else "finalize"


def _acquire_gate(next_node: str):
    """
    生成一个条件边函数，用于库存驱动模式中的通用门控。
    如果上游节点产生了失败结果（_result_failed 为 True），则强制路由到 finalize；
    否则正常路由到 next_node。
    参数 next_node: 正常情况下应进入的下一个节点名称。
    返回一个接受 state 返回节点名称的函数。
    """
    def gate(state: Dict[str, Any]) -> str:
        return "finalize" if _result_failed(state) else next_node
    return gate


def _route_after_unitcheck(state: Dict[str, Any]) -> str:
    """
    unit_check 节点之后的路由决策函数（库存驱动模式）。
    如果结果失败，直接 finalize；
    否则，如果 goal（目标）为 "return"（退货），则跳过库存查询，直接进入 route_workflow；
    否则进入 inventory_query 库存查询节点。
    """
    if _result_failed(state):
        return "finalize"
    return "route_workflow" if state.get("goal") == "return" else "inventory_query"


def build_acquire_graph(executor, checkpointer=None):
    """
    构建第一阶段/第二阶段库存驱动模式的图（Phase-1/2 inventory-driven router）。
    classify_goal 根据目标分为两种路径：

    采购路径 acquire: intake → preflight → classify_goal → pdm_enrich → unit_check
             → inventory_query → route_workflow(412/89/458) → prepare → execute_plan → finalize
    退货路径 return:  …→ unit_check → route_workflow(414, bucket by WBS) → prepare → execute_plan → finalize
    任何上游产生阻塞结果（失败）都会短路到 finalize（可恢复）。

    参数 executor: 执行器对象，用于执行具体业务逻辑。
    参数 checkpointer: 可选的检查点保存器，用于断点续传。
    返回编译后的图对象。
    """
    g = StateGraph(GraphState)  # 创建一个状态图，状态类型为 GraphState
    # 添加节点，每个节点绑定对应的处理函数
    g.add_node("intake", intake_node)  # 输入接收节点
    g.add_node("preflight", make_preflight(executor))  # 前置检查节点（工厂函数传入 executor）
    g.add_node("resolve_wbs", make_resolve_wbs(executor))  # 工作分解结构解析节点
    g.add_node("classify_goal", classify_goal_node)  # 目标分类节点（采购 / 退货）
    g.add_node("pdm_enrich", make_pdm_enrich(executor))  # PDM 数据丰富节点
    g.add_node("unit_check", unit_check_node)  # 单元检查节点
    g.add_node("inventory_query", make_inventory_query(executor))  # 库存查询节点
    g.add_node("route_workflow", route_workflow_node)  # 工作流路由节点
    g.add_node("prepare", make_prepare(executor))  # 准备执行节点
    g.add_node("execute_plan", make_execute_plan(executor))  # 执行计划节点
    g.add_node("finalize", finalize_node)  # 结束节点（清理、输出结果）

    # 添加边（有向边）
    g.add_edge(START, "intake")  # 开始 → intake
    # intake 之后的条件边：根据 _route_after_intake 的返回值，路由到 finalize 或 preflight
    g.add_conditional_edges("intake", _route_after_intake,
                            {"finalize": "finalize", "preflight": "preflight"})
    # preflight 之后的条件边：根据 _route_after_preflight 路由到 finalize、diagnose（实际代码中路由到 finalize 或 resolve_wbs，但宏定义中 diagnose 映射到 finalize？注意：这里原代码写的是将 diagnose 映射到 finalize，因为 preflight 返回 diagnose 时在该模式下视为阻塞结束）
    g.add_conditional_edges("preflight", _route_after_preflight,
                            {"finalize": "finalize", "diagnose": "finalize", "understand": "resolve_wbs"})
    # resolve_wbs → classify_goal（固定边）
    g.add_edge("resolve_wbs", "classify_goal")
    # classify_goal → pdm_enrich（固定边）
    g.add_edge("classify_goal", "pdm_enrich")
    # pdm_enrich 之后：通过 _acquire_gate("unit_check") 门控，若失败则 finalize，否则 unit_check
    g.add_conditional_edges("pdm_enrich", _acquire_gate("unit_check"),
                            {"finalize": "finalize", "unit_check": "unit_check"})
    # unit_check 之后：根据 _route_after_unitcheck 路由到 finalize、inventory_query 或 route_workflow（退货情况）
    g.add_conditional_edges("unit_check", _route_after_unitcheck,
                            {"finalize": "finalize", "inventory_query": "inventory_query",
                             "route_workflow": "route_workflow"})
    # inventory_query 之后：门控到 route_workflow（失败则 finalize）
    g.add_conditional_edges("inventory_query", _acquire_gate("route_workflow"),
                            {"finalize": "finalize", "route_workflow": "route_workflow"})
    # route_workflow 之后：门控到 prepare（失败则 finalize）
    g.add_conditional_edges("route_workflow", _acquire_gate("prepare"),
                            {"finalize": "finalize", "prepare": "prepare"})
    # prepare → execute_plan（固定边）
    g.add_edge("prepare", "execute_plan")
    # execute_plan → finalize（固定边）
    g.add_edge("execute_plan", "finalize")
    # finalize → END（结束）
    g.add_edge("finalize", END)

    # 编译图，返回可执行的对象，并传入 checkpointer 以支持断点续传
    return g.compile(checkpointer=checkpointer)


def build_graph(executor, checkpointer=None, mode: str = "single"):
    """
    主图构建函数。根据 mode 参数选择构建库存驱动模式（acquire）还是标准对话模式（single）。
    参数 executor: 执行器。
    参数 checkpointer: 检查点保存器。
    参数 mode: 模式，默认为 "single"（标准交互循环），若为 "acquire" 则调用 build_acquire_graph。
    返回编译后的图。
    """
    if mode == "acquire":
        return build_acquire_graph(executor, checkpointer=checkpointer)  # 库存驱动模式
    # 以下是标准 single 模式（无人值守或交互式槽填充循环）
    g = StateGraph(GraphState)
    # 添加标准模式下的所有节点
    g.add_node("intake", intake_node)  # 输入接收
    g.add_node("preflight", make_preflight(executor))  # 前置检查
    g.add_node("understand", understand_node)  # 理解用户意图
    g.add_node("personalize", personalize_node)  # 个性化处理
    g.add_node("check_slot", check_slot_node)  # 检查槽位填充状态
    g.add_node("ask", ask_node)  # 询问用户以获取缺失信息
    g.add_node("pdm_enrich", make_pdm_enrich(executor))  # PDM 数据丰富
    g.add_node("resolve_params", resolve_params_node)  # 解析执行参数
    g.add_node("execute", make_execute(executor))  # 执行操作
    g.add_node("verify", verify_node)  # 验证执行结果
    g.add_node("diagnose", diagnose_node)  # 诊断错误原因
    g.add_node("finalize", finalize_node)  # 结束并返回结果

    # 添加边
    g.add_edge(START, "intake")  # 开始 → intake
    # intake 之后的条件边
    g.add_conditional_edges("intake", _route_after_intake,
                            {"finalize": "finalize", "preflight": "preflight"})
    # preflight 之后的条件边：可能路由到 finalize、diagnose 或 understand
    g.add_conditional_edges("preflight", _route_after_preflight,
                            {"finalize": "finalize", "diagnose": "diagnose", "understand": "understand"})
    # understand → personalize（固定边）
    g.add_edge("understand", "personalize")
    # personalize → check_slot（固定边）
    g.add_edge("personalize", "check_slot")
    # check_slot 之后的条件边：缺少信息则 ask，否则 pdm_enrich
    g.add_conditional_edges("check_slot", _route_after_check_slot,
                            {"ask": "ask", "pdm_enrich": "pdm_enrich"})
    # ask 之后的条件边：需要输入（无人值守）则 finalize，否则回到 understand 继续交互
    g.add_conditional_edges("ask", _route_after_ask,
                            {"finalize": "finalize", "understand": "understand"})
    # pdm_enrich 之后的条件边：需要输入则 diagnose，否则 resolve_params
    g.add_conditional_edges("pdm_enrich", _route_after_pdm,
                            {"diagnose": "diagnose", "resolve_params": "resolve_params"})
    # resolve_params → execute（固定边）
    g.add_edge("resolve_params", "execute")
    # execute → verify（固定边）
    g.add_edge("execute", "verify")
    # verify 之后的条件边：成功则 finalize，失败则 diagnose
    g.add_conditional_edges("verify", _route_after_verify,
                            {"finalize": "finalize", "diagnose": "diagnose"})
    # diagnose 之后的条件边：诊断结果为 retry 则回到 execute 重试，否则 finalize
    g.add_conditional_edges("diagnose", _route_after_diagnose,
                            {"execute": "execute", "finalize": "finalize"})
    # finalize → END（结束）
    g.add_edge("finalize", END)

    # 编译图
    return g.compile(checkpointer=checkpointer)


def make_checkpointer(path: Optional[Path]):
    """
    创建一个 SQLite 检查点保存器（SqliteSaver）。
    如果给定路径 path，则使用文件持久化（支持断点续传）；
    如果 path 为 None，则使用内存数据库（适合测试）。
    参数 path: 可选的路径对象，用于保存检查点数据。
    返回 SqliteSaver 实例。
    """
    if path is None:
        # 使用内存数据库，不持久化
        conn = sqlite3.connect(":memory:", check_same_thread=False)
    else:
        # 创建父目录（如果不存在），然后连接到文件数据库
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=False)
    # 使用 SqliteSaver 封装连接，返回检查点保存器
    return SqliteSaver(conn)