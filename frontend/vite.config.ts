import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  // Extension priority: prefer .tsx / .ts over .js so stray transpiled
  // siblings (some IDEs / Babel watchers create them on save) never win
  // resolution. Without this override, Vite's default order puts .js
  // before .tsx, which silently shipped stale UI to production.
  resolve: {
    extensions: [".tsx", ".ts", ".jsx", ".js", ".mjs", ".json"],
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/healthz": "http://localhost:8000",
    },
  },
  build: {
    outDir: "dist",
    assetsDir: "assets",
    sourcemap: false,
  },
});
