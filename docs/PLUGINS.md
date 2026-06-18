# Bard Plugins — the manifest seam

This document explains the plugin seam Bard exposes to the console plugin
manager (`features.md` #65). It is a companion to the frozen contract at
[`contracts/plugin-manifest.schema.json`](../contracts/plugin-manifest.schema.json).

> **The contract is the source of truth.** The eds-rules book's capstone
> chapter (F7, Squawk Box) walks through this same manifest as its worked
> example. The book *documents* the schema defined here — it never defines it.
> If the manifest changes, it changes in `contracts/`, then the book and this
> doc are re-propagated. The contract shown in the book and the one the console
> manages are the same seam, not parallel inventions.

## What a manifest is

A **plugin manifest** is a single JSON file that fully describes a plugin to the
console *without the plugin's code being loaded*. The manager browses the
catalog, decides where a plugin may run, renders a config form, launches it, and
monitors it — all from the manifest alone. The plugin's own logic stays opaque to
the manager; the manifest is the entire interface between them.

The manifest is deliberately minimal: it carries only the fields a plugin
manager actually consumes.

| Field | Required | Purpose |
| --- | --- | --- |
| `id` | yes | Stable identity (reverse-DNS or kebab). Enablement state and config key off this; immutable across versions. |
| `version` | yes | Semantic version. Upgrade ordering and version pinning. |
| `displayName` | yes | Human label in the Plugins pane. |
| `description` | no | Plain-language catalog card summary. |
| `kind` | yes | `client` \| `service` \| `bridge` — how the manager treats `entry` and health. |
| `requiredCapabilities` | no | Fleet/device capabilities the plugin needs. Drives where it may be enabled. |
| `configSchema` | no | A nested JSON Schema for the plugin's *own* config; the console renders a form from it. |
| `healthEndpoint` | no | Path the manager polls once enabled, or `null` for an unmonitored plugin. |
| `entry` | yes | How the plugin is launched/served (module, container, or url). |

### `kind`

- **client** — runs in/with the user-facing app: a UI surface like the Squawk
  Box walkie-talkie. Usually a `module` entry loaded in-process, often with no
  health endpoint.
- **service** — a long-lived backend the manager launches and supervises (e.g.
  an SSH relay). Usually a `container` entry run under podman with the device's
  power-profile, with a health endpoint the manager polls.
- **bridge** — connects Bard to an external system or protocol (a gateway to a
  third-party network).

### `requiredCapabilities` and the capability vocabulary

`requiredCapabilities` draws from the **same capability vocabulary the Registry
advertises per agent** and that the power-profile schema
([`power-profile.schema.yaml`](../contracts/power-profile.schema.yaml)) keys
placement on (e.g. `audio`, `gpu`, `llm`, `network.lan`). A plugin declares what
it needs; the manager only offers and enables it on devices or workgroups whose
advertised capabilities are a superset of that list. An empty list means the
plugin runs anywhere. This is the same matching axis the Router already uses for
placement — plugins reuse it rather than inventing a parallel one.

### `configSchema` is a schema, not config

`configSchema` is itself a JSON Schema (draft 2020-12) describing the plugin's
configuration *shape*. The console renders an operator form from it and validates
the entered values against it **before** enabling the plugin. The manager treats
it as opaque beyond "this must be a valid schema" — the plugin owns its config.

## Lifecycle: declared → enabled → health-checked

```
  catalog (manifest declared)
        │  operator picks a plugin in the console Plugins pane
        ▼
  capability check
        │  manager intersects requiredCapabilities with the
        │  target device/workgroup's advertised capabilities;
        │  only matching targets are offered
        ▼
  configure
        │  console renders a form from configSchema, validates
        │  the operator's input against it
        ▼
  enabled (per device / per workgroup)
        │  manager launches per `entry` (module / container / url)
        ▼
  health-checked
           if healthEndpoint is set, the manager polls it and
           shows live status; if null, the plugin is shown enabled
           but unmonitored
```

Enablement is scoped **per device or per workgroup**, not globally: the same
plugin can be live for one crew's devices and absent for another's.

## Worked example: Squawk Box

[`examples/plugins/squawk-box.manifest.json`](../examples/plugins/squawk-box.manifest.json)
is the proving case for the seam — the Maude walkie-talkie client presented as a
plugin, and the eds-rules book capstone's worked example.

```jsonc
{
  "id": "pro.bardllm.squawk-box",      // stable reverse-DNS identity
  "version": "1.0.0",                  // semver
  "displayName": "Squawk Box",
  "kind": "client",                    // a UI surface, loaded in-process
  "requiredCapabilities": ["audio", "network.lan"],
  "healthEndpoint": null,              // pure client UI — unmonitored
  "entry": { "type": "module", "target": "clients.squawk_box:create_client" },
  "configSchema": { /* the operator-facing config form, see below */ }
}
```

Reading it the way the manager does:

1. **Catalog.** The card shows "Squawk Box" and its description.
2. **Capability check.** `requiredCapabilities: ["audio", "network.lan"]` — the
   manager only offers it on devices that advertise both a microphone/speaker
   (`audio`) and LAN reachability (`network.lan`). A headless GPU box with no
   audio is filtered out.
3. **Configure.** From `configSchema` the console renders a form: a required
   `channel`, a `pushToTalk` toggle, and a **`squelch`** group (`features.md`
   #66) for noisy jobsites — `enabled`, a `threshold` in dBFS (the noise floor;
   audio below it is gated), `side` (gate the **sender** to save relay
   bandwidth, the **receiver**, or **both**), and `autoCalibrate`. Operator
   input is validated against this schema before enable.
4. **Enabled per device/workgroup.** The owner enables Squawk Box for a crew's
   workgroup; the host app loads `clients.squawk_box:create_client`.
5. **Health.** `healthEndpoint` is `null`, so the manager lists it as enabled
   but does not poll — appropriate for a client UI surface.

## Second example: SSH (the seam generalizes)

[`examples/plugins/ssh.manifest.json`](../examples/plugins/ssh.manifest.json)
proves the seam is not Squawk-Box-specific. It is a `service`: the manager runs
the container `ghcr.io/edhaynes/bard-ssh` under podman, polls its `/healthz`
endpoint, and renders a config form (`listenPort`, `allowScp`,
`idleTimeoutSeconds`). Same manifest contract, different `kind` and `entry.type`
— one seam, many plugin shapes.

## Validating a manifest

Both example manifests are validated against the schema in
`tests/test_plugin_manifest.py`, which also confirms each `configSchema` is
itself a valid draft 2020-12 schema and that malformed manifests (missing
required field, bad semver, unknown `kind`) are rejected.

## Managing plugins (Sprint B8)

The control plane implements the lifecycle above without touching this
contract: `contracts/control-plane.openapi.yaml` adds `GET /plugins` (the
catalog with enable state and health), `POST /plugins/{id}/enable|disable`
(per device or per workgroup), `GET|PUT /plugins/{id}/config` (per-target
config, validated against the manifest's `configSchema` before it is stored
— a plugin is never enabled with invalid settings), and
`POST /plugins/{id}/health` (REPORTED health on the agent-heartbeat pattern;
a report older than the freshness TTL reads "stale"; nothing probes the
plugin over the network from the control plane). `registry/plugin_store.py`
loads the catalog from `BARDPRO_PLUGIN_CATALOG_DIR`, validating every
manifest against this contract at startup — fail fast on an invalid catalog.
The console's Plugins pane renders its settings form from `configSchema`
(plain-language labels; raw JSON under a collapsed "Advanced" section), and
every enable/disable/config action lands in the audit log.

Two Powell calls recorded at B8: schema `default`s are **form pre-fill
hints** — the control plane validates strictly and never injects values; and
enablement is **desired state** — the manager component that launches
`entry` (e.g. the actual SSH relay container) is ROADMAP Sprint 5 scope, so
the SSH catalog entry is fully manageable today while its service ships
later.
