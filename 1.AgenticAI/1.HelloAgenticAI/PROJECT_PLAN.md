# HelloAgenticAI — Project Plan

This is the build roadmap. Claude Code executes against this. Each phase has explicit deliverables and acceptance criteria. Move to the next phase only when the current one is "done" per the criteria below.

## Vision

Build a **reusable Python + Bicep framework** for agentic AI on Azure-native infrastructure, demonstrated with a **fruit-market shopping agent**. Inheriting projects (refinery vertical, etc.) keep `framework/` intact and swap only the tools, prompts, and eval cases.

## Architecture (one paragraph)

A LangGraph agent (`Plan → Route → Reflect → Terminate`) runs in Azure Container Apps, calls Azure OpenAI and MCP-style tools, persists state to Cosmos DB, is gated by Azure AI Content Safety, and traces every step to App Insights and a self-hosted Langfuse — fronted by a Chainlit UI that streams the live agent flow to the user. A Static Web App portfolio site can launch and tear down the demo on-demand via GitHub Actions workflows triggered through OIDC. Full details in `docs/ARCHITECTURE.md`.

## Folder structure (target end-state)

```
1.AgenticAI/1.HelloAgenticAI/
├── README.md
├── CLAUDE.md
├── PROJECT_PLAN.md
├── pyproject.toml
├── Dockerfile
├── .pre-commit-config.yaml
├── .gitignore
├── docs/
│   ├── ARCHITECTURE.md
│   └── decisions/                   ADRs as design questions arise
├── framework/                       reusable scaffolding (inherited by future verticals)
│   ├── agents/
│   ├── tools/
│   ├── memory/
│   ├── observability/
│   ├── guardrails/
│   ├── llm/
│   └── eval/
├── demo-fruitmarket/                v1 demo vertical (the swap-out layer)
│   ├── tools/                       mock shop MCP servers
│   ├── prompts/
│   ├── graph.py                     LangGraph composition
│   ├── ui/                          Chainlit app
│   ├── eval/cases.json
│   └── Dockerfile
├── infra/                           Bicep + azd
│   ├── main.bicep
│   ├── azure.yaml
│   ├── main.parameters.json
│   └── modules/                     one module per Azure service
├── tests/                           integration tests (unit tests live next to code)
└── .github/workflows/
    ├── deploy.yml
    └── evals.yml
```

## Phase 1 — Foundation

**Goal:** Repository scaffolded, infrastructure deploys cleanly via `azd up`, dev environment is fully reproducible.

**Deliverables:**
- `pyproject.toml` (uv-based, Python 3.12, all dependencies pinned with `uv.lock`)
- `Dockerfile` for the agent app container (multi-stage, slim base)
- `.pre-commit-config.yaml` with ruff, mypy, gitleaks, trailing-whitespace
- `.gitignore`, `.editorconfig`, `.python-version`
- `infra/main.bicep` complete and **all eleven modules written**:
  identity, observability, keyvault, cosmos, storage, search, openai, contentsafety, registry, container-env, container-app
- `infra/azure.yaml` (azd config)
- `infra/main.parameters.json` (env-specific params, no secrets)
- A placeholder Container App that returns 200 on `/health` (so we can verify the infra is wired correctly before there's any agent code)
- Empty `framework/` package skeleton with `__init__.py` files

**Acceptance criteria:**
- `uv sync` installs cleanly on a fresh checkout
- `pre-commit run --all-files` passes
- `azd up` succeeds end-to-end in under 15 minutes
- `azd env get-values` returns valid endpoints for Cosmos, Azure OpenAI, App Insights, Container App
- Hitting the placeholder Container App's `/health` returns 200
- All resources tagged with `project=helloagenticai`, `environment=dev`, `managedBy=bicep`

## Phase 2 — Framework interfaces and minimal agent

**Goal:** Framework Python package importable; one minimal agent runs end-to-end against deployed Azure resources with a single mock tool, demonstrating the loop.

**Deliverables:**
- `framework/agents/base.py` — `AgentBase`, `AgentState` (full implementation, not stubs)
- `framework/tools/base.py` — `MCPToolBase`, `ToolRegistry`
- `framework/memory/cosmos.py` — Cosmos provider with `DefaultAzureCredential`
- `framework/observability/events.py` — `AgentEventEmitter` with App Insights + stub Langfuse + UI stream sinks
- `framework/guardrails/content_safety.py` — guardrail layer (input + output + schema)
- `framework/llm/azure_openai.py` — typed wrapper around `openai.AsyncAzureOpenAI`
- `framework/eval/harness.py` — `EvalHarness`, `EvalCase`, three scoring modes
- Unit tests for every module under `framework/`
- An integration test `tests/integration/test_minimal_agent.py` that runs a tiny `MinimalAgent` (subclass of `AgentBase`) against deployed AOAI with one in-process mock tool

**Acceptance criteria:**
- `uv run pytest framework/` passes 100%
- `uv run pytest tests/integration/` passes against the dev environment from Phase 1
- `uv run mypy --strict framework/` clean
- The integration test's logs visibly show: plan → tool call → tool result → reflect → terminate
- Cosmos `traces` container has rows for the test run

## Phase 3 — Fruit market demo

**Goal:** The user-facing demo. Chainlit UI streams the live agent flow against 5–10 mock fruit shops. Out-of-stock replanning visibly works.

**Deliverables:**
- `demo-fruitmarket/tools/` — 5–10 mock shop MCP servers (each implements `MCPToolBase`; some hold inventory, some are out-of-stock by default to force replans)
- `demo-fruitmarket/prompts/` — planner, router, reflector, terminator prompts as `.md` files loaded at runtime
- `demo-fruitmarket/graph.py` — full LangGraph composition wiring framework nodes to demo tools
- `demo-fruitmarket/ui/app.py` — Chainlit app. Each `AgentEventEmitter` event renders as a step in the UI with collapsible details (tool input/output, reasoning).
- `demo-fruitmarket/Dockerfile`
- 3–5 hand-crafted demo prompts in the README ("buy a tropical fruit basket under $20", "find pomegranates and dates, prefer local", etc.)

**Acceptance criteria:**
- `uv run chainlit run demo-fruitmarket/ui/app.py` starts UI; user submits goal, watches every step stream
- The canonical replanning demo runs cleanly: a shop returns out-of-stock, the agent visibly replans, finds an alternate shop, completes the basket
- Each step in the UI shows: name, status, duration, expandable input/output JSON
- Container builds via `docker build` locally
- `azd deploy` pushes the new image and the deployed Container App URL works for an external user

## Phase 4 — Observability and guardrails wired live

**Goal:** Every agent step is traced. Content Safety blocks bad input. Langfuse trace UI shows the same agent flow Chainlit shows, in production-style form.

**Deliverables:**
- App Insights events flowing for every `AgentEventType`, with `session_id` correlation
- Langfuse deployed as a sidecar Container App; `framework/observability/events.py` ingests live
- Content Safety wired on input + output gates; pre-defined "block" demo prompts trigger it
- Pydantic schema validation enforced on every node's structured output (refuses malformed LLM outputs and retries up to 2x)
- App Insights workbook (committed as JSON in `infra/workbooks/`) with: latency per node, replan rate, guardrail-block rate, tool-error rate
- README screenshots: live Chainlit demo, Langfuse trace tree, App Insights workbook

**Acceptance criteria:**
- A prompt-injection-style input is blocked with a clear UI message and a `guardrail_block` event recorded in App Insights
- Every demo run produces a complete trace in Langfuse
- App Insights workbook renders with live data when a few demo runs have completed
- An LLM output that violates the planner's Pydantic schema triggers a retry and is recorded as a `schema_validation_failure` event

## Phase 5 — Evals, CI/CD, publishing

**Goal:** Quality gates run automatically on every PR. Demo is launchable from a public portfolio website.

**Deliverables:**
- `demo-fruitmarket/eval/cases.json` — 8–10 eval cases across happy path, replanning, human escape, guardrail block, multi-step planning
- `.github/workflows/evals.yml` — runs evals on every PR; comments results on the PR; fails the PR if pass rate <90%
- `.github/workflows/deploy.yml` — `provision`, `deploy`, `teardown` modes via `workflow_dispatch`
- OIDC federated credentials configured (zero secrets in GitHub) — Claude Code documents the manual Entra app-registration steps in `docs/setup-oidc.md`
- Azure Static Web App for the portfolio site (lives at the repo root, separate from this folder, but referenced here)
- Project profile page for HelloAgenticAI on the portfolio site with: overview, architecture diagram, GitHub link, Launch / Teardown buttons, live status indicator
- Tiny Azure Function that the Launch/Teardown buttons call to dispatch the GitHub Actions workflows
- README updated with screenshots, demo GIF, link to the live portfolio profile page

**Acceptance criteria:**
- Opening a PR runs evals and posts the results as a PR comment
- "Launch demo" on the portfolio site provisions the RG within ~12 minutes and displays the live URL
- "Teardown" wipes the RG to zero
- A reviewer who has never seen the project can go from portfolio site → live demo → understanding agentic AI in under 5 minutes
- The project is ready to be linked from a resume

## Definition of v1 done

- All five phases' acceptance criteria met
- README and `docs/ARCHITECTURE.md` complete with screenshots, GIF, mermaid diagrams
- Demo runs end-to-end via the portfolio site Launch button
- One reviewer who has never seen the project can run the demo without help
- The project is at a state where Project #2 (refinery vertical) can be started by copying the repo structure and swapping only `demo-fruitmarket/` with the refinery use case

## Explicitly NOT in v1 (intentional scope cuts)

These are framework hooks; refinery vertical projects will wire them up:

- **APIM AI Gateway** — Bicep module hook stays stubbed, off by default
- **AI Search RAG** — module conditional (`deploySearch=false`), off by default
- **Redis semantic cache** — extension point only
- **Private Endpoints / VNet integration** — extension point for regulated data
- **Multi-region / DR** — single region only

`docs/ARCHITECTURE.md` calls each of these out explicitly so reviewers see the architectural intent without confusion about scope.

## Reference architecture diagram

See `docs/ARCHITECTURE.md` for the full mermaid diagram. Quick text version:

```
User → Static Web App (portfolio profile)
         ↓ Launch button
       GitHub Actions (OIDC) → azd up
         ↓
       Azure RG: { Container App (Chainlit + LangGraph), AOAI, Cosmos, Content Safety, Key Vault, App Insights, Langfuse, ACR }
         ↑
       User interacts with Chainlit
         agent loop: Plan → Route → call MCP tools → Reflect → loop or Terminate
         every step streams to UI + App Insights + Langfuse + Cosmos traces
```
