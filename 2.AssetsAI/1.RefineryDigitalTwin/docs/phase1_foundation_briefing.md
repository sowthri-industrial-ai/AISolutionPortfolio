# Phase 1 Foundation Briefing — Portfolio Contract Compliance

**Project:** Refinery Digital Twin
**Issued by:** Architect chat
**Implementer:** Claude Code (separate session from Stage 1 streamer)
**Operator:** Sowthri
**Status:** Stage 1 streamer in flight (parallel session) → this briefing
**Branch:** `phase-1-foundation` (per portfolio convention)
**Estimated effort:** ~1 day Claude Code + ~30 min operator (verify `azd up` deploys)

---

## Goal

Make this project compliant with the portfolio coordination contract:
- Architecture diagram (mermaid) the portfolio site renders on the profile page
- Bicep + azd infrastructure that provisions a dedicated RG and deploys a placeholder Static Web App
- GitHub Actions `deploy.yml` workflow that the shared portfolio site triggers via Azure Function for Launch/Teardown
- Project metadata file the portfolio site reads to populate the profile page
- Pre-commit hooks scoped to this project's lane only

The output: a public demo URL that the portfolio site can link to (placeholder for now; real demo arrives with Feature 5).

## Context

The AISolutionPortfolio repo hosts a shared portfolio website (Astro + Tailwind on Azure Static Web Apps, built in HelloAgenticAI Phase 5). That site renders profile pages for every project and exposes Launch/Teardown buttons that provision each project's dedicated Azure RG via GitHub Actions `workflow_dispatch`.

This briefing covers RefineryDigitalTwin's side of that contract. The website itself is NOT built here — only the artifacts the website needs from this project.

## Required reading before code

In this order:

1. `~/Documents/AISolutionPortfolio/1.AgenticAI/1.HelloAgenticAI/.github/workflows/deploy.yml` — canonical pattern for the workflow we'll mirror
2. `~/Documents/AISolutionPortfolio/1.AgenticAI/1.HelloAgenticAI/PROJECT_PLAN.md` — Phase 5 section defines the metadata format
3. `~/Documents/AISolutionPortfolio/1.AgenticAI/1.HelloAgenticAI/docs/ARCHITECTURE.md` — canonical pattern for the architecture mermaid structure
4. `~/Documents/AISolutionPortfolio/1.AgenticAI/1.HelloAgenticAI/CLAUDE.md` — any cross-cutting context
5. `~/Documents/AISolutionPortfolio/.pre-commit-config.yaml` — to understand which hooks need re-scoping

If any HelloAgenticAI reference pattern is unclear or seems stale, flag it; don't improvise. The architect chat resolves contract ambiguities.

## Project layout context

```
~/Documents/AISolutionPortfolio/2.AssetsAI/1.RefineryDigitalTwin/
├── docs/                engineering docs (KB, briefings, findings)
│                        (renamed from 1.docs/ in item 2 of this briefing)
├── 2.automation/        scripts (Phase 0a probe, Stage 1 streamer)
├── 3.probes/phase0a/    Phase 0a output artifacts (read-only references)
├── 4.snapshots/stage1/  Stage 1 streamer output (created by streamer)
│
└── (this briefing creates:)
    ├── docs/ARCHITECTURE.md         mermaid diagram
    ├── docs/project-metadata.md     portfolio profile content
    ├── infra/                       Bicep + azd
    │   ├── main.bicep
    │   ├── modules/staticwebapp.bicep
    │   ├── azure.yaml
    │   └── placeholder/index.html
    └── .github/workflows/deploy.yml CI workflow
```

## Toolchain

- Same x86 venv from Phase 0a/Stage 1 (no Python work in this briefing — venv is just a record of the project's Python environment)
- `az cli` and `azure developer cli (azd)` — operator installs if not present (`brew install azure-cli` and `brew tap azure/azd && brew install azd`)
- Bicep comes bundled with `az cli`
- Lane discipline: ONLY modify files under `2.AssetsAI/1.RefineryDigitalTwin/`, with one explicit exception (the pre-commit config at the repo root). Do not touch any other repo-root file or any other project's files.

---

## Sequenced work items

### Item 1: Pre-commit re-scoping  (do this first)

**Where:** `~/Documents/AISolutionPortfolio/.pre-commit-config.yaml` (repo root — explicit exception to lane discipline)

**What:** Add `files: ^2\.AssetsAI/1\.RefineryDigitalTwin/` to every hook in the config so they only fire when files in this project's lane are modified.

**Why:** Currently hooks fire across the whole repo. This autoformatted `probe.py` mid-flight in Phase 0a (root cause of the post-processor workaround). The portfolio contract explicitly requires lane-scoped hooks.

**Constraints:**
- Add `files:` regex to existing hooks; do NOT add or remove hooks
- Do not rename or restructure the file
- Do not modify any other repo-root file in this session

**Acceptance:**
- A test commit that touches a file outside our lane should not trigger our hooks
- A test commit inside our lane should still trigger them

### Item 2: Path migration  (OPERATOR ACTION, post-Stage-1)

**Not Claude Code's job — documented here for completeness.**

After Stage 1 streamer closes (to avoid race conditions with the in-flight session), Sowthri runs:

```bash
cd ~/Documents/AISolutionPortfolio/2.AssetsAI/1.RefineryDigitalTwin/
git mv 1.docs docs
grep -rln '1\.docs' docs/ 2.automation/   # find any path references
# Manually update each occurrence found
git add -A
git commit -m "refactor: migrate 1.docs to docs per portfolio contract"
```

After this, all paths in this briefing's `docs/` references work. If item 3-6 are written before migration happens, they should target `docs/` as their final location and the operator's migration will land them in the right place.

### Item 3: `docs/ARCHITECTURE.md` with mermaid

**Where:** `2.AssetsAI/1.RefineryDigitalTwin/docs/ARCHITECTURE.md`

**What:** Markdown file with a mermaid diagram showing the 5-feature architecture. Mirror the structural conventions of `1.AgenticAI/1.HelloAgenticAI/docs/ARCHITECTURE.md`.

**Required content:**

- Project overview (~100 words)
- Mermaid diagram showing:
  - **DWSIM substrate** (Petroleum + Thermal Oil subsystems) at the bottom
  - **Streamer process** (Stage 1, long-running) in the middle, consuming substrate, emitting JSON snapshots
  - **Azure data fabric** (F1: Eventstream → Eventhouse → OneLake)
  - **Twin ontology** (F2: Fabric IQ, ISA-95)
  - **Agentic AI** (F3: Foundry agents, Azure OpenAI, MCP servers, AI Search)
  - **Experience layer** (F5: Real-Time Dashboard, Power BI, web UI, Omniverse 3D)
  - Arrows showing data flow direction (substrate → snapshots → Fabric → twin → agents → web)
- Brief 1-2 sentence description of each layer below the diagram
- Status indicators per layer: ✅ done / 🔄 in flight / ⬜ planned

**Acceptance:**
- Mermaid renders cleanly in GitHub's markdown preview
- Layers are clearly distinguished (use `subgraph` for grouping)
- Data flow direction is unambiguous

### Item 4: Bicep + azd skeleton

**Where:** `2.AssetsAI/1.RefineryDigitalTwin/infra/`

**What:** Bicep templates and azd config that provision a dedicated RG with a Static Web App hosting a placeholder landing page, output the demo URL for portfolio-site consumption.

**Files to create:**

```
infra/
├── main.bicep              top-level subscription-scoped template
├── modules/
│   └── staticwebapp.bicep  Static Web App resource module
├── azure.yaml              azd config
└── placeholder/
    └── index.html          minimal landing page
```

**`main.bicep` responsibilities:**

- `targetScope = 'subscription'`
- Parameter: `environmentName` (default: `dev`)
- Parameter: `location` (default: `eastus2` or whatever HelloAgenticAI uses; mirror)
- Resource: `rg-refinerydigitaltwin-${environmentName}` (created if missing)
- Module call: `staticwebapp.bicep` deployed into that RG
- Outputs:
  - `RESOURCE_GROUP_NAME` — the RG name
  - `DEMO_URL` — the Static Web App's `defaultHostname` prefixed with `https://`

**`staticwebapp.bicep` responsibilities:**

- Resource: `Microsoft.Web/staticSites`
- SKU: `Free` (sufficient for placeholder)
- No app source repo connection (we deploy the static content via azd, not via SWA's GitHub integration)
- Output: `defaultHostname`

**`azure.yaml` responsibilities:**

- Define `name: refinerydigitaltwin`
- Specify the Bicep template at `main.bicep`
- Define a service for the Static Web App pointing at `infra/placeholder/`

**`placeholder/index.html` content:**

- Title: "Refinery Digital Twin"
- Status section: "Phase 1 foundation complete. Stages 2-6 + Features 1, 2, 3, 5 in progress."
- Brief 50-word overview
- Link back to GitHub repo (`https://github.com/sowthri-industrial-ai/AISolutionPortfolio`)
- Plain HTML/CSS, no JS framework. Tailwind via CDN is acceptable but not required.
- Eventually replaced by Feature 5's demo UI; design accordingly (not too fancy, not embarrassingly bare)

**Acceptance:**

- `azd up --environment dev` provisions the RG and deploys the placeholder; outputs include `DEMO_URL`
- Visiting `DEMO_URL` shows the placeholder page in a browser
- `azd env get-values | grep DEMO_URL` returns the URL
- `azd down --purge --environment dev` removes the RG cleanly (verify in Azure portal: RG no longer exists)

### Item 5: `.github/workflows/deploy.yml`

**Where:** `2.AssetsAI/1.RefineryDigitalTwin/.github/workflows/deploy.yml`

**What:** GitHub Actions workflow with `workflow_dispatch` trigger accepting an `action` input of `provision | deploy | teardown`. Mirror the shape of `1.AgenticAI/1.HelloAgenticAI/.github/workflows/deploy.yml`.

**Workflow trigger:**

```yaml
on:
  workflow_dispatch:
    inputs:
      action:
        description: "Action to perform"
        required: true
        type: choice
        options:
          - provision
          - deploy
          - teardown
      environment:
        description: "Environment"
        required: false
        default: dev
```

**Job structure:**

- Single job (e.g. `run`)
- Runs on `ubuntu-latest`
- Uses Azure OIDC for auth — mirror HelloAgenticAI's secret/variable naming exactly (likely `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`)
- Working directory: `2.AssetsAI/1.RefineryDigitalTwin/infra/`
- Conditional steps based on `inputs.action`:
  - `provision` → `azd provision --environment ${{ inputs.environment }}`
  - `deploy` → `azd up --environment ${{ inputs.environment }} --no-prompt`
  - `teardown` → `azd down --environment ${{ inputs.environment }} --purge --force`

**Acceptance:**

- Workflow file passes YAML validation (`actionlint` or similar)
- All three action paths are present and conditional logic is correct
- OIDC auth follows the same pattern as HelloAgenticAI's deploy.yml
- A manual workflow_dispatch run with action=deploy successfully provisions and deploys; with action=teardown, removes cleanly

### Item 6: Project metadata

**Where:** Path and format defined by HelloAgenticAI's PROJECT_PLAN.md Phase 5 section. Most likely `2.AssetsAI/1.RefineryDigitalTwin/docs/project-metadata.md` but read the canonical spec to confirm.

**Required content (read HelloAgenticAI's own metadata file as a template):**

- Title: "Refinery Digital Twin"
- Tagline (~20 words): something like "Azure-native digital twin for petroleum distillation, grounded in DWSIM steady-state simulation."
- Overview (~150 words): the goal, the substrate, the 5-feature architecture, the demo experience
- Tech stack: DWSIM (Mono x86_64), Python 3.9.6, pythonnet 3.0.5, Microsoft Fabric (Eventstream + Eventhouse + OneLake), Fabric IQ Digital Twin Builder, DTDL, ISA-95, Foundry agents, Azure OpenAI, AI Search, MCP servers, Real-Time Dashboard, Power BI, NVIDIA Omniverse, Azure Static Web Apps
- Status: "Phase 1 foundation complete; Stages 2-5 + Features 1, 2, 3, 5 in progress" (update as phases land)
- Demo URL: pull from `azd env get-values | grep DEMO_URL`, or note that it's available at the URL output by `azd up`
- GitHub link: `https://github.com/sowthri-industrial-ai/AISolutionPortfolio/tree/main/2.AssetsAI/1.RefineryDigitalTwin`
- Screenshots section: placeholder for now — add as features land

**Format:** Mirror exactly what HelloAgenticAI's PROJECT_PLAN.md Phase 5 specifies (likely YAML frontmatter + markdown body, but defer to the spec). If unclear, copy HelloAgenticAI's own metadata file structure verbatim and substitute content.

**Acceptance:** File parses correctly per the format HelloAgenticAI defines. Portfolio site (when built) can read it without errors.

---

## Acceptance criteria (overall)

- [ ] `.pre-commit-config.yaml` updated; hooks scoped to `^2\.AssetsAI/1\.RefineryDigitalTwin/`
- [ ] Test: commit outside the lane does not trigger hooks; commit inside the lane does
- [ ] `docs/ARCHITECTURE.md` exists with mermaid that renders in GitHub
- [ ] `infra/` directory contains Bicep + azd files (main.bicep, modules/, azure.yaml, placeholder/)
- [ ] `azd up --environment dev` provisions `rg-refinerydigitaltwin-dev` and deploys placeholder Static Web App
- [ ] `azd env get-values | grep DEMO_URL` returns a working URL
- [ ] Visiting `DEMO_URL` in a browser shows the placeholder page
- [ ] `azd down --purge --environment dev` removes RG cleanly (verified in Azure portal)
- [ ] `.github/workflows/deploy.yml` exists with all three action paths (provision | deploy | teardown)
- [ ] Workflow passes YAML validation
- [ ] `docs/project-metadata.md` (or contract-specified name) exists per HelloAgenticAI's format
- [ ] All commits on branch `phase-1-foundation`; no direct pushes to `main`

## Anti-goals

- ✗ Build the shared portfolio website (that's HelloAgenticAI Phase 5)
- ✗ Build the Feature 5 demo UI (separate briefing, much later)
- ✗ Modify files outside `2.AssetsAI/1.RefineryDigitalTwin/`, except `.pre-commit-config.yaml` (the one scoped exception)
- ✗ Push to `origin/main` directly — use `phase-1-foundation` branch
- ✗ Add or remove pre-commit hooks (only add `files:` constraints)
- ✗ Create RGs other than `rg-refinerydigitaltwin-dev`
- ✗ Modify Phase 0a or Stage 1 artifacts in `3.probes/` or `4.snapshots/`
- ✗ Touch `docs/` beyond creating ARCHITECTURE.md and project-metadata.md (and the migration noted in item 2)
- ✗ Build anything in F1-F5 (Fabric, twin, agents, demo UI) — that's all later phases

## Methodology rules

- Lane discipline: only `2.AssetsAI/1.RefineryDigitalTwin/` plus the one pre-commit-config exception
- Branch: `phase-1-foundation` only; do not push to `main`
- Conventional commits: `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`
- Verify each Bicep deployment locally (`azd up`) before pushing the workflow file
- 3-attempt cap: if any item fails 3 times, stop and report; do not improvise

## Definition of done

1. All six work items completed per acceptance criteria
2. `azd up --environment dev` runs cleanly to completion on operator's machine
3. Operator visits the `DEMO_URL` in a browser, sees placeholder page
4. Operator runs `azd down --purge --environment dev`, verifies RG is deleted in Azure portal
5. Operator commits all changes to `phase-1-foundation` branch and pushes
6. Operator approves; architect issues next briefing (Stage 2 streamer JSONL, or Feature 1 Fabric ingestion)

## Hand-off note for Claude Code

This is a multi-deliverable foundation task. Items 1, 3, 4, 5, 6 are yours; item 2 (path migration) is operator territory and happens between sessions.

Read the four canonical pattern files first (HelloAgenticAI's `deploy.yml`, `docs/ARCHITECTURE.md`, `PROJECT_PLAN.md` Phase 5 section, `CLAUDE.md`). Mirror them for consistency. The portfolio contract is explicit that conventions are settled — do not propose alternatives.

Bicep + azd is the largest item — budget most of your session there. The other items are small (each 30 min - 1 hr).

If a HelloAgenticAI reference pattern is unclear or seems stale, flag it. The architect chat resolves contract-level ambiguities. Do not improvise around contract decisions.

End of briefing.
