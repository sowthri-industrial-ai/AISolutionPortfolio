import typography from '@tailwindcss/typography';

/** @type {import('tailwindcss').Config} */
export default {
  // Astro pages + components + content collection markdown bodies
  content: ['./src/**/*.{astro,html,js,jsx,md,mdx,ts,tsx}'],
  theme: {
    extend: {
      // Status-pill colours wired in Batch 3 when <DemoStatusIndicator>
      // lands. Kept blank in Batch 1 so we don't bake premature
      // visual decisions into the theme.
    },
  },
  plugins: [
    // `prose` class for rendering markdown bodies on project profile
    // pages (Batch 4). Adds ~5 KB compressed; replaces the need for
    // bespoke heading/paragraph CSS as projects accumulate.
    typography,
  ],
};
