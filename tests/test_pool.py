"""Capability persistence + pooled-capacity aggregation (demo Phase 1).

Covers `common.power.parse_memory_bytes` / `aggregate_pool`, the registry store
persisting + aggregating power profiles, and the `GET /pool` endpoint — against
`contracts/registry.openapi.yaml` (PoolCapacity) with no network.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from common.auth import JwtVerifier
from common.power import aggregate_pool, parse_memory_bytes
from registry.app import create_app
from registry.store import RegistryStore
from tests.fakes.jwt_helper import TEST_JWT_SECRET, mint_test_token

GPU = {"name": "gpu-server", "cpus": 16, "memory": "32g", "gpus": "all"}
LAPTOP = {"name": "laptop", "cpus": 2, "memory": "2g", "gpus": None}


# --- common.power.parse_memory_bytes ---------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [("2g", 2 * 1024**3), ("512m", 512 * 1024**2), ("8k", 8 * 1024), ("100b", 100), ("1024", 1024)],
)
def test_parse_memory_bytes_units_and_bare(text, expected):
    assert parse_memory_bytes(text) == expected


def test_parse_memory_bytes_invalid_raises():
    with pytest.raises(ValueError):
        parse_memory_bytes("2x")


# --- common.power.aggregate_pool -------------------------------------------


def test_aggregate_pool_empty():
    assert aggregate_pool([]) == {"nodes": 0, "cpus": 0.0, "memoryBytes": 0, "gpuNodes": 0}


def test_aggregate_pool_mixed_fields():
    # one full GPU node, one CPU laptop, and one sparse profile missing every
    # optional field — exercises the present/absent branch of each.
    out = aggregate_pool([GPU, LAPTOP, {"name": "sparse"}])
    assert out == {
        "nodes": 3,
        "cpus": 18.0,
        "memoryBytes": 34 * 1024**3,
        "gpuNodes": 1,
    }


# --- registry store --------------------------------------------------------


def test_store_persists_and_returns_power_profile():
    store = RegistryStore()
    rec = store.register("a1", "10.0.0.5:8444", ["gpu", "llm"], GPU)
    assert rec["powerProfile"] == GPU
    assert store.get("a1")["powerProfile"] == GPU


def test_store_register_without_power_profile_omits_it():
    store = RegistryStore()
    rec = store.register("a2", "10.0.0.6:8444")
    assert "powerProfile" not in rec


def test_store_pool_aggregates_only_profiled_agents():
    store = RegistryStore()
    store.register("gpu", "h1:8444", ["gpu"], GPU)
    store.register("cpu", "h2:8444", ["llm"], LAPTOP)
    store.register("bare", "h3:8444")  # no profile → excluded from the pool
    assert store.pool() == {"nodes": 2, "cpus": 18.0, "memoryBytes": 34 * 1024**3, "gpuNodes": 1}


# --- GET /pool endpoint ----------------------------------------------------


def _client() -> TestClient:
    store = RegistryStore()
    store.register("gpu", "h1:8444", ["gpu"], GPU)
    verifier = JwtVerifier(TEST_JWT_SECRET, "HS256", "bardllm-pro")
    return TestClient(create_app(store, verifier))


def test_pool_endpoint_authed_returns_aggregate():
    resp = _client().get(
        "/pool",
        headers={"Authorization": f"Bearer {mint_test_token(secret=TEST_JWT_SECRET)}"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"nodes": 1, "cpus": 16.0, "memoryBytes": 32 * 1024**3, "gpuNodes": 1}


def test_pool_endpoint_unauthed_401():
    resp = _client().get("/pool")
    assert resp.status_code == 401
    assert resp.json()["error"] == "unauthorized"
