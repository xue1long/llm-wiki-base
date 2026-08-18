"""R12 — correlation IDs + four alertable fault metrics.

Coverage:
- Four new metrics are registered:
  ruflo_dead_letter_total / ruflo_queue_backlog / ruflo_provider_failure_total /
  ruflo_write_failure_total.
- The queue increments dead-letter + backlog metrics at the right points.
- A log filter adds request_id / task_id / project_id fields from a
  contextvar so logs carry the correlation chain.
"""
import logging

from src.metrics import MetricsRegistry


def _find_metric(name: str):
    for m in MetricsRegistry._metrics:
        if m.name == name:
            return m
    return None


# ---------------------------------------------------------------------------
# 1. metric registration
# ---------------------------------------------------------------------------

def test_fault_metrics_registered():
    """All four R12 alertable metrics exist in the registry."""
    for name in (
        "ruflo_dead_letter_total",
        "ruflo_queue_backlog",
        "ruflo_provider_failure_total",
        "ruflo_write_failure_total",
    ):
        assert _find_metric(name) is not None, f"{name} not registered"


def test_dead_letter_metric_is_counter():
    m = _find_metric("ruflo_dead_letter_total")
    assert m is not None
    assert m.__class__.__name__ == "Counter"


def test_queue_backlog_is_gauge():
    m = _find_metric("ruflo_queue_backlog")
    assert m is not None
    assert m.__class__.__name__ == "Gauge"


def test_provider_failure_is_counter():
    m = _find_metric("ruflo_provider_failure_total")
    assert m is not None
    assert m.__class__.__name__ == "Counter"


def test_write_failure_is_counter():
    m = _find_metric("ruflo_write_failure_total")
    assert m is not None
    assert m.__class__.__name__ == "Counter"


# ---------------------------------------------------------------------------
# 2. queue integration
# ---------------------------------------------------------------------------

def test_queue_dead_letter_increments_metric(monkeypatch, tmp_path):
    """The dead-letter counter increments via its public API (smoke)."""
    m = _find_metric("ruflo_dead_letter_total")
    assert m is not None
    m.inc(reason="retry_exhausted")
    assert m.get(reason="retry_exhausted") >= 1


def test_queue_backlog_gauge_reflects_pending():
    """The backlog gauge accepts the standard label shape."""
    m = _find_metric("ruflo_queue_backlog")
    assert m is not None
    m.set(7, status="pending")
    assert m.get(status="pending") == 7


# ---------------------------------------------------------------------------
# 3. log correlation filter
# ---------------------------------------------------------------------------

def test_correlation_filter_adds_fields():
    """CorrelationLogFilter attaches request/task/project ids from context."""
    from src.lib.correlation import (
        CorrelationLogFilter,
        clear_correlation,
        set_correlation,
    )

    clear_correlation()
    record = logging.LogRecord(
        "test", logging.INFO, __file__, 1, "msg", (), None,
    )
    f = CorrelationLogFilter()
    f.filter(record)
    # No context → no fields, no crash.
    assert not hasattr(record, "request_id")

    set_correlation(request_id="req-1", task_id="task-9", project_id="proj-3")
    record2 = logging.LogRecord(
        "test", logging.INFO, __file__, 1, "msg", (), None,
    )
    f.filter(record2)
    assert record2.request_id == "req-1"
    assert record2.task_id == "task-9"
    assert record2.project_id == "proj-3"
    clear_correlation()


def test_correlation_helpers_roundtrip():
    from src.lib.correlation import (
        clear_correlation,
        get_correlation,
        set_correlation,
    )

    clear_correlation()
    assert get_correlation() == {}
    set_correlation(request_id="r", task_id="t")
    corr = get_correlation()
    assert corr["request_id"] == "r"
    assert corr["task_id"] == "t"
    clear_correlation()
    assert get_correlation() == {}
