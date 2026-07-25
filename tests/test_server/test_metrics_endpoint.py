"""Tests for the /metrics HTTP endpoint (Plan 7 fix).

The endpoint was previously dead code — get_router() existed but
app.py never called it. These tests verify the wiring + format.
"""
import re

from fastapi.testclient import TestClient

from src.server.app import create_app
from src.server.metrics_route import get_router


def _client() -> TestClient:
    return TestClient(create_app())


def test_metrics_endpoint_returns_200() -> None:
    """GET /metrics returns 200 (the Plan 7 bug was 404)."""
    r = _client().get("/metrics")
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:200]}"


def test_metrics_endpoint_returns_prometheus_format() -> None:
    """Body looks like Prometheus text format (HELP/TYPE comments optional but # prefix is required)."""
    r = _client().get("/metrics")
    assert r.headers["content-type"].startswith("text/plain")
    # Either has metric lines or is empty (no metrics registered yet)
    body = r.text
    # If non-empty, every non-comment line should be `<name>{<labels>} <value>`
    for line in body.splitlines():
        if not line or line.startswith("#"):
            continue
        # basic shape: at least one space separates name+labels from value
        assert " " in line, f"malformed metric line: {line!r}"


def test_metrics_endpoint_idempotent() -> None:
    """Calling get_router() twice returns the same router instance (id)."""
    r1 = get_router()
    r2 = get_router()
    assert r1 is r2, "get_router() must cache and return the same router instance"


def test_metrics_endpoint_includes_ruflo_ingest_total() -> None:
    """The pre-registered ruflo_ingest_total counter appears in the response."""
    # Increment the pre-registered counter so it has a non-zero value
    from src.metrics import INGEST_TOTAL
    INGEST_TOTAL.inc(1, status="ok", source_type="url")

    r = _client().get("/metrics")
    assert r.status_code == 200
    assert "ruflo_ingest_total" in r.text, f"counter not in response: {r.text}"
