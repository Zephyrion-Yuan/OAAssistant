"""CLI entry — a thin wrapper over the frontend-agnostic run_workflow().

Examples:
  python -m oa_orchestrator.run \
      --request "按这个 Excel 做库存转储，从设备零件仓 D002 转到成品仓 A001" \
      --excel /path/req.xlsx --dry-run
  python -m oa_orchestrator.run --resume --thread st-ab12cd34
  python -m oa_orchestrator.run --executor mock --excel sample.xlsx --request "..." --save
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict

from .runner import build_runtime, run_workflow


def _summarize_delta(delta: Any) -> str:
    if not isinstance(delta, dict):
        return str(delta)
    bits = []
    for k, v in delta.items():
        if k == "history":
            continue
        bits.append(f"{k}=<{type(v).__name__}>" if isinstance(v, (dict, list)) else f"{k}={v}")
    return ", ".join(bits) or "(history)"


def _printer(chunk: Dict[str, Any]) -> None:
    for node, delta in chunk.items():
        if node == "__interrupt__":
            continue
        print(f"  • {node}: {_summarize_delta(delta)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the OA workflow-89 LangGraph orchestrator.")
    parser.add_argument("--request", default="", help="natural-language request")
    parser.add_argument("--excel", help="path to the purchase workbook")
    parser.add_argument("--thread", help="thread id (required with --resume); generated if omitted")
    parser.add_argument("--resume", action="store_true", help="resume an existing thread from its checkpoint")
    parser.add_argument("--save", action="store_true", help="save the OA draft (default is dry-run, no save)")
    parser.add_argument("--dry-run", action="store_true", help="force dry-run (fill only, never save)")
    parser.add_argument("--interactive", action="store_true", help="prompt for missing slots (ask loop)")
    parser.add_argument("--user", help="user id for personalization profile")
    parser.add_argument("--mode", choices=["single", "acquire"], default="single",
                        help="single = one workflow (default); acquire = inventory-driven WBS-fan-out router")
    parser.add_argument("--executor", help="override EXECUTOR: http-node | mock")
    args = parser.parse_args()

    if args.executor:
        os.environ["EXECUTOR"] = args.executor
    if args.resume and not args.thread:
        parser.error("--resume requires --thread")

    settings, executor, graph = build_runtime(mode=args.mode)
    common = dict(graph=graph, executor=executor, settings=settings,
                  interactive=args.interactive, on_update=_printer, mode=args.mode)
    save = bool(args.save) and not args.dry_run

    if args.resume:
        print(f"[resume] thread={args.thread} executor={executor.name} mode={args.mode}")
        res = run_workflow(thread_id=args.thread, **common)
    else:
        print(f"[start] executor={executor.name} mode={args.mode} save={save} interactive={args.interactive}")
        res = run_workflow(request=args.request, excel_path=args.excel, thread_id=args.thread,
                           save=save, user_id=args.user, **common)

    # interactive ask loop (stdin) — frontend-specific; the graph itself is UI-agnostic
    while res.get("interrupted") and args.interactive:
        answer = input(f"\n{res['pending_question']}\n> ").strip()
        res = run_workflow(thread_id=res["thread_id"], resume=answer, **common)

    summary = {k: res.get(k) for k in
               ("thread_id", "status", "ok", "requestId", "requestUrl", "pending_question", "audit_path")}
    print("\n=== result ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
