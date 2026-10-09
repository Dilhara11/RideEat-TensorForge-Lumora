// Build: static files in dist/, hosted on their own (AWS Amplify, see amplify.yml at the repo root).
//        The API address is baked in from VITE_API_BASE_URL at build time.
// Dev:   `npm run dev` on :5173 proxies API calls to the engine on :8000 (leave VITE_API_BASE_URL unset).
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const ENGINE = process.env.ENGINE_URL ?? "http://127.0.0.1:8000";
const API_PATHS = ["/health", "/predict", "/batch", "/docs", "/redoc", "/openapi.json"];

export default defineConfig(() => ({
  base: "/",
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(API_PATHS.map((p) => [p, { target: ENGINE, changeOrigin: true }])),
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    assetsDir: "assets",
    sourcemap: false,
    chunkSizeWarningLimit: 600,
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
}));
