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


__all__ = [
    "Counter", "Gauge", "Histogram", "MetricsRegistry",
    "prometheus_format",
    "INGEST_TOTAL", "CHAT_TOTAL", "LLM_CALL_DURATION",
    "LLM_COST_USD_TOTAL", "ACTIVE_TASKS",
    "DEFAULT_BUCKETS",
]
