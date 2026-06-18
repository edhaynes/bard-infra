"""CORS for the demo console (browser → Registry). `apply_cors` is off by
default (covered by every other create_app call passing no origins); this covers
the origins-set branch."""

from __future__ import annotations

from fastapi.testclient import TestClient

from common.auth import JwtVerifier
from registry.app import create_app
from registry.store import RegistryStore

ORIGIN = "http://localhost:5173"


def test_registry_cors_enabled_echoes_origin():
    app = create_app(
        RegistryStore(), JwtVerifier("x" * 32, "HS256", "bardllm-pro"), cors_origins=[ORIGIN]
    )
    resp = TestClient(app).get("/healthz", headers={"Origin": ORIGIN})
    assert resp.headers.get("access-control-allow-origin") == ORIGIN
