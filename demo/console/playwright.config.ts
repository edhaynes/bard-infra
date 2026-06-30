import { defineConfig } from "@playwright/test";

// Structural tests assume the orchestrator (7090) and the console preview/dev
// server are already running. baseURL points at the Vite dev server (5175).
export default defineConfig({
  testDir: "./tests",
  timeout: 90_000,
  use: {
    baseURL: process.env.CONSOLE_BASE ?? "http://127.0.0.1:5175",
    headless: true,
  },
  reporter: [["list"]],
});
