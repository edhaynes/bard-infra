import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Console talks to the orchestrator (CORS-enabled) at VITE_ORCH_BASE.
// Dev server on 5175 (matches the orchestrator's default CORS origin).
export default defineConfig({
  plugins: [react()],
  server: { port: 5175, host: "127.0.0.1" },
});
