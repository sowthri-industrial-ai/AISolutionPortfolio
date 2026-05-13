# HelloAgenticAI

Foundational framework for agentic AI on Azure-native infrastructure, demonstrated with a fruit-market shopping agent.

This is project #1 of the AgenticAI track. It builds the reusable `framework/` package and a fruit-market demo (`demo_fruitmarket/`). Future vertical projects (refinery domain) inherit `framework/` and swap only the demo layer.

## Status

**Phase 4 — Observability + guardrails wired live.** The Phase 3 Chainlit demo is now backed by real-time observability and content safety:

- Every chat session emits a Langfuse trace with the agent's plan / tool / reflect spans nested under one parent — the UI surfaces a clickable "🔗 View full trace in Langfuse" link below each answer.
- Every event also ships to an Azure App Insights workbook with five live KQL charts (event timeline, p50/p95 latency, schema-validation failures, guardrail blocks, plus a cost-trend placeholder deferred to v2).
- User input is checked against Azure AI Content Safety before the agent plans; the final answer is checked again before it ships back. Blocks render as a friendly "your message was flagged" message, not as a crash.
- Pydantic schema validation gates every LLM call and tool I/O boundary with retry-on-failure semantics — 3 attempts before propagation, each retry emitting a `SCHEMA_VALIDATION_FAILED` event.

See [PROJECT_PLAN.md](PROJECT_PLAN.md) for the full phased plan and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the architecture.

## Quickstart (local)

Prerequisites: Python 3.12, [`uv`](https://docs.astral.sh/uv/), [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli), [`azd`](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd), Docker Desktop, `pre-commit` (installed via `uv sync` as a dev dep).

```bash
# Install dependencies and set up commit hooks
uv sync
uv run pre-commit install

# Quality gates (run before every commit; pre-commit hooks enforce)
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict framework/ demo_fruitmarket/
uv run pytest

# Provision Azure infrastructure (one-time; requires az login)
cd infra && azd provision --preview          # mandatory dry-run
cd infra && azd up                           # only after preview is clean
cd ..

# After azd up: grant the dev principal data-plane RBAC
# (see CLAUDE.md "First-time / post-teardown developer setup" for the
# exact `az` commands — currently just two: Cosmos + AOAI)

# Run the live demo locally (Chainlit UI on port 8000)
uv run chainlit run demo_fruitmarket/ui/app.py --host 0.0.0.0 --port 8000
```

Then open http://localhost:8000.

## Demo prompts

Five hand-picked prompts that exercise different agent paths. Try them in the local UI:

1. **Tropical basket with replan**
   > *Buy a tropical fruit basket under $20 — include pineapple, mango, and dragon fruit*

   The planner picks tropical fruits; router goes to `tropical_paradise` first (cheaper). Pineapple is out of season → reflector loops → router picks `global_imports` (premium fallback). Final basket includes mango + dragon fruit + pineapple across two shops with a budget summary.

2. **Happy path, single shop**
   > *Pick up some apples and pears for a fruit salad*

   Planner picks specific variants (e.g. `apple_gala`, `pear_bartlett`). Router goes straight to `apple_orchard`. Single iteration, immediate done.

3. **Terminal failure path (graceful)**
   > *Build me a berry mix: strawberries, blueberries, and raspberries*

   `berry_basket` has blueberries + raspberries but strawberries are off-season — and no other shop carries strawberries. Reflector recognises the unsourceable item and terminates with 2/3 sourced and an explicit "couldn't source: strawberries" callout.

4. **Preferences + happy path**
   > *Find peaches and cherries, prefer local*

   Planner captures `local` as a preference; router uses it to weight shop choice. Single iteration at `stone_fruit_stand`.

5. **Rationing replan**
   > *I need 5 dragon fruit*

   `tropical_paradise` rations dragon fruit at 2 per visit → returns 2 purchased + dragon_fruit on the `rationed` list → reflector loops → router picks `global_imports` for the remaining 3 (more expensive). Final basket honestly reports 2 cheap + 3 premium.

Each step renders in the UI as a Chainlit step with collapsible JSON details (tool input/output, reasoning). Final answer appears as a top-level message.

## What Phase 4 adds (observability + guardrails)

The Phase 3 demo loop runs unchanged. Phase 4 wraps it with four production-grade signals:

### 1. Real-time Langfuse trace tree per chat session

Every Chainlit chat session opens a Langfuse trace whose id IS the session id (1:1 mapping → deterministic trace URLs, no round-trip needed). The agent's `plan` / `tool:<shop>` / `reflect` events become nested spans on that trace; `schema_validation_failed` / `guardrail_blocked` surface as `level=ERROR` spans so they highlight at-a-glance in the Langfuse UI.

**Visible manifestation:** below each agent answer, the UI renders `🔗 [View full trace in Langfuse](https://cloud.langfuse.com/trace/<session-id>)`. Clicking opens the trace tree:
```
agent_run                                                    (~5.9s)
├── plan                                                     (~2.7s)
├── tool:stone_fruit_stand                                   (~0.01s)
└── reflect                                                  (~3.1s)
```

Trace input = the user goal; trace output = the final answer; per-span input/output = the AgentEvent payload.

### 2. App Insights workbook — operational dashboard

Five live KQL charts queryable in the Azure Portal:

| Chart | KQL source | Purpose |
|---|---|---|
| Agent runs (last 24h) | `dependencies \| where name == "complete"` | Quick "is anyone using this" signal |
| Events per minute by type (stacked area) | `dependencies \| summarize count() by bin(timestamp, 1m), name` | Traffic shape + which events dominate |
| Plan-to-complete latency (p50/p95, 5-min buckets) | join `plan_start` → `complete` per session | End-to-end UX latency |
| Top 5 schema-validation failures by model | `dependencies \| where name == "schema_validation_failed"` | Which Pydantic model + node is the LLM having trouble with |
| Top 5 Content Safety blocks by gate + categories | `dependencies \| where name == "guardrail_blocked"` | What's being filtered and where |

Plus a cost-trend placeholder section (deferred to framework-v2 per the Batch 7 design call; the workbook layout is in place so the chart slots in cleanly when token usage emission lands).

**Visible manifestation:** open Azure Portal → resource group `rg-helloagenticai-{env}` → Application Insights `appi-helloagenticai-{env}-{token}` → Workbooks → **HelloAgenticAI Agent Observability**. The resource ID is also surfaced as `AZURE_WORKBOOK_ID` in `azd env get-values`.

### 3. Content Safety input + output gates

`ContentSafetyClient` (built on `azure-ai-contentsafety` with AAD-only auth via the user-assigned managed identity) wraps the agent loop with two gates:

- **Input gate** — `agent.run(goal)` calls `check_text(goal)` before planning. On BLOCK: emits `GUARDRAIL_BLOCKED(gate="input")`, raises `ContentSafetyError`. Chainlit renders a friendly "⚠️ I can't process that — your message was flagged" message. PLAN_START never fires.
- **Output gate** — before `COMPLETE` emits, the final answer is checked. On BLOCK: the answer is replaced with an agent-voice redaction notice ("I generated an answer, but it was redacted by safety filters…"). COMPLETE still fires so the trace closes cleanly — no orphan events.

**Visible manifestation when safe:** silent. The gate doesn't interrupt the demo for prompts Azure scores as SAFE — including some that *sound* dramatic but don't trigger Azure's threshold (e.g. generic frustration like "I hate everything" isn't directed hate speech and won't fire the `Hate` category). To see the gate fire, use a prompt that triggers Azure's documented hate-speech / self-harm / sexual / violence categories at MEDIUM+ severity.

### 4. Pydantic schema validation with retry on every LLM / tool boundary

`AgentBase._invoke_with_validation_retry` wraps `_plan_node`, `_tool_node` (covers both `_route` and tool-input validation), and `_reflect_node` with 3-attempt retry semantics. Each failed attempt emits `SCHEMA_VALIDATION_FAILED` with the offending Pydantic model name, attempt index, and truncated error detail; the 3rd failure propagates as a typed exception that Chainlit's existing four-class error sink renders as a failed step.

`AzureOpenAIClient.chat_structured` raises `SchemaValidationError` (not `RuntimeError`) when the OpenAI SDK can't parse, so the retry helper catches a single typed exception class for both LLM-side and tool-input failures.

**Visible manifestation:** none on happy paths (the LLM almost always returns valid Pydantic-shaped output at `temperature=0.0`). When it does fire, both the UI and the workbook show the retry trail.

### Architectural rule — fail-open observability

All four Phase 4 components (Content Safety, App Insights, Langfuse, plus the LangfuseSink's Key Vault dependency) follow the same lazy-init contract: construct cheap (no I/O at startup), initialize on first use, **never crash the agent on init or per-call failure**. The agent keeps running on a degraded observability path with a one-time WARNING log — availability is guaranteed, observability is best-effort. See ADR-0003 risk #9 + the Phase 4 backlog for the failure modes this hides and the work item to surface them more loudly.

## Architecture

Full target architecture in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Working rules and conventions in [CLAUDE.md](CLAUDE.md). Architectural decisions in [docs/decisions/](docs/decisions/). Framework-v2 backlog (signature gaps, structural improvements deferred from each phase) in [docs/framework-v2-backlog.md](docs/framework-v2-backlog.md).

## Layout

```
1.AgenticAI/1.HelloAgenticAI/
├── framework/                       reusable agent runtime
│   ├── agents/                      AgentBase + LangGraph loop + schema-retry helper (Phase 2/4)
│   ├── guardrails/                  Content Safety client + Pydantic schema gate (Phase 2/4)
│   ├── llm/                         Azure OpenAI typed async wrapper (Phase 2)
│   ├── memory/                      Cosmos persistence + CosmosSink (Phase 2)
│   ├── observability/               events + AppInsightsSink + LangfuseSink (Phase 2/4)
│   └── tools/                       MCP-style typed tool registry (Phase 2)
├── demo_fruitmarket/                fruit-market vertical
│   ├── shops.py + agent.py + prompts/   six shops + FruitMarketAgent + .md prompts (Phase 3)
│   ├── graph.py                     composition factory wiring env-driven Phase 4 sinks (Phase 4)
│   └── ui/                          Chainlit app + ChainlitSink with Langfuse trace link (Phase 3/4)
├── infra/                           Bicep + azd
│   ├── modules/                     identity, openai, cosmos, contentsafety, ..., workbook (Phase 1/4)
│   └── workbooks/                   agent-observability.workbook.json (Phase 4)
├── docs/                            ARCHITECTURE.md + decisions/ (ADR-0001..0003) + framework-v2-backlog.md
├── tests/integration/               end-to-end tests against the deployed env
├── CLAUDE.md                        operational rules + dev-setup runbook
└── PROJECT_PLAN.md                  five-phase plan
```

## License

MIT.
