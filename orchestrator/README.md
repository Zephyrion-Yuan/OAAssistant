# OA Orchestrator (Python LangGraph)

The "brain" layer on top of the deterministic Node/Playwright service. It turns a
natural-language request + Excel into a filled OA **workflow 89 (库存转储)** draft,
validating materials against PDM first. LLM is used **only** for understanding
(intent / slot-filling / failure diagnosis); Playwright stays the deterministic
hand and **never submits** — at most it saves a draft.

Design rationale and the full plan: `../docs` and the approved plan file.

## Layout

```
oa_orchestrator/
  config.py        env-driven settings (reads env at call time)
  schemas.py       Pydantic contracts (BusinessInput, Intent, FillRequest, Diagnosis…)
  state.py         GraphState (TypedDict) + status constants
  store.py         SQLite business_inputs table
  llm.py           ChatDeepSeek factory + structured-output helper (heuristic fallback)
  executors/       device-agnostic Executor contract
    base.py        Protocol: session_status / query_pdm / fill_stock_transfer
    http_node.py   talks to the Node service (Windows/mac differences live here)
    mock.py        in-memory fake OA/PDM for offline tests/CI
  nodes/           intake · understand · check_slot · ask · preflight ·
                   pdm_enrich · resolve_params · execute · verify · diagnose · finalize
  graph.py         StateGraph wiring + SqliteSaver checkpointer
  run.py           CLI entry
tests/smoke.py     offline end-to-end (MockExecutor, no DeepSeek/Edge/network)
```

## Setup (mac — do NOT reuse the repo `.venv`, which is a Windows venv)

```bash
python3.12 -m venv orchestrator/.venv
orchestrator/.venv/bin/pip install -r orchestrator/requirements.txt
cp orchestrator/.env.example orchestrator/.env   # set DEEPSEEK_API_KEY for real LLM
```

## Run

Offline smoke test (no external deps):
```bash
orchestrator/.venv/bin/python orchestrator/tests/smoke.py
```

Against the mock backend (no real OA):
```bash
PYTHONPATH=orchestrator orchestrator/.venv/bin/python -m oa_orchestrator.run \
  --executor mock --excel /path/req.xlsx \
  --request "从设备零件仓 D002 转到成品仓 A001" --save
```

Against the real Node backend:
```bash
# 1) start the Node service logged-in (managed Edge, manual SSO once)
MEGANT_EDGE_PROFILE_MODE=sso-handoff npm start
# 2) drive it (default is dry-run; add --save to save the draft)
PYTHONPATH=orchestrator orchestrator/.venv/bin/python -m oa_orchestrator.run \
  --excel /path/req.xlsx --request "..." --dry-run
```

CLI flags: `--request --excel --thread --resume --save --dry-run --interactive --executor`.
`--interactive` enables the slot-filling ask loop; without it, missing slots end at a
resumable `needs_input` state (re-invoke with `--resume --thread <id>`).

## Boundaries

- The graph only talks to the local Node API; it never sees cookies/tokens (Node redacts).
- Only business fields are sent to the LLM — never SSO URLs/tokens/screenshots.
- Execution saves a draft at most; submit/approve always stays manual in the browser.
