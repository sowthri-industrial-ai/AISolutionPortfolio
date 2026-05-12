# HelloAgenticAI

Foundational framework for agentic AI on Azure-native infrastructure, demonstrated with a fruit-market shopping agent.

This is project #1 of the AgenticAI track. It builds the reusable `framework/` package and a fruit-market demo (`demo_fruitmarket/`). Future vertical projects (refinery domain) inherit `framework/` and swap only the demo layer.

## Status

**Phase 3 — Fruit-market demo.** Live Chainlit UI streams every step of the agent loop (plan → tool call → tool result → reflect → terminate) against six mock fruit shops with deliberately varied inventory. See [PROJECT_PLAN.md](PROJECT_PLAN.md) for the full phased plan and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the architecture.

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

## Architecture

Full target architecture in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Working rules and conventions in [CLAUDE.md](CLAUDE.md). Architectural decisions in [docs/decisions/](docs/decisions/). Framework-v2 backlog (signature gaps, structural improvements deferred from each phase) in [docs/framework-v2-backlog.md](docs/framework-v2-backlog.md).

## Layout

```
1.AgenticAI/1.HelloAgenticAI/
├── framework/             reusable agent runtime (Phase 2)
├── demo_fruitmarket/      this vertical: shops, agent, prompts, Chainlit UI (Phase 3)
├── infra/                 Bicep + azd (Phase 1)
├── docs/                  ARCHITECTURE.md + decisions/
├── tests/integration/     end-to-end tests against the deployed env
├── CLAUDE.md              operational rules + dev-setup runbook
└── PROJECT_PLAN.md        five-phase plan
```

## License

MIT.
