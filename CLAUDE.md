# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A locally-run Edge/Playwright automation service for MEGA's OA (workflow forms) and PDM (master-data) web systems. **The program contains no AI/LLM inference and no agent graph** — every action is decided by explicit commands, JSON input, whitelisted domains, deterministic DOM scans, and config rules. Treat "no model in the loop" as a hard architectural constraint, not a default.

Pure Node.js ESM (`"type": "module"`, Node ≥ 20). Runtime deps: `playwright`, `commander`, `zod`, `pino`, `dotenv`. Excel parsing is delegated to Python helpers. Despite `vitest`/`typescript` in devDeps, there are **no `.ts` sources and no test files** — `npm run check` (below) is the only verification gate.

## Commands

```bash
npm run check          # THE verification step: node --check syntax-checks every src/ + scripts/ file. Run this after edits.
npm start              # start HTTP server on http://127.0.0.1:8787 (control panel UI + /api/*)
npm run dev            # same with --watch

# Python venv (Excel helpers live in scripts/*.py)
npm run venv:setup     # create .venv + npm install
npm run venv:start     # start server through the venv (so `python` resolves the helpers)
npm run sso:start      # start in sso-handoff mode + auto-launch managed Edge (Windows DingTalk flow)

# Fixed business tasks (each --help lists options)
npm run pdm:query -- --material-code 4000059295 --max-pages 2
npm run pdm:query -- --material-name "传感器" --max-pages 5
npm run oa:purchase-from-excel -- --file <xlsx>        # OA workflow 458
npm run oa:outbound-from-excel -- --file <xlsx>        # OA workflow 412
npm run oa:inbound-from-excel  -- --file <xlsx>        # OA workflow 414
npm run oa:stock-transfer-from-excel -- --file <xlsx>  # OA workflow 89

# Page exploration (generic framework — see below)
npm run explore:page -- --name "..." --page-id ... --url "https://oa.megarobo.info/..." --full
npm run pdm:explore -- --url "https://pdm.megarobo.info/masterdata/master-data-material" --full
```

There is no single-test runner because there are no tests. To exercise one OA/PDM flow, run its `npm run oa:*`/`pdm:*` script against a logged-in managed Edge.

> Note on platform: README/GUIDE.md document the **Windows** workflow and use `npm.cmd`, PowerShell, and a compiled SSO relay `.exe`. Edge process management (`profileCache.js`, `close-edge.js`), the SSO relay, and `sso:install-relay` are **Windows-only** and no-op or warn on macOS/Linux. The core server, exploration, and fill logic run cross-platform (the Edge user-data path is resolved per-OS in `edgeSession.js`/`profileCache.js`).

## Architecture

### Privacy-first post-login model (the central design rule)
The user logs into company SSO **manually** inside a Playwright-controlled Edge profile. Automation only ever operates on already-authenticated, stable business URLs. The code must **never**: intercept/replay DingTalk SSO links, import/export cookies, read tokens/SAML/OAuth-code/password/MFA, or auto-submit/approve/pay/delete/publish/send. See `AGENTS.md` and `docs/AUTOMATION_RULES.md` — these are binding constraints, enforced in code (see Safety layer).

### Request flow
`src/server.js` is a zero-framework `http` server (default `127.0.0.1:8787`). It serves the `public/` control-panel SPA, exposes `/api/*` (routed by a long if-chain in `handleApi`), and serves exploration artifacts under `/runtime/*`. Key endpoints: `/api/oa/scan`, `/api/oa/fill`, `/api/pdm/query`, `/api/explore/page`, `/api/sso/open`, and `/api/*/login/*` + `/api/*/profile/*`.

### Two browser sessions (singletons)
- `src/browser/edgeSession.js` → `edgeSession`: the live managed Edge. Profile behavior is driven by `MEGANT_EDGE_PROFILE_MODE` (`isolated` | `current` | `current-profile-dir` | `sso-handoff` | `custom`). Launches via `chromium.launchPersistentContext(channel: 'msedge', headless: false)`.
- `src/browser/cachedProfileSession.js` → `cachedProfileSession`: opens a **copy** of the real Edge profile cached under `.runtime/edge-profile-cache/User Data` (created by `src/profile/profileCache.js`). Used mainly for PDM queries so a normal-Edge SSO session can be reused without keeping that browser open.

Both go through `src/browser/browserLaunch.js` for channel/args resolution.

### Three capability layers
1. **`src/automation/`** — fixed OA/PDM logic.
   - `domScanner.js`: deterministic in-page DOM scan (`scanDom` → fields/buttons/tables with generated CSS selectors, required/disabled/readonly detection across Ant Design / e-cology / Element UI markup), `detectLoginPage`, `waitForSettledPage`.
   - `oaAutomation.js`: generic scan + **fuzzy field matching** (`chooseField` scores label/name/placeholder/id/selector) + value setting; only clicks draft/save buttons, never submit.
   - `pdmAutomation.js`: PDM material query — fills filter inputs, clicks 搜索, and reads results **from the captured XHR response** (`/admin-api/master/data/material/page`) rather than scraping the table, with pagination + de-dup.
   - `apiRecorder.js`, `loginDiagnostics.js`, `sessionDiagnostics.js`.
2. **`src/explorer/`** — the generic, reusable page-exploration framework (`POST /api/explore/page` / `npm run explore:page`). `pageExplorer.js` orchestrates: `domainGuard` (HTTPS + host whitelist) → `surfaceScanner` (fields/buttons/tables/field-deltas) → `actionRunner` (safe interaction protocol) → `safeNetworkRecorder` (XHR/fetch capture with body summarization + list-API classification) → `artifacts` (writes `<id>.json` + `<id>.md` to `.runtime/exploration/`). This is how new pages are reverse-engineered before being hardened into a fixed task.
3. **`src/security/redaction.js`** — `redactUrl`/`redactText`/`sensitiveNamePattern`. Applied to every URL/body/log that leaves the system.

### Safety layer (enforced, not advisory)
- `explorer/domainGuard.js`: exploration targets must be HTTPS and on a whitelisted host (derived from `config/pages.json` + `MEGANT_EXPLORE_ALLOWED_HOSTS`). `server.js` has its own SSO host whitelist (`MEGANT_SSO_ALLOWED_HOSTS`).
- `explorer/actionRunner.js`: refuses to `click`/`clickText` any control matching `提交|批准|审批|同意|付款|支付|删除|作废|发布|发送|submit|approve|pay|delete|publish|send`, and refuses to `fill`/`select` fields matching the sensitive-name pattern. `oaAutomation.clickDraftButton` similarly excludes 提交/submit/发送.

### Two patterns for OA form filling (important distinction)
- **Generic** (`/api/oa/fill` → `oaAutomation.fillOaPage`): scans the page, fuzzy-matches your `values` keys to fields, fills, optionally clicks a draft button. Good for exploration / simple forms.
- **Hardened per-workflow scripts** (`scripts/oa-*-from-excel.js`): each targets one workflow with **hardcoded CSS selectors + modal/browser-field interaction sequences**, parameterized by a `config/oa-workflow-*.json` selector+mapping file (412/414/89; 458 has selectors inline). These handle the real complexity — WBS/cost-center "browser field" modals, dropdown option text, attachment upload, and `保存` (save draft). They emit a timestamped JSON report (+ failure screenshot/surface) under `.runtime/<task>-requests/`.

### Excel-driven scripts (Node ↔ Python boundary)
`scripts/oa-*-from-excel.js` (Node, Playwright) shell out via `execFileSync(python, ...)` to a sibling `scripts/*_excel.py` helper that parses/normalizes the spreadsheet and prints JSON. Python is resolved from `$PYTHON` or `python` (hence run through the venv). The Node side then drives the form. When changing input fields, both the `.py` helper output and the `.js` consumer must stay in sync.

### Config & runtime
- `config/pages.json`: canonical OA workflow URLs + PDM page URL. `resolveOaPage`/`resolvePdmPage` in `config.js` are the only resolvers.
- `config/oa-workflow-*.json`: per-workflow selector maps + business lookups (factory→company, WBS-prefix→purpose, etc.).
- `.runtime/`: all generated output (exploration artifacts, task reports, login screenshots, cached Edge profile). Served read-only at `/runtime/*`; writes are guarded to stay inside `.runtime`.

### Docker
`Dockerfile` + `docker-compose.yml` run the server headful inside Xvfb with noVNC (port 7900) in `isolated` profile mode with `--no-sandbox`. See `docs/DOCKER.md`.

## Key environment variables

`MEGANT_EDGE_PROFILE_MODE`, `MEGANT_EDGE_PROFILE_NAME`, `MEGANT_EDGE_USER_DATA_DIR`, `MEGANT_AUTO_LAUNCH_EDGE`, `MEGANT_STARTUP_URL`, `MEGANT_BROWSER_CHANNEL` (`msedge`|`bundled`), `MEGANT_BROWSER_ARGS`, `MEGANT_SSO_ALLOWED_HOSTS`, `MEGANT_EXPLORE_ALLOWED_HOSTS`, `MEGANT_PLAYWRIGHT_TIMEOUT_MS`, `MEGANT_PLAYWRIGHT_NAV_TIMEOUT_MS`, `PORT`, `HOST`, `PYTHON`, `MEGANT_DOCKER`.

## Python LangGraph orchestrator (`orchestrator/`)

A separate Python "brain" layer sits **on top of** the deterministic Node service (which stays unchanged as the "hand"). It turns a natural-language request + Excel into a filled OA **workflow 89 (库存转储)** draft, validating materials against PDM first. **LLM (DeepSeek) is used only for understanding** — intent extraction, slot-filling, failure diagnosis; Playwright still never submits.

- Integration is **server-side HTTP**: the new `POST /api/oa/stock-transfer` endpoint (`src/server.js`) wraps `runStockTransfer(input)` extracted into `src/automation/flows/stockTransfer.js`. The endpoint takes **already-structured input** (`{structured:{materialPlans,…}, …, save}`), zod-validated, serialized by an in-process mutex; `NeedInputError` → `{ok:false, needsInput:true, input:{kind,question,options}}`. **Excel parsing was lifted out of Node** — the CLI `scripts/oa-stock-transfer-from-excel.js` still parses via `stock_transfer_excel.py` for backward compat, but the orchestrator parses Excel itself (openpyxl) in its `intake` node.
- The graph is **device-agnostic**: it depends only on an Executor contract (`orchestrator/oa_orchestrator/executors/base.py` — `session_status`/`query_pdm`/`fill_stock_transfer`), with `HttpNodeExecutor` (real Node service; Windows/mac differences live here) and `MockExecutor` (offline tests). Graph topology: `intake → preflight → understand → check_slot →(ask)→ pdm_enrich → resolve_params → execute → verify →(diagnose self-heal)→ finalize`, with a `SqliteSaver` checkpointer for resume.
- **Separate mac venv** (the repo `.venv` is a stale Windows venv — do not reuse). Setup + run: see `orchestrator/README.md`. Offline verification needs no DeepSeek/Edge: `orchestrator/.venv/bin/python orchestrator/tests/smoke.py`.

## When exploring a new page (the documented workflow)

Use the existing exploration framework (never write ad-hoc scrapers): no-interaction scan first, then safe interactions to trigger queries, never click dangerous buttons, artifacts to `.runtime/exploration/`. Then record confirmed findings into `docs/EXPLORATION_RESULTS.md` and a per-page `docs/explorations/<page>/README.md`. Full protocol: `COMMANDS.md`, `docs/PAGE_EXPLORATION_FRAMEWORK.md`, `docs/OA_WORKFLOW_AUTOMATION_PLAYBOOK.md`.
