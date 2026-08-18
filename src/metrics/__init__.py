"""Prometheus-format metrics for observability."""
from .counter import Counter
from .gauge import Gauge
from .histogram import Histogram
from .registry import MetricsRegistry
from . import prometheus_format


# Default histogram buckets — Prometheus convention.
# Histogram.buckets is an instance attr, not a class attr, so import directly.
from .histogram import DEFAULT_BUCKETS as DEFAULT_BUCKETS  # noqa: F401 (re-export)


# Pre-register 5 core metrics
INGEST_TOTAL = MetricsRegistry.counter(
    "ruflo_ingest_total", "Total number of ingest operations",
    label_names=["status", "source_type"],
)
CHAT_TOTAL = MetricsRegistry.counter(
    "ruflo_chat_total", "Total number of chat agent runs",
    label_names=["status", "mode"],
)
LLM_CALL_DURATION = MetricsRegistry.histogram(
    "ruflo_llm_call_duration_seconds", "LLM API call duration in seconds",
    label_names=["provider", "model", "operation"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf")),
)
LLM_COST_USD_TOTAL = MetricsRegistry.counter(
    "ruflo_llm_cost_usd_total", "Total LLM cost in USD",
    label_names=["provider", "model"],
)
ACTIVE_TASKS = MetricsRegistry.gauge(
    "ruflo_active_tasks", "Number of currently active tasks",
    label_names=["status"],
)
INGEST_CANDIDATE_REJECTED_TOTAL = MetricsRegistry.counter(
    "ruflo_ingest_candidate_rejected_total",
    "Number of candidates rejected during ingest",
    label_names=["reason"],
)
INGEST_DURATION_SECONDS = MetricsRegistry.histogram(
    "ruflo_ingest_duration_seconds", "Duration of ingest operations in seconds",
    label_names=["verdict"],
    buckets=(30, 60, 90, 120, 180, 300, 600, float("inf")),
)
INGEST_VERDICT_TOTAL = MetricsRegistry.counter(
    "ruflo_ingest_verdict_total", "Total number of ingest operations by verdict",
    label_names=["verdict", "reason"],
)

# ── R12: four alertable fault metrics ──────────────────────────────────
# Each has a documented alert threshold (see docs/ops/runbook.md):
#   dead-letter        → alert when rate > 0 over 5 min (task loss)
#   queue backlog      → alert when pending+dead_letter > 50 (backlog)
#   provider failure   → alert when 3 consecutive failures (circuit open)
#   write failure      → alert when > 0 in 10 min (disk / permissions)
DEAD_LETTER_TOTAL = MetricsRegistry.counter(
    "ruflo_dead_letter_total",
    "Total number of tasks moved to dead letter",
    label_names=["reason"],
)
QUEUE_BACKLOG = MetricsRegistry.gauge(
    "ruflo_queue_backlog",
    "Number of tasks pending or dead-lettered (queue pressure)",
    label_names=["status"],
)
PROVIDER_FAILURE_TOTAL = MetricsRegistry.counter(
    "ruflo_provider_failure_total",
    "Total LLM provider failures (connect / timeout / auth)",
    label_names=["provider"],
)
WRITE_FAILURE_TOTAL = MetricsRegistry.counter(
    "ruflo_write_failure_total",
    "Total wiki/file write failures (disk, permissions, atomic commit)",
    label_names=["path_kind"],
)


__all__ = [
    "Counter", "Gauge", "Histogram", "MetricsRegistry",
    "prometheus_format",
    "INGEST_TOTAL", "INGEST_CANDIDATE_REJECTED_TOTAL",
    "INGEST_DURATION_SECONDS", "INGEST_VERDICT_TOTAL",
    "CHAT_TOTAL", "LLM_CALL_DURATION",
    "LLM_COST_USD_TOTAL", "ACTIVE_TASKS",
    "DEAD_LETTER_TOTAL", "QUEUE_BACKLOG",
    "PROVIDER_FAILURE_TOTAL", "WRITE_FAILURE_TOTAL",
    "DEFAULT_BUCKETS",
]
