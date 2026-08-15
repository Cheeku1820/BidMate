import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "./",
  plugins: [react()],
  server: {
    port: 5173,
    open: true,
    // Same-origin in dev so the httpOnly session cookie (Task 16's login)
    // works with no CORS — proxies to the Compose api service, published
    // on 8000 by docker-compose.yml. Port 5173 itself is often already
    // taken by an unrelated app on this machine; if Vite picks another
    // port instead, that's fine and does not affect this proxy.
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: false },
    },
  },
  test: {
    environment: "jsdom",
  },
});
