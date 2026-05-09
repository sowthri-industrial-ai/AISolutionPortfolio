# HelloAgenticAI

Foundational framework for agentic AI on Azure-native infrastructure, demonstrated with a fruit-market shopping agent.

This is project #1 of the AgenticAI track. It builds the reusable `framework/` package and a fruit-market demo (`demo-fruitmarket/`). Future vertical projects (refinery domain) inherit `framework/` and swap only the demo layer.

## Status

**Phase 1 — Foundation.** Project scaffold, Bicep modules, placeholder Container App. See [PROJECT_PLAN.md](PROJECT_PLAN.md) for the full phased plan.

## Quickstart (local development)

Prerequisites: Python 3.12, [`uv`](https://docs.astral.sh/uv/), [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli), [`azd`](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd), Docker, `pre-commit` (installed via `uv sync` as a dev dep).

```bash
# Install dependencies and set up commit hooks
uv sync
uv run pre-commit install

# Quality gates
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict framework/
uv run pytest

# Provision Azure infrastructure (requires az login)
cd infra && azd up
```

## Architecture

Full target architecture is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Working rules and conventions are in [CLAUDE.md](CLAUDE.md).

## License

MIT.
