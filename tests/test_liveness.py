"""Feature #54 — registry agent liveness: heartbeat, lastSeen, stale exclusion.

Covers the store's staleness computation (injected clock — no sleeping), the
registry app's stale filtering on /pool and /schedule, the agent heartbeat
loop (injected sleep + faked httpx client — no network), and the agent app's
lifespan start/cancel of the heartbeat task.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from agent import register
from agent.app import create_app as create_agent_app
from agent.engine import EchoEngine
from common.auth import JwtVerifier
from common.config import load_config
from registry.app import create_app as create_registry_app
from registry.store import RegistryStore
from tests.fakes.jwt_helper import TEST_JWT_SECRET, mint_test_token
from tests.test_register import _Client, _config, _Resp

TTL = 45.0
GPU = {"name": "gpu-server", "cpus": 16, "memory": "32g", "gpus": "all"}


class FakeClock:
    """Injectable UTC clock — tests advance time instead of sleeping."""

    def __init__(self) -> None:
        self.now = _dt.datetime(2026, 6, 10, 12, 0, 0, tzinfo=_dt.UTC)

    def __call__(self) -> _dt.datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += _dt.timedelta(seconds=seconds)


def _store(tmp_path, clock: FakeClock) -> RegistryStore:
    return RegistryStore(tmp_path / "state.json", ttl_s=TTL, clock=clock)


# --- store: lastSeen + status ------------------------------------------------


def test_register_stamps_last_seen_and_active_status(tmp_path):
    clock = FakeClock()
    rec = _store(tmp_path, clock).register("a1", "h:1")
    assert rec["lastSeen"] == clock.now.isoformat()
    assert rec["status"] == "active"


def test_reregister_refreshes_last_seen_and_keeps_registered_at(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    first = store.register("a1", "h:1")
    clock.advance(100)
    second = store.register("a1", "h:1")
    assert second["registeredAt"] == first["registeredAt"]
    assert second["lastSeen"] == clock.now.isoformat()
    assert second["status"] == "active"


def test_stale_strictly_after_ttl_boundary(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    store.register("a1", "h:1")
    clock.advance(TTL)  # age == TTL -> still active (strictly greater is stale)
    assert store.get("a1")["status"] == "active"
    clock.advance(0.001)
    assert store.get("a1")["status"] == "stale"


def test_status_is_computed_not_persisted(tmp_path):
    clock = FakeClock()
    _store(tmp_path, clock).register("a1", "h:1")
    on_disk = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert "status" not in on_disk["a1"]
    assert on_disk["a1"]["lastSeen"] == clock.now.isoformat()


def test_legacy_record_without_last_seen_falls_back_to_registered_at(tmp_path):
    clock = FakeClock()
    path = tmp_path / "state.json"
    legacy = {"a1": {"agentId": "a1", "address": "h:1", "registeredAt": clock.now.isoformat()}}
    path.write_text(json.dumps(legacy), encoding="utf-8")
    store = RegistryStore(path, ttl_s=TTL, clock=clock)
    assert store.get("a1")["status"] == "active"
    clock.advance(TTL + 1)
    assert store.get("a1")["status"] == "stale"


def test_record_without_any_timestamp_is_stale(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"a1": {"agentId": "a1", "address": "h:1"}}), encoding="utf-8")
    store = RegistryStore(path, ttl_s=TTL, clock=FakeClock())
    assert store.get("a1")["status"] == "stale"


def test_list_keeps_stale_unless_excluded_and_pool_excludes_stale(tmp_path):
    clock = FakeClock()
    store = _store(tmp_path, clock)
    store.register("old", "h:1", ["gpu"], GPU)
    clock.advance(TTL + 1)  # "old" goes stale
    store.register("fresh", "h:2", ["gpu"], GPU)
    assert {a["agentId"]: a["status"] for a in store.list()} == {
        "old": "stale",
        "fresh": "active",
    }
    assert [a["agentId"] for a in store.list(include_stale=False)] == ["fresh"]
    # Stale node's profile no longer counts toward pooled capacity.
    assert store.pool() == {"nodes": 1, "cpus": 16.0, "memoryBytes": 32 * 1024**3, "gpuNodes": 1}


# --- registry app: stale exclusion over HTTP ----------------------------------


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_test_token(secret=TEST_JWT_SECRET)}"}


def _registry_client(tmp_path, clock: FakeClock) -> tuple[TestClient, RegistryStore]:
    store = _store(tmp_path, clock)
    verifier = JwtVerifier(TEST_JWT_SECRET, "HS256", "bardllm-pro")
    return TestClient(create_registry_app(store, verifier)), store


def test_agents_endpoints_expose_last_seen_and_status(tmp_path):
    clock = FakeClock()
    client, _ = _registry_client(tmp_path, clock)
    client.post("/register", json={"agentId": "a1", "address": "h:1"}, headers=_auth())
    listed = client.get("/agents", headers=_auth()).json()
    assert listed[0]["lastSeen"] == clock.now.isoformat()
    assert listed[0]["status"] == "active"
    single = client.get("/agents/a1", headers=_auth()).json()
    assert single["status"] == "active" and single["lastSeen"] == clock.now.isoformat()


def test_schedule_skips_stale_agents(tmp_path):
    clock = FakeClock()
    client, store = _registry_client(tmp_path, clock)
    store.register("old-gpu", "h:1", ["gpu"], GPU)
    clock.advance(TTL + 1)
    store.register("fresh-cpu", "h:2", ["llm"], {"name": "laptop", "cpus": 2})
    # The stale GPU node would win placement; staleness must exclude it.
    chosen = client.get("/schedule", params={"gpu": "true"}, headers=_auth()).json()
    assert chosen["agentId"] == "fresh-cpu"


def test_schedule_404_when_all_agents_stale(tmp_path):
    clock = FakeClock()
    client, store = _registry_client(tmp_path, clock)
    store.register("only", "h:1", ["gpu"], GPU)
    clock.advance(TTL + 1)
    resp = client.get("/schedule", headers=_auth())
    assert resp.status_code == 404 and resp.json()["error"] == "not_found"


# --- agent heartbeat loop ------------------------------------------------------


class _CancellingSleep:
    """Fake asyncio.sleep — yields `allowed` times, then cancels the loop."""

    def __init__(self, allowed: int):
        self.allowed = allowed
        self.intervals: list[float] = []

    async def __call__(self, interval: float) -> None:
        if len(self.intervals) >= self.allowed:
            raise asyncio.CancelledError
        self.intervals.append(interval)


def test_heartbeat_reposts_register_on_interval():
    client = _Client(_Resp({"agentId": "gpu-1", "address": "10.0.0.5:8444"}))
    sleep = _CancellingSleep(allowed=1)
    cfg = _config(self_register=True, heartbeat_interval_s=5.0)

    async def run() -> None:
        await register.heartbeat_loop(cfg, client=client, sleep=sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run())
    assert sleep.intervals == [5.0]
    assert client.posted["url"] == "https://10.0.0.2:8081/register"
    assert client.posted["json"]["agentId"] == "gpu-1"


def test_heartbeat_http_error_logged_and_loop_continues(caplog):
    client = _Client(_Resp(error=httpx.HTTPError("registry down")))
    sleep = _CancellingSleep(allowed=2)  # two failed beats before cancellation

    async def run() -> None:
        await register.heartbeat_loop(_config(self_register=True), client=client, sleep=sleep)

    with caplog.at_level(logging.WARNING), pytest.raises(asyncio.CancelledError):
        asyncio.run(run())
    assert len(sleep.intervals) == 2  # survived the first failure and retried
    assert "heartbeat re-registration failed" in caplog.text


def test_heartbeat_config_error_logged_and_loop_continues(caplog):
    sleep = _CancellingSleep(allowed=2)
    cfg = _config(self_register=True, jwt_secret=None)  # require() raises ConfigError

    async def run() -> None:
        await register.heartbeat_loop(cfg, sleep=sleep)

    with caplog.at_level(logging.WARNING), pytest.raises(asyncio.CancelledError):
        asyncio.run(run())
    assert len(sleep.intervals) == 2
    assert "heartbeat re-registration failed" in caplog.text


def test_heartbeat_default_sleep_branch():
    # sleep=None -> real asyncio.sleep; interval 0 keeps the test instant.
    client = _Client(_Resp({"ok": True}))
    cfg = _config(self_register=True, heartbeat_interval_s=0.0)

    async def run() -> None:
        task = asyncio.create_task(register.heartbeat_loop(cfg, client=client))
        while client.posted is None:
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert client.posted["json"]["agentId"] == "gpu-1"


# --- agent app lifespan: heartbeat task start/cancel ----------------------------


def _verifier() -> JwtVerifier:
    return JwtVerifier(TEST_JWT_SECRET, "HS256", "bardllm-pro")


def test_agent_app_starts_and_cancels_heartbeat_task():
    state = {"started": False, "cancelled": False}

    async def heartbeat() -> None:
        state["started"] = True
        try:
            await asyncio.Event().wait()  # run until cancelled at shutdown
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise

    app = create_agent_app(EchoEngine("agent-1"), _verifier(), heartbeat=heartbeat)
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert state["started"] is True
        assert state["cancelled"] is False
    assert state["cancelled"] is True


def test_agent_app_without_heartbeat_runs_lifespan_noop():
    app = create_agent_app(EchoEngine("agent-1"), _verifier())
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}


# --- config: new liveness fields coerce from env --------------------------------


def test_liveness_config_fields_default_and_coerce():
    cfg = load_config(dotenv_path=None, environ={})
    assert cfg.heartbeat_interval_s == 15.0 and cfg.agent_ttl_s == 45.0
    cfg = load_config(
        dotenv_path=None,
        environ={"BARDPRO_HEARTBEAT_INTERVAL_S": "5", "BARDPRO_AGENT_TTL_S": "20.5"},
    )
    assert cfg.heartbeat_interval_s == 5.0 and cfg.agent_ttl_s == 20.5
