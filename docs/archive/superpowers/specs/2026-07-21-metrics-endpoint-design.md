# Metrics Endpoint Design Spec

**Date:** 2026-07-22
**Status:** Approved (pending user sign-off)
**Target codebase:** ruflo-kb (Python 3.11+, master @ 24a76fd, post-Wiki-Heat-5Pool spec)

## Goal

Expose operational metrics in **Prometheus text format** at `GET /metrics` on the existing FastAPI server (no auth, localhost-only — same security model as the rest of the HTTP API). Metrics cover operation counts (counters), real-time state (gauges), latency distributions (histograms), and LLM cost tracking. Persisted to `.index/metrics.db` (SQLite) with a 24-hour rolling window so metrics survive process restarts.

This unlocks Grafana dashboards, Prometheus alerting, SLO monitoring, and day-to-day operational visibility for production deployments.

## Non-goals

- No OpenTelemetry / OTLP export (deferred; Prometheus is sufficient for v1).
- No alerting rules engine (use Prometheus / Grafana for that).
- No per-task-id cardinality (would cause Prometheus label explosion).
- No high-cardinality metrics (e.g., per-user, per-project-id); keep label sets bounded.
- No metrics export to external systems (Datadog, New Relic); Prometheus pull model is sufficient.


## Input Contract

> Reference: [`_input_contracts.md`](_input_contracts.md) for cross-spec dependency map.

**This spec provides** (consumed by other specs):

- `Counter` + `Gauge` + `Histogram` metric classes
- `MetricsRegistry`
- `LLMCostTracker` (per-model USD)
- `MetricsStore` (SQLite 24h rolling window)
- Prometheus text format 0.0.4 serializer
- `GET /metrics` endpoint

**This spec requires from other specs**:

- **src/shared/**: event hooks for instrumentation

**Phase**: Phase 4 — Polish
**Priority**: P1 — v2.0.1

## Architecture

```
Operation lifecycle hooks (existing):
  ingest.start, ingest.complete, ingest.failed
  chat.start, chat.complete, chat.failed
  search.execute, search.complete
  llm.call.start, llm.call.complete
  judge.batch.start, judge.batch.complete
  task.queue, task.process
   │
   ▼
MetricsRegistry.observe(event_type, **labels)
   │
   ├── Increment Counter (e.g., ruflo_ingest_total{status="completed"})
   ├── Record Histogram observation (e.g., ruflo_llm_call_duration_seconds.observe(elapsed))
   ├── Update Gauge (e.g., ruflo_active_tasks.set(current_count))
   └── Track cost (e.g., ruflo_llm_cost_usd_total{model="gpt-4o-mini"} += cost)

GET /metrics HTTP request:
   1. Iterate all registered metrics
   2. Serialize to Prometheus text format 0.0.4
   3. Set Content-Type: text/plain; version=0.0.4
   4. Stream response

Persistence:
  - Each metric, on increment/observe, asynchronously writes to .index/metrics.db (SQLite)
  - SQLite schema: metric_name + labels_json + value + timestamp
  - 24-hour rolling window: rows older than 24h deleted on each write
  - On process restart: load last 24h from SQLite to memory
```

## Components

### New modules

```
src/metrics/
├── __init__.py
├── registry.py             # MetricsRegistry singleton + counter/gauge/histogram factories
├── counter.py              # Counter class
├── gauge.py                # Gauge class
├── histogram.py            # Histogram class (default buckets)
├── cost.py                 # LLMCostTracker (per-model cost aggregation)
├── persistence.py          # MetricsStore (SQLite at .index/metrics.db)
├── prometheus_format.py    # serialize metrics to Prometheus text 0.0.4
└── hooks.py                # Operation event hooks → metrics observation

src/server/metrics_route.py  # GET /metrics endpoint

tests/test_metrics/
├── test_registry.py
├── test_counter.py
├── test_gauge.py
├── test_histogram.py
├── test_cost.py
├── test_persistence.py
├── test_prometheus_format.py
└── test_metrics_route.py
```

### Modified modules

| Path | Change |
|---|---|
| `src/server/app.py` | Mount `/metrics` route (outside `/api/v1/`) |
| `src/pipeline/*.py` | Hook ingest / analyzer / generator / judge with metrics.observe |
| `src/chat_agent/runtime.py` | Hook iteration, tool call, llm call with metrics.observe |
| `src/queue/queue.py` | Hook enqueue / dequeue / fail with metrics.observe |
| `src/llm/*.py` | Hook complete() / complete_stream() with cost tracking + duration histogram |
| `src/cli.py` | `metrics` subcommand: show / reset / export |
| `pyproject.toml` | Add `prometheus-client>=0.20` (or use raw Prometheus format; TBD) |

## Data structures

```python
# src/metrics/counter.py
class Counter:
    def __init__(self, name: str, help: str, label_names: list[str] = []):
        self.name = name
        self.help = help
        self.label_names = label_names
        self._values: dict[tuple[str, ...], float] = {}  # label_values → value
        # Default 0.0 for unseen label combinations
    
    def inc(self, amount: float = 1, **labels) -> None:
        key = tuple(labels.get(n, "") for n in self.label_names)
        self._values[key] = self._values.get(key, 0) + amount
        self._notify_persistence()

# src/metrics/gauge.py
class Gauge:
    def set(self, value: float, **labels) -> None: ...
    def inc(self, amount: float = 1, **labels) -> None: ...
    def dec(self, amount: float = 1, **labels) -> None: ...

# src/metrics/histogram.py
DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, +inf)

class Histogram:
    def __init__(self, name: str, help: str, label_names: list[str] = [],
                 buckets: tuple[float, ...] = DEFAULT_BUCKETS):
        self.buckets = buckets
        self._counts: dict[tuple, dict[float, int]] = {}  # labels → {bucket → count}
        self._sums: dict[tuple, float] = {}
        self._totals: dict[tuple, int] = {}
    
    def observe(self, value: float, **labels) -> None: ...
```

```python
# src/metrics/registry.py
class MetricsRegistry:
    _instance: "MetricsRegistry" = None
    
    @classmethod
    def instance(cls) -> "MetricsRegistry": ...
    
    @classmethod
    def counter(cls, name: str, help: str, label_names: list[str] = []) -> Counter: ...
    @classmethod
    def gauge(cls, name: str, help: str, label_names: list[str] = []) -> Gauge: ...
    @classmethod
    def histogram(cls, name: str, help: str, label_names: list[str] = [],
                 buckets: tuple[float, ...] = DEFAULT_BUCKETS) -> Histogram: ...
    
    def observe_event(self, event_type: str, **labels) -> None:
        """Called by hooks. Increments appropriate counter / observes histogram."""
        ...
    
    def all_metrics(self) -> list[Metric]:
        """Returns all registered metrics for serialization."""
        ...

# Pre-registered metrics (defined in src/metrics/__init__.py):
INGEST_TOTAL = MetricsRegistry.counter(
    "ruflo_ingest_total",
    "Total number of ingest operations",
    ["status", "source_type"],   # status: pending|completed|failed; source_type: url|file|folder
)

CHAT_TOTAL = MetricsRegistry.counter(
    "ruflo_chat_total",
    "Total number of chat agent runs",
    ["status", "mode"],
)

SEARCH_TOTAL = MetricsRegistry.counter(
    "ruflo_search_total",
    "Total number of search operations",
    ["mode"],   # hybrid|keyword|vector
)

JUDGE_TOTAL = MetricsRegistry.counter(
    "ruflo_judge_total",
    "Total number of judge operations",
    ["verdict"],   # pass|warn|reject|hard_reject
)

LLM_CALL_DURATION = MetricsRegistry.histogram(
    "ruflo_llm_call_duration_seconds",
    "LLM API call duration in seconds",
    ["provider", "model", "operation"],   # operation: complete|stream|embed
)

LLM_TOKENS_TOTAL = MetricsRegistry.counter(
    "ruflo_llm_tokens_total",
    "Total LLM tokens consumed",
    ["provider", "model", "direction"],   # direction: prompt|completion
)

LLM_COST_USD_TOTAL = MetricsRegistry.counter(
    "ruflo_llm_cost_usd_total",
    "Total LLM cost in USD",
    ["provider", "model"],
)

ACTIVE_TASKS = MetricsRegistry.gauge(
    "ruflo_active_tasks",
    "Number of currently active tasks",
    ["status"],   # pending|running
)

QUEUE_DEPTH = MetricsRegistry.gauge(
    "ruflo_queue_depth",
    "Number of tasks in queue",
)

WIKI_PAGES_TOTAL = MetricsRegistry.gauge(
    "ruflo_wiki_pages_total",
    "Total number of wiki pages",
    ["pool", "type"],   # pool_1..drift; type: source|entity|concept|...
)

HEAT_DISTRIBUTION = MetricsRegistry.gauge(
    "ruflo_heat_sum",
    "Sum of heat scores across all pages",
    ["pool"],
)

HEAT_ZOMBIES = MetricsRegistry.gauge(
    "ruflo_heat_zombies",
    "Number of zombie pages (heat=0 for 30 days)",
)

HTTP_REQUESTS_TOTAL = MetricsRegistry.counter(
    "ruflo_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)

HTTP_REQUEST_DURATION = MetricsRegistry.histogram(
    "ruflo_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
)

UPTIME_SECONDS = MetricsRegistry.gauge(
    "ruflo_uptime_seconds",
    "Server uptime in seconds",
)

SERVER_INFO = MetricsRegistry.gauge(
    "ruflo_server_info",
    "Server build info",
    ["version", "python_version"],
)
```

```python
# src/metrics/cost.py
@dataclass
class ModelPricing:
    prompt_per_1k_usd: float
    completion_per_1k_usd: float
    embedding_per_1k_usd: float = 0.0

DEFAULT_PRICING = {
    "gpt-4o-mini":        ModelPricing(0.00015, 0.0006, 0.00002),
    "gpt-4o":              ModelPricing(0.0025, 0.01, 0.00013),
    "claude-haiku-4-5":   ModelPricing(0.0008, 0.004, 0.0),
    "claude-sonnet-4":    ModelPricing(0.003, 0.015, 0.0),
    "qwen2.5:7b":         ModelPricing(0.0, 0.0, 0.0),   # local Ollama
    "nomic-embed-text":   ModelPricing(0.0, 0.0, 0.0),
}

class LLMCostTracker:
    def compute_cost(self, provider: str, model: str, prompt_tokens: int,
                      completion_tokens: int) -> float:
        pricing = DEFAULT_PRICING.get(model, ModelPricing(0, 0, 0))
        prompt_cost = (prompt_tokens / 1000) * pricing.prompt_per_1k_usd
        completion_cost = (completion_tokens / 1000) * pricing.completion_per_1k_usd
        return prompt_cost + completion_cost
```

```python
# src/metrics/persistence.py
@dataclass
class MetricRow:
    name: str
    labels: dict[str, str]
    value: float
    metric_type: str          # "counter" | "gauge" | "histogram"
    bucket: float | None = None    # for histogram bucket rows
    timestamp: int

class MetricsStore:
    DB_PATH = ".index/metrics.db"
    RETENTION_HOURS = 24
    
    @staticmethod
    def init() -> None:
        """Create SQLite table."""
        ...
    
    @staticmethod
    def append(row: MetricRow) -> None: ...
    @staticmethod
    def query(name: str, since_ms: int) -> list[MetricRow]: ...
    @staticmethod
    def cleanup_old() -> int:
        """Delete rows older than RETENTION_HOURS. Returns rows deleted."""
        ...
    
    @staticmethod
    def load_to_memory(registry: MetricsRegistry) -> int:
        """On startup, load last 24h from SQLite into registry's in-memory state."""
        ...
```

## Prometheus text format

```
# HELP ruflo_ingest_total Total number of ingest operations
# TYPE ruflo_ingest_total counter
ruflo_ingest_total{source_type="url",status="completed"} 142.0
ruflo_ingest_total{source_type="file",status="completed"} 89.0
ruflo_ingest_total{source_type="url",status="failed"} 3.0
ruflo_ingest_total{source_type="file",status="failed"} 1.0

# HELP ruflo_llm_call_duration_seconds LLM API call duration in seconds
# TYPE ruflo_llm_call_duration_seconds histogram
ruflo_llm_call_duration_seconds_bucket{provider="openai",model="gpt-4o-mini",operation="complete",le="0.1"} 5.0
ruflo_llm_call_duration_seconds_bucket{provider="openai",model="gpt-4o-mini",operation="complete",le="0.25"} 12.0
ruflo_llm_call_duration_seconds_bucket{provider="openai",model="gpt-4o-mini",operation="complete",le="+Inf"} 18.0
ruflo_llm_call_duration_seconds_sum{provider="openai",model="gpt-4o-mini",operation="complete"} 4.521
ruflo_llm_call_duration_seconds_count{provider="openai",model="gpt-4o-mini",operation="complete"} 18.0

# HELP ruflo_active_tasks Number of currently active tasks
# TYPE ruflo_active_tasks gauge
ruflo_active_tasks{status="running"} 2.0
ruflo_active_tasks{status="pending"} 5.0

# HELP ruflo_uptime_seconds Server uptime in seconds
# TYPE ruflo_uptime_seconds gauge
ruflo_uptime_seconds 86423.5
```

## CLI surface

```
python -m src.cli metrics show [--json]
    # Print current metric values in human-readable format

python -m src.cli metrics reset
    # Reset all in-memory + SQLite metrics (testing only)

python -m src.cli metrics export <file.json>
    # Export all metric rows to JSON file

python -m src.cli metrics cost [--project <id>]
    # Print cost summary (per-model, per-operation, per-day)
```

## HTTP endpoint

```
GET /metrics
    No auth (localhost-only by design)
    Content-Type: text/plain; version=0.0.4
    Body: Prometheus text format
```

Note: `/metrics` is OUTSIDE `/api/v1/` prefix because Prometheus standard scrape config expects `/metrics` at root.

## MCP tools

```
ruflo_kb_metrics_show(project_id)
    # Returns key metrics as JSON for display
```

## Cardinality control

To prevent Prometheus label explosion:

| Metric | Allowed labels | Forbidden |
|---|---|---|
| `ruflo_ingest_total` | `status`, `source_type` | task_id, page_id, project_id |
| `ruflo_chat_total` | `status`, `mode` | session_id, project_id |
| `ruflo_search_total` | `mode` | query, page_id |
| `ruflo_llm_call_duration_seconds` | `provider`, `model`, `operation` | task_id, session_id |
| `ruflo_wiki_pages_total` | `pool`, `type` | page_id |

WIKI_PAGES_TOTAL labels bounded: 6 pools × 6 types = 36 series max.

## Error handling

| Stage | Error | Strategy |
|---|---|---|
| Persistence write | SQLite disk full / locked | Skip; in-memory state retained; log warning |
| Persistence write | I/O error | Skip + log; retry next metric |
| HTTP /metrics | Scrape during SQLite cleanup | Lock acquired briefly; typically < 100ms |
| Cost calculation | Unknown model (e.g., user runs new model) | Default to $0 + log warning |
| Cost calculation | Missing token usage in LLM response | Cost = 0; log warning |
| Histogram bucket overflow | Value > +Inf bucket | Goes into +Inf bucket (always exists) |
| SQLite schema mismatch | Old DB version | Migrate via `MetricsStore.upgrade_schema()` |

## Backwards compatibility

- `/metrics` endpoint is additive (no existing endpoint at that path).
- `MetricsRegistry.instance()` lazily inits; existing code that doesn't call `metrics.observe_*` works unchanged.
- Persistence is opt-in: if `.index/metrics.db` doesn't exist, create on first metric write.
- CLI `metrics` subcommand is additive.

## Testing strategy

### Unit tests

| Module | Test focus |
|---|---|
| `src/metrics/counter.py` | inc; label combinations; persistence notification |
| `src/metrics/gauge.py` | set/inc/dec; negative values |
| `src/metrics/histogram.py` | observe; bucket assignment; sum + count tracking |
| `src/metrics/registry.py` | Pre-registered metrics; observe_event dispatch |
| `src/metrics/cost.py` | compute_cost for known + unknown models |
| `src/metrics/persistence.py` | SQLite schema; load_to_memory; cleanup_old |
| `src/metrics/prometheus_format.py` | Serialization format; HELP/TYPE comments; bucket ordering |
| `src/server/metrics_route.py` | GET /metrics response shape; Content-Type header |

### Integration tests

```
tests/test_integration/test_metrics_e2e.py:
    def test_ingest_increments_counter():
        # Run ingest; verify ruflo_ingest_total{status="completed"} incremented

    def test_llm_cost_tracked():
        # Run chat; verify ruflo_llm_cost_usd_total{provider,model} > 0

    def test_metrics_persist_across_restart():
        # Trigger metric; simulate restart (recreate MetricsRegistry instance)
        # Verify metric value restored from .index/metrics.db

    def test_metrics_endpoint_format():
        # GET /metrics; verify Prometheus text format
        # Verify Content-Type: text/plain; version=0.0.4

    def test_cardinality_bounded():
        # Run 1000 ingests; verify number of unique label combinations bounded
```


## MVP Scope / Polish / Deferred

> This section partitions the spec's features into delivery tiers. See [`_input_contracts.md`](_input_contracts.md) for cross-spec context.

### MVP Scope (P1)

- 5 core metrics: ingest_total / chat_total / llm_cost_usd_total / active_tasks / uptime_seconds
- SQLite persistence with 24h rolling window
- `GET /metrics` endpoint
- CLI: `metrics {show,reset,export,cost}`

### Polish (v2.0.1 or later)

- Full metrics suite (search_total / judge_total / http_requests_total / etc.)
- `--only` / `--skip` filtering

### Deferred (v2.1+)

- OpenTelemetry / OTLP export
- Per-project metrics namespace
- Long-term retention (30 days)
- Alerting rules engine

## Implementation order

5 phases:

1. **Foundation** — Counter / Gauge / Histogram + MetricsRegistry + tests
2. **Prometheus format + persistence** — text serialization + SQLite store + tests
3. **Cost tracking** — LLMCostTracker + integration with LLM providers + tests
4. **Hook integration** — wire metrics into pipeline / chat / queue / LLM providers + tests
5. **HTTP endpoint + CLI** — `GET /metrics` route + `cmd_metrics` + integration tests

## Cost estimation

- LLM cost tracking: 0 tokens overhead (computes from existing usage data)
- Persistence: ~10 rows per metric per minute; 1KB DB per day for moderate use
- `/metrics` scrape: 1-2ms response (in-memory read + format)
- Bundle: ~50KB (raw implementation; prometheus-client would be +500KB)

## Open questions / deferred

- OpenTelemetry / OTLP export (future: OTLP endpoint alongside Prometheus).
- Per-project metrics (currently global; could namespace by project_id).
- Custom alerting rules engine.
- Trace context propagation (OpenTelemetry traces for LLM calls).
- Histogram quantile summaries (e.g., p99 latency) — Prometheus computes from buckets.
- Long-term storage (24h rolling is sufficient for operational visibility but not for capacity planning; could add 30-day retention tier).