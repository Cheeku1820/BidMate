import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { viteSingleFile } from "vite-plugin-singlefile";

/* ============================================================
   vite.demo.config.js — builds demo/index.html, the single-file,
   file://-openable build the README calls out as "fastest, no
   install" (final-review fix 4).

   Before this file existed, demo/index.html was a hand-made artifact
   with no reproducible build path — nothing in package.json,
   vite.config.js, or the GitHub Actions workflows produced it, so it
   silently predated whatever the client actually does today. It
   predated this branch's router entirely (no react-router references
   in the committed bundle), which defeats the reason App.jsx chose
   HashRouter over BrowserRouter in the first place (router-base.test.jsx):
   HashRouter was picked *specifically* to keep this file:// path
   working, and shipping a stale bundle wastes that.

   vite-plugin-singlefile inlines every JS and CSS asset into one HTML
   file with no separate chunk requests — the reason the original file
   had to be hand-assembled at all is that a browser refuses to fetch
   an ES module script over file://, which is exactly what a normal
   multi-chunk `vite build` produces. Its own docs list "SPA hash-based
   routing" as supported, matching the HashRouter choice above.

   Deliberately a separate config rather than a flag on vite.config.js:
   the normal `npm run build` output (dist/) is a multi-file build meant
   to be served over http(s) (GitHub Pages, the `web` Docker container),
   and inlining everything into one file there would just make that
   build slower and heavier for no benefit anything there needs.

   Seed mode only: VITE_DATA_SOURCE is never set for this build (the
   "build:demo" script in package.json clears it explicitly, in case a
   developer's shell happens to export it for the api-mode build) --
   demo/index.html has no backend behind it to talk to, so shipping it
   wired to api mode would just be a login screen that can never sign
   in, per README's "npm run dev alone still runs the seed/localStorage
   mode" contract.
   ============================================================ */
export default defineConfig({
  base: "./",
  plugins: [react(), viteSingleFile()],
  build: {
    outDir: "demo",
    emptyOutDir: true,
  },
});
