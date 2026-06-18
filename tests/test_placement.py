"""Capability-aware placement (demo Phase 1.4) — `select_agent` + GET /schedule.

Pure-function ranking + the Registry endpoint, against
`contracts/registry.openapi.yaml`, with no network.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from common.auth import JwtVerifier
from common.placement import select_agent
from registry.app import create_app
from registry.store import RegistryStore
from tests.fakes.jwt_helper import TEST_JWT_SECRET, mint_test_token

GPU = {
    "agentId": "gpu",
    "powerProfile": {"name": "gpu", "cpus": 16, "memory": "32g", "gpus": "all"},
}
CPU_BIG = {"agentId": "big", "powerProfile": {"name": "big", "cpus": 8, "memory": "16g"}}
CPU_SMALL = {"agentId": "small", "powerProfile": {"name": "small", "cpus": 2, "memory": "2g"}}
BARE = {"agentId": "bare"}  # no power profile → no gpu, 0 cpus, 0 memory


# --- select_agent ----------------------------------------------------------


def test_select_empty_fleet_returns_none():
    assert select_agent([]) is None


def test_select_require_gpu_picks_gpu_node():
    assert select_agent([CPU_SMALL, GPU, CPU_BIG], require_gpu=True)["agentId"] == "gpu"


def test_select_require_gpu_falls_back_to_cpu_when_no_gpu():
    # CPU fallback ("any accelerator") — best CPU node wins.
    assert select_agent([CPU_SMALL, CPU_BIG], require_gpu=True)["agentId"] == "big"


def test_select_no_gpu_ranks_by_cpus_then_memory():
    # exercises absent-profile (BARE: 0/0/no-gpu) vs present ranking.
    assert select_agent([BARE, CPU_SMALL, CPU_BIG])["agentId"] == "big"


# --- GET /schedule ---------------------------------------------------------


def _auth() -> dict:
    return {"Authorization": f"Bearer {mint_test_token(secret=TEST_JWT_SECRET)}"}


def _client(*agents) -> TestClient:
    store = RegistryStore()
    for a in agents:
        store.register(a["agentId"], "h:8444", a.get("capabilities"), a.get("powerProfile"))
    verifier = JwtVerifier(TEST_JWT_SECRET, "HS256", "bardllm-pro")
    return TestClient(create_app(store, verifier))


def test_schedule_authed_gpu_picks_gpu_node():
    resp = _client(CPU_SMALL, GPU).get("/schedule", params={"gpu": "true"}, headers=_auth())
    assert resp.status_code == 200
    assert resp.json()["agentId"] == "gpu"


def test_schedule_no_agents_404():
    resp = _client().get("/schedule", headers=_auth())
    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


def test_schedule_unauthed_401():
    resp = _client(GPU).get("/schedule")
    assert resp.status_code == 401
    assert resp.json()["error"] == "unauthorized"
