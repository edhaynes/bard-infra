// Typed control-plane API client (contracts/control-plane.openapi.yaml).
//
// This file is the single seam between the console and the control plane:
// every endpoint the console talks to gets a typed method here, and the UI
// never hand-builds a request. Sprint B5 added the read-only fleet view;
// Sprint B6 adds the manage actions (approve / revoke / rename / workgroup)
// and the audit read.

import type { AuditView } from './audit';
import type { FleetView } from './fleet';
import type { NodesView } from './nodes';
import type { PluginCatalogView, PluginScopeKind, PluginStatus } from './plugins';

/** POST /devices/{id}/approve 200 (enrollment.schema.json ApproveResponse).
 *  The device secret is disclosed EXACTLY ONCE here — the UI must show it
 *  to the manager immediately; it can never be fetched again. */
export interface ApproveResult {
  device: unknown;
  deviceSecret: string;
}

export class ControlPlaneClient {
  constructor(
    private readonly baseUrl: string,
    private readonly token: string,
  ) {}

  /** GET /fleet — the fleet view (devices, status, capabilities, groups). */
  async fetchFleet(): Promise<FleetView> {
    return this.request<FleetView>('/fleet');
  }

  /** GET /audit — management action history, newest first (Sprint B6). */
  async fetchAudit(): Promise<AuditView> {
    return this.request<AuditView>('/audit');
  }

  /** GET /nodes — per-node hardware facts for the Fleet tree (Sprint S4,
   *  feature #91). Read-only; the heavy facts payload is kept off the fast
   *  device-list refresh by living on its own endpoint. */
  async fetchNodes(): Promise<NodesView> {
    return this.request<NodesView>('/nodes');
  }

  /** POST /devices/{id}/approve — pending device joins the fleet. */
  async approveDevice(deviceId: string): Promise<ApproveResult> {
    return this.request<ApproveResult>(`/devices/${encodeURIComponent(deviceId)}/approve`, {
      method: 'POST',
    });
  }

  /** POST /devices/{id}/revoke — device loses access immediately. */
  async revokeDevice(deviceId: string): Promise<unknown> {
    return this.request(`/devices/${encodeURIComponent(deviceId)}/revoke`, { method: 'POST' });
  }

  /** POST /devices/{id}/rename — set the human name shown in the console. */
  async renameDevice(deviceId: string, label: string): Promise<unknown> {
    return this.request(`/devices/${encodeURIComponent(deviceId)}/rename`, {
      method: 'POST',
      body: JSON.stringify({ label }),
    });
  }

  /** POST /devices/{id}/workgroup — put in a group by name; null takes it out. */
  async assignWorkgroup(deviceId: string, name: string | null): Promise<unknown> {
    return this.request(`/devices/${encodeURIComponent(deviceId)}/workgroup`, {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
  }

  // --- Plugins (Sprint B8, feature #65) -------------------------------------

  /** GET /plugins — the catalog with enable state and reported health. */
  async fetchPlugins(): Promise<PluginCatalogView> {
    return this.request<PluginCatalogView>('/plugins');
  }

  /** POST /plugins/{id}/enable — turn it on for one device/workgroup target.
   *  The config travels with the enable; the server validates it against the
   *  manifest's own settings schema and refuses an invalid enable. */
  async enablePlugin(
    pluginId: string,
    scope: PluginScopeKind,
    target: string,
    config?: Record<string, unknown>,
  ): Promise<PluginStatus> {
    return this.request<PluginStatus>(`/plugins/${encodeURIComponent(pluginId)}/enable`, {
      method: 'POST',
      body: JSON.stringify(config !== undefined ? { scope, target, config } : { scope, target }),
    });
  }

  /** POST /plugins/{id}/disable — turn it off for one target (settings kept). */
  async disablePlugin(
    pluginId: string,
    scope: PluginScopeKind,
    target: string,
  ): Promise<PluginStatus> {
    return this.request<PluginStatus>(`/plugins/${encodeURIComponent(pluginId)}/disable`, {
      method: 'POST',
      body: JSON.stringify({ scope, target }),
    });
  }

  /** GET /plugins/{id}/config — the stored settings for one target ({} if none). */
  async fetchPluginConfig(
    pluginId: string,
    scope: PluginScopeKind,
    target: string,
  ): Promise<{ config: Record<string, unknown> }> {
    const query = `scope=${encodeURIComponent(scope)}&target=${encodeURIComponent(target)}`;
    return this.request(`/plugins/${encodeURIComponent(pluginId)}/config?${query}`);
  }

  /** PUT /plugins/{id}/config — store settings for one target (validated first). */
  async savePluginConfig(
    pluginId: string,
    scope: PluginScopeKind,
    target: string,
    config: Record<string, unknown>,
  ): Promise<{ config: Record<string, unknown> }> {
    return this.request(`/plugins/${encodeURIComponent(pluginId)}/config`, {
      method: 'PUT',
      body: JSON.stringify({ scope, target, config }),
    });
  }

  /** One fetch path for every endpoint: bearer auth, JSON, loud plain-language
   *  failures (§0.11 — never a silent fallback). */
  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        ...init,
        headers: {
          Authorization: `Bearer ${this.token}`,
          ...(init?.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        },
      });
    } catch {
      throw new Error(
        `Could not reach the server at ${this.baseUrl}. ` +
          'Check that the Registry is running and this machine can reach it.',
      );
    }
    if (!response.ok) {
      // Surface the server's own detail when it sent one (e.g. which settings
      // field failed validation on a plugin enable) — never swallow it.
      let detail: string | null = null;
      try {
        const body = (await response.json()) as { detail?: unknown };
        if (typeof body.detail === 'string') detail = body.detail;
      } catch {
        detail = null;
      }
      throw new Error(
        `The server at ${this.baseUrl} answered with an error (HTTP ${response.status}). ` +
          (detail ??
            (response.status === 401
              ? 'The console token was not accepted — check VITE_API_TOKEN.'
              : 'Check the Registry logs.')),
      );
    }
    return (await response.json()) as T;
  }
}
