import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: proxy /api to the FastAPI backend. Prod: `vite build` → web/dist, served by FastAPI at "/".
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        // VERSTKA_API: another backend (a second `verstka serve` on its own port while the first one keeps running)
        target: process.env.VERSTKA_API || "http://127.0.0.1:8000",
        changeOrigin: true,
        // SSE streams must not be buffered by the proxy
        configure: (proxy) => {
          proxy.on("proxyRes", (proxyRes) => {
            if (String(proxyRes.headers["content-type"] || "").includes("text/event-stream")) {
              proxyRes.headers["cache-control"] = "no-cache";
              proxyRes.headers["x-accel-buffering"] = "no";
            }
          });
        },
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
  },
});
