# Metrics Endpoint (Prometheus) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Prometheus-format metrics at `GET /metrics` (localhost, no auth). 5 core metrics MVP. SQLite 24h rolling window persistence.

**Tech Stack:** Python 3.11+, dataclass, sqlite3, prometheus text format 0.0.4.

**MVP Scope** (per spec): 5 core metrics + SQLite persistence + `metrics show/reset/export/cost` CLI.

---

### Task 1: Counter / Gauge / Histogram + Prometheus format

**Files:** `src/metrics/__init__.py` + `src/metrics/counter.py` + `src/metrics/gauge.py` + `src/metrics/histogram.py` + `src/metrics/prometheus_format.py` + tests

```python
# src/metrics/__init__.py
"""Prometheus-format metrics for observability."""
from .counter import Counter
from .gauge import Gauge
from .histogram import Histogram
from .registry import MetricsRegistry


DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf"))


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
    buckets=DEFAULT_BUCKETS,
)
LLM_COST_USD_TOTAL = MetricsRegistry.counter(
    "ruflo_llm_cost_usd_total", "Total LLM cost in USD",
    label_names=["provider", "model"],
)
ACTIVE_TASKS = MetricsRegistry.gauge(
    "ruflo_active_tasks", "Number of currently active tasks",
    label_names=["status"],
)
```

```python
# src/metrics/counter.py
class Counter:
    def __init__(self, name, help, label_names=None):
        self.name = name
        self.help = help
        self.label_names = label_names or []
        self._values: dict[tuple, float] = {}

    def inc(self, amount=1, **labels):
        key = tuple(labels.get(n, "") for n in self.label_names)
        self._values[key] = self._values.get(key, 0) + amount

    def get(self, **labels) -> float:
        key = tuple(labels.get(n, "") for n in self.label_names)
        return self._values.get(key, 0)
```

```python
# src/metrics/gauge.py
class Gauge:
    def __init__(self, name, help, label_names=None):
        self.name = name
        self.help = help
        self.label_names = label_names or []
        self._values: dict[tuple, float] = {}

    def set(self, value, **labels):
        key = tuple(labels.get(n, "") for n in self.label_names)
        self._values[key] = value

    def inc(self, amount=1, **labels):
        key = tuple(labels.get(n, "") for n in self.label_names)
        self._values[key] = self._values.get(key, 0) + amount
```

```python
# src/metrics/histogram.py
class Histogram:
    def __init__(self, name, help, label_names=None, buckets=None):
        self.name = name
        self.help = help
        self.label_names = label_names or []
        self.buckets = buckets or DEFAULT_BUCKETS
        self._counts: dict[tuple, dict[float, int]] = {}
        self._sums: dict[tuple, float] = {}
        self._totals: dict[tuple, int] = {}

    def observe(self, value, **labels):
        key = tuple(labels.get(n, "") for n in self.label_names)
        bucket_counts = self._counts.setdefault(key, {})
        for b in self.buckets:
            if value <= b:
                bucket_counts[b] = bucket_counts.get(b, 0) + 1
        self._sums[key] = self._sums.get(key, 0) + value
        self._totals[key] = self._totals.get(key, 0) + 1
```

```python
# src/metrics/registry.py
class MetricsRegistry:
    _metrics: list = []

    @classmethod
    def counter(cls, name, help, label_names=None):
        from .counter import Counter
        c = Counter(name, help, label_names)
        cls._metrics.append(c)
        return c

    @classmethod
    def gauge(cls, name, help, label_names=None):
        from .gauge import Gauge
        g = Gauge(name, help, label_names)
        cls._metrics.append(g)
        return g

    @classmethod
    def histogram(cls, name, help, label_names=None, buckets=None):
        from .histogram import Histogram
        h = Histogram(name, help, label_names, buckets)
        cls._metrics.append(h)
        return h

    @classmethod
    def all_metrics(cls):
        return list(cls._metrics)

    @classmethod
    def reset(cls):
        """Test-only: clear all metric state."""
        cls._metrics.clear()
```

```python
# src/metrics/prometheus_format.py
def to_prometheus_text(metrics: list) -> str:
    """Serialize metrics to Prometheus text format 0.0.4."""
    lines: list[str] = []
    for m in metrics:
        lines.append(f"# HELP {m.name} {m.help}")
        if hasattr(m, "_values") and not hasattr(m, "_counts"):  # Counter / Gauge
            lines.append(f"# TYPE {m.name} {'gauge' if isinstance(m, Gauge) else 'counter'}")
            for key, val in m._values.items():
                labels_str = _format_labels(m.label_names, key)
                lines.append(f"{m.name}{labels_str} {val}")
        elif hasattr(m, "_counts"):  # Histogram
            lines.append(f"# TYPE {m.name} histogram")
            for key, bucket_counts in m._counts.items():
                labels_str = _format_labels(m.label_names, key)
                cumulative = 0
                for b in m.buckets:
                    cumulative += bucket_counts.get(b, 0)
                    b_str = "+Inf" if b == float("inf") else str(b)
                    lines.append(f'{m.name}_bucket{{le="{b_str}"{_label_suffix(m.label_names, key)}}} {cumulative}')
                lines.append(f"{m.name}_sum{labels_str} {m._sums.get(key, 0)}")
                lines.append(f"{m.name}_count{labels_str} {m._totals.get(key, 0)}")
    return "\n".join(lines) + "\n"


def _format_labels(names, values):
    if not names:
        return ""
    pairs = [f'{n}="{v}"' for n, v in zip(names, values) if v]
    return "{" + ",".join(pairs) + "}" if pairs else ""


def _label_suffix(names, values):
    pairs = [f'{n}="{v}"' for n, v in zip(names, values) if v]
    return "," + ",".join(pairs) if pairs else ""
```

**Tests** (5): test_counter_inc, test_gauge_set, test_histogram_observe, test_to_prometheus_text, test_labels_omitted.

```bash
git add src/metrics/ tests/test_metrics/__init__.py tests/test_metrics/test_format.py
git commit -m "feat(metrics): add Counter/Gauge/Histogram + Prometheus text format + 5 core metrics"
```

---

### Task 2: SQLite persistence + /metrics endpoint + CLI

**Files:** `src/metrics/persistence.py` + `src/server/metrics_route.py` + `src/cli_ext/metrics_cmd.py` + tests

```python
# src/metrics/persistence.py
"""SQLite-backed persistence for metrics (24h rolling window)."""
import json
import sqlite3
import time
from pathlib import Path


DB_PATH = ".index/metrics.db"
RETENTION_HOURS = 24


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS counter (
                name TEXT, labels TEXT, value REAL, timestamp INTEGER,
                PRIMARY KEY (name, labels, timestamp)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gauge (
                name TEXT, labels TEXT, value REAL, timestamp INTEGER,
                PRIMARY KEY (name, labels, timestamp)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS histogram (
                name TEXT, labels TEXT, bucket REAL, count INTEGER, sum REAL, total INTEGER, timestamp INTEGER,
                PRIMARY KEY (name, labels, bucket, timestamp)
            )
        """)


def persist_counter(db_path: Path, name: str, labels: dict, value: float) -> None:
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO counter (name, labels, value, timestamp) VALUES (?, ?, ?, ?)",
            (name, json.dumps(labels, sort_keys=True), value, int(time.time() * 1000)),
        )


def cleanup_old(db_path: Path) -> int:
    """Delete rows older than 24h. Returns count."""
    if not db_path.exists():
        return 0
    cutoff = int(time.time() * 1000) - RETENTION_HOURS * 3600 * 1000
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute("DELETE FROM counter WHERE timestamp < ?", (cutoff,))
        return cur.rowcount
```

```python
# src/server/metrics_route.py
"""GET /metrics endpoint — Prometheus text format."""
from fastapi import APIRouter
from ..metrics import MetricsRegistry
from ..metrics.persistence import persist_counter
from ..metrics.prometheus_format import to_prometheus_text


router = APIRouter()


@router.get("/metrics")
async def metrics_endpoint():
    """Return all metrics in Prometheus text format 0.0.4."""
    metrics = MetricsRegistry.all_metrics()
    # Persist + cleanup
    from ..project.paths import config_dir
    db_path = config_dir() / "metrics.db"
    for m in metrics:
        if hasattr(m, "_values"):
            for key, val in m._values.items():
                labels = dict(zip(m.label_names, key))
                persist_counter(db_path, m.name, labels, val)
    cleanup_old(db_path)  # 24h retention
    text = to_prometheus_text(metrics)
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(content=text, media_type="text/plain; version=0.0.4")
```

```python
# src/cli_ext/metrics_cmd.py
"""Metrics CLI."""
import argparse
import json
import sys

from ..metrics import MetricsRegistry
from ..metrics.prometheus_format import to_prometheus_text


def cmd_metrics_show(args: argparse.Namespace) -> None:
    """Print current metrics in Prometheus text format."""
    print(to_prometheus_text(MetricsRegistry.all_metrics()))


def cmd_metrics_reset(args: argparse.Namespace) -> None:
    """Reset all in-memory metrics (testing only)."""
    MetricsRegistry.reset()
    print("Metrics reset")


def cmd_metrics_export(args: argparse.Namespace) -> None:
    """Export all metric values to JSON file."""
    data = []
    for m in MetricsRegistry.all_metrics():
        if hasattr(m, "_values"):
            for key, val in m._values.items():
                data.append({
                    "name": m.name, "type": "counter" if not hasattr(m, "_counts") else "gauge",
                    "labels": dict(zip(m.label_names, key)), "value": val,
                })
    with open(args.path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Exported {len(data)} metric rows to {args.path}")


def cmd_metrics_cost(args: argparse.Namespace) -> None:
    """Print LLM cost summary from LLM_COST_USD_TOTAL metric."""
    from ..metrics import LLM_COST_USD_TOTAL
    total = 0.0
    print("LLM cost by provider/model:")
    for (provider, model), val in LLM_COST_USD_TOTAL._values.items():
        if provider or model:
            print(f"  {provider}/{model}: ${val:.4f}")
            total += val
    print(f"Total: ${total:.4f}")
```

**Wire in cli.py**: 4 subcommands.

**Tests** (3): test_metrics_endpoint_format, test_metrics_reset, test_metrics_export.

```bash
git add src/metrics/persistence.py src/server/metrics_route.py src/cli_ext/metrics_cmd.py src/cli.py tests/test_metrics/ tests/test_server/test_metrics_route.py tests/test_cli_ext/test_cmd_metrics.py
git commit -m "feat(metrics): add SQLite persistence + /metrics endpoint + 4 CLI subcommands"
```

---

## Self-Review

- [x] 5 core metrics pre-registered ✓
- [x] Prometheus text format 0.0.4 ✓
- [x] SQLite 24h rolling window ✓
- [x] /metrics endpoint + CLI ✓
- [x] No placeholders
- [x] Full metrics suite deferred to v2.0.1
- [x] OpenTelemetry/OTLP deferred to v3

## Implementation order

Tasks 1-2 chain. Total: 2 tasks, ~1.5 hours.