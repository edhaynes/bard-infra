"""Plugin catalog + enable/config/health state (Sprint B8 / feature #65).

The catalog is DECLARED by manifest files frozen against
``contracts/plugin-manifest.schema.json`` — the eds-rules book-capstone seam.
That contract is consumed here, never extended: this store adds the
control-plane state AROUND the manifests (the manager side of the seam):

- **enablement** per device AND per workgroup (workgroups by NAME, the
  WorkgroupId derived with the same deterministic v2 rule the console's
  device assignment uses — :func:`registry.device_store.derive_workgroup_id`),
- **config** per (plugin, scope, target), validated against the manifest's
  own ``configSchema`` BEFORE it is stored or an enable goes through —
  fail fast (§0.11), a plugin is never enabled with invalid settings,
- **health** as REPORTED state: the device-side agent polls the plugin's
  manifest-declared healthEndpoint locally and reports up, mirroring agent
  heartbeat liveness. A report older than ``health_ttl_s`` reads as
  ``stale`` — the missed-heartbeat rule applied to plugins. The control
  plane never probes a plugin over the network (and neither do unit tests).

Enablement is desired state in the control plane; the manager component
that launches ``entry`` (module/container/url) is later ROADMAP scope
(Sprint 5 ships the actual SSH service, e.g.).

Persistence follows the established per-concern-file rule (``DeviceStore``,
``ChannelStore``, ``AuditLog``): its OWN JSON file, never merged into the
agent/device/channel state. The clock is injected so the unit suite is
hermetic (no real time, §11).
"""

from __future__ import annotations

import datetime as _dt
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import jsonschema

from registry.device_store import derive_workgroup_id

#: The frozen book-capstone contract every catalog manifest must satisfy.
DEFAULT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "contracts" / ("plugin-manifest.schema.json")
)

SCOPE_DEVICE = "device"
SCOPE_WORKGROUP = "workgroup"

HEALTH_OK = "ok"
HEALTH_FAILING = "failing"
HEALTH_STALE = "stale"


class PluginNotFound(KeyError):
    """Raised when an unknown pluginId is looked up (maps to 404)."""


class InvalidPluginCatalog(ValueError):
    """Raised at load time when the catalog dir or a manifest is bad (fail fast)."""


class InvalidPluginConfig(ValueError):
    """Raised when a config violates the manifest's configSchema (maps to 400)."""


class PluginNotMonitored(ValueError):
    """Raised when health is reported for a plugin with no healthEndpoint (409)."""


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


class PluginStore:
    """JSON-persisted enable/config/health state around a declared catalog.

    The persisted map is ``{pluginId: {"devices": {deviceId: {"enabled",
    "config"}}, "workgroups": {workgroupId: {"name", "enabled", "config"}},
    "health": {deviceId: {"status", "reportedAt", "detail"?}}}}``. Manifests
    are read fresh from ``catalog_dir`` at construction and validated against
    the frozen contract — an invalid catalog crashes loudly at startup, it
    never limps (§0.11).
    """

    def __init__(
        self,
        catalog_dir: str | Path,
        state_path: str | Path | None = None,
        *,
        clock: Callable[[], _dt.datetime] | None = None,
        health_ttl_s: float = 45.0,
        schema_path: str | Path = DEFAULT_SCHEMA_PATH,
    ):
        self._clock = clock or _utcnow
        self._health_ttl_s = health_ttl_s
        self._manifests = self._load_catalog(Path(catalog_dir), Path(schema_path))
        self._path = Path(state_path) if state_path else None
        self._state: dict[str, dict[str, Any]] = {}
        self._load_state()

    # --- catalog ---------------------------------------------------------------

    @staticmethod
    def _load_catalog(catalog_dir: Path, schema_path: Path) -> dict[str, dict[str, Any]]:
        if not catalog_dir.is_dir():
            raise InvalidPluginCatalog(f"plugin catalog directory not found: {catalog_dir}")
        validator = jsonschema.Draft202012Validator(
            json.loads(schema_path.read_text(encoding="utf-8"))
        )
        manifests: dict[str, dict[str, Any]] = {}
        paths = sorted(catalog_dir.glob("*.manifest.json"))
        if not paths:
            raise InvalidPluginCatalog(f"no *.manifest.json files in {catalog_dir}")
        for path in paths:
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
                validator.validate(manifest)
            except (json.JSONDecodeError, jsonschema.ValidationError) as exc:
                raise InvalidPluginCatalog(f"invalid plugin manifest {path.name}: {exc}") from exc
            if manifest["id"] in manifests:
                raise InvalidPluginCatalog(f"duplicate plugin id {manifest['id']!r} in {path.name}")
            manifests[manifest["id"]] = manifest
        return manifests

    # --- persistence -------------------------------------------------------------

    def _load_state(self) -> None:
        if self._path and self._path.is_file():
            self._state = json.loads(self._path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        if self._path:
            self._path.write_text(json.dumps(self._state, indent=2), encoding="utf-8")

    # --- views ---------------------------------------------------------------------

    def catalog_view(self) -> dict[str, Any]:
        """GET /plugins body: every PluginStatus + generatedAt, console-ready."""
        return {
            "plugins": [
                self.status(plugin_id)
                for plugin_id in sorted(
                    self._manifests, key=lambda pid: self._manifests[pid]["displayName"]
                )
            ],
            "generatedAt": self._clock().isoformat(),
        }

    def status(self, plugin_id: str) -> dict[str, Any]:
        """One PluginStatus (control-plane.openapi.yaml): manifest + state."""
        manifest = self.manifest(plugin_id)
        state = self._state.get(plugin_id, {})
        devices = state.get("devices", {})
        workgroups = state.get("workgroups", {})
        return {
            "manifest": manifest,
            "enabledDevices": sorted(d for d, e in devices.items() if e["enabled"]),
            "enabledWorkgroups": sorted(
                (
                    {"workgroupId": wid, "name": entry["name"]}
                    for wid, entry in workgroups.items()
                    if entry["enabled"]
                ),
                key=lambda w: w["name"],
            ),
            "health": self._health_view(manifest, state),
        }

    def _health_view(
        self, manifest: dict[str, Any], state: dict[str, Any]
    ) -> list[dict[str, Any]] | None:
        """Reported health, staleness derived at read time — or None when the
        manifest declares no healthEndpoint (unmonitored)."""
        if manifest.get("healthEndpoint") is None:
            return None
        now = self._clock()
        entries: list[dict[str, Any]] = []
        for device_id in sorted(state.get("health", {})):
            stored = state["health"][device_id]
            reported_at = _dt.datetime.fromisoformat(stored["reportedAt"])
            age_s = (now - reported_at).total_seconds()
            entry: dict[str, Any] = {
                "deviceId": device_id,
                "status": HEALTH_STALE if age_s > self._health_ttl_s else stored["status"],
                "reportedAt": stored["reportedAt"],
            }
            if "detail" in stored:
                entry["detail"] = stored["detail"]
            entries.append(entry)
        return entries

    # --- enable / disable -------------------------------------------------------------

    def enable(
        self, plugin_id: str, *, scope: str, target: str, config: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Turn the plugin on for one device/workgroup target.

        The EFFECTIVE config — provided here, else the target's stored
        config, else ``{}`` — must validate against the manifest's
        configSchema or the enable is refused; a plugin is never enabled
        with invalid settings (§0.11)."""
        manifest = self.manifest(plugin_id)
        entry = self._target_entry(plugin_id, scope, target)
        effective = config if config is not None else entry.get("config", {})
        self._validate_config(manifest, effective)
        entry["enabled"] = True
        if config is not None:
            entry["config"] = config
        self._save()
        return self.status(plugin_id)

    def disable(self, plugin_id: str, *, scope: str, target: str) -> dict[str, Any]:
        """Turn the plugin off for one target. Idempotent destination (like a
        device revoke); the stored config is KEPT so re-enabling restores it."""
        self.manifest(plugin_id)  # 404 before any state is touched
        entry = self._target_entry(plugin_id, scope, target)
        entry["enabled"] = False
        self._save()
        return self.status(plugin_id)

    # --- config ----------------------------------------------------------------------

    def get_config(self, plugin_id: str, *, scope: str, target: str) -> dict[str, Any]:
        """The stored config for one target; {} when none was ever set."""
        self.manifest(plugin_id)
        scoped = self._state.get(plugin_id, {}).get(self._bucket(scope), {})
        return scoped.get(self._key(scope, target), {}).get("config", {})

    def set_config(
        self, plugin_id: str, *, scope: str, target: str, config: dict[str, Any]
    ) -> dict[str, Any]:
        """Validate against the manifest's configSchema, then store. Invalid
        config is refused and the previous config stays untouched."""
        self._validate_config(self.manifest(plugin_id), config)
        entry = self._target_entry(plugin_id, scope, target)
        entry["config"] = config
        self._save()
        return config

    # --- health ----------------------------------------------------------------------

    def report_health(
        self, plugin_id: str, *, device_id: str, status: str, detail: str | None = None
    ) -> dict[str, Any]:
        """Record one device-side health observation (the heartbeat pattern).

        Refused for an unmonitored plugin (manifest healthEndpoint null) —
        there is nothing to report on."""
        manifest = self.manifest(plugin_id)
        if manifest.get("healthEndpoint") is None:
            raise PluginNotMonitored(
                f"plugin {plugin_id!r} declares no healthEndpoint (unmonitored)"
            )
        stored: dict[str, Any] = {"status": status, "reportedAt": self._clock().isoformat()}
        if detail is not None:
            stored["detail"] = detail
        plugin_state = self._state.setdefault(plugin_id, {})
        plugin_state.setdefault("health", {})[device_id] = stored
        self._save()
        return {"deviceId": device_id, **stored}

    # --- helpers ---------------------------------------------------------------------

    def manifest(self, plugin_id: str) -> dict[str, Any]:
        try:
            return self._manifests[plugin_id]
        except KeyError as exc:
            raise PluginNotFound(plugin_id) from exc

    @staticmethod
    def _bucket(scope: str) -> str:
        return "devices" if scope == SCOPE_DEVICE else "workgroups"

    @staticmethod
    def _key(scope: str, target: str) -> str:
        """State key per target: the deviceId itself, or the DERIVED workgroup
        id — so 'Front office' is the same group here as it is in the device
        assignment path."""
        return target if scope == SCOPE_DEVICE else derive_workgroup_id(target)

    def _target_entry(self, plugin_id: str, scope: str, target: str) -> dict[str, Any]:
        plugin_state = self._state.setdefault(plugin_id, {})
        scoped = plugin_state.setdefault(self._bucket(scope), {})
        entry = scoped.setdefault(self._key(scope, target), {"enabled": False})
        if scope == SCOPE_WORKGROUP:
            entry["name"] = target  # keep the operator's name beside the derived id
        return entry

    @staticmethod
    def _validate_config(manifest: dict[str, Any], config: dict[str, Any]) -> None:
        try:
            jsonschema.validate(config, manifest.get("configSchema", {}))
        except jsonschema.ValidationError as exc:
            raise InvalidPluginConfig(exc.message) from exc
