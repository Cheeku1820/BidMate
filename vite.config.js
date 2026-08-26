import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Two topologies run this file (task-16-brief.md §2):
//   - `npm run dev` on the host, against `docker compose up postgres api`
//     — the api container publishes on the HOST's localhost:8000, so
//     Vite (also on the host) reaches it at localhost:8000.
//   - `docker compose up`, everything containerised — Vite itself runs
//     inside the `web` container, where `localhost` means the container,
//     not the `api` container, so `localhost:8000` here would be
//     ECONNREFUSED with nothing obviously wrong. docker-compose.yml's
//     `web` service sets VITE_API_PROXY_TARGET to the Compose network
//     alias (`http://api:8000`) to cover this case.
// process.env, not import.meta.env: this file runs in Node at Vite
// config-load time, not in the browser.
const proxyTarget = process.env.VITE_API_PROXY_TARGET || "http://localhost:8000";
// The same signal doubles as "am I in the web container": there's no
// browser to open there, and Vite's `open: true` otherwise logs a
// harmless but scary `spawn xdg-open ENOENT` on every start.
const runningInCompose = Boolean(process.env.VITE_API_PROXY_TARGET);

export default defineConfig({
  base: "./",
  plugins: [react()],
  server: {
    port: 5173,
    open: !runningInCompose,
    // Same-origin in dev so the httpOnly session cookie (Task 16's login)
    // works with no CORS. Port 5173 itself is often already taken by an
    // unrelated app on this machine; if Vite picks another port instead,
    // that's fine and does not affect this proxy.
    proxy: {
      "/api": { target: proxyTarget, changeOrigin: false },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/setupTests.js"],
  },
});
