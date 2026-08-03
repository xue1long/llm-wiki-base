"""Tests for the /metrics HTTP endpoint (Plan 7 fix).

The endpoint was previously dead code — get_router() existed but
app.py never called it. These tests verify the wiring + format.
"""

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


def test_metrics_endpoint_includes_ingest_duration_histogram() -> None:
    """D2: INGEST_DURATION_SECONDS histogram appears in /metrics with correct buckets."""
    from src.metrics import INGEST_DURATION_SECONDS
    from src.metrics.registry import MetricsRegistry

    MetricsRegistry.reset_values()
    INGEST_DURATION_SECONDS.observe(45.0, verdict="success")

    r = _client().get("/metrics")
    assert r.status_code == 200
    assert "ruflo_ingest_duration_seconds" in r.text, (
        f"histogram not in response: {r.text[:500]}"
    )
    assert "# TYPE ruflo_ingest_duration_seconds histogram" in r.text
    assert 'ruflo_ingest_duration_seconds_bucket{le="30"' in r.text
    assert 'ruflo_ingest_duration_seconds_bucket{le="60"' in r.text
    assert 'ruflo_ingest_duration_seconds_bucket{le="600"' in r.text
    assert 'ruflo_ingest_duration_seconds_bucket{le="+Inf"' in r.text


def test_metrics_endpoint_includes_ingest_verdict_counter() -> None:
    """D2: INGEST_VERDICT_TOTAL counter appears in /metrics response."""
    from src.metrics import INGEST_VERDICT_TOTAL
    from src.metrics.registry import MetricsRegistry

    MetricsRegistry.reset_values()
    INGEST_VERDICT_TOTAL.inc(verdict="success", reason="")
    INGEST_VERDICT_TOTAL.inc(verdict="failed", reason="api_error")

    r = _client().get("/metrics")
    assert r.status_code == 200
    assert "ruflo_ingest_verdict_total" in r.text, (
        f"counter not in response: {r.text[:500]}"
    )
    assert "# TYPE ruflo_ingest_verdict_total counter" in r.text
    # Success verdict with empty reason
    assert 'verdict="success"' in r.text
    # Failed verdict with api_error reason
    assert 'verdict="failed"' in r.text
    assert 'reason="api_error"' in r.text
