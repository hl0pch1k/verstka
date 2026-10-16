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
    rollupOptions: {
      output: {
        // четыре куска, и ни один не перерастает предел предупреждения Vite (500 kB): библиотеки (React) — `vendor`;
        // логика без интерфейса (src/lib, api.ts, types.ts: тексты, разбор событий агента, запросы к API) — `lib`, она не
        // импортирует ни компонентов, ни store, так что куски не ссылаются друг на друга по кругу; интерфейс — основной
        // кусок. Первые три грузятся сразу; содержимое листа «Подробнее» (ui/details/SheetPanels — вкладки, «Почему так» с
        // данными) — отдельный ленивый кусок: его спрашивают в свободное время после первой отрисовки и при открытии
        // листа (ui/details/lazySheet)
        manualChunks: (id) => {
          if (id.includes("node_modules")) return "vendor";
          if (/\/src\/(lib\/|api\.ts$|types\.ts$)/.test(id)) return "lib";
          return undefined;
        },
      },
    },
  },
});
