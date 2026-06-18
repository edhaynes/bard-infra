// Audit types + plain-language rendering (Sprint B6, feature #64).
// Mirrors contracts/control-plane.openapi.yaml `GET /audit` (AuditView /
// AuditEntry) — kept in sync by hand like src/fleet.ts. Pure functions so
// the Activity pane stays trivially testable (§14: structure only).

export type AuditAction =
  | 'approve'
  | 'revoke'
  | 'rename'
  | 'workgroup'
  | 'plugin-enable'
  | 'plugin-disable'
  | 'plugin-config';

export interface AuditEntry {
  at: string;
  /** Token subject of the manager who performed the action. */
  actor: string;
  action: AuditAction;
  /** The acted-on device — or, for workgroup-scoped plugin actions, the
   *  workgroup NAME (Sprint B8 additive extension). */
  deviceId: string;
  /** New label for rename; group name for an assignment (absent = removed);
   *  the plugin's display name for plugin actions. */
  detail?: string;
  /** Plugin actions only (Sprint B8). */
  pluginId?: string;
  scope?: 'device' | 'workgroup';
}

export interface AuditView {
  entries: AuditEntry[];
  generatedAt: string;
}

/** "on Front desk PC" / 'for the "Front office" group' — plugin target text. */
function pluginTarget(entry: AuditEntry): string {
  return entry.scope === 'workgroup'
    ? `for the "${entry.deviceId}" group`
    : `on ${entry.deviceId}`;
}

function pluginName(entry: AuditEntry): string {
  return entry.detail ?? entry.pluginId ?? 'a plugin';
}

/** One plain-language sentence per entry (§1: no jargon, no field names). */
export function auditText(entry: AuditEntry): string {
  switch (entry.action) {
    case 'approve':
      return `Approved ${entry.deviceId}`;
    case 'revoke':
      return `Removed ${entry.deviceId}`;
    case 'rename':
      return `Renamed ${entry.deviceId} to "${entry.detail ?? ''}"`;
    case 'workgroup':
      return entry.detail !== undefined
        ? `Moved ${entry.deviceId} to the "${entry.detail}" group`
        : `Took ${entry.deviceId} out of its group`;
    case 'plugin-enable':
      return `Turned on ${pluginName(entry)} ${pluginTarget(entry)}`;
    case 'plugin-disable':
      return `Turned off ${pluginName(entry)} ${pluginTarget(entry)}`;
    case 'plugin-config':
      return `Changed ${pluginName(entry)} settings ${pluginTarget(entry)}`;
  }
}
