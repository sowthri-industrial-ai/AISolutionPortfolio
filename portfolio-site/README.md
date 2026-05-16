# Portfolio Site

Astro + Tailwind static site for the AI Solution Portfolio. Hosted on Azure Static Web Apps (free tier).

**Live:** https://victorious-grass-0d2d45e03.7.azurestaticapps.net/

Architectural decision: see [`0002-portfolio-site-stack-astro.md`](../1.AgenticAI/1.HelloAgenticAI/docs/decisions/0002-portfolio-site-stack-astro.md) (HelloAgenticAI track owns the ADR; the portfolio site is the runtime).

## Local development

```bash
cd portfolio-site
npm install
npm run dev          # http://localhost:4321
```

## Build

```bash
npm run build        # produces dist/
npm run preview      # serves dist/ on http://localhost:4321
```

## Format

```bash
npm run format       # writes Prettier formatting
npm run format:check # verifies; CI quality gate uses this
```

## How to publish updates

```bash
cd portfolio-site/infra
azd deploy
```

That's it. The `prepackage` hook runs `npm ci && npm run build`, then azd uploads `dist/` to the Static Web App. `azure.yaml` lives in `infra/`, so run `azd deploy` from there (not the project root). No GitHub Actions in v1 — deployment trigger is Option A (`azd deploy`); migration to a GitHub Actions trigger is revisited in Phase 5c when OIDC federated credentials land.

First-time / fresh environment instead uses `azd provision` then `azd deploy` — see **Infrastructure** below.

## Observability

The Static Web App streams diagnostics to the **shared Phase 1 Log Analytics workspace** (`log-helloagenticai-dev-…` in `rg-helloagenticai-dev`) via a `swa-to-law` diagnostic setting — single-pane observability alongside HelloAgenticAI, whose App Insights component is workspace-based on the same LAW.

Wired categories: `StaticSiteHttpLogs` (HTTP request logs — status, path, latency, edge region), `StaticSiteDiagnosticLogs` (platform logs), `AllMetrics`. The LAW resource id is supplied at provision time via the `AZURE_PORTFOLIO_LAW_ID` azd env var; leaving it empty skips the diagnostic setting entirely (no error). See [`infra/modules/swa.bicep`](infra/modules/swa.bicep).

## Adding a project

Per ADR-0002, adding a project to the site is content-only:

1. Add `src/content/projects/<slug>.md` with frontmatter (`title`, `track`, `status`, `tagline`, `summary`, `techStack`, optional `githubPath` / `demoUrl`).
2. The home-grid card and the profile page at `/projects/<slug>` are generated automatically (Astro content collection + the `[...slug].astro` route).
3. *(Optional)* screenshots in `public/`.

## Infrastructure

```
portfolio-site/infra/
├── azure.yaml            # azd project + 'portfolio' service definition
├── main.bicep            # subscription-scoped: RG + SWA module
├── main.parameters.json  # env-driven params (incl. AZURE_PORTFOLIO_LAW_ID)
└── modules/swa.bicep     # SWA (Free) + optional LAW diagnostic setting
```

```bash
cd portfolio-site/infra
azd provision --preview   # dry-run validation
azd provision             # create / update RG + SWA + diagnostics
azd deploy                # publish the built site
```

Region: **West Europe** (`Microsoft.Web/staticSites` is not offered in swedencentral — see ADR-0003 risk #10). Resource group: `rg-helloagenticai-portfolio-dev`. SKU: Free.

## Layout

```
portfolio-site/
├── src/
│   ├── components/      # ProjectCard, TrackSection, DemoStatusIndicator, etc.
│   ├── content/         # Astro content collection — projects/*.md, now/*.md
│   ├── layouts/         # BaseLayout, ProjectProfile
│   ├── pages/           # index.astro (home), projects/[...slug].astro
│   └── styles/          # global.css with Tailwind directives
├── public/              # favicon, headshot.jpg, staticwebapp.config.json
├── infra/               # azd + Bicep (see Infrastructure above)
├── astro.config.mjs
├── tailwind.config.mjs
└── package.json
```

## Phase 5 batch status

- [x] Batch 1 — scaffolding (Astro + Tailwind + base layout)
- [x] Batch 2 — content collection schema + project entries
- [x] Batch 3 — components + home page
- [x] Batch 4 — project profile route + header/footer/home polish
- [x] Batch 5 — Bicep for Azure Static Web Apps + provision
- [x] Batch 6 — deploy + smoke-test + PR

Phase 5a complete — site is live. Later Phase 5 sub-phases (architecture diagrams, CI/OIDC, demo Launch button, evals) are tracked in HelloAgenticAI's `PROJECT_PLAN.md`.

Two project entries (`src/content/projects/helloagenticai.md`, `refinery-digital-twin.md`) and the track titles/descriptions in `src/components/TrackSection.astro` carry `DRAFT` markers pending Sowthri's copy review before the visitor-facing text is final.
