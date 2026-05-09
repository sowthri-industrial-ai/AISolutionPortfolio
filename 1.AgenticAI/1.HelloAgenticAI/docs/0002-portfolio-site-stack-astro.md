# 0002 — Portfolio Site Stack: Astro + Tailwind on Azure Static Web Apps

## Status

Accepted, 2026-05-09.

## Context

The portfolio (`AISolutionPortfolio`) needs a public-facing website to host one profile page per project and to surface the "Launch / Teardown demo" buttons that drive the Tier 2 on-demand demo provisioning (see ARCHITECTURE.md §Publishing strategy).

Constraints:

- Must be free or near-free to run continuously — it is the always-on tier
- Must integrate cleanly with GitHub Actions and Azure
- Must render mermaid diagrams natively — project ARCHITECTURE.md files are diagram-heavy
- Must support per-project profile pages with a consistent layout
- Must support a small amount of interactivity (Launch button, demo status indicator) without dragging in a full SPA
- Should look polished and "senior-engineer-made"

## Options considered

1. **Astro + Tailwind on Azure Static Web Apps** *(chosen)*
2. Next.js + Tailwind on Azure Static Web Apps — viable, more React overhead, larger bundles for what is fundamentally a content site
3. Plain HTML/CSS — simplest, but no markdown rendering and layouts get inconsistent as projects multiply
4. Hugo or Jekyll — purely static, but integrating modern interactive components (the Launch button) is awkward
5. SvelteKit — modern and fast, but smaller ecosystem than Astro for content-first sites

## Decision

Use **Astro** as the framework, **Tailwind CSS** for styling, deployed to **Azure Static Web Apps** (free tier).

Rationale:

- Content-first: project profile pages authored as markdown, importing diagrams from each project's `docs/ARCHITECTURE.md` directly
- Builds to fast static HTML — zero JS shipped by default
- Native mermaid rendering via `@astrojs/markdown-remark` plus `rehype-mermaid`
- Islands architecture — drop in React (or Vue / Svelte) components for the Launch button and status indicator without making the whole site React
- Static Web Apps free tier covers it indefinitely (100 GB bandwidth, unlimited static files)
- First-party Static Web Apps GitHub Actions deploy action
- Tailwind keeps styling consistent and avoids bespoke CSS sprawl as projects accumulate

## Consequences

Positive:

- Fast iteration on content — just markdown
- Each project's ARCHITECTURE.md diagrams render directly on its profile page
- Zero ongoing cost
- Adding a new project = a new markdown page + a navigation entry
- Per-component framework choice: islands can be React, Vue, or Svelte depending on fit

Negative:

- Smaller community than Next.js *(mitigation: Astro is mature and well-documented; the use case here is core Astro territory)*
- Heavy SPA interactivity later would require migrating off Astro *(mitigation: nothing in Phase 5 needs that; per-project demos remain free to use whatever fits — Chainlit for HelloAgenticAI, possibly a 3D viewer for RefineryDigitalTwin, etc.)*

## Scope

This decision applies to the portfolio site at `AISolutionPortfolio/portfolio-site/` (created in HelloAgenticAI Phase 5).

Individual project demos are **not constrained** by this decision — each project chooses the right stack for its own demo. The portfolio site only hosts profile pages and the Launch/Teardown control plane.

## References

- `1.AgenticAI/1.HelloAgenticAI/docs/ARCHITECTURE.md` §Publishing strategy
- `1.AgenticAI/1.HelloAgenticAI/PROJECT_PLAN.md` Phase 5
