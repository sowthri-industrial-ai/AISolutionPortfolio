# F3 — Agentic AI + MCP server

LangGraph agent (Claude Sonnet 4.6) over an MCP server that exposes
Stage 3's read + write + advisory surface to a CLI REPL. Path A of F3:
the agent reads live values, recommends actions, and the operator
approves/rejects. Direct perturbation is available but cautious by
default.

> **F3 close-out status — COMPLETE.** Commits C3–C6 on
> `phase-6-agents`:
> - **C3** catalog filter (`Recycle.MaximumIterations` →
>   non-perturbable; DWSIM resets it each cycle)
> - **C4** MCP server, 9 tools over stdio — verified e2e (8/9 tools
>   exercised; `approve_advisory` structurally identical to the verified
>   `reject_advisory`)
> - **C5** LangGraph agent + CLI — verified behaviourally (pure read /
>   read-before-recommend / confirmation-gate on direct perturb /
>   out-of-bounds refusal; MemorySaver continuity solid)
> - **C6** OpenAPI regen (17 ops) + 28-test regression suite (green) +
>   these close-out notes
>
> Known issues are parked in the **Backlog** section below — none block
> the F3 demo path. Highest priority post-close-out is the pump
> bounds-units bug (the C5 agent caught it unprompted).

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                          CLI REPL (cli.py)                           │
│                          stdin / stdout                              │
└──────────────────────────────────────────────────────────────────────┘
                                  │
                       agent.astream / ainvoke
                                  │
              ┌───────────────────▼────────────────────┐
              │   LangGraph ReAct agent (agent.py)     │
              │   ChatAnthropic claude-sonnet-4-6      │
              │   MemorySaver (thread_id per session)  │
              └───────────────────┬────────────────────┘
                                  │
                           MCP stdio transport
                                  │
              ┌───────────────────▼────────────────────┐
              │   FastMCP server (mcp_server.py)       │
              │   9 tools: 5 read + 1 perturb + 4 adv  │
              └─────────────┬───────────────────┬──────┘
              in-process    │                   │ httpx
              SetpointCatalog                   │
                            │                   ▼
                            ▼      ┌───────────────────────────┐
              Phase 0a setpoint    │  Stage 3 FastAPI :8080    │
              dictionary (JSON)    │  (api.py — 21 routes)     │
                                   └───────┬───────────────────┘
                                           │
                              file IPC (perturbation inbox)
                                           │
                                           ▼
                                  ┌──────────────────────┐
                                  │  Stage 2 streamer    │
                                  │  (DWSIM Mono x86)    │
                                  │  ../.venv-x86        │
                                  └──────────────────────┘
```

Two Python venvs, intentional:

| Venv | Python | Purpose |
| --- | --- | --- |
| `2.automation/.venv-x86` | 3.9 (x86_64) | DWSIM Mono interop — `clr` / pythonnet, Stage 2 streamer, Stage 3 API |
| `2.automation/f3/.venv` | 3.11 (arm64) | `mcp` SDK (requires ≥3.10), LangGraph stack |

The two processes communicate only via the Stage 2 perturbation inbox
(filesystem) and Stage 3 HTTP. The MCP server's `mcp_server.py` itself
runs in the 3.11 venv but is spawned as a subprocess by the agent.

## Install

One-time, from this directory (`2.automation/f3/`):

```bash
/opt/homebrew/bin/python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install mcp httpx langgraph langchain-anthropic langchain-mcp-adapters
# regression suite extras (Stage 3 is DWSIM-free so it runs in this venv):
.venv/bin/pip install fastapi "uvicorn[standard]" pyyaml pytest
```

Versions confirmed working (May 2026):

- `mcp` 1.27.x
- `langgraph` 1.2.x
- `langchain-anthropic` 1.4.x
- `langchain-mcp-adapters` 0.2.x
- `anthropic` 0.102.x

## Run

The agent CLI needs Stage 3 running so the MCP tools have a backend to
talk to. Order matters:

```bash
# Terminal 1 — Stage 2 streamer (DWSIM)
cd 2.automation/stage2
arch -x86_64 ../.venv-x86/bin/python streamer.py

# Terminal 2 — Stage 3 API
cd 2.automation/stage3
arch -x86_64 ../.venv-x86/bin/uvicorn api:app --host 0.0.0.0 --port 8080

# Terminal 3 — Agent CLI (this directory)
cd 2.automation/f3
export ANTHROPIC_API_KEY=sk-ant-...   # your Claude key
.venv/bin/python cli.py
```

The CLI prints a banner with the model, Stage 3 URL, and thread_id,
runs a preflight `check_health`, and drops into the prompt. Each REPL
session = one thread_id (UUID4); conversation continuity within the
session is in-process (`MemorySaver`). Closing the CLI ends the thread.

## Environment

Read by `cli.py` / `agent.py`:

| Variable | Default | Notes |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | (required) | Sonnet 4.6 API access |
| `AGENT_MODEL` | `claude-sonnet-4-6` | Override only if testing a different Claude model |
| `AGENT_TEMPERATURE` | `0.0` | Deterministic tool selection by default |
| `AGENT_MAX_TOKENS` | `4096` | |

Read by the spawned `mcp_server.py` (propagated through):

| Variable | Default | Notes |
| --- | --- | --- |
| `STAGE3_BASE_URL` | `http://localhost:8080` | |
| `SETPOINT_DICT_PATH` | `<repo>/3.probes/phase0a/phase0a_setpoint_dictionary.json` | |
| `MCP_HTTP_TIMEOUT` | `10.0` | seconds |

## Tools available to the agent (9)

| Tool | Side effect | Notes |
| --- | --- | --- |
| `check_health` | none | Stage 3 + Stage 2 liveness |
| `get_tag(tag_id)` | none | Live tag value from Stage 2 snapshot |
| `get_setpoint(setpoint_id)` | none | Catalog entry (in-process — fast) |
| `list_perturbables` | none | All writable setpoints (24 entries) |
| `list_advisories(state?)` | none | Filterable by pending / approved / rejected |
| `recommend_action(setpoint_id, target_value, rationale)` | creates pending advisory | **Default write path** |
| `perturb_setpoint(setpoint_id, value)` | enqueues perturbation directly | Cautious path — needs explicit user opt-in |
| `approve_advisory(advisory_id)` | enqueues perturbation | Operator action; agent rarely calls |
| `reject_advisory(advisory_id, reason?)` | closes advisory, no write | Operator action |

Posture is set by `prompts.SYSTEM_PROMPT`. Edit there to tune behaviour.

## Example session

```
> what is the current reflux ratio?

  -> tool: get_tag({'tag_id': 'COL-DISTILLATION_COLUMN.RefluxRatio'})
  <- get_tag: {'tag_id': 'COL-DISTILLATION_COLUMN.RefluxRatio', 'value': 2.4987, ...}

  The column is operating at a reflux ratio of 2.50. Anything else you'd
  like to check?

> recommend dropping reflux to 2.0 to save reboiler duty

  -> tool: get_setpoint({'setpoint_id': 'COL-DISTILLATION_COLUMN.RefluxRatio'})
  <- get_setpoint: {'bounds': {'low': 1.0, 'high': 5.0}, 'perturbable': True, ...}
  -> tool: recommend_action({'setpoint_id': 'COL-...', 'target_value': 2.0, 'rationale': '...'})
  <- recommend_action: {'advisory_id': '...', 'state': 'pending', ...}

  Advisory created (id: abc123). Rationale recorded. The operator can
  approve via approve_advisory or reject. Note: 2.0 is within Phase 0a
  bounds but reduces overhead reflux substantially — watch tray
  temperatures and distillate composition after approval.
```

## Regression suite

`test_f3_regression.py` — 28 tests, the F3 close-out gate. Runs in this
venv (Stage 3 is DWSIM-free; `streamer.py` defers its `clr` imports, so
both import cleanly under Python 3.11):

```bash
.venv/bin/python -m pytest test_f3_regression.py -v
```

Four areas:

1. **Endpoint shapes** — every Stage 3 route (F1 read + F2 ontology + F3
   write/advisory) returns the expected status + schema; bad-param and
   not-found paths return the right 4xx.
2. **Strategy dispatch** — `WRITE_STRATEGIES` has all four families
   (`reflection`, `reflection_int`, `calc_mode`, `column_spec`), the four
   representative mappings resolve, and **every perturbable catalog entry
   has a strategy** (the cross-reference that protects the demo from a
   "perturbable but no write path" regression).
3. **Advisory lifecycle** — create → list → reject; create → approve →
   inbox file enqueued + `perturbation_request_id` stamped;
   double-resolve → 409.
4. **`NON_PERTURBABLE_OVERRIDES` enforcement** — `Recycle.MaximumIterations`
   stays in the read catalog but rejects both direct writes and advisory
   creation with 422.

The suite redirects the perturbation inbox + advisory store to a
throwaway tempdir, so it never touches real runtime state. Env vars are
wired at module import time (api.State reads env at class-definition
time, before `import api`).

## Backlog (captured by operator, not yet acted on)

These were filed during C4 verification + C5 wiring; addressing them
belongs to a follow-up commit cycle.

### High (immediately after C6)

- **Pump bounds-units bug.** Pump perturbable entries' bounds are in the
  wrong units, which means `perturb_setpoint` either always rejects or
  always accepts incorrect values. Without the fix, pump perturbables
  aren't really perturbable in the demo.

### Medium (pre-customer-demo)

- **669 K cross-loop anomaly** when the column spec switches between
  RefluxRatio and HeatDuty. Worth investigating before customer demos.

### Low (cosmetic)

- **`.applied` cycle field discrepancy** — `enqueued_at` cycle vs
  `applied_at` cycle reported by Stage 2 sometimes disagree. Doesn't
  affect strategy correctness or agent behaviour.

### C4 follow-ups (deferred from C4-verify)

- **Field naming consistency.** `target_value` (MCP input) vs
  `proposed_value` (operator instinct). Pick one canonical name across
  the MCP tool input, the advisory JSON, and the system prompt.
- **`reject_advisory` doesn't persist `rejected_reason`.** Response
  shows `null` despite valid input — handler bug in
  `stage3/advisories.py`.
- **MCP tool error responses set `isError=true` for app-level errors.**
  `setpoint_not_found`, `tag_not_found`, `validation_failed` currently
  return with `isError=false`. The agent can still parse the error
  dict, but MCP clients can't distinguish success from error without
  reading the payload.

### Future (post-demo, post-auth)

- **`rejected_by` / `approved_by` derived from auth context** rather
  than hardcoded "operator" — when we add auth in a later iteration.

## Files

```
2.automation/f3/
├── README.md          (this file)
├── mcp_server.py            FastMCP server, 9 tools, stdio transport
├── agent.py                 LangGraph ReAct agent build
├── cli.py                   REPL entry point
├── prompts.py               system prompt (single source of truth for posture)
├── test_f3_regression.py    F3 close-out regression (28 tests)
├── probe_*.py               diagnostic scratch (gitignored — see .gitignore)
└── .venv/                   Python 3.11 venv (gitignored)
```
