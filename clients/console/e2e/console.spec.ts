// Structural tests (§14): elements exist, device rows render from a mocked
// API payload, status classes applied, grouping correct, and (Sprint B6) the
// manage actions are wired — clicking a button fires the right request and
// the UI reflects the mocked state change. The API is mocked with page.route
// — no live network. These tests prove STRUCTURE only; visual correctness is
// signed off by a human from screenshots.
import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';

const MINUTE_MS = 60_000;

function mockFleet() {
  const now = Date.now();
  return {
    generatedAt: new Date(now).toISOString(),
    devices: [
      {
        id: 'dev-front-desk',
        label: 'Front desk PC',
        enrollment: 'active',
        connection: 'online',
        lastSeen: new Date(now - MINUTE_MS / 2).toISOString(),
        address: 'front-desk.local:8444',
        capabilities: ['llm'],
        powerProfile: { name: 'laptop', cpus: 2, memory: '2g', gpus: null },
        workgroup: { workgroupId: 'wg_front_office_e2e001', name: 'Front office' },
      },
      {
        id: 'dev-front-printer-pc',
        label: 'Printer PC',
        enrollment: 'active',
        connection: 'stale',
        lastSeen: new Date(now - 90 * MINUTE_MS).toISOString(),
        address: 'printer-pc.local:8444',
        workgroup: { workgroupId: 'wg_front_office_e2e001', name: 'Front office' },
      },
      {
        id: 'dev-workshop-server',
        label: 'Workshop server',
        enrollment: 'active',
        connection: 'online',
        lastSeen: new Date(now - MINUTE_MS).toISOString(),
        address: 'workshop.local:8444',
        capabilities: ['gpu', 'llm'],
        powerProfile: { name: 'gpu-server', cpus: 16, memory: '32g', gpus: 'all' },
        workgroup: { workgroupId: 'wg_back_office_e2e0001', name: 'Back office' },
      },
      {
        id: 'dev-owners-laptop',
        label: "Owner's laptop",
        enrollment: 'pending',
        connection: 'offline',
        lastSeen: null,
        workgroup: null,
      },
    ],
  };
}

async function openConsoleWithFleet(page: Page, body: unknown = mockFleet()) {
  await page.route('**/fleet', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) }),
  );
  await page.goto('/');
}

test('shell renders the Devices pane', async ({ page }) => {
  await openConsoleWithFleet(page);
  await expect(page.locator('nav')).toContainText('Bard · Console');
  await expect(page.getByRole('heading', { level: 1, name: 'Devices' })).toBeVisible();
});

test('device rows render from the mocked API payload', async ({ page }) => {
  await openConsoleWithFleet(page);
  await expect(page.locator('.device-row')).toHaveCount(4);
  for (const name of ['Front desk PC', 'Printer PC', 'Workshop server', "Owner's laptop"]) {
    await expect(page.locator('.device-name', { hasText: name })).toBeVisible();
  }
  // Plain-language facts, not JSON field names.
  await expect(page.locator('[data-device-id="dev-front-desk"]')).toContainText('Last seen:');
  await expect(page.locator('[data-device-id="dev-workshop-server"]')).toContainText('Processors');
  await expect(page.locator('[data-device-id="dev-workshop-server"]')).toContainText('Memory');
});

test('status classes and plain-language status labels are applied', async ({ page }) => {
  await openConsoleWithFleet(page);
  const frontDesk = page.locator('[data-device-id="dev-front-desk"]');
  await expect(frontDesk).toHaveClass(/connection-online/);
  await expect(frontDesk.locator('.status-badge.status-online')).toHaveText('Online');

  const printer = page.locator('[data-device-id="dev-front-printer-pc"]');
  await expect(printer).toHaveClass(/connection-stale/);
  await expect(printer.locator('.status-badge.status-stale')).toHaveText('Not responding');

  const laptop = page.locator('[data-device-id="dev-owners-laptop"]');
  await expect(laptop).toHaveClass(/connection-offline/);
  await expect(laptop.locator('.status-badge.status-offline')).toHaveText('Offline');
  await expect(laptop).toContainText('Last seen: Never');
  await expect(laptop.locator('.approval-badge')).toHaveText('Waiting for approval');
});

test('devices are grouped by workgroup, unassigned last', async ({ page }) => {
  await openConsoleWithFleet(page);
  const groups = page.locator('.workgroup-group');
  await expect(groups).toHaveCount(3);
  // Alphabetical groups first, the "not yet assigned" bucket always last.
  await expect(groups.nth(0)).toHaveAttribute('data-workgroup', 'Back office');
  await expect(groups.nth(1)).toHaveAttribute('data-workgroup', 'Front office');
  await expect(groups.nth(2)).toHaveAttribute('data-workgroup', 'Not in a workgroup yet');

  const frontOffice = page.locator('[data-workgroup="Front office"]');
  await expect(frontOffice.locator('.device-row')).toHaveCount(2);
  await expect(frontOffice).toContainText('Front desk PC');
  await expect(frontOffice).toContainText('Printer PC');
  await expect(frontOffice).toContainText('2 devices');

  const unassigned = page.locator('[data-workgroup="Not in a workgroup yet"]');
  await expect(unassigned.locator('.device-row')).toHaveCount(1);
  await expect(unassigned).toContainText("Owner's laptop");
});

// --- Sprint B6: manage actions (mocked API, structure only) -----------------

const AUTH = 'Bearer playwright-structural-test-token';

test('action buttons exist with plain-language labels; Approve only on pending', async ({
  page,
}) => {
  await openConsoleWithFleet(page);
  const laptop = page.locator('[data-device-id="dev-owners-laptop"]');
  await expect(laptop.locator('.action-approve')).toHaveText('Approve');
  await expect(laptop.locator('.action-rename')).toHaveText('Rename');
  await expect(laptop.locator('.action-group')).toHaveText('Group');
  await expect(laptop.locator('.action-remove')).toHaveText('Remove device');
  // Active devices have no Approve button.
  await expect(page.locator('[data-device-id="dev-front-desk"] .action-approve')).toHaveCount(0);
  await expect(page.locator('[data-device-id="dev-front-desk"] .action-remove')).toHaveCount(1);
});

test('Approve fires the approve request, shows the one-time code, and refreshes', async ({
  page,
}) => {
  await openConsoleWithFleet(page);
  // Let the initial fleet render before swapping the /fleet mock, or the
  // first fetch could race onto the post-approve payload.
  await expect(page.locator('[data-device-id="dev-owners-laptop"] .action-approve')).toBeVisible();
  await page.route('**/devices/dev-owners-laptop/approve', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        device: { deviceId: 'dev-owners-laptop', state: 'active', createdAt: '2026-06-12' },
        deviceSecret: 'one-time-code-abc123',
      }),
    }),
  );
  // The refresh after the mutation returns the updated fleet (newer route wins).
  const updated = mockFleet();
  const laptopRow = updated.devices.find((d) => d.id === 'dev-owners-laptop');
  laptopRow.enrollment = 'active';
  await page.route('**/fleet', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(updated) }),
  );

  const approveRequest = page.waitForRequest(
    (req) => req.url().includes('/devices/dev-owners-laptop/approve') && req.method() === 'POST',
  );
  await page.locator('[data-device-id="dev-owners-laptop"] .action-approve').click();
  const request = await approveRequest;
  expect(request.headers()['authorization']).toBe(AUTH);

  // The one-time secret is surfaced exactly where the manager can copy it...
  await expect(page.locator('.approve-secret')).toBeVisible();
  await expect(page.locator('.approve-secret-code')).toHaveText('one-time-code-abc123');
  // ...and the refreshed list no longer shows the waiting badge.
  await expect(
    page.locator('[data-device-id="dev-owners-laptop"] .approval-badge'),
  ).toHaveCount(0);
  // The banner dismisses.
  await page.locator('.approve-secret-dismiss').click();
  await expect(page.locator('.approve-secret')).toHaveCount(0);
});

test('Remove device confirms, then fires the revoke request', async ({ page }) => {
  await openConsoleWithFleet(page);
  await page.route('**/devices/dev-front-desk/revoke', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ device: { deviceId: 'dev-front-desk', state: 'revoked' } }),
    }),
  );
  page.once('dialog', (dialog) => {
    expect(dialog.type()).toBe('confirm');
    expect(dialog.message()).toContain('Remove Front desk PC?');
    void dialog.accept();
  });
  const revokeRequest = page.waitForRequest(
    (req) => req.url().includes('/devices/dev-front-desk/revoke') && req.method() === 'POST',
  );
  await page.locator('[data-device-id="dev-front-desk"] .action-remove').click();
  expect((await revokeRequest).headers()['authorization']).toBe(AUTH);
});

test('Rename prompts for the new name and sends it', async ({ page }) => {
  await openConsoleWithFleet(page);
  await page.route('**/devices/dev-front-desk/rename', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ device: { deviceId: 'dev-front-desk', state: 'active' } }),
    }),
  );
  page.once('dialog', (dialog) => {
    expect(dialog.type()).toBe('prompt');
    void dialog.accept('Reception PC');
  });
  const renameRequest = page.waitForRequest(
    (req) => req.url().includes('/devices/dev-front-desk/rename') && req.method() === 'POST',
  );
  await page.locator('[data-device-id="dev-front-desk"] .action-rename').click();
  const request = await renameRequest;
  expect(request.postDataJSON()).toEqual({ label: 'Reception PC' });
  expect(request.headers()['authorization']).toBe(AUTH);
});

test('Group prompts for the group name; empty answer clears the group', async ({ page }) => {
  await openConsoleWithFleet(page);
  await page.route('**/devices/dev-owners-laptop/workgroup', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ device: { deviceId: 'dev-owners-laptop', state: 'pending' } }),
    }),
  );
  page.once('dialog', (dialog) => void dialog.accept('Front office'));
  const assignRequest = page.waitForRequest(
    (req) => req.url().includes('/devices/dev-owners-laptop/workgroup') && req.method() === 'POST',
  );
  await page.locator('[data-device-id="dev-owners-laptop"] .action-group').click();
  expect((await assignRequest).postDataJSON()).toEqual({ name: 'Front office' });

  // Empty answer = take it out of its group (name: null on the wire).
  page.once('dialog', (dialog) => void dialog.accept(''));
  const clearRequest = page.waitForRequest(
    (req) => req.url().includes('/devices/dev-owners-laptop/workgroup') && req.method() === 'POST',
  );
  await page.locator('[data-device-id="dev-owners-laptop"] .action-group').click();
  expect((await clearRequest).postDataJSON()).toEqual({ name: null });
});

test('Activity pane renders audit entries in plain language', async ({ page }) => {
  await openConsoleWithFleet(page);
  await page.route('**/audit', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        generatedAt: new Date().toISOString(),
        entries: [
          {
            at: '2026-06-12T12:02:00+00:00',
            actor: 'eddie',
            action: 'workgroup',
            deviceId: 'dev-front-desk',
            detail: 'Front office',
          },
          {
            at: '2026-06-12T12:01:00+00:00',
            actor: 'eddie',
            action: 'rename',
            deviceId: 'dev-front-desk',
            detail: 'Front desk PC',
          },
          {
            at: '2026-06-12T12:00:00+00:00',
            actor: 'eddie',
            action: 'approve',
            deviceId: 'dev-front-desk',
          },
        ],
      }),
    }),
  );
  await page.locator('nav .nav-activity').click();
  await expect(page.getByRole('heading', { level: 1, name: 'Activity' })).toBeVisible();
  const entries = page.locator('.audit-entry');
  await expect(entries).toHaveCount(3);
  await expect(entries.nth(0)).toContainText('Moved dev-front-desk to the "Front office" group');
  await expect(entries.nth(1)).toContainText('Renamed dev-front-desk to "Front desk PC"');
  await expect(entries.nth(2)).toContainText('Approved dev-front-desk');
  await expect(entries.nth(2)).toContainText('by eddie');
});

test('Activity pane shows a friendly empty state', async ({ page }) => {
  await openConsoleWithFleet(page);
  await page.route('**/audit', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ generatedAt: new Date().toISOString(), entries: [] }),
    }),
  );
  await page.locator('nav .nav-activity').click();
  await expect(page.locator('.empty-audit')).toContainText('No activity yet');
});

// --- Sprint B8: Plugins pane (mocked API, structure only) --------------------

function mockPlugins() {
  return {
    generatedAt: new Date().toISOString(),
    plugins: [
      {
        manifest: {
          id: 'pro.bardllm.ssh',
          version: '0.3.1',
          displayName: 'SSH / SCP',
          description: 'Remote shell and file transfer to fleet devices.',
          kind: 'service',
          healthEndpoint: '/healthz',
          entry: { type: 'container', target: 'ghcr.io/edhaynes/bard-ssh:0.3.1' },
          configSchema: {
            type: 'object',
            required: ['listenPort'],
            properties: {
              listenPort: { type: 'integer', default: 2200, description: 'Port the relay listens on.' },
              allowScp: { type: 'boolean', default: true },
            },
          },
        },
        enabledDevices: [],
        enabledWorkgroups: [{ workgroupId: 'wg_front_office_e2e001', name: 'Front office' }],
        health: [
          { deviceId: 'dev-front-desk', status: 'ok', reportedAt: new Date().toISOString() },
          { deviceId: 'dev-workshop-server', status: 'stale', reportedAt: new Date().toISOString() },
        ],
      },
      {
        manifest: {
          id: 'pro.bardllm.squawk-box',
          version: '1.0.0',
          displayName: 'Squawk Box',
          description: 'Push-to-talk walkie-talkie for the fleet.',
          kind: 'client',
          healthEndpoint: null,
          entry: { type: 'module', target: 'clients.squawk_box:create_client' },
          configSchema: {
            type: 'object',
            required: ['channel'],
            properties: {
              channel: { type: 'string', description: 'Channel the device joins on enable.' },
              pushToTalk: { type: 'boolean', default: true },
              squelch: {
                type: 'object',
                description: 'Noise gate for loud jobsites.',
                properties: {
                  enabled: { type: 'boolean', default: true },
                  threshold: { type: 'number', minimum: -90, maximum: 0, default: -45 },
                  side: { type: 'string', enum: ['sender', 'receiver', 'both'], default: 'sender' },
                },
              },
            },
          },
        },
        enabledDevices: [],
        enabledWorkgroups: [],
        health: null,
      },
    ],
  };
}

async function openPluginsPane(page: Page) {
  await openConsoleWithFleet(page);
  await page.route('**/plugins', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockPlugins()),
    }),
  );
  await page.route('**/plugins/*/config?*', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"config":{}}' }),
  );
  await page.locator('nav .nav-plugins').click();
}

test('Plugins pane renders the catalog from the mocked API', async ({ page }) => {
  await openPluginsPane(page);
  await expect(page.getByRole('heading', { level: 1, name: 'Plugins' })).toBeVisible();
  await expect(page.locator('.plugin-card')).toHaveCount(2);
  await expect(page.locator('.plugin-name', { hasText: 'SSH / SCP' })).toBeVisible();
  await expect(page.locator('.plugin-name', { hasText: 'Squawk Box' })).toBeVisible();
  // Enable state in plain language: a chip per place the plugin is on.
  const ssh = page.locator('[data-plugin-id="pro.bardllm.ssh"]');
  await expect(ssh.locator('.plugin-enabled-chip')).toHaveText('On for Front office group');
  const squawk = page.locator('[data-plugin-id="pro.bardllm.squawk-box"]');
  await expect(squawk.locator('.plugin-enabled-for')).toContainText('Not turned on anywhere yet');
});

test('plugin health shows in plain words; unmonitored plugin shows none', async ({ page }) => {
  await openPluginsPane(page);
  const ssh = page.locator('[data-plugin-id="pro.bardllm.ssh"]');
  await expect(ssh.locator('.plugin-health-entry.health-ok')).toContainText('Working');
  await expect(ssh.locator('.plugin-health-entry.health-stale')).toContainText('Not responding');
  // Squawk Box declares no health endpoint — no health section at all.
  const squawk = page.locator('[data-plugin-id="pro.bardllm.squawk-box"]');
  await expect(squawk.locator('.plugin-health')).toHaveCount(0);
});

test('config form renders from the manifest schema with plain-language labels', async ({
  page,
}) => {
  await openPluginsPane(page);
  const squawk = page.locator('[data-plugin-id="pro.bardllm.squawk-box"]');
  const form = squawk.locator('.plugin-config-form');
  // Labels are humanized from the schema keys — never raw field names.
  await expect(form.locator('.field-channel')).toContainText('Channel');
  await expect(form.locator('.field-pushToTalk')).toContainText('Push to talk');
  await expect(form.locator('.field-pushToTalk input[type=checkbox]')).toBeChecked(); // default
  // The nested squelch object renders as a labeled group with its own fields.
  const squelch = form.locator('.plugin-field-group.field-squelch');
  await expect(squelch.locator('legend')).toHaveText('Squelch');
  await expect(squelch.locator('.field-threshold input[type=number]')).toHaveValue('-45');
  await expect(squelch.locator('.field-side select')).toHaveValue('sender');
});

test('Advanced raw-JSON section is collapsed by default and opens on demand', async ({
  page,
}) => {
  await openPluginsPane(page);
  const squawk = page.locator('[data-plugin-id="pro.bardllm.squawk-box"]');
  await expect(squawk.locator('.plugin-advanced')).toHaveCount(1);
  await expect(squawk.locator('.plugin-advanced-json')).toBeHidden();
  await squawk.locator('.plugin-advanced summary').click();
  await expect(squawk.locator('.plugin-advanced-json')).toBeVisible();
});

test('Turn on fires the enable request with the scope, target and form config', async ({
  page,
}) => {
  await openPluginsPane(page);
  const squawk = page.locator('[data-plugin-id="pro.bardllm.squawk-box"]');
  await page.route('**/plugins/pro.bardllm.squawk-box/enable', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockPlugins().plugins[1]),
    }),
  );
  await squawk.locator('.plugin-target').selectOption({ label: 'Group: Front office' });
  await squawk.locator('.field-channel input').fill('crew-north');
  const enableRequest = page.waitForRequest(
    (req) => req.url().includes('/plugins/pro.bardllm.squawk-box/enable') && req.method() === 'POST',
  );
  await squawk.locator('.plugin-toggle').click();
  const request = await enableRequest;
  expect(request.headers()['authorization']).toBe(AUTH);
  expect(request.postDataJSON()).toEqual({
    scope: 'workgroup',
    target: 'Front office',
    config: {
      channel: 'crew-north',
      pushToTalk: true,
      squelch: { enabled: true, threshold: -45, side: 'sender' },
    },
  });
});

test('toggle reflects enable state per target and Turn off fires disable', async ({ page }) => {
  await openPluginsPane(page);
  const ssh = page.locator('[data-plugin-id="pro.bardllm.ssh"]');
  // Default target (Group: Back office) is not enabled -> "Turn on".
  await expect(ssh.locator('.plugin-toggle')).toHaveText('Turn on');
  // The enabled workgroup -> "Turn off", and clicking fires the disable.
  await ssh.locator('.plugin-target').selectOption({ label: 'Group: Front office' });
  await expect(ssh.locator('.plugin-toggle')).toHaveText('Turn off');
  await page.route('**/plugins/pro.bardllm.ssh/disable', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockPlugins().plugins[0]),
    }),
  );
  const disableRequest = page.waitForRequest(
    (req) => req.url().includes('/plugins/pro.bardllm.ssh/disable') && req.method() === 'POST',
  );
  await ssh.locator('.plugin-toggle').click();
  expect((await disableRequest).postDataJSON()).toEqual({
    scope: 'workgroup',
    target: 'Front office',
  });
});

test('saving settings sends the validated config for the picked target', async ({ page }) => {
  await openPluginsPane(page);
  const ssh = page.locator('[data-plugin-id="pro.bardllm.ssh"]');
  await page.route('**/plugins/pro.bardllm.ssh/config', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '{"config":{"listenPort":2222,"allowScp":true}}',
    }),
  );
  await ssh.locator('.plugin-target').selectOption({ label: 'Device: Front desk PC' });
  await ssh.locator('.field-listenPort input').fill('2222');
  const saveRequest = page.waitForRequest(
    (req) => req.url().endsWith('/plugins/pro.bardllm.ssh/config') && req.method() === 'PUT',
  );
  await ssh.locator('.plugin-config-save').click();
  const request = await saveRequest;
  expect(request.postDataJSON()).toEqual({
    scope: 'device',
    target: 'dev-front-desk',
    config: { listenPort: 2222, allowScp: true },
  });
  await expect(ssh.locator('.plugin-notice')).toContainText('Settings saved');
});

test('API failure fails loudly — error banner, no silent sample fallback', async ({ page }) => {
  await page.route('**/fleet', (route) =>
    route.fulfill({ status: 500, contentType: 'application/json', body: '{"error":"boom"}' }),
  );
  await page.goto('/');
  await expect(page.locator('.fetch-error')).toBeVisible();
  await expect(page.locator('.fetch-error')).toContainText('Could not update the device list');
  await expect(page.locator('.device-row')).toHaveCount(0);
  await expect(page.locator('.sample-banner')).toHaveCount(0);
});

test('empty fleet shows a friendly empty state', async ({ page }) => {
  await openConsoleWithFleet(page, { generatedAt: new Date().toISOString(), devices: [] });
  await expect(page.locator('.empty-fleet')).toContainText('No devices yet');
  await expect(page.locator('.device-row')).toHaveCount(0);
});
