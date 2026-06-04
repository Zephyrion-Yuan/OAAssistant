"""Offline test: save-mode bucket idempotency in execute_plan.

A correction triggers a full rerun from intake. Buckets already saved to OA (with
a requestId) must NOT be re-executed — execute_plan reuses them by a
content-stable bucket key, so no duplicate OA drafts are created. A bucket whose
*content* changed gets a new key and is re-executed. Dry-run never reuses (there
is no real draft to duplicate). No network / DeepSeek / Edge. Run:
    orchestrator/.venv/bin/python orchestrator/tests/idempotency.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from oa_orchestrator.nodes.execute_plan import _bucket_key, make_execute_plan  # noqa: E402
from oa_orchestrator.schemas import ExecutionResult  # noqa: E402


class CountingExec:
    """Records every fill_outbound call so we can prove a saved bucket is skipped."""

    def __init__(self):
        self.calls = []

    def fill_outbound(self, request) -> ExecutionResult:
        wbs = (request.structured or {}).get("wbsCode")
        self.calls.append(wbs)
        return ExecutionResult(ok=True, requestId=f"MOCK-412-NEW-{wbs}",
                               requestUrl=f"url/{wbs}", summary={}, actions=[])


def _entry(wbs: str, qty: str) -> dict:
    return {
        "workflow_id": "412", "wbsCode": wbs, "transferOutWbs": None,
        "materialLines": [{"materialCode": "4000023659", "quantity": qty, "unit": "EA"}],
        "request": {"structured": {"wbsCode": wbs}, "save": True},
    }


def main() -> int:
    entry_saved = _entry("W1", "4")
    entry_new = _entry("W2", "5")
    key_saved = _bucket_key(entry_saved)
    prior = {"ok": True, "requestId": "MOCK-412-OLD-W1", "requestUrl": "url/old"}

    # 1) rerun (correction): W1 already saved -> reuse (no re-execute); W2 fresh -> execute
    exec1 = CountingExec()
    out = make_execute_plan(exec1)({
        "plan": {"entries": [entry_saved, entry_new]}, "save": True,
        "saved_buckets": {key_saved: prior}, "history": [],
    })
    drafts = {d["wbsCode"]: d for d in out["result"]["drafts"]}
    assert exec1.calls == ["W2"], exec1.calls  # W1 NOT re-executed -> no duplicate draft
    assert drafts["W1"]["requestId"] == "MOCK-412-OLD-W1" and drafts["W1"]["reused"] is True, drafts["W1"]
    assert drafts["W2"]["requestId"] == "MOCK-412-NEW-W2" and drafts["W2"]["reused"] is False, drafts["W2"]
    assert out["result"]["reusedCount"] == 1 and out["result"]["savedCount"] == 2, out["result"]
    assert key_saved in out["saved_buckets"], out["saved_buckets"]
    print("PASS rerun reuses saved bucket W1, executes only the fresh bucket W2")

    # 2) content change on W1 (qty 4 -> 6) invalidates the key -> re-executes
    exec2 = CountingExec()
    out2 = make_execute_plan(exec2)({
        "plan": {"entries": [_entry("W1", "6")]}, "save": True,
        "saved_buckets": {key_saved: prior}, "history": [],
    })
    assert exec2.calls == ["W1"], exec2.calls
    assert out2["result"]["drafts"][0]["reused"] is False, out2["result"]
    print("PASS changed bucket content invalidates reuse -> re-executes")

    # 3) dry-run never reuses (no real draft to duplicate)
    exec3 = CountingExec()
    out3 = make_execute_plan(exec3)({
        "plan": {"entries": [entry_saved]}, "save": False,
        "saved_buckets": {key_saved: prior}, "history": [],
    })
    assert exec3.calls == ["W1"], exec3.calls
    assert out3["result"]["drafts"][0]["reused"] is False, out3["result"]
    print("PASS dry-run ignores saved_buckets (always executes)")

    print("\nALL IDEMPOTENCY OFFLINE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
