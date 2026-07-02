"""S3 — the read-only GET /nodes route (control-plane.openapi.yaml NodesView).

Same app-test pattern as tests/test_fleet.py: in-process TestClient, injected
JWT verifier, bearer auth header. Covers the authed happy path over a populated
temp cache dir, the fail-soft empty view for a missing dir and for an unwired
cache, and the unauthorized guard.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from common.auth import JwtVerifier
from registry.app import create_app
from registry.store import RegistryStore
from tests.fakes.jwt_helper import TEST_JWT_SECRET, mint_test_token

ISSUER = "bardllm-pro"


def _client(*, facts_cache_dir=None) -> TestClient:
    store = RegistryStore(state_path=None)
    verifier = JwtVerifier(TEST_JWT_SECRET, "HS256", ISSUER)
    app = create_app(
        store,
        verifier,
        facts_cache_dir=str(facts_cache_dir) if facts_cache_dir is not None else None,
    )
    return TestClient(app)


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_test_token(secret=TEST_JWT_SECRET)}"}


def test_nodes_requires_auth():
    assert _client().get("/nodes").status_code == 401


def test_nodes_happy_path_over_populated_cache(tmp_path):
    (tmp_path / "gx10").write_text(
        json.dumps(
            {
                "ansible_hostname": "gx10",
                "ansible_architecture": "aarch64",
                "ansible_processor": ["0", "ARM", "NVIDIA Grace"],
                "ansible_processor_cores": 10,
                "ansible_processor_count": 2,
                "ansible_processor_vcpus": 20,
                "ansible_memtotal_mb": 131072,
                "bard_gpu": ["NVIDIA GB10, 131072"],
                "ansible_devices": {"nvme0n1": {"size": "3.64 TB"}, "loop0": {"size": "1 GB"}},
                "ansible_interfaces": ["lo", "enp1s0"],
                "ansible_default_ipv4": {"interface": "enp1s0"},
                "ansible_enp1s0": {"ipv4": {"address": "10.0.0.2"}, "speed": 10000},
                "ansible_date_time": {"iso8601": "2026-07-01T08:00:00+00:00"},
            }
        ),
        encoding="utf-8",
    )
    body = _client(facts_cache_dir=tmp_path).get("/nodes", headers=_auth()).json()
    assert body["generatedAt"]
    (node,) = body["nodes"]
    assert node["nodeId"] == "gx10"
    assert node["cpu"] == {"model": "NVIDIA Grace", "arch": "aarch64", "cores": 20, "vcpus": 20}
    assert node["memory"] == {"totalMb": 131072}
    assert node["gpu"] == {"model": "NVIDIA GB10", "memoryMb": 131072}
    assert node["storage"] == [{"device": "nvme0n1", "sizeGb": 3640.0}]
    assert node["networking"] == [{"iface": "enp1s0", "ipv4": "10.0.0.2", "speedMbps": 10000}]
    assert node["gatheredAt"] == "2026-07-01T08:00:00+00:00"


def test_nodes_missing_cache_dir_is_empty_view(tmp_path):
    body = _client(facts_cache_dir=tmp_path / "absent").get("/nodes", headers=_auth()).json()
    assert body["nodes"] == []
    assert body["generatedAt"]


def test_nodes_unwired_cache_is_empty_view():
    body = _client().get("/nodes", headers=_auth()).json()
    assert body["nodes"] == []
    assert body["generatedAt"]
