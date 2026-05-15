# Portfolio Site

Astro + Tailwind static site for the AI Solution Portfolio. Hosted on Azure Static Web Apps (free tier).

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

## Adding a project

(Wired in Batch 2 — once the content collection schema lands. Update this section then.)

## Layout

```
portfolio-site/
├── src/
│   ├── components/      # ProjectCard, TrackSection, etc. (Batch 3+)
│   ├── content/         # Astro content collection — projects/*.md (Batch 2)
│   ├── layouts/         # BaseLayout, ProjectProfile (Batch 4)
│   ├── pages/           # index.astro (home), projects/[...slug].astro (Batch 4)
│   └── styles/          # global.css with Tailwind directives
├── public/              # favicon, og image, screenshots
├── astro.config.mjs
├── tailwind.config.mjs
└── package.json
```

## Phase 5 batch status

- [x] Batch 1 — scaffolding (Astro + Tailwind + base layout + smoke page)
- [ ] Batch 2 — content collection schema + project entries
- [ ] Batch 3 — components + home page
- [ ] Batch 4 — project profile route + polish
- [ ] Batch 5 — Bicep for Azure Static Web Apps
- [ ] Batch 6 — deploy + smoke + PR
