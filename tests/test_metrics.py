"""Feature #55 — /metrics (Prometheus) on router, registry, and agent apps.

Each test injects an AppMetrics with its own CollectorRegistry (never the
global default — apps are created repeatedly across the suite) and reads
samples back via ``registry.get_sample_value``. The duration clock is
injected, so nothing here measures real time.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry

from agent.app import create_app as create_agent_app
from agent.engine import EchoEngine, InferenceError
from common.auth import JwtVerifier
from common.metrics import AppMetrics
from registry.app import create_app as create_registry_app
from registry.store import RegistryStore
from router.app import create_app as create_router_app
from router.clients import AgentUnavailable
from tests.fakes.jwt_helper import TEST_JWT_SECRET, mint_test_token


def _verifier() -> JwtVerifier:
    return JwtVerifier(TEST_JWT_SECRET, "HS256", "bardllm-pro")


def _registry_client(metrics: AppMetrics) -> TestClient:
    return TestClient(create_registry_app(RegistryStore(), _verifier(), metrics=metrics))


# --- exposition + request counting ------------------------------------------


def test_metrics_endpoint_exposes_request_counter():
    metrics = AppMetrics("registry")
    client = _registry_client(metrics)
    client.get("/healthz")
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert "http_requests_total" in resp.text
    assert (
        metrics.registry.get_sample_value(
            "http_requests_total", {"service": "registry", "path": "/healthz", "status": "200"}
        )
        == 1.0
    )


def test_metrics_endpoint_is_not_self_instrumented():
    metrics = AppMetrics("registry")
    client = _registry_client(metrics)
    client.get("/metrics")
    scrape = client.get("/metrics").text
    assert 'path="/metrics"' not in scrape


def test_duration_histogram_uses_injected_clock():
    ticks = iter([10.0, 11.5])  # start, end -> 1.5 s elapsed
    metrics = AppMetrics("registry", registry=CollectorRegistry(), clock=lambda: next(ticks))
    client = _registry_client(metrics)
    client.get("/healthz")
    assert (
        metrics.registry.get_sample_value(
            "http_request_duration_seconds_sum", {"service": "registry", "path": "/healthz"}
        )
        == 1.5
    )
    assert (
        metrics.registry.get_sample_value(
            "http_request_duration_seconds_count", {"service": "registry", "path": "/healthz"}
        )
        == 1.0
    )


def test_path_label_uses_route_template_with_raw_fallback():
    metrics = AppMetrics("registry")
    client = _registry_client(metrics)
    auth = {"Authorization": f"Bearer {mint_test_token(secret=TEST_JWT_SECRET)}"}
    client.get("/agents/some-agent", headers=auth)  # matched: template label
    client.get("/no-such-route")  # unmatched 404: raw-path label
    assert (
        metrics.registry.get_sample_value(
            "http_requests_total",
            {"service": "registry", "path": "/agents/{agent_id}", "status": "404"},
        )
        == 1.0
    )
    assert (
        metrics.registry.get_sample_value(
            "http_requests_total",
            {"service": "registry", "path": "/no-such-route", "status": "404"},
        )
        == 1.0
    )


# --- router app ---------------------------------------------------------------


class _UnusedRegistry:
    def lookup(self, agent_id: str, token: str) -> str:  # pragma: no cover - never reached
        raise AgentUnavailable("unused")


class _UnusedAgent:
    def infer(self, address, request, token):  # pragma: no cover - never reached
        raise AssertionError("should not be called")


def test_router_metrics_count_requests():
    metrics = AppMetrics("router")
    client = TestClient(
        create_router_app(_UnusedRegistry(), _UnusedAgent(), _verifier(), metrics=metrics)
    )
    client.get("/healthz")
    assert (
        metrics.registry.get_sample_value(
            "http_requests_total", {"service": "router", "path": "/healthz", "status": "200"}
        )
        == 1.0
    )
    assert "http_request_duration_seconds" in client.get("/metrics").text


# --- agent app: inference_requests_total{backend,outcome} ----------------------


class _BoomEngine:
    def infer(self, request):
        raise InferenceError("backend down")


def _infer_body() -> dict:
    return {
        "id": "c3f9a1e2-7b4d-4a12-9f8b-1e2d3f4a5b6c",
        "type": "text",
        "content": "hi",
        "metadata": {
            "targetAgent": "a1",
            "authToken": mint_test_token(secret=TEST_JWT_SECRET),
        },
    }


def test_agent_inference_counter_ok_outcome():
    metrics = AppMetrics("agent")
    app = create_agent_app(EchoEngine("a1"), _verifier(), metrics=metrics, backend_name="echo")
    resp = TestClient(app).post("/infer", json=_infer_body())
    assert resp.status_code == 200
    assert (
        metrics.registry.get_sample_value(
            "inference_requests_total", {"backend": "echo", "outcome": "ok"}
        )
        == 1.0
    )


def test_agent_inference_counter_error_outcome():
    metrics = AppMetrics("agent")
    app = create_agent_app(_BoomEngine(), _verifier(), metrics=metrics, backend_name="llamacpp")
    resp = TestClient(app).post("/infer", json=_infer_body())
    assert resp.status_code == 502
    assert (
        metrics.registry.get_sample_value(
            "inference_requests_total", {"backend": "llamacpp", "outcome": "error"}
        )
        == 1.0
    )
    assert (
        metrics.registry.get_sample_value(
            "inference_requests_total", {"backend": "llamacpp", "outcome": "ok"}
        )
        is None
    )


def test_agent_metrics_endpoint_default_appmetrics():
    # No injected AppMetrics: create_app builds its own isolated registry.
    app = create_agent_app(EchoEngine("a1"), _verifier())
    resp = TestClient(app).get("/metrics")
    assert resp.status_code == 200 and "http_requests_total" in resp.text
