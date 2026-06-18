// Bard — the relationship model (TRUST_MODEL.md §3.1–§3.3, ADR-0006/0007).
// This is the single typed source the console renders. Mirrors the frozen
// contracts in ../../../contracts/trust.schema.yaml (kept in sync by hand for now;
// a generator is a follow-up).

export type Visibility = 'visible' | 'hidden';
export type EnrollMode = 'independent' | 'organization';
export type Role = 'manager' | 'member' | 'auditor' | 'bridge';
export type AppKind = 'agent' | 'router' | 'registry' | 'client';

/** Hardware a device advertises (TRUST_MODEL §3.1) — drives capability routing (#41). */
export interface CapabilityProfile {
  cpuCores: number;
  /** GPU model, or null when none. */
  gpu: string | null;
  memoryGb: number;
  /** e.g. "10GbE", "wifi-6", "tailscale". */
  networking: string;
  storageGb: number;
}

/** The physical machine. Holds the hardware-backed hybrid-PQ identity key. */
export interface Device {
  id: string;
  name: string;
  ownerUserId: string;
  capabilities: CapabilityProfile;
  visibility: Visibility;
  /** Applications running on this device. */
  applicationIds: string[];
  /** secure-enclave | tpm2 | android-strongbox | stub (Level-0). */
  keystore: 'secure-enclave' | 'tpm2' | 'android-strongbox' | 'stub';
}

/** Human principal. Owns devices. */
export interface User {
  id: string;
  name: string;
  deviceIds: string[];
}

/** Software entity running on a device. */
export interface Application {
  id: string;
  name: string;
  kind: AppKind;
  deviceId: string;
}

/** An MLS group connecting devices (TRUST_MODEL §4). */
export interface Workgroup {
  id: string;
  name: string;
  /** null = independent / personal scope (no org). */
  orgId: string | null;
  visibility: Visibility;
  epoch: number;
  memberDeviceIds: string[];
  managerUserIds: string[];
}

/** Managed multi-user scope above workgroups (TRUST_MODEL §3.2). */
export interface Organization {
  id: string;
  name: string;
  workgroupIds: string[];
  memberUserIds: string[];
}

/** This identity's enrollment scope (TRUST_MODEL §3.2). */
export interface EnrollmentState {
  mode: EnrollMode;
  userId: string;
  /** null when independent. */
  orgId: string | null;
}

/** The whole graph the console models. */
export interface World {
  enrollment: EnrollmentState;
  organizations: Organization[];
  users: User[];
  devices: Device[];
  applications: Application[];
  workgroups: Workgroup[];
}
