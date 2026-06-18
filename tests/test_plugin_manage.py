"""Sprint B8 — plugin manage (feature #65 complete).

Written against the contracts FIRST (CLAUDE.md §11): the B8 extensions to
``contracts/control-plane.openapi.yaml`` (GET /plugins, enable/disable,
config get/set, health report; PluginCatalogView/PluginStatus and the
additive AuditEntry plugin actions). The plugin-manifest contract itself
(``contracts/plugin-manifest.schema.json``) is the FROZEN book-capstone seam
and is consumed, never changed, here. Covers:

- PluginStore: catalog loading (fail fast on a bad catalog), JSON
  persistence, enable/disable per device AND per workgroup, per-target
  config validated against the manifest's configSchema, reported health
  with heartbeat-style staleness (injected clock — no real time)
- the Registry routes: auth, 404s, 400 on invalid config, 409 on reporting
  health for an unmonitored plugin, audit recording with pluginId/scope

Hermetic: injected clock, no network, TestClient in-process (§11). Health is
REPORTED state (the agent-side heartbeat pattern) — nothing here probes a
plugin over a socket.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from common.auth import JwtVerifier
from registry.app import create_app
from registry.audit_log import (
    ACTION_PLUGIN_CONFIG,
    ACTION_PLUGIN_DISABLE,
    ACTION_PLUGIN_ENABLE,
    AuditLog,
)
from registry.device_store import derive_workgroup_id
from registry.plugin_store import (
    InvalidPluginCatalog,
    InvalidPluginConfig,
    PluginNotFound,
    PluginNotMonitored,
    PluginStore,
)
from registry.store import RegistryStore
from tests.fakes.jwt_helper import TEST_JWT_SECRET, mint_test_token

ROOT = Path(__file__).resolve().parents[1]
CONTROL_PLANE = ROOT / "contracts" / "control-plane.openapi.yaml"
CATALOG_DIR = ROOT / "examples" / "plugins"

ISSUER = "bardllm-pro"
MANAGER = "manager-eddie"
SQUAWK = "pro.bardllm.squawk-box"
SSH = "pro.bardllm.ssh"
HEALTH_TTL_S = 45.0
# The SSH configSchema REQUIRES listenPort (its schema "default" is a console
# form pre-fill hint, not server-injected — validation is strict, §0.11).
SSH_CONFIG = {"listenPort": 2200}


class FakeClock:
    """Deterministic clock (no real time, §11)."""

    def __init__(self) -> None:
        self.now = _dt.datetime(2026, 6, 12, 12, 0, 0, tzinfo=_dt.UTC)

    def __call__(self) -> _dt.datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += _dt.timedelta(seconds=seconds)


def _store(tmp_path: Path | None = None, clock: FakeClock | None = None) -> PluginStore:
    return PluginStore(
        CATALOG_DIR,
        (tmp_path / "plugins.json") if tmp_path else None,
        clock=clock or FakeClock(),
        health_ttl_s=HEALTH_TTL_S,
    )


# --- contract: the B8 surface is contracted before it is implemented ---------


def test_control_plane_contract_has_b8_plugin_paths():
    spec = yaml.safe_load(CONTROL_PLANE.read_text(encoding="utf-8"))
    paths = spec["paths"]
    assert "get" in paths["/plugins"]
    assert "post" in paths["/plugins/{pluginId}/enable"]
    assert "post" in paths["/plugins/{pluginId}/disable"]
    assert "get" in paths["/plugins/{pluginId}/config"]
    assert "put" in paths["/plugins/{pluginId}/config"]
    assert "post" in paths["/plugins/{pluginId}/health"]
    schemas = spec["components"]["schemas"]
    status = schemas["PluginStatus"]
    assert status["required"] == ["manifest", "enabledDevices", "enabledWorkgroups", "health"]
    # The manifest inside the view IS the frozen book-capstone contract.
    assert status["properties"]["manifest"]["$ref"] == "./plugin-manifest.schema.json"
    assert schemas["PluginScope"]["properties"]["scope"]["enum"] == ["device", "workgroup"]
    assert schemas["PluginHealthEntry"]["properties"]["status"]["enum"] == [
        "ok",
        "failing",
        "stale",
    ]


def test_audit_entry_contract_extended_additively_for_plugins():
    spec = yaml.safe_load(CONTROL_PLANE.read_text(encoding="utf-8"))
    entry = spec["components"]["schemas"]["AuditEntry"]
    # Additive: the B6 required set is untouched; plugin fields are optional.
    assert entry["required"] == ["at", "actor", "action", "deviceId"]
    assert entry["properties"]["action"]["enum"] == [
        "approve",
        "revoke",
        "rename",
        "workgroup",
        "plugin-enable",
        "plugin-disable",
        "plugin-config",
    ]
    assert "pluginId" in entry["properties"]
    assert entry["properties"]["scope"]["enum"] == ["device", "workgroup"]


# --- PluginStore: catalog loading ---------------------------------------------


def test_catalog_loads_both_example_manifests_sorted_by_display_name():
    plugins = _store().catalog_view()["plugins"]
    # "SSH / SCP" < "Squawk Box" — stable display order for the console.
    assert [p["manifest"]["id"] for p in plugins] == [SSH, SQUAWK]
    assert all(p["enabledDevices"] == [] and p["enabledWorkgroups"] == [] for p in plugins)


def test_catalog_view_health_null_only_for_unmonitored():
    plugins = {p["manifest"]["id"]: p for p in _store().catalog_view()["plugins"]}
    assert plugins[SQUAWK]["health"] is None  # healthEndpoint: null
    assert plugins[SSH]["health"] == []  # monitored, no reports yet


def test_missing_catalog_dir_fails_fast(tmp_path):
    with pytest.raises(InvalidPluginCatalog, match="catalog directory"):
        PluginStore(tmp_path / "nope", None)


def test_empty_catalog_dir_fails_fast(tmp_path):
    (tmp_path / "catalog").mkdir()
    with pytest.raises(InvalidPluginCatalog, match="no \\*.manifest.json"):
        PluginStore(tmp_path / "catalog", None)


def test_malformed_manifest_json_fails_fast(tmp_path):
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    (catalog / "bad.manifest.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(InvalidPluginCatalog, match="bad.manifest.json"):
        PluginStore(catalog, None)


def test_schema_violating_manifest_fails_fast(tmp_path):
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    bad = json.loads((CATALOG_DIR / "ssh.manifest.json").read_text())
    bad["kind"] = "daemon"  # not in the frozen enum
    (catalog / "bad.manifest.json").write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(InvalidPluginCatalog, match="bad.manifest.json"):
        PluginStore(catalog, None)


def test_duplicate_plugin_id_fails_fast(tmp_path):
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    manifest = (CATALOG_DIR / "ssh.manifest.json").read_text()
    (catalog / "a.manifest.json").write_text(manifest, encoding="utf-8")
    (catalog / "b.manifest.json").write_text(manifest, encoding="utf-8")
    with pytest.raises(InvalidPluginCatalog, match="duplicate plugin id"):
        PluginStore(catalog, None)


# --- PluginStore: enable / disable ---------------------------------------------


def test_enable_for_device_round_trips_and_persists(tmp_path):
    store = _store(tmp_path)
    status = store.enable(SSH, scope="device", target="dev-a", config=SSH_CONFIG)
    assert status["enabledDevices"] == ["dev-a"]
    reloaded = _store(tmp_path)
    assert reloaded.status(SSH)["enabledDevices"] == ["dev-a"]


def test_enable_for_workgroup_derives_the_workgroup_id():
    store = _store()
    status = store.enable(SSH, scope="workgroup", target="Front office", config=SSH_CONFIG)
    assert status["enabledWorkgroups"] == [
        {"workgroupId": derive_workgroup_id("Front office"), "name": "Front office"}
    ]


def test_enable_requires_valid_effective_config():
    # Squawk Box's configSchema REQUIRES "channel" — enabling with no config
    # (effective {}) must be refused; the plugin is never enabled half-set-up.
    store = _store()
    with pytest.raises(InvalidPluginConfig, match="channel"):
        store.enable(SQUAWK, scope="workgroup", target="North crew")
    assert store.status(SQUAWK)["enabledWorkgroups"] == []


def test_enable_with_config_stores_it():
    store = _store()
    store.enable(SQUAWK, scope="workgroup", target="North crew", config={"channel": "crew-north"})
    assert store.get_config(SQUAWK, scope="workgroup", target="North crew") == {
        "channel": "crew-north"
    }


def test_enable_reuses_previously_stored_config():
    # Configure-then-enable (the PLUGINS.md lifecycle order): config saved
    # first makes a later config-less enable valid.
    store = _store()
    store.set_config(SQUAWK, scope="device", target="dev-a", config={"channel": "yard"})
    status = store.enable(SQUAWK, scope="device", target="dev-a")
    assert status["enabledDevices"] == ["dev-a"]


def test_enable_with_invalid_config_is_refused_and_nothing_stored():
    store = _store()
    with pytest.raises(InvalidPluginConfig):
        store.enable(SSH, scope="device", target="dev-a", config={"listenPort": "not-a-port"})
    assert store.status(SSH)["enabledDevices"] == []
    assert store.get_config(SSH, scope="device", target="dev-a") == {}


def test_enable_is_idempotent():
    store = _store()
    store.enable(SSH, scope="device", target="dev-a", config=SSH_CONFIG)
    status = store.enable(SSH, scope="device", target="dev-a")  # config kept
    assert status["enabledDevices"] == ["dev-a"]


def test_disable_keeps_config_for_reenable(tmp_path):
    store = _store(tmp_path)
    store.enable(SQUAWK, scope="device", target="dev-a", config={"channel": "yard"})
    status = store.disable(SQUAWK, scope="device", target="dev-a")
    assert status["enabledDevices"] == []
    assert store.get_config(SQUAWK, scope="device", target="dev-a") == {"channel": "yard"}
    # Re-enable without config succeeds off the kept config — and persists.
    assert _store(tmp_path).enable(SQUAWK, scope="device", target="dev-a")["enabledDevices"] == [
        "dev-a"
    ]


def test_disable_of_never_enabled_target_is_a_noop():
    store = _store()
    status = store.disable(SSH, scope="workgroup", target="Front office")
    assert status["enabledWorkgroups"] == []


def test_enabled_devices_and_workgroups_are_sorted():
    store = _store()
    store.enable(SSH, scope="device", target="dev-b", config=SSH_CONFIG)
    store.enable(SSH, scope="device", target="dev-a", config=SSH_CONFIG)
    store.enable(SSH, scope="workgroup", target="Yard", config=SSH_CONFIG)
    store.enable(SSH, scope="workgroup", target="Front office", config=SSH_CONFIG)
    status = store.status(SSH)
    assert status["enabledDevices"] == ["dev-a", "dev-b"]
    assert [w["name"] for w in status["enabledWorkgroups"]] == ["Front office", "Yard"]


def test_unknown_plugin_raises_everywhere():
    store = _store()
    with pytest.raises(PluginNotFound):
        store.status("ghost")
    with pytest.raises(PluginNotFound):
        store.enable("ghost", scope="device", target="dev-a")
    with pytest.raises(PluginNotFound):
        store.disable("ghost", scope="device", target="dev-a")
    with pytest.raises(PluginNotFound):
        store.get_config("ghost", scope="device", target="dev-a")
    with pytest.raises(PluginNotFound):
        store.set_config("ghost", scope="device", target="dev-a", config={})
    with pytest.raises(PluginNotFound):
        store.report_health("ghost", device_id="dev-a", status="ok")


# --- PluginStore: config storage ------------------------------------------------


def test_set_config_validates_against_manifest_schema():
    store = _store()
    with pytest.raises(InvalidPluginConfig, match="listenPort"):
        store.set_config(SSH, scope="device", target="dev-a", config={"allowScp": True})


def test_set_config_rejects_unknown_keys():
    # additionalProperties: false in the SSH configSchema — fail fast (§0.11).
    store = _store()
    with pytest.raises(InvalidPluginConfig):
        store.set_config(
            SSH, scope="device", target="dev-a", config={"listenPort": 22, "typo": True}
        )


def test_set_and_get_config_round_trip_per_target(tmp_path):
    store = _store(tmp_path)
    store.set_config(SSH, scope="device", target="dev-a", config={"listenPort": 2201})
    store.set_config(SSH, scope="workgroup", target="Yard", config={"listenPort": 2202})
    assert store.get_config(SSH, scope="device", target="dev-a") == {"listenPort": 2201}
    assert store.get_config(SSH, scope="workgroup", target="Yard") == {"listenPort": 2202}
    reloaded = _store(tmp_path)
    assert reloaded.get_config(SSH, scope="device", target="dev-a") == {"listenPort": 2201}


def test_get_config_defaults_to_empty():
    assert _store().get_config(SSH, scope="device", target="dev-a") == {}


def test_invalid_set_config_leaves_previous_config_untouched():
    store = _store()
    store.set_config(SSH, scope="device", target="dev-a", config={"listenPort": 2201})
    with pytest.raises(InvalidPluginConfig):
        store.set_config(SSH, scope="device", target="dev-a", config={"listenPort": 0})
    assert store.get_config(SSH, scope="device", target="dev-a") == {"listenPort": 2201}


def test_nested_config_validates_against_nested_schema():
    store = _store()
    good = {"channel": "yard", "squelch": {"enabled": True, "threshold": -45}}
    store.set_config(SQUAWK, scope="device", target="dev-a", config=good)
    with pytest.raises(InvalidPluginConfig):
        store.set_config(
            SQUAWK,
            scope="device",
            target="dev-a",
            config={"channel": "yard", "squelch": {"threshold": 10}},  # > maximum 0
        )


# --- PluginStore: reported health (the heartbeat rule applied to plugins) -------


def test_health_report_round_trips_with_injected_clock(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    entry = store.report_health(SSH, device_id="dev-a", status="ok")
    assert entry == {
        "deviceId": "dev-a",
        "status": "ok",
        "reportedAt": "2026-06-12T12:00:00+00:00",
    }
    assert store.status(SSH)["health"] == [entry]
    # Persisted: a reload sees the same report (clock still fresh).
    assert _store(tmp_path, clock).status(SSH)["health"] == [entry]


def test_health_failing_report_carries_detail():
    store = _store()
    store.report_health(SSH, device_id="dev-a", status="failing", detail="connection refused")
    (entry,) = store.status(SSH)["health"]
    assert entry["status"] == "failing"
    assert entry["detail"] == "connection refused"


def test_health_goes_stale_past_the_ttl():
    clock = FakeClock()
    store = _store(clock=clock)
    store.report_health(SSH, device_id="dev-a", status="ok")
    clock.advance(HEALTH_TTL_S - 1)
    assert store.status(SSH)["health"][0]["status"] == "ok"
    clock.advance(2)  # now past the TTL — reports stopped, like a missed heartbeat
    assert store.status(SSH)["health"][0]["status"] == "stale"


def test_health_newer_report_replaces_the_old_one():
    clock = FakeClock()
    store = _store(clock=clock)
    store.report_health(SSH, device_id="dev-a", status="failing", detail="boot")
    clock.advance(10)
    store.report_health(SSH, device_id="dev-a", status="ok")
    (entry,) = store.status(SSH)["health"]
    assert entry["status"] == "ok"
    assert "detail" not in entry


def test_health_entries_sorted_by_device():
    store = _store()
    store.report_health(SSH, device_id="dev-b", status="ok")
    store.report_health(SSH, device_id="dev-a", status="ok")
    assert [e["deviceId"] for e in store.status(SSH)["health"]] == ["dev-a", "dev-b"]


def test_health_report_for_unmonitored_plugin_is_refused():
    # Squawk Box declares healthEndpoint: null — there is nothing to report on.
    with pytest.raises(PluginNotMonitored):
        _store().report_health(SQUAWK, device_id="dev-a", status="ok")


def test_default_clock_is_aware_utc():
    store = PluginStore(CATALOG_DIR, None)
    entry = store.report_health(SSH, device_id="dev-a", status="ok")
    parsed = _dt.datetime.fromisoformat(entry["reportedAt"])
    assert parsed.utcoffset() == _dt.timedelta(0)


# --- the Registry routes ---------------------------------------------------------


def _app(
    *, with_audit: bool = True, clock: FakeClock | None = None
) -> tuple[TestClient, PluginStore, AuditLog | None]:
    clock = clock or FakeClock()
    plugin_store = _store(clock=clock)
    audit_log = AuditLog(None, clock=clock) if with_audit else None
    app = create_app(
        RegistryStore(state_path=None),
        JwtVerifier(TEST_JWT_SECRET, "HS256", ISSUER),
        plugin_store=plugin_store,
        audit_log=audit_log,
    )
    return TestClient(app), plugin_store, audit_log


def _auth(subject: str = MANAGER) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_test_token(subject, secret=TEST_JWT_SECRET)}"}


def test_plugin_routes_require_auth():
    client, _, _ = _app()
    body = {"scope": "device", "target": "dev-a"}
    assert client.get("/plugins").status_code == 401
    assert client.post(f"/plugins/{SSH}/enable", json=body).status_code == 401
    assert client.post(f"/plugins/{SSH}/disable", json=body).status_code == 401
    assert (
        client.get(f"/plugins/{SSH}/config", params={"scope": "device", "target": "dev-a"})
    ).status_code == 401
    assert (client.put(f"/plugins/{SSH}/config", json={**body, "config": {}})).status_code == 401
    assert (
        client.post(f"/plugins/{SSH}/health", json={"deviceId": "dev-a", "status": "ok"})
    ).status_code == 401


def test_get_plugins_returns_the_catalog_view():
    client, _, _ = _app()
    body = client.get("/plugins", headers=_auth()).json()
    assert [p["manifest"]["id"] for p in body["plugins"]] == [SSH, SQUAWK]
    assert body["generatedAt"]


def test_enable_route_round_trips_and_audits():
    client, _, audit_log = _app()
    r = client.post(
        f"/plugins/{SSH}/enable",
        json={"scope": "workgroup", "target": "Front office", "config": SSH_CONFIG},
        headers=_auth(),
    )
    assert r.status_code == 200
    assert r.json()["enabledWorkgroups"][0]["name"] == "Front office"
    # Round-trip: the catalog GET reflects the enable.
    view = client.get("/plugins", headers=_auth()).json()
    ssh = next(p for p in view["plugins"] if p["manifest"]["id"] == SSH)
    assert ssh["enabledWorkgroups"][0]["name"] == "Front office"
    (entry,) = audit_log.entries()
    assert entry["actor"] == MANAGER
    assert entry["action"] == ACTION_PLUGIN_ENABLE
    assert entry["deviceId"] == "Front office"
    assert entry["detail"] == "SSH / SCP"
    assert entry["pluginId"] == SSH
    assert entry["scope"] == "workgroup"


def test_enable_route_refuses_invalid_config_and_does_not_audit():
    client, store, audit_log = _app()
    r = client.post(
        f"/plugins/{SQUAWK}/enable",
        json={"scope": "device", "target": "dev-a"},  # squawk REQUIRES channel
        headers=_auth(),
    )
    assert r.status_code == 400
    assert "channel" in r.json()["detail"]
    assert store.status(SQUAWK)["enabledDevices"] == []
    assert audit_log.entries() == []


def test_enable_route_unknown_plugin_404():
    client, _, _ = _app()
    r = client.post(
        "/plugins/ghost/enable", json={"scope": "device", "target": "dev-a"}, headers=_auth()
    )
    assert r.status_code == 404


def test_disable_route_disables_and_audits():
    client, store, audit_log = _app()
    store.enable(SSH, scope="device", target="dev-a", config=SSH_CONFIG)
    r = client.post(
        f"/plugins/{SSH}/disable",
        json={"scope": "device", "target": "dev-a"},
        headers=_auth(),
    )
    assert r.status_code == 200
    assert r.json()["enabledDevices"] == []
    (entry,) = audit_log.entries()
    assert entry["action"] == ACTION_PLUGIN_DISABLE
    assert entry["deviceId"] == "dev-a"
    assert entry["scope"] == "device"


def test_disable_route_unknown_plugin_404():
    client, _, _ = _app()
    r = client.post(
        "/plugins/ghost/disable", json={"scope": "device", "target": "dev-a"}, headers=_auth()
    )
    assert r.status_code == 404


def test_config_get_set_round_trip_and_audit():
    client, _, audit_log = _app()
    r = client.put(
        f"/plugins/{SSH}/config",
        json={"scope": "workgroup", "target": "Yard", "config": {"listenPort": 2222}},
        headers=_auth(),
    )
    assert r.status_code == 200
    assert r.json() == {"config": {"listenPort": 2222}}
    r = client.get(
        f"/plugins/{SSH}/config",
        params={"scope": "workgroup", "target": "Yard"},
        headers=_auth(),
    )
    assert r.json() == {"config": {"listenPort": 2222}}
    (entry,) = audit_log.entries()
    assert entry["action"] == ACTION_PLUGIN_CONFIG
    assert entry["pluginId"] == SSH


def test_config_put_refuses_invalid_400():
    client, _, _ = _app()
    r = client.put(
        f"/plugins/{SSH}/config",
        json={"scope": "device", "target": "dev-a", "config": {"listenPort": 0}},
        headers=_auth(),
    )
    assert r.status_code == 400


def test_config_routes_unknown_plugin_404():
    client, _, _ = _app()
    assert (
        client.get(
            "/plugins/ghost/config",
            params={"scope": "device", "target": "dev-a"},
            headers=_auth(),
        ).status_code
        == 404
    )
    assert (
        client.put(
            "/plugins/ghost/config",
            json={"scope": "device", "target": "dev-a", "config": {}},
            headers=_auth(),
        ).status_code
        == 404
    )


def test_health_report_route_records_and_shows_in_view():
    client, _, audit_log = _app()
    r = client.post(
        f"/plugins/{SSH}/health",
        json={"deviceId": "dev-a", "status": "ok"},
        headers=_auth(),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    view = client.get("/plugins", headers=_auth()).json()
    ssh = next(p for p in view["plugins"] if p["manifest"]["id"] == SSH)
    assert ssh["health"][0]["deviceId"] == "dev-a"
    # Health reports are telemetry, not management actions — not audited.
    assert audit_log.entries() == []


def test_health_report_route_unmonitored_409_unknown_404():
    client, _, _ = _app()
    r = client.post(
        f"/plugins/{SQUAWK}/health",
        json={"deviceId": "dev-a", "status": "ok"},
        headers=_auth(),
    )
    assert r.status_code == 409
    r = client.post(
        "/plugins/ghost/health", json={"deviceId": "dev-a", "status": "ok"}, headers=_auth()
    )
    assert r.status_code == 404


def test_plugin_mutations_work_without_an_audit_log():
    client, _, audit_log = _app(with_audit=False)
    assert audit_log is None
    r = client.post(
        f"/plugins/{SSH}/enable",
        json={"scope": "device", "target": "dev-a", "config": SSH_CONFIG},
        headers=_auth(),
    )
    assert r.status_code == 200


def test_plugin_routes_absent_when_no_store_is_wired():
    app = create_app(RegistryStore(state_path=None), JwtVerifier(TEST_JWT_SECRET, "HS256", ISSUER))
    client = TestClient(app)
    assert client.get("/plugins", headers=_auth()).status_code == 404
