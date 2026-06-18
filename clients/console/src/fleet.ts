// Fleet view types + pure presentation helpers (Sprint B5, feature #64).
// Mirrors contracts/control-plane.openapi.yaml `GET /fleet` (FleetView /
// FleetDevice) — kept in sync by hand like src/types.ts; a generator is a
// follow-up. All functions here are pure so the rendering stays trivially
// testable and the Playwright suite only asserts structure (§14).

/** Heartbeat-derived liveness (see the contract's `connection` description). */
export type Connection = 'online' | 'stale' | 'offline';

/** Enrollment lifecycle (enrollment.schema.json); null = pre-identity agent. */
export type Enrollment = 'pending' | 'active' | 'revoked' | null;

/** contracts/power-profile.schema.yaml */
export interface PowerProfile {
  name: string;
  cpus?: number;
  memory?: string;
  pidsLimit?: number;
  gpus?: string | null;
  batteryAware?: boolean;
}

export interface FleetWorkgroup {
  workgroupId: string;
  name: string;
}

export interface FleetDevice {
  id: string;
  label?: string;
  enrollment: Enrollment;
  connection: Connection;
  lastSeen: string | null;
  address?: string;
  capabilities?: string[];
  powerProfile?: PowerProfile;
  /** Always null from the v2 Registry; populated when assignment ships (B6). */
  workgroup: FleetWorkgroup | null;
}

export interface FleetView {
  devices: FleetDevice[];
  generatedAt: string;
}

// --- plain-language labels (§1: the user is a non-technical SMB owner) ------

export const UNGROUPED_NAME = 'Not in a workgroup yet';

const CONNECTION_LABELS: Record<Connection, string> = {
  online: 'Online',
  stale: 'Not responding',
  offline: 'Offline',
};

export function connectionLabel(connection: Connection): string {
  return CONNECTION_LABELS[connection];
}

export function enrollmentLabel(enrollment: Enrollment): string | null {
  switch (enrollment) {
    case 'pending':
      return 'Waiting for approval';
    case 'revoked':
      return 'Access removed';
    // 'active' is the normal state — no badge; the status badge carries the news.
    default:
      return null;
  }
}

export function deviceDisplayName(device: FleetDevice): string {
  return device.label ?? device.id;
}

const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;

/** "Never" / "Just now" / "5 minutes ago" / "3 hours ago" / "2 days ago". */
export function lastSeenText(lastSeen: string | null, nowMs: number): string {
  if (lastSeen === null) return 'Never';
  const age = nowMs - Date.parse(lastSeen);
  if (age < MINUTE_MS) return 'Just now';
  if (age < HOUR_MS) return plural(Math.floor(age / MINUTE_MS), 'minute');
  if (age < DAY_MS) return plural(Math.floor(age / HOUR_MS), 'hour');
  return plural(Math.floor(age / DAY_MS), 'day');
}

function plural(n: number, unit: string): string {
  return `${n} ${unit}${n === 1 ? '' : 's'} ago`;
}

// --- grouping (trust.schema.yaml: workgroups contain devices) ---------------

export interface DeviceGroup {
  /** null for the "not yet assigned" bucket. */
  workgroupId: string | null;
  name: string;
  devices: FleetDevice[];
}

/**
 * Group devices by workgroup, alphabetical by group name, with the
 * "Not in a workgroup yet" bucket always last. Device order within a group
 * follows the server's (display-name sorted) order.
 */
export function groupDevices(devices: FleetDevice[]): DeviceGroup[] {
  const grouped = new Map<string, DeviceGroup>();
  const ungrouped: DeviceGroup = { workgroupId: null, name: UNGROUPED_NAME, devices: [] };
  for (const device of devices) {
    if (device.workgroup === null) {
      ungrouped.devices.push(device);
      continue;
    }
    const existing = grouped.get(device.workgroup.workgroupId);
    if (existing) {
      existing.devices.push(device);
    } else {
      grouped.set(device.workgroup.workgroupId, {
        workgroupId: device.workgroup.workgroupId,
        name: device.workgroup.name,
        devices: [device],
      });
    }
  }
  const groups = [...grouped.values()].sort((a, b) => a.name.localeCompare(b.name));
  if (ungrouped.devices.length > 0) groups.push(ungrouped);
  return groups;
}
