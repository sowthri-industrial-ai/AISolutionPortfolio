// @ts-check
import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';

// https://astro.build/config
export default defineConfig({
  // `site` is set in Batch 5 once the Static Web Apps URL is known.
  // Without it, Astro falls back to localhost — fine for dev + builds.
  integrations: [tailwind()],
});
