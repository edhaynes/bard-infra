"""Prometheus metrics for the fleet apps (feature #55).

Each app gets its own :class:`AppMetrics` with a **per-app**
``CollectorRegistry`` — never the global default registry, because the test
suite creates apps repeatedly and the global registry would raise
duplicate-timeseries errors.

``instrument`` wires a Starlette middleware that records
``http_requests_total{service,path,status}`` and the
``http_request_duration_seconds{service,path}`` histogram, plus an
unauthenticated ``GET /metrics`` exposition endpoint (standard scrape
practice, same trust level as ``/healthz``). ``/metrics`` itself is excluded
from instrumentation. The clock is injectable so duration tests are
deterministic.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from fastapi import FastAPI, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

METRICS_PATH = "/metrics"


class AppMetrics:
    """Per-app metric family holder backed by an isolated registry."""

    def __init__(
        self,
        service: str,
        *,
        registry: CollectorRegistry | None = None,
        clock: Callable[[], float] | None = None,
    ):
        self.service = service
        self.registry = registry or CollectorRegistry()
        self.clock = clock or time.perf_counter
        self.http_requests = Counter(
            "http_requests_total",
            "HTTP requests handled, by service, route and response status.",
            ["service", "path", "status"],
            registry=self.registry,
        )
        self.http_duration = Histogram(
            "http_request_duration_seconds",
            "HTTP request handling duration in seconds, by service and route.",
            ["service", "path"],
            registry=self.registry,
        )

    def render(self) -> bytes:
        """Prometheus text exposition of this app's registry."""
        return generate_latest(self.registry)


def make_inference_counter(metrics: AppMetrics) -> Counter:
    """Agent-only counter: inference attempts by backend and outcome."""
    return Counter(
        "inference_requests_total",
        "Inference requests executed by the agent engine, by backend and outcome.",
        ["backend", "outcome"],
        registry=metrics.registry,
    )


class BrokerMetrics:
    """Router-only broker-link metrics (feature #59 / ADR-0013).

    Same per-app-registry pattern as :func:`make_inference_counter`: families
    are registered on the injected :class:`AppMetrics` registry, never the
    global one. ``agentId`` label cardinality is bounded by fleet size.
    """

    def __init__(self, metrics: AppMetrics):
        self.link_active = Gauge(
            "broker_link_active",
            "1 while an agent holds a live outbound broker link, else 0.",
            ["agentId"],
            registry=metrics.registry,
        )
        self.dispatch = Counter(
            "broker_dispatch_total",
            "Broker-link dispatches by agent and outcome "
            "(ok|error|timeout|disconnected|send_failed).",
            ["agentId", "outcome"],
            registry=metrics.registry,
        )


def instrument(app: FastAPI, metrics: AppMetrics) -> None:
    """Attach request instrumentation + the ``GET /metrics`` endpoint."""

    @app.middleware("http")
    async def _observe(request: Request, call_next):
        if request.url.path == METRICS_PATH:
            return await call_next(request)  # never self-instrument the scrape
        start = metrics.clock()
        response = await call_next(request)
        elapsed = metrics.clock() - start
        # Label with the matched route template (bounded cardinality); fall
        # back to the raw path for unmatched routes (404s).
        route = request.scope.get("route")
        path = route.path if route else request.url.path
        metrics.http_requests.labels(
            service=metrics.service, path=path, status=str(response.status_code)
        ).inc()
        metrics.http_duration.labels(service=metrics.service, path=path).observe(elapsed)
        return response

    @app.get(METRICS_PATH)
    def metrics_endpoint() -> Response:
        return Response(content=metrics.render(), media_type=CONTENT_TYPE_LATEST)
