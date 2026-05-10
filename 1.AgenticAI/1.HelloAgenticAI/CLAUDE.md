# CLAUDE.md — HelloAgenticAI

Operational guide for Claude Code working in this repo. Read this every session.

## What this project is

HelloAgenticAI is the **foundational framework** for the AgenticAI track of this portfolio. Project #1 (this folder) demonstrates the framework with a **fruit-market shopping agent** — universally relatable, exercises every agentic capability (planning, tool discovery, tool use, reflection, replanning, memory, termination, human-in-loop). Subsequent vertical projects (refinery domain) reuse `framework/` and swap only `demo-*/` and Bicep parameters.

Full architecture: `docs/ARCHITECTURE.md`. Build plan: `PROJECT_PLAN.md`. Read both before starting work.

## Repo location

`AISolutionPortfolio/1.AgenticAI/1.HelloAgenticAI/`

## Tech stack — canonical, do not substitute without asking

- Python 3.12 managed with `uv`
- LangGraph for agent orchestration
- Chainlit for the live UI
- FastAPI under Chainlit for HTTP endpoints
- Azure OpenAI for models (gpt-4o, gpt-4o-mini, text-embedding-3-large)
- Cosmos DB (NoSQL, serverless) for memory and traces
- Azure AI Content Safety for guardrails
- Azure App Insights + self-hosted Langfuse for observability
- Bicep + `azd` for infrastructure as code
- pytest for tests, ruff for lint/format, mypy --strict for type checks
- GitHub Actions with OIDC federated credentials for CI/CD
- Azure Static Web Apps for the portfolio publishing tier

## Conventions

- Type hints on every function. `mypy --strict` clean.
- No keys or secrets in code anywhere. Use `DefaultAzureCredential` for Azure auth, env vars for non-Azure tokens (managed via Key Vault references in production).
- Pydantic models for all structured I/O between agent nodes and tools.
- Async by default for I/O.
- When a package exposes async APIs via optional extras (e.g. `azure-storage-blob[aio]`), declare the extras in `pyproject.toml` — never add the underlying transport (`aiohttp`, `httpx`) as a separate top-level dep. Extras are the package author's stable contract; explicit transports leak the package's internal choice into our dep graph. (Exception: `azure-cosmos` as of v4.15.0 has no `[aio]` extras — see comment in `pyproject.toml` and the upstream issue linked there. Re-check on every azure-cosmos version bump.)
- One module per concern. Public API explicit in `__init__.py`.
- Tests live next to code as `test_*.py` and in a top-level `tests/` for integration.
- Conventional Commits format (`feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`).

## Workflow rules — non-negotiable

1. **Read `PROJECT_PLAN.md` before starting work.** Identify the current phase. Do not start a phase before the previous phase's acceptance criteria are met.
2. **Run quality gates before every commit.** `pytest && ruff check && ruff format --check && mypy --strict framework/`. If anything fails, fix before commit.
3. **Commit small, commit often.** One logical change per commit, Conventional Commits format.
4. **Pause for explicit approval before:**
   - `git push` (any branch)
   - `azd up` or any Azure provisioning command
   - `azd down` or any Azure teardown
   - Adding a dependency to `pyproject.toml`
   - Modifying `infra/main.bicep` (vs. adding a new module)
   - Anything touching `.github/workflows/*.yml`
   - Creating a new top-level folder or file
5. **Never commit secrets.** Pre-commit hook with `gitleaks` runs on every commit. If it isn't installed, install it.
6. **Tell me what you're about to do, then do it.** No long autonomous runs. Each phase is a check-in point. After completing a phase, post a summary and wait for "approved, push" before pushing.

## Phase completion criteria

A phase is "done" when:
- All deliverables listed in `PROJECT_PLAN.md` exist
- All acceptance criteria are demonstrably met (with logs / screenshots / test output)
- Quality gates pass clean
- Code is committed (not pushed) on a feature branch named `phase-N-<short-description>`
- A summary is posted with: what changed, test results, any open questions

I review, approve, and you push. Then we start the next phase.

## Things to avoid

- Don't reach for AKS, Helm, or Kubernetes. Use Container Apps.
- Don't bypass managed identity for "convenience" (e.g. don't fall back to API keys).
- Don't add new agent frameworks (Semantic Kernel, AutoGen, CrewAI) without asking.
- Don't generate documentation outside `docs/`. `README.md` and `docs/ARCHITECTURE.md` are the only top-level docs.
- Don't write Mermaid diagrams in `README.md` longer than ~15 lines; use `docs/ARCHITECTURE.md` for the detailed ones.
- Don't introduce a Postgres / MySQL / etc. — Cosmos is canonical for this project.
- Don't optimize prematurely (no caching layer in v1, no eager async batching in v1).

## Useful commands

```bash
# Setup (one-time)
uv sync                                    # install dependencies
pre-commit install                          # set up commit hooks

# Develop
uv run chainlit run demo-fruitmarket/ui/app.py --watch
uv run pytest                               # all tests
uv run pytest framework/ -v                 # framework only
uv run ruff check . && uv run ruff format .
uv run mypy --strict framework/

# Infra (require approval per workflow rule 4)
# MANDATORY preflight before any azd up — catches deprecation, role-id typos,
# unsupported properties in ~30s instead of 5–8 min of partial failure. See
# docs/decisions/0003-azd-up-preflight-risks.md.
cd infra && azd provision --preview         # dry-run validation (no resources created)
cd infra && azd up                          # provision dev environment (only after preview is clean)
cd infra && azd deploy                      # deploy code only
cd infra && azd down --purge                # full teardown
```

## When something goes wrong

- Build fails after a dependency upgrade → revert pyproject.toml, ask.
- `azd up` fails partway → run `azd provision --debug`, capture output, ask.
- Tests fail in CI but pass locally → don't merge, investigate environment differences first.
- Got stuck on a design call → stop, write a short ADR-style note in `docs/decisions/`, ask.
