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

## Multi-project support

The portfolio site is **one shared Astro app**, not duplicated per project. Every project in the portfolio (HelloAgenticAI, RefineryDigitalTwin, and any future projects under `1.AgenticAI/`, `2.AssetsAI/`, `3.PhysicalAI/`) gets a profile page on the same site.

Adding a new project to the site requires three additions to the portfolio-site repo only:

1. A markdown file at `src/content/<project-slug>.md` with project frontmatter (title, summary, tech stack, GitHub link, demo metadata, screenshots)
2. A profile page at `src/pages/<project-slug>.astro` — typically a one-liner that delegates to a shared `<ProjectProfile>` layout component
3. *(Optional)* screenshots and GIFs in `public/<project-slug>/`

Reusable components, built once, used by every project's profile page:

- `<ProjectCard>` — homepage grid card
- `<LaunchButton project="<slug>" />` — accepts the project slug as a prop, calls the shared Azure Function with that slug, the Function dispatches the corresponding project's GitHub Actions workflow, which provisions the right RG (`rg-<slug>-{env}`)
- `<ArchitectureDiagram>` — pulls the mermaid diagram from each project's `docs/ARCHITECTURE.md` automatically
- `<TechStackTable>`, `<DemoStatusIndicator>`, `<ScreenshotGallery>`, `<GitHubLink>`

Per-project contract — every project, regardless of its internal architecture, must provide:

1. A mermaid architecture diagram in `<project-root>/docs/ARCHITECTURE.md`
2. A GitHub Actions workflow at `<project-root>/.github/workflows/deploy.yml` accepting `workflow_dispatch` with an `action` input of `provision | deploy | teardown`. Reference shape: `1.AgenticAI/1.HelloAgenticAI/.github/workflows/deploy.yml`.
3. An `azd up`–deployable Bicep stack that targets a dedicated RG named `rg-<project-slug>-{env}` and outputs the live demo URL via `azd env get-values`
4. Project metadata in the form expected by the portfolio site's content folder (defined in HelloAgenticAI Phase 5)

**Result:** adding any new project to the portfolio site is ~20 lines of code, not a new website. RefineryDigitalTwin, future agentic projects, future asset-AI projects all plug into the same site through the four-point contract above.

## References

- `1.AgenticAI/1.HelloAgenticAI/docs/ARCHITECTURE.md` §Publishing strategy
- `1.AgenticAI/1.HelloAgenticAI/PROJECT_PLAN.md` Phase 5
