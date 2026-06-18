// Plugin types + pure presentation helpers (Sprint B8, feature #65).
// Mirrors contracts/control-plane.openapi.yaml (PluginCatalogView /
// PluginStatus / PluginHealthEntry) and consumes — never redefines — the
// frozen plugin-manifest contract (contracts/plugin-manifest.schema.json,
// the eds-rules book-capstone seam). All functions here are pure so the
// rendering stays trivially testable and Playwright only asserts structure
// (§14).

/** contracts/plugin-manifest.schema.json — the fields the console consumes. */
export interface PluginManifest {
  id: string;
  version: string;
  displayName: string;
  description?: string;
  kind: 'client' | 'service' | 'bridge';
  requiredCapabilities?: string[];
  configSchema?: ConfigSchema;
  healthEndpoint?: string | null;
  entry: { type: string; target: string; args?: string[] };
}

/** The slice of JSON Schema the form renderer understands (one nesting level). */
export interface ConfigSchema {
  properties?: Record<string, ConfigProperty>;
  required?: string[];
  [key: string]: unknown;
}

export interface ConfigProperty {
  type?: string | string[];
  description?: string;
  default?: unknown;
  enum?: unknown[];
  minimum?: number;
  maximum?: number;
  properties?: Record<string, ConfigProperty>;
  required?: string[];
  [key: string]: unknown;
}

export interface PluginHealthEntry {
  deviceId: string;
  status: 'ok' | 'failing' | 'stale';
  reportedAt: string;
  detail?: string;
}

export interface PluginStatus {
  manifest: PluginManifest;
  enabledDevices: string[];
  enabledWorkgroups: { workgroupId: string; name: string }[];
  /** null = the manifest declares no health endpoint (unmonitored). */
  health: PluginHealthEntry[] | null;
}

export interface PluginCatalogView {
  plugins: PluginStatus[];
  generatedAt: string;
}

export type PluginScopeKind = 'device' | 'workgroup';

/** One enable/config target the operator can pick in the pane. */
export interface PluginTarget {
  scope: PluginScopeKind;
  /** What the API wants: the deviceId, or the workgroup NAME. */
  target: string;
  /** What the operator reads: "Group: Front office" / "Device: Front desk PC". */
  label: string;
}

// --- plain-language labels (§1: the reader is a non-technical owner) ---------

/** Reported health in plain words — never the raw enum. */
export function healthText(status: PluginHealthEntry['status']): string {
  return status === 'ok' ? 'Working' : 'Not responding';
}

/** "pushToTalk" -> "Push to talk", "listen_port"/"listen-port" -> "Listen port". */
export function humanizeKey(key: string): string {
  const words = key
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .toLowerCase()
    .trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Is the selected target currently enabled for this plugin? */
export function isEnabledFor(status: PluginStatus, target: PluginTarget): boolean {
  return target.scope === 'device'
    ? status.enabledDevices.includes(target.target)
    : status.enabledWorkgroups.some((w) => w.name === target.target);
}

/** Plain-language summary chips of where the plugin is on. */
export function enabledSummary(status: PluginStatus): string[] {
  return [
    ...status.enabledWorkgroups.map((w) => `${w.name} group`),
    ...status.enabledDevices,
  ];
}

// --- schema -> form fields (the manifest's configSchema drives the form) -----

export type FieldKind = 'text' | 'number' | 'boolean' | 'select' | 'group';

export interface FormField {
  key: string;
  label: string;
  help?: string;
  kind: FieldKind;
  required: boolean;
  options?: string[];
  defaultValue?: unknown;
  /** Sub-fields when kind === 'group' (one nesting level, e.g. squelch). */
  fields?: FormField[];
}

function fieldKind(prop: ConfigProperty): FieldKind {
  if (prop.enum !== undefined) return 'select';
  const type = Array.isArray(prop.type) ? prop.type[0] : prop.type;
  if (type === 'boolean') return 'boolean';
  if (type === 'number' || type === 'integer') return 'number';
  if (type === 'object') return 'group';
  return 'text';
}

function toField(key: string, prop: ConfigProperty, required: boolean): FormField {
  const kind = fieldKind(prop);
  const field: FormField = {
    key,
    label: humanizeKey(key),
    help: prop.description,
    kind,
    required,
    defaultValue: prop.default,
  };
  if (kind === 'select') field.options = (prop.enum ?? []).map(String);
  if (kind === 'group') {
    const subRequired = prop.required ?? [];
    field.fields = Object.entries(prop.properties ?? {}).map(([subKey, subProp]) =>
      toField(subKey, subProp, subRequired.includes(subKey)),
    );
  }
  return field;
}

/** Derive the operator form from a manifest's configSchema. */
export function schemaFields(schema: ConfigSchema | undefined): FormField[] {
  const required = schema?.required ?? [];
  return Object.entries(schema?.properties ?? {}).map(([key, prop]) =>
    toField(key, prop, required.includes(key)),
  );
}

// --- form values <-> config objects ------------------------------------------

export type FormValues = Record<string, unknown>;

/** Initial form values: the stored config over the schema's declared defaults.
 *  (Defaults are pre-fill HINTS — the control plane validates strictly and
 *  never injects values; the form is where defaults become real.) */
export function seedValues(fields: FormField[], config: Record<string, unknown>): FormValues {
  const values: FormValues = {};
  for (const field of fields) {
    const stored = config[field.key];
    if (field.kind === 'group') {
      values[field.key] = seedValues(
        field.fields ?? [],
        (stored as Record<string, unknown>) ?? {},
      );
    } else if (stored !== undefined) {
      values[field.key] = stored;
    } else if (field.defaultValue !== undefined) {
      values[field.key] = field.defaultValue;
    }
  }
  return values;
}

/** Build the config object to send: only fields the operator has values for.
 *  Empty text and blank numbers are omitted, never sent as "" (§0.11 — the
 *  server-side schema validation is the authority on what is missing). */
export function buildConfig(fields: FormField[], values: FormValues): Record<string, unknown> {
  const config: Record<string, unknown> = {};
  for (const field of fields) {
    const value = values[field.key];
    if (field.kind === 'group') {
      const sub = buildConfig(field.fields ?? [], (value as FormValues) ?? {});
      if (Object.keys(sub).length > 0) config[field.key] = sub;
    } else if (value !== undefined && value !== '' && !Number.isNaN(value)) {
      config[field.key] = value;
    }
  }
  return config;
}
