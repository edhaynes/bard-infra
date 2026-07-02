import { useCallback, useEffect, useMemo, useState } from 'react';
import { ControlPlaneClient } from './api';
import { auditText } from './audit';
import type { AuditView } from './audit';
import { loadConfig } from './config';
import type { ConsoleConfig } from './config';
import {
  connectionLabel,
  deviceDisplayName,
  enrollmentLabel,
  groupDevices,
  lastSeenText,
} from './fleet';
import type { Connection, FleetDevice, FleetView } from './fleet';
import { FleetPane } from './FleetPane';
import { PluginsPane } from './PluginsPane';
import { buildSampleFleet } from './sampleData';
import { s } from './styles';

// Bard console — Sprint B5 wired the real fleet view from the control plane
// (contracts/control-plane.openapi.yaml GET /fleet); Sprint B6 adds the
// manage actions (Approve / Remove device / Rename / Group) and the
// read-only Activity pane (GET /audit); Sprint B8 adds the managed Plugins
// pane (src/PluginsPane.tsx — enable/disable per device/workgroup, settings,
// health). Every request goes through the typed seam in src/api.ts.
//
// Plain language throughout (§1): the reader is a small-business owner,
// not a developer. No JSON field names, no jargon on the surface.

const VERSION = '0.3.0';
// How often the device list refreshes. Matches the Registry heartbeat scale
// (agent TTL 45s) — frequent enough to feel live, gentle enough for a tailnet.
const REFRESH_MS = 10_000;

const config: ConsoleConfig = loadConfig(import.meta.env as Record<string, string | undefined>);

type Pane = 'devices' | 'fleet' | 'plugins' | 'activity';

export function App() {
  const [pane, setPane] = useState<Pane>('devices');
  const client = useMemo(
    () =>
      config.mode === 'api' && config.apiBaseUrl && config.apiToken
        ? new ControlPlaneClient(config.apiBaseUrl, config.apiToken)
        : null,
    [],
  );

  return (
    <div style={s.shell} className="console-shell">
      <nav style={s.nav}>
        <div style={s.brand}>Bard · Console</div>
        <button
          className="nav-devices"
          style={{ ...s.navItem, ...(pane === 'devices' ? s.navItemActive : {}) }}
          onClick={() => setPane('devices')}
        >
          Devices
        </button>
        <button
          className="nav-fleet"
          style={{ ...s.navItem, ...(pane === 'fleet' ? s.navItemActive : {}) }}
          onClick={() => setPane('fleet')}
        >
          Fleet
        </button>
        <button
          className="nav-plugins"
          style={{ ...s.navItem, ...(pane === 'plugins' ? s.navItemActive : {}) }}
          onClick={() => setPane('plugins')}
        >
          Plugins
        </button>
        <button
          className="nav-activity"
          style={{ ...s.navItem, ...(pane === 'activity' ? s.navItemActive : {}) }}
          onClick={() => setPane('activity')}
        >
          Activity
        </button>
        <div style={s.version}>
          v{VERSION}
          {config.mode === 'sample' ? ' · sample data' : ''}
        </div>
      </nav>
      <main style={s.main}>
        {config.errors.length > 0 ? (
          <ConfigErrorPanel errors={config.errors} />
        ) : pane === 'devices' ? (
          <DevicesPane client={client} />
        ) : pane === 'fleet' ? (
          <FleetPane client={client} />
        ) : pane === 'plugins' ? (
          <PluginsPane client={client} />
        ) : (
          <ActivityPane client={client} />
        )}
      </main>
    </div>
  );
}

/** Configuration problems render loudly and nothing else renders (§0.11). */
function ConfigErrorPanel({ errors }: { errors: string[] }) {
  return (
    <div style={s.errorBanner} className="config-error" role="alert">
      <div style={s.errorTitle}>The console is not set up yet</div>
      {errors.map((message) => (
        <p key={message} style={s.errorText}>
          {message}
        </p>
      ))}
    </div>
  );
}

/** The one-time device code shown after an approval (it is never re-emitted). */
interface ApprovedSecret {
  deviceName: string;
  secret: string;
}

function DevicesPane({ client }: { client: ControlPlaneClient | null }) {
  const [fleet, setFleet] = useState<FleetView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [approvedSecret, setApprovedSecret] = useState<ApprovedSecret | null>(null);

  const load = useCallback(async () => {
    if (client === null) return;
    try {
      const view = await client.fetchFleet();
      setFleet(view);
      setError(null);
    } catch (cause) {
      // Fail loudly: surface the message, keep the last good list on
      // screen, and NEVER swap in sample data (§0.11).
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }, [client]);

  useEffect(() => {
    if (client === null) {
      // Explicit demo mode only — loadConfig never routes here as a fallback.
      setFleet(buildSampleFleet(Date.now()));
      return;
    }
    let cancelled = false;
    const tick = async () => {
      if (!cancelled) await load();
    };
    void tick();
    const timer = setInterval(() => void tick(), REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [client, load]);

  /** Run one manage action, then refresh the list so the change shows. */
  const act = useCallback(
    async (action: () => Promise<void>) => {
      try {
        await action();
        await load();
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : String(cause));
      }
    },
    [load],
  );

  const actions =
    client === null
      ? null
      : {
          approve: (device: FleetDevice) =>
            act(async () => {
              const result = await client.approveDevice(device.id);
              setApprovedSecret({
                deviceName: deviceDisplayName(device),
                secret: result.deviceSecret,
              });
            }),
          remove: (device: FleetDevice) => {
            const ok = window.confirm(
              `Remove ${deviceDisplayName(device)}? It will lose access to your fleet right away.`,
            );
            if (!ok) return;
            void act(async () => {
              await client.revokeDevice(device.id);
            });
          },
          rename: (device: FleetDevice) => {
            const label = window.prompt('New name for this device', deviceDisplayName(device));
            if (label === null || label.trim() === '') return;
            void act(async () => {
              await client.renameDevice(device.id, label.trim());
            });
          },
          group: (device: FleetDevice) => {
            const name = window.prompt(
              'Which group should this device be in? Leave empty to take it out of its group.',
              device.workgroup?.name ?? '',
            );
            if (name === null) return;
            void act(async () => {
              await client.assignWorkgroup(device.id, name.trim() === '' ? null : name.trim());
            });
          },
        };

  const groups = fleet ? groupDevices(fleet.devices) : [];

  return (
    <div>
      <h1 style={s.h1}>Devices</h1>
      <p style={s.dim}>Every machine in your fleet. The list refreshes automatically.</p>
      {config.mode === 'sample' && (
        <div style={s.sampleBanner} className="sample-banner">
          Showing sample data (demo mode). These are not your real devices.
        </div>
      )}
      {error !== null && (
        <div style={s.errorBanner} className="fetch-error" role="alert">
          <div style={s.errorTitle}>Could not update the device list</div>
          <p style={s.errorText}>{error}</p>
        </div>
      )}
      {approvedSecret !== null && (
        <div style={s.secretBanner} className="approve-secret" role="alert">
          <div style={s.errorTitle}>{approvedSecret.deviceName} is approved</div>
          <p style={s.errorText}>
            Give this one-time code to the device — it is shown only once and cannot be looked
            up later:
          </p>
          <code style={s.secretCode} className="approve-secret-code">
            {approvedSecret.secret}
          </code>
          <div>
            <button
              style={s.secretDismiss}
              className="approve-secret-dismiss"
              onClick={() => setApprovedSecret(null)}
            >
              OK, I saved it
            </button>
          </div>
        </div>
      )}
      {fleet === null && error === null && (
        <p style={s.dim} className="loading">
          Checking your devices…
        </p>
      )}
      {fleet !== null && fleet.devices.length === 0 && (
        <p style={s.dim} className="empty-fleet">
          No devices yet. Add your first machine from its setup screen, and it will appear here.
        </p>
      )}
      {groups.map((group) => (
        <section key={group.name} style={s.group} className="workgroup-group" data-workgroup={group.name}>
          <h2 style={s.h2}>
            {group.name}{' '}
            <span style={s.groupCount}>
              {group.devices.length} {group.devices.length === 1 ? 'device' : 'devices'}
            </span>
          </h2>
          {group.devices.map((device) => (
            <DeviceRow key={device.id} device={device} nowMs={Date.now()} actions={actions} />
          ))}
        </section>
      ))}
    </div>
  );
}

interface DeviceActions {
  approve: (device: FleetDevice) => void;
  remove: (device: FleetDevice) => void;
  rename: (device: FleetDevice) => void;
  group: (device: FleetDevice) => void;
}

// Status + facts, plus the manage actions (Sprint B6). Actions need a device
// record, so pre-identity agent-only rows (enrollment null) stay read-only;
// sample mode (actions null) is read-only too.
function DeviceRow({
  device,
  nowMs,
  actions,
}: {
  device: FleetDevice;
  nowMs: number;
  actions: DeviceActions | null;
}) {
  const profile = device.powerProfile;
  const approval = enrollmentLabel(device.enrollment);
  const manageable = actions !== null && device.enrollment !== null;
  return (
    <div
      style={s.card}
      className={`device-row connection-${device.connection}`}
      data-device-id={device.id}
    >
      <div style={s.cardTitle} className="device-name">
        {deviceDisplayName(device)}
        <StatusBadge connection={device.connection} />
        {approval !== null && (
          <span style={{ ...s.badge, ...s.badgeApproval }} className="approval-badge">
            {approval}
          </span>
        )}
      </div>
      <div style={s.dim} className="device-last-seen">
        Last seen: {lastSeenText(device.lastSeen, nowMs)}
      </div>
      {(profile !== undefined || device.capabilities !== undefined) && (
        <div style={s.caps} className="device-facts">
          {profile?.cpus !== undefined && <Cap k="Processors" v={String(profile.cpus)} />}
          {profile?.memory !== undefined && <Cap k="Memory" v={profile.memory} />}
          {profile !== undefined && (
            <Cap k="Graphics card" v={profile.gpus != null ? 'Yes' : 'None'} />
          )}
          {device.capabilities !== undefined && (
            <Cap k="Can run" v={device.capabilities.join(', ')} />
          )}
        </div>
      )}
      {manageable && (
        <div style={s.actions} className="device-actions">
          {device.enrollment === 'pending' && (
            <button
              style={{ ...s.actionBtn, ...s.actionPrimary }}
              className="action-approve"
              onClick={() => actions.approve(device)}
            >
              Approve
            </button>
          )}
          <button style={s.actionBtn} className="action-rename" onClick={() => actions.rename(device)}>
            Rename
          </button>
          <button style={s.actionBtn} className="action-group" onClick={() => actions.group(device)}>
            Group
          </button>
          {device.enrollment !== 'revoked' && (
            <button
              style={{ ...s.actionBtn, ...s.actionDanger }}
              className="action-remove"
              onClick={() => actions.remove(device)}
            >
              Remove device
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// Read-only history of changes made from this console (GET /audit).
function ActivityPane({ client }: { client: ControlPlaneClient | null }) {
  const [view, setView] = useState<AuditView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (client === null) return;
    client
      .fetchAudit()
      .then((body) => {
        setView(body);
        setError(null);
      })
      .catch((cause: unknown) => {
        setError(cause instanceof Error ? cause.message : String(cause));
      });
  }, [client]);

  if (client === null) {
    return (
      <div>
        <h1 style={s.h1}>Activity</h1>
        <p style={s.dim} className="audit-unavailable">
          Activity is not available with sample data.
        </p>
      </div>
    );
  }

  return (
    <div>
      <h1 style={s.h1}>Activity</h1>
      <p style={s.dim}>A record of every change made from this console, newest first.</p>
      {error !== null && (
        <div style={s.errorBanner} className="fetch-error" role="alert">
          <div style={s.errorTitle}>Could not load the activity list</div>
          <p style={s.errorText}>{error}</p>
        </div>
      )}
      {view !== null && view.entries.length === 0 && (
        <p style={s.dim} className="empty-audit">
          No activity yet. Changes you make on the Devices page will show up here.
        </p>
      )}
      {view !== null &&
        view.entries.map((entry, index) => (
          <div key={`${entry.at}-${index}`} style={s.card} className="audit-entry">
            <div style={s.cardTitle} className="audit-entry-text">
              {auditText(entry)}
            </div>
            <div style={s.dim} className="audit-entry-meta">
              {new Date(entry.at).toLocaleString()} · by {entry.actor}
            </div>
          </div>
        ))}
    </div>
  );
}

function StatusBadge({ connection }: { connection: Connection }) {
  const palette: Record<Connection, React.CSSProperties> = {
    online: s.badgeOnline,
    stale: s.badgeStale,
    offline: s.badgeOffline,
  };
  return (
    <span style={{ ...s.badge, ...palette[connection] }} className={`status-badge status-${connection}`}>
      {connectionLabel(connection)}
    </span>
  );
}

function Cap({ k, v }: { k: string; v: string }) {
  return (
    <div style={s.capItem}>
      <div style={s.capKey}>{k}</div>
      <div style={s.capVal}>{v}</div>
    </div>
  );
}

// Styles live in src/styles.ts since Sprint B8 (shared with PluginsPane).
