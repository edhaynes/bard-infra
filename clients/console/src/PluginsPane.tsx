import { useCallback, useEffect, useState } from 'react';
import type { ControlPlaneClient } from './api';
import { deviceDisplayName } from './fleet';
import type { FleetView } from './fleet';
import {
  buildConfig,
  enabledSummary,
  healthText,
  isEnabledFor,
  schemaFields,
  seedValues,
} from './plugins';
import type {
  FormField,
  FormValues,
  PluginCatalogView,
  PluginStatus,
  PluginTarget,
} from './plugins';
import { s } from './styles';

// Plugins pane (Sprint B8, feature #65 complete) — from read-only catalog to
// managed: turn a plugin on/off per device or per workgroup, edit its
// settings (the manifest's own configSchema drives the form — plain-language
// labels per §1, raw JSON under a collapsed "Advanced" section), and see
// reported health in plain words. Every action lands in the audit log
// server-side and shows on the Activity pane.

/** Build the target choices from the fleet: workgroups first, then devices. */
export function fleetTargets(fleet: FleetView): PluginTarget[] {
  const groups = new Map<string, string>();
  for (const device of fleet.devices) {
    if (device.workgroup !== null) groups.set(device.workgroup.workgroupId, device.workgroup.name);
  }
  const targets: PluginTarget[] = [...groups.values()]
    .sort((a, b) => a.localeCompare(b))
    .map((name) => ({ scope: 'workgroup', target: name, label: `Group: ${name}` }));
  for (const device of fleet.devices) {
    if (device.enrollment === null) continue; // pre-identity rows are read-only
    targets.push({
      scope: 'device',
      target: device.id,
      label: `Device: ${deviceDisplayName(device)}`,
    });
  }
  return targets;
}

export function PluginsPane({ client }: { client: ControlPlaneClient | null }) {
  const [view, setView] = useState<PluginCatalogView | null>(null);
  const [targets, setTargets] = useState<PluginTarget[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (client === null) return;
    try {
      const [plugins, fleet] = await Promise.all([client.fetchPlugins(), client.fetchFleet()]);
      setView(plugins);
      setTargets(fleetTargets(fleet));
      setError(null);
    } catch (cause) {
      // Fail loudly; keep the last good list on screen (§0.11).
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }, [client]);

  useEffect(() => {
    void load();
  }, [load]);

  if (client === null) {
    return (
      <div>
        <h1 style={s.h1}>Plugins</h1>
        <p style={s.dim} className="plugins-unavailable">
          Plugins are not available with sample data.
        </p>
      </div>
    );
  }

  return (
    <div>
      <h1 style={s.h1}>Plugins</h1>
      <p style={s.dim}>
        Extras you can turn on for a whole group or a single device. Changes show up on the
        Activity page.
      </p>
      {error !== null && (
        <div style={s.errorBanner} className="fetch-error" role="alert">
          <div style={s.errorTitle}>Could not update the plugin list</div>
          <p style={s.errorText}>{error}</p>
        </div>
      )}
      {view === null && error === null && (
        <p style={s.dim} className="loading">
          Checking your plugins…
        </p>
      )}
      {view !== null &&
        view.plugins.map((status) => (
          <PluginCard
            key={status.manifest.id}
            status={status}
            targets={targets}
            client={client}
            onChanged={load}
          />
        ))}
    </div>
  );
}

function PluginCard({
  status,
  targets,
  client,
  onChanged,
}: {
  status: PluginStatus;
  targets: PluginTarget[];
  client: ControlPlaneClient;
  onChanged: () => Promise<void>;
}) {
  const { manifest } = status;
  const fields = schemaFields(manifest.configSchema);
  const [targetIndex, setTargetIndex] = useState(0);
  const [values, setValues] = useState<FormValues>(() => seedValues(fields, {}));
  const [advancedText, setAdvancedText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const target = targets[targetIndex] ?? null;
  const enabled = target !== null && isEnabledFor(status, target);
  const where = enabledSummary(status);

  // Load the stored settings whenever the picked target changes.
  useEffect(() => {
    if (target === null) return;
    let cancelled = false;
    client
      .fetchPluginConfig(manifest.id, target.scope, target.target)
      .then((body) => {
        if (cancelled) return;
        const seeded = seedValues(fields, body.config);
        setValues(seeded);
        setAdvancedText(JSON.stringify(buildConfig(fields, seeded), null, 2));
        setError(null);
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause));
      });
    return () => {
      cancelled = true;
    };
    // `fields` derives 1:1 from the (immutable) manifest — not a dependency.
  }, [client, manifest.id, target?.scope, target?.target]);

  /** Run one action, surface the result, refresh the catalog. */
  const act = async (action: () => Promise<unknown>, done: string) => {
    try {
      await action();
      setNotice(done);
      setError(null);
      await onChanged();
    } catch (cause) {
      setNotice(null);
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  };

  const toggle = () => {
    if (target === null) return;
    if (enabled) {
      void act(
        () => client.disablePlugin(manifest.id, target.scope, target.target),
        `${manifest.displayName} is now off for ${target.label.toLowerCase()}.`,
      );
    } else {
      void act(
        () =>
          client.enablePlugin(
            manifest.id,
            target.scope,
            target.target,
            buildConfig(fields, values),
          ),
        `${manifest.displayName} is now on for ${target.label.toLowerCase()}.`,
      );
    }
  };

  const saveSettings = () => {
    if (target === null) return;
    void act(
      () =>
        client.savePluginConfig(manifest.id, target.scope, target.target, buildConfig(fields, values)),
      'Settings saved.',
    );
  };

  const saveAdvanced = () => {
    if (target === null) return;
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(advancedText) as Record<string, unknown>;
    } catch {
      setError('That text is not valid JSON — fix it and try again.');
      return;
    }
    void act(async () => {
      await client.savePluginConfig(manifest.id, target.scope, target.target, parsed);
      setValues(seedValues(fields, parsed));
    }, 'Settings saved.');
  };

  return (
    <div style={s.card} className="plugin-card" data-plugin-id={manifest.id}>
      <div style={s.cardTitle} className="plugin-name">
        {manifest.displayName}
      </div>
      <div style={s.pluginMeta} className="plugin-version">
        Version {manifest.version}
      </div>
      {manifest.description !== undefined && (
        <p style={s.dim} className="plugin-description">
          {manifest.description}
        </p>
      )}
      <HealthLines status={status} />
      <div className="plugin-enabled-for">
        {where.length === 0 ? (
          <span style={s.dim}>Not turned on anywhere yet.</span>
        ) : (
          where.map((name) => (
            <span key={name} style={s.chip} className="plugin-enabled-chip">
              On for {name}
            </span>
          ))
        )}
      </div>
      {targets.length === 0 ? (
        <p style={s.dim} className="plugin-no-targets">
          Add a device first — then you can turn plugins on for it.
        </p>
      ) : (
        <div style={s.pluginRow}>
          <select
            style={s.pluginSelect}
            className="plugin-target"
            value={targetIndex}
            onChange={(event) => setTargetIndex(Number(event.target.value))}
          >
            {targets.map((option, index) => (
              <option key={option.label} value={index}>
                {option.label}
              </option>
            ))}
          </select>
          <button
            style={{ ...s.actionBtn, ...(enabled ? s.actionDanger : s.actionPrimary) }}
            className="plugin-toggle"
            onClick={toggle}
          >
            {enabled ? 'Turn off' : 'Turn on'}
          </button>
        </div>
      )}
      {error !== null && (
        <div style={s.errorBanner} className="plugin-error" role="alert">
          <p style={s.errorText}>{error}</p>
        </div>
      )}
      {notice !== null && (
        <div style={s.okBanner} className="plugin-notice">
          {notice}
        </div>
      )}
      {target !== null && fields.length > 0 && (
        <>
          <form
            style={s.form}
            className="plugin-config-form"
            onSubmit={(event) => {
              event.preventDefault();
              saveSettings();
            }}
          >
            {fields.map((field) => (
              <Field
                key={field.key}
                field={field}
                values={values}
                onChange={(next) => {
                  setValues(next);
                  setAdvancedText(JSON.stringify(buildConfig(fields, next), null, 2));
                }}
              />
            ))}
            <div>
              <button type="submit" style={s.actionBtn} className="plugin-config-save">
                Save settings
              </button>
            </div>
          </form>
          <details style={s.advanced} className="plugin-advanced">
            <summary style={s.advancedSummary}>Advanced</summary>
            <p style={s.fieldHelp}>
              The exact settings text sent to the plugin, for people comfortable editing it
              directly.
            </p>
            <textarea
              style={s.advancedText}
              className="plugin-advanced-json"
              value={advancedText}
              onChange={(event) => setAdvancedText(event.target.value)}
            />
            <div>
              <button
                type="button"
                style={s.actionBtn}
                className="plugin-advanced-save"
                onClick={saveAdvanced}
              >
                Save exactly this text
              </button>
            </div>
          </details>
        </>
      )}
    </div>
  );
}

/** Reported health in plain words; nothing for an unmonitored (client) plugin. */
function HealthLines({ status }: { status: PluginStatus }) {
  if (status.health === null) return null;
  if (status.health.length === 0) {
    return (
      <p style={s.dim} className="plugin-health-empty">
        No health reports yet.
      </p>
    );
  }
  return (
    <div className="plugin-health">
      {status.health.map((entry) => (
        <div key={entry.deviceId} style={s.dim} className={`plugin-health-entry health-${entry.status}`}>
          {entry.deviceId}: {healthText(entry.status)}
          {entry.detail !== undefined ? ` — ${entry.detail}` : ''}
        </div>
      ))}
    </div>
  );
}

function Field({
  field,
  values,
  onChange,
}: {
  field: FormField;
  values: FormValues;
  onChange: (next: FormValues) => void;
}) {
  const set = (value: unknown) => onChange({ ...values, [field.key]: value });
  const value = values[field.key];

  if (field.kind === 'group') {
    const sub = (value as FormValues) ?? {};
    return (
      <fieldset style={s.fieldGroup} className={`plugin-field-group field-${field.key}`}>
        <legend style={s.fieldGroupLegend}>{field.label}</legend>
        {field.help !== undefined && <div style={s.fieldHelp}>{field.help}</div>}
        {(field.fields ?? []).map((subField) => (
          <Field key={subField.key} field={subField} values={sub} onChange={set} />
        ))}
      </fieldset>
    );
  }

  if (field.kind === 'boolean') {
    return (
      <label style={s.checkboxRow} className={`plugin-field field-${field.key}`}>
        <input
          type="checkbox"
          checked={value === true}
          onChange={(event) => set(event.target.checked)}
        />
        <span style={s.fieldLabel}>{field.label}</span>
      </label>
    );
  }

  return (
    <label style={s.field} className={`plugin-field field-${field.key}`}>
      <span style={s.fieldLabel}>{field.label}</span>
      {field.help !== undefined && <span style={s.fieldHelp}>{field.help}</span>}
      {field.kind === 'select' ? (
        <select
          style={s.fieldInput}
          value={value === undefined ? '' : String(value)}
          onChange={(event) => set(event.target.value)}
        >
          <option value="">(not set)</option>
          {(field.options ?? []).map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      ) : (
        <input
          style={s.fieldInput}
          type={field.kind === 'number' ? 'number' : 'text'}
          value={value === undefined ? '' : String(value)}
          onChange={(event) =>
            set(
              field.kind === 'number'
                ? event.target.value === ''
                  ? undefined
                  : Number(event.target.value)
                : event.target.value,
            )
          }
        />
      )}
    </label>
  );
}
