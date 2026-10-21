// Vite and Vitest configuration of the web UI: React plugin, a dev-server proxy that forwards
// "/api" to the local FastAPI backend (port 8000, prefix stripped) and the jsdom test setup.
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks: (id) => {
          if (id.includes("node_modules/uplot")) return "uplot";
          if (/node_modules\/(react|react-dom|scheduler)\//.test(id)) return "react";
          return undefined;
        },
      },
    },
  },
  server: { proxy: { "/api": { target: process.env.CROSSCUT_API ?? "http://127.0.0.1:8000", rewrite: (p) => p.replace(/^\/api/, "") } } },
  test: { exclude: ["e2e/**", "node_modules/**"], environment: "jsdom", globals: true, setupFiles: ["./src/setupTests.ts"] },
});
