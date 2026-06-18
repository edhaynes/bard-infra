import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The console talks to the Registry/Router via VITE_REGISTRY_BASE / VITE_ROUTER_BASE
// (plain-HTTP + CORS on localhost for the demo); no dev proxy needed.
export default defineConfig({
  plugins: [react()],
});
