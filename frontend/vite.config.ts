import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const api = "http://127.0.0.1:8000";
const proxied = ["/auth", "/alerts", "/cases", "/audit", "/agent", "/stream", "/metrics",
  "/transactions", "/graph", "/simulate"];

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: Object.fromEntries(proxied.map((p) => [p, api])) },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test-setup.ts"] },
});
