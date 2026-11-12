import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const api = "http://127.0.0.1:8000";
const proxied = ["/auth", "/alerts", "/cases", "/audit", "/agent", "/stream", "/metrics",
  "/transactions", "/graph", "/simulate"];

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: Object.fromEntries(proxied.map((p) => [p, api])) },
  // AG Grid is slow to render in jsdom, and slower still while the machine is busy
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test-setup.ts"], testTimeout: 15000 },
});
