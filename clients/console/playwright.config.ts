import { defineConfig, devices } from '@playwright/test';

// Structural tests only (§14): elements exist, classes applied, grouping
// correct. They prove structure, NOT visual correctness — screenshots are
// Eddie's sign-off. The API is mocked per-test via page.route(); the env
// below points at a port nothing listens on so an unmocked request can
// never silently hit a live service.
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: 'list',
  use: {
    // Vite binds the IPv6 localhost on modern Node; use the name, not 127.0.0.1.
    baseURL: 'http://localhost:5273',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'npm run dev',
    port: 5273,
    reuseExistingServer: !process.env.CI,
    env: {
      // Test-only placeholders — NOT credentials. 8099: nothing listens there.
      VITE_API_BASE_URL: 'http://127.0.0.1:8099',
      VITE_API_TOKEN: 'playwright-structural-test-token',
      VITE_USE_SAMPLE_DATA: 'false',
    },
  },
});
