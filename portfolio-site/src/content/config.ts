// Astro content collections — schemas for the portfolio site's
// project entries and the home-page "Now" callout. Phase 5a Batch 2.
//
// Adding a new project = drop a .md file under src/content/projects/.
// The Zod schema below validates its frontmatter at build time; the
// markdown body becomes the long-form profile-page content.
//
// `id` (the filename stem, e.g. `helloagenticai`) is the slug that
// drives the /projects/<id> route in Batch 4 — no separate `slug`
// field needed in frontmatter.

import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

// Track ids match the repo's three top-level track folders. The
// home page (Batch 3) renders one <TrackSection> per id, in this
// declared order.
const TRACK_IDS = ['agentic-ai', 'assets-ai', 'physical-ai'] as const;

// Project lifecycle status — drives the <DemoStatusIndicator> pill
// colour (Batch 3) and conditionally hides the demo CTA when a
// project has no public URL yet.
const STATUS_VALUES = ['Live', 'In Development', 'Planned'] as const;

const projects = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/projects' }),
  schema: z.object({
    /** Display title — shown on the card and as the profile-page H1. */
    title: z.string().min(1),
    /** Which top-level track this project belongs to. */
    track: z.enum(TRACK_IDS),
    /** Lifecycle status — drives status pill + conditional demo CTA. */
    status: z.enum(STATUS_VALUES),
    /** One sentence — fits under the title on the card. ~200 char cap to keep cards visually consistent. */
    tagline: z.string().min(1).max(200),
    /** One paragraph — renders on the card body. ~500 char cap so cards stay scannable. */
    summary: z.string().min(1).max(500),
    /** Tech-stack chip list. First N shown on card, full list on profile page. */
    techStack: z.array(z.string()).min(1),
    /** Path within this repo, e.g. "1.AgenticAI/1.HelloAgenticAI". <GitHubLink> resolves to https://github.com/sowthri-industrial-ai/AISolutionPortfolio/tree/main/<githubPath>. */
    githubPath: z.string().optional(),
    /** Public live URL. Only set when status="Live". */
    demoUrl: z.string().url().optional(),
    /** Path to the project's docs/ARCHITECTURE.md — forward-looking field for <ArchitectureDiagram> in Phase 5b. */
    architectureDocPath: z.string().optional(),
    /** Screenshots / images, paths under public/. Forward-looking for <ScreenshotGallery>. */
    screenshots: z.array(z.string()).optional(),
    /** Ascending order within a track. Lower = leftmost / topmost. */
    order: z.number().default(0),
  }),
});

// Single-entry collection for the home-page "Now" hero. Updating it
// is a one-file edit (src/content/now/current.md). Keeping it as a
// content collection (rather than a free file under src/data/) means
// the markdown body benefits from the same Astro rendering pipeline
// projects use, and we get a typed entry id (`current`).
const now = defineCollection({
  loader: glob({ pattern: '*.md', base: './src/content/now' }),
  schema: z.object({
    /** When this snapshot was last refreshed. Optional; the home page may surface "as of <date>" text in a later batch. */
    updated: z.coerce.date().optional(),
  }),
});

export const collections = { projects, now };
