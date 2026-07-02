// Structural tests (§14) for the Fleet node tree (Sprint S4, feature #91):
// the tree renders one row per node from a mocked GET /nodes payload,
// expanding a node reveals its facts panel (CPU / memory / GPU / storage /
// networking), and a no-GPU node shows "None". The API is mocked with
// page.route — no live network. These prove STRUCTURE only; visual
// correctness is signed off by a human from screenshots.
import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';

function mockNodes() {
  const now = Date.now();
  const gatheredAt = new Date(now - 5 * 60_000).toISOString();
  return {
    generatedAt: new Date(now).toISOString(),
    nodes: [
      {
        nodeId: 'gx10',
        cpu: { model: 'NVIDIA Grace GB10', arch: 'aarch64', cores: 20, vcpus: 20 },
        memory: { totalMb: 131072 },
        gpu: { model: 'NVIDIA GB10', memoryMb: 131072 },
        storage: [
          { device: 'nvme0n1', sizeGb: 1024 },
          { device: 'nvme1n1', sizeGb: 4096 },
        ],
        networking: [
          { iface: 'enp1s0', ipv4: '192.168.1.20', speedMbps: 10000 },
          { iface: 'wlan0', ipv4: null, speedMbps: null },
        ],
        gatheredAt,
      },
      {
        nodeId: 'snoopy',
        cpu: { model: 'Intel Core i5-8259U', arch: 'x86_64', cores: 4, vcpus: 8 },
        memory: { totalMb: 16384 },
        gpu: null,
        storage: [{ device: 'sda', sizeGb: 512 }],
        networking: [{ iface: 'eth0', ipv4: '192.168.1.31', speedMbps: 1000 }],
        gatheredAt,
      },
    ],
  };
}

async function openFleetPane(page: Page, body: unknown = mockNodes()) {
  // The Devices pane loads /fleet on mount; keep it mocked so nothing races
  // onto a live service (the config env points at a dead port).
  await page.route('**/fleet', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ generatedAt: new Date().toISOString(), devices: [] }),
    }),
  );
  await page.route('**/nodes', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) }),
  );
  await page.goto('/');
  await page.locator('nav .nav-fleet').click();
  await expect(page.getByRole('heading', { level: 1, name: 'Fleet' })).toBeVisible();
}

test('the tree renders one row per node, sorted by id', async ({ page }) => {
  await openFleetPane(page);
  const rows = page.locator('.fleet-tree .node-row');
  await expect(rows).toHaveCount(2);
  // buildNodeTree sorts by nodeId: gx10 before snoopy.
  await expect(rows.nth(0)).toHaveAttribute('data-node-id', 'gx10');
  await expect(rows.nth(1)).toHaveAttribute('data-node-id', 'snoopy');
  // Collapsed summary reads in plain language.
  await expect(rows.nth(0).locator('.node-name')).toHaveText('gx10');
  await expect(rows.nth(0).locator('.node-summary')).toContainText('20 cores');
  await expect(rows.nth(0).locator('.node-summary')).toContainText('128 GB');
});

test('the fleet summary strip totals the fleet capacity', async ({ page }) => {
  await openFleetPane(page);
  const summary = page.locator('.fleet-summary');
  await expect(summary).toBeVisible();
  // gx10 (20 vcpu, 128 GB, GPU, 1+4 TB) + snoopy (8 vcpu, 16 GB, no GPU, 512 GB).
  await expect(summary.locator('.stat-machines .stat-value')).toHaveText('2');
  await expect(summary.locator('.stat-threads .stat-value')).toHaveText('28');
  await expect(summary.locator('.stat-memory .stat-value')).toHaveText('144 GB');
  await expect(summary.locator('.stat-storage .stat-value')).toHaveText('5.5 TB');
  await expect(summary.locator('.stat-gpus .stat-value')).toHaveText('1');
  // Freshness line reuses the tested lastSeenText helper.
  await expect(page.locator('.fleet-gathered')).toContainText('Hardware facts last gathered');
});

test('facts are hidden until a node is expanded', async ({ page }) => {
  await openFleetPane(page);
  const gx10 = page.locator('[data-node-id="gx10"]');
  await expect(gx10).not.toHaveClass(/node-expanded/);
  await expect(gx10.locator('.node-facts')).toHaveCount(0);
});

test('expanding a node reveals the full facts panel', async ({ page }) => {
  await openFleetPane(page);
  const gx10 = page.locator('[data-node-id="gx10"]');
  await gx10.locator('.node-toggle').click();
  await expect(gx10).toHaveClass(/node-expanded/);

  const facts = gx10.locator('.node-facts');
  await expect(facts).toHaveCount(1);
  // CPU: model, arch, cores, threads.
  await expect(facts.locator('.fact-cpu')).toContainText('NVIDIA Grace GB10');
  await expect(facts.locator('.fact-cpu')).toContainText('aarch64');
  await expect(facts.locator('.fact-cpu')).toContainText('20 cores');
  // Memory formatted MB -> GB.
  await expect(facts.locator('.fact-memory')).toContainText('128 GB');
  // GPU present.
  await expect(facts.locator('.fact-gpu')).toContainText('NVIDIA GB10');
  // Storage: one line per disk, GB and TB formatting.
  await expect(facts.locator('.fact-storage .fact-storage-item')).toHaveCount(2);
  await expect(facts.locator('.fact-storage')).toContainText('nvme0n1 — 1 TB');
  await expect(facts.locator('.fact-storage')).toContainText('nvme1n1 — 4 TB');
  // Networking: one line per interface; missing address/speed degrade to words.
  await expect(facts.locator('.fact-networking .fact-networking-item')).toHaveCount(2);
  await expect(facts.locator('.fact-networking')).toContainText('enp1s0 — 192.168.1.20 — 10000 Mbps');
  await expect(facts.locator('.fact-networking')).toContainText('wlan0 — No address — Speed unknown');
});

test('a no-GPU node shows "None"', async ({ page }) => {
  await openFleetPane(page);
  const snoopy = page.locator('[data-node-id="snoopy"]');
  await expect(snoopy.locator('.node-summary')).toContainText('No graphics card');
  await snoopy.locator('.node-toggle').click();
  await expect(snoopy.locator('.node-facts .fact-gpu')).toContainText('None');
});

test('a node collapses again on a second click', async ({ page }) => {
  await openFleetPane(page);
  const gx10 = page.locator('[data-node-id="gx10"]');
  await gx10.locator('.node-toggle').click();
  await expect(gx10.locator('.node-facts')).toHaveCount(1);
  await gx10.locator('.node-toggle').click();
  await expect(gx10).not.toHaveClass(/node-expanded/);
  await expect(gx10.locator('.node-facts')).toHaveCount(0);
});

test('empty node list shows a friendly empty state', async ({ page }) => {
  await openFleetPane(page, { generatedAt: new Date().toISOString(), nodes: [] });
  await expect(page.locator('.empty-fleet')).toContainText('No machine details yet');
  await expect(page.locator('.node-row')).toHaveCount(0);
  // No capacity strip when there is nothing to total.
  await expect(page.locator('.fleet-summary')).toHaveCount(0);
});

test('a GET /nodes failure fails loudly — error banner, no silent fallback', async ({ page }) => {
  await page.route('**/fleet', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ generatedAt: new Date().toISOString(), devices: [] }),
    }),
  );
  await page.route('**/nodes', (route) =>
    route.fulfill({ status: 500, contentType: 'application/json', body: '{"error":"boom"}' }),
  );
  await page.goto('/');
  await page.locator('nav .nav-fleet').click();
  await expect(page.locator('.fetch-error')).toBeVisible();
  await expect(page.locator('.fetch-error')).toContainText('Could not load your machines');
  await expect(page.locator('.node-row')).toHaveCount(0);
  await expect(page.locator('.sample-banner')).toHaveCount(0);
});
