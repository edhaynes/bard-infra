// Reproducible screenshots of the Fleet node-tree pane in SAMPLE mode — the
// §14 visual-review artifact (feature #91). Spawns vite with
// VITE_USE_SAMPLE_DATA=true, drives Playwright's bundled chromium, and writes
// PNGs to clients/console/screenshots/ (gitignored). No backend needed.
//
//   node scripts/capture-screenshots.mjs
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { setTimeout as sleep } from 'node:timers/promises';
import { chromium } from '@playwright/test';

const PORT = 5399;
const BASE = `http://localhost:${PORT}`;
const OUT = fileURLToPath(new URL('../screenshots/', import.meta.url));
mkdirSync(OUT, { recursive: true });

const server = spawn('npx', ['vite', '--port', String(PORT), '--strictPort'], {
  env: { ...process.env, VITE_USE_SAMPLE_DATA: 'true' },
  stdio: 'inherit',
});

let browser;
try {
  // Wait for vite to answer.
  let up = false;
  for (let i = 0; i < 60 && !up; i++) {
    try {
      const r = await fetch(BASE);
      up = r.ok;
    } catch {
      /* not up yet */
    }
    if (!up) await sleep(500);
  }
  if (!up) throw new Error(`vite did not come up on ${BASE}`);

  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1160, height: 900 } });
  await page.goto(BASE);
  await page.locator('nav .nav-fleet').click();
  await page.waitForSelector('.fleet-summary');

  await page.screenshot({ path: `${OUT}fleet-collapsed.png`, fullPage: true });

  // Expand every node to show the full facts panels.
  for (const toggle of await page.locator('.node-toggle').all()) await toggle.click();
  await page.waitForSelector('.node-expanded .node-facts');
  await page.screenshot({ path: `${OUT}fleet-expanded.png`, fullPage: true });

  console.log(`SCREENSHOTS: wrote fleet-collapsed.png + fleet-expanded.png to ${OUT}`);
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM');
}
