# Queue & Pipeline Refactor for Testability — Design Spec

**Date:** 2026-07-25
**Status:** Draft (pending user sign-off)
**Target codebase:** ruflo-kb (Python 3.11+, master @ d59768c, post-M4 cleanup)
**Series:** Optimization sub-project #1 of 4 (predecessor to reliability / throughput / observability)
**Inspired by:** hexagonal architecture (Ports & Adapters) pattern

## Goal

Split `src/queue/queue.py` (350+ lines) and `src/pipeline/pipeline.py` (110+ lines) from monolithic modules with mixed concerns into a **Protocol-bounded, dependency-injectable** structure where business logic is testable in isolation from IO. All 748 existing tests must remain green; all existing public import paths must continue to work.

### Critical behavioral invariants (REFUSE to break)

These are the things that are **easy to subtly break** during this refactor and that would surface only at runtime or in obscure test failures:

1. **`safe_write` integration** — `JsonFileBackend` must call `safe_write` (not direct `os.replace`) so that queue.json writes participate in the `AtomicContext` suspension/batching system. Detected by `tests/test_queue/test_save_atomic.py::test_atomic_write_does_not_partial_write` (monkeypatches `os.replace`).
2. **APPROVED task filtering** — APPROVED tasks are not persisted to disk and are filtered out of `snapshot()`. If we naively save every task, the queue file balloons with already-processed tasks and may re-process them on restart.
3. **Service-level single lock** — all multi-step orchestration (snapshot + check + acquire + emit + save) must happen inside `QueueService._service_lock`. Splitting into per-component locks reintroduces a race that `tests/test_queue/test_lock.py` guards.
4. **External `collector:done` listener** — `collect()` must still emit `EventName.COLLECTOR_DONE` for external subscribers, even though the pipeline-internal chain now drives `_on_collector_done` via direct `await`. Detected by `tests/test_pipeline/test_pipeline_event_bus_integration.py::test_event_bus_dispatch_external_listener_runs`.
5. **Circuit breaker is a process-level singleton** — `get_circuit_breaker("task_queue")` returns the same `CircuitBreaker` instance every call. Do not cache the instance on `QueueService`; resolve the name on each call so test reset (`breaker.state = CircuitState.CLOSED`) takes effect.
6. **Monkeys-patchable private helpers** — `pipeline._resolve_wiki_paths` and `pipeline._get_provider` are imported and patched by `tests/test_pipeline/test_pipeline_event_bus_integration.py:126-127`. They must remain reachable from `src.pipeline.pipeline` (compat shim is OK).

## Non-goals (out of #1 scope)

- ❌ Add concurrency (deferred to #3)
- ❌ Persist `InFlightTracker` (deferred to #2)
- ❌ Change event names or payload schemas (only **centralize** constants)
- ❌ Add metrics endpoints (deferred to #4)
- ❌ Wire `folder ingestion` route (deferred to #2)
- ❌ Change MAX_RETRIES semantics (deferred to #2)

## Input Contract

> Reference: [`_input_contracts.md`](_input_contracts.md) for cross-spec dependency map.

**This spec provides** (consumed by other specs):

- `QueueBackend` / `InFlightTracker` / `EventEmitter` / `RetryPolicy` Protocol contracts
- `JsonFileBackend` default `QueueBackend` implementation
- `InMemoryInFlightTracker` default `InFlightTracker` implementation
- `DefaultRetryPolicy` default `RetryPolicy` implementation
- `QueueService` composition root
- `PipelineStage` Protocol + `PipelineRunner` orchestrator
- 3+ example tests using Protocol + Fake pattern (template for future test work)

**This spec requires from other specs**:

- Existing `src/events/event_bus.py::EventBus` (default `EventEmitter` implementation)
- Existing `src/types.py::KnowledgeTask`, `TaskStatus`, `SourceType`
- Existing `src/circuit_breaker.py::get_circuit_breaker`
- Existing `src/utils/idempotency.py::check_duplicate`

**Phase**: Phase 1 — Foundations (prerequisite for #2, #3, #4)
**Priority**: P1 — high value, low risk, unblocks larger work

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│                  Application Layer                          │
│   src/server/routes/*    src/cli_ext/*    scripts/*        │
│   (HTTP routes, CLI commands) — call QueueService.enqueue() │
└──────────────────────┬─────────────────────────────────────┘
                       │
                       ▼
┌────────────────────────────────────────────────────────────┐
│                  Service Layer (NEW)                        │
│   src/queue/service.py::QueueService                        │
│   - assembles backend / tracker / emitter / retry_policy   │
│   - enqueue() / get_stats() / pause() / resume()            │
│   - **only place that holds process-level global state**   │
└──────────────────────┬─────────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│  Backend     │ │  In-Flight   │ │  Retry       │
│  (Protocol)  │ │  (Protocol)  │ │  (Protocol)  │
│              │ │              │ │              │
│  JsonFile-   │ │  InMemory-   │ │  Default-    │
│  Backend     │ │  Tracker     │ │  RetryPolicy │
│  (default)   │ │  (default)   │ │  (default)   │
└──────────────┘ └──────────────┘ └──────────────┘
        │
        ▼
┌────────────────────────────────────────────────────────────┐
│         Adapters (default implementations) + Domain         │
│   src/queue/state.py        can_transition (pure)           │
│   src/queue/scheduler.py    select_next_task (pure)         │
│   src/queue/events.py       EventName + payload dataclass   │
│   src/queue/persistence.py  JsonFileBackend (IO adapter)    │
│   src/queue/in_flight.py    InMemoryInFlightTracker (adapter) │
│   src/queue/retry.py        DefaultRetryPolicy (adapter)    │
│                                                              │
│   Note: "pure" = no IO side effects (testable without fs).  │
│   "adapter" = default concrete impl; swappable via Protocol. │
└────────────────────────────────────────────────────────────┘
```

```
┌────────────────────────────────────────────────────────────┐
│                Pipeline Layer (similar split)               │
│   src/pipeline/service.py::PipelineService                  │
│   - assembles stages + runner + dispatcher                  │
│   - only place that owns "asyncio.run wrapping"             │
│   - explicit register_stages() instead of import-time       │
│                                                              │
│   src/pipeline/ports.py       PipelineStage Protocol        │
│   src/pipeline/runner.py      PipelineRunner (domain logic) │
│   src/pipeline/dispatcher.py  sync→async bridge             │
│   src/pipeline/stages/        collector / analyzer / generator separated │
│   src/pipeline/ingest.py      run_ingest pure function      │
│   src/pipeline/events.py      event dataclasses             │
└────────────────────────────────────────────────────────────┘
```

## Module boundaries

### `src/queue/` new structure

| File | Public API | Private | Depends on |
|---|---|---|---|
| `__init__.py` | `enqueue_task`, `update_task_status`, `get_queue`, `pause_queue`, `resume_queue`, `generate_task_id`, `get_default_queue_service` | — | re-export from `service` + `state` |
| `ports.py` | `QueueBackend`, `InFlightTracker`, `EventEmitter`, `RetryPolicy` (Protocol) | — | `typing`, `dataclass` only |
| `events.py` | **Re-export** `EventName` constants and queue-related payload dataclasses from `src/events/events.py` (NOT redefine — only centralize imports) | — | `src/events/events.py` |
| `state.py` | `can_transition`, `InvalidTransition` | — | `src/types.py::TaskStatus` |
| `persistence.py` | `JsonFileBackend` (implements `QueueBackend`) | `_acquire_file_lock`, `_release_file_lock` | `state`, `events` |
| `in_flight.py` | `InMemoryInFlightTracker` (implements `InFlightTracker`) | — | — |
| `retry.py` | `DefaultRetryPolicy` (implements `RetryPolicy`), `DeadLetter`, `decide_retry_action`, `RetryDecision` dataclass | — | `state`, circuit_breaker |
| `scheduler.py` | `Scheduler` class, `select_next_task` (pure function) | — | `ports`, `state` |
| `service.py` | `QueueService`, `get_default_queue_service`, `__reset_for_testing` (test-only re-load hook, replaces `queue.py:281`) | `_default_service`, `release_in_flight` (private — only `pipeline.py` consumes it via `from src.queue.service import release_in_flight`) | all of the above |
| `queue.py` | **DELETED** (replaced by service + submodules) | — | — |

### `src/pipeline/` new structure

| File | Public API | Private | Depends on |
|---|---|---|---|
| `__init__.py` | re-exports `run_ingest`, `PipelineService`, `get_default_pipeline_service`; **compat layer** aliases `src.pipeline.pipeline`, `src.pipeline.collector`, `src.pipeline.analyzer`, `src.pipeline.generator` via `sys.modules` | — | all submodules |
| `ports.py` | `PipelineStage` (Protocol), `StageResult` (dataclass), `PipelineContext` (dataclass) | — | — |
| `events.py` | **Re-export** pipeline-related payloads (`CollectorStartPayload`, `CollectorDonePayload`) from `src/events/events.py` (NOT redefine — only centralize imports) | — | `src/events/events.py` |
| `dispatcher.py` | `dispatch_collector_start` (sync→async bridge) | — | `ports`, `events` |
| `runner.py` | `PipelineRunner`, `run_stages` (pure function) | — | `ports` |
| `stages/collector.py` | `CollectorStage` (implements `PipelineStage`) | — | `wiki`, `queue.ports` |
| `stages/analyzer.py` | `AnalyzerStage` | — | `llm`, `pipeline.schemas` |
| `stages/generator.py` | `GeneratorStage` | — | `llm`, `pipeline.schemas` |
| `ingest.py` | `run_ingest` (async coroutine; NOT a pure function — has IO side effects: LLM calls + wiki page writes under `AtomicContext`) | — | `stages/`, `wiki.storage` |
| `service.py` | `PipelineService`, `get_default_pipeline_service`, `register_stages` (explicit registration) | — | all of the above |
| `pipeline.py` | **DELETED** | — | — |

### Public vs private principles

**Public** (re-exported from `__init__.py` or top-level):
- All Protocol contracts (`ports.py`)
- Orchestration entry points (`QueueService.enqueue`, `PipelineService.run`)
- Pure functions (`can_transition`, `run_ingest`, `decide_retry_action`)
- Event dataclasses (for external listeners)
- Test-only hooks (`__reset_for_testing`) — must remain importable for tests but are NOT part of the production API surface

**Private** (`_` prefix / not re-exported):
- `_acquire_file_lock` / `_release_file_lock`
- Internal helpers (e.g. `_save_queue_unlocked`)
- Default singleton private variables (e.g. `_default_service`)
- `release_in_flight` — only `pipeline.py` (and its successors) consume it; keep as `QueueService._release_in_flight` (or module-private `service._release_in_flight`) and import explicitly there. **Not in `__init__.py`.**

**No cross-module private access**:
- `persistence.py` cannot import `service.py` (would create cycle)
- `state.py` cannot import `ports.py` (state machine is pure logic)
- `in_flight.py` doesn't know about backend (independent dimension)

### Key invariants (REFUSE to break)

1. `enqueue_task` signature unchanged: `(source, source_type, task_hash, project_id=None) -> str`
2. `update_task_status` signature unchanged: `(task_id, status, error=None) -> None`, still raises `InvalidTransition`
3. `generate_task_id` signature unchanged: `() -> str`
4. `run_ingest` signature unchanged (verify against all current call sites); behavior unchanged: async coroutine, performs LLM calls (analyze + generate), appends a source page (Fix D from `pipeline.py:217-260`), writes pages under `AtomicContext`, returns `list[WikiPage]`
5. `EventName` string values unchanged: `"collector:start"`, `"task:created"`, etc. (only **centralize** to constants, do not rename)
6. Event payload field order/types preserved

## Data flow

### `enqueue_task` flow

```
HTTP /api/v1/projects/{p}/ingest
    │
    ▼
src/server/routes/ingest.py::ingest
    │ pydantic validation
    ▼
src/services/ingest.py::enqueue_source(project_id, source, folder_context)
    │ resolve project + compute task_hash
    ▼
src/queue/__init__.py::enqueue_task(source, source_type, task_hash, project_id)
    │ ← compat layer, directly re-exports service
    ▼
src/queue/service.py::QueueService.enqueue(...)
    │
    ├── 1. retry_policy.should_dedupe(task_hash) → hit returns ""
    ├── 2. backend.enqueue(KnowledgeTask(...))   ← JsonFileBackend
    │       └─ persistence.py::_save_queue_unlocked() writes .kb-queue.json
    ├── 3. emitter.emit("task:created", TaskCreatedPayload(...))
    │       └─ events/event_bus.py::EventBus.emit (default impl)
    └── 4. scheduler.advance() → calls _process_next(...)
            │
            ▼
    scheduler.select_next_task(backend, tracker) → KnowledgeTask
            │
            ├── hit: tracker.acquire(task_id), emitter.emit("collector:start", payload)
            └── miss: nothing (waits for next advance)
```

### `_process_next` split (pure function vs orchestration)

```python
# scheduler.py — pure
def select_next_task(
    backend: QueueBackend,
    tracker: InFlightTracker,
    *,
    prefer_task_id: str | None = None,
) -> KnowledgeTask | None:
    candidates = backend.snapshot()
    if prefer_task_id is not None:
        return next((t for t in candidates
                     if t.id == prefer_task_id
                     and t.status == TaskStatus.PENDING
                     and not tracker.is_in_flight(t.id)), None)
    return next((t for t in candidates
                 if t.status == TaskStatus.PENDING
                 and not tracker.is_in_flight(t.id)), None)


# service.py
class QueueService:
    def advance(self, *, prefer_task_id: str | None = None,
                project_id: str | None = None) -> bool:
        if self._paused: return False
        if not self._breaker.can_execute(): return False

        task = select_next_task(self.backend, self.tracker,
                                prefer_task_id=prefer_task_id)
        if task is None: return False

        if not self.tracker.acquire(task.id): return False

        effective_project_id = project_id or task.project_id
        payload = {
            "task_id": task.id,
            "source": task.source,
            "source_type": task.source_type,
        }
        if effective_project_id is not None:
            payload["project_id"] = effective_project_id

        self.emitter.emit("collector:start", payload)
        return True
```

### State machine + persistence

```
update_task_status(task_id, new_status, error=None)
    │
    ▼
QueueService.update_status(...)
    │
    ├── 1. backend.find(task_id) → KnowledgeTask
    ├── 2. can_transition(task.status, new_status) → bool
    │       (state.py pure, no IO)
    │       └─ False → raise InvalidTransition
    ├── 3. retry_policy.apply(task, new_status) → may modify status
    │       - FAILED → retry_count++, decide PENDING vs DEAD_LETTER
    │       - ARCHIVED → breaker.record_success()
    │       - TIMEOUT → same as FAILED
    ├── 4. backend.save(task)  ← JsonFileBackend internal _save_queue_unlocked
    └── 5. emitter.emit("task:status_changed", payload)
        └── 6. if dead letter, emit "task:dead_letter"
        └── 7. if retry (→ PENDING), advance() re-dispatches
```

### Pipeline flow

```
EventBus.emit("collector:start", payload)
    │
    ▼ (handler explicitly registered in service.py::register_stages)
PipelineService.handle_collector_start(payload)
    │
    ├── detect runtime: loop exists → loop.create_task(coro), no loop → asyncio.run(coro)
    ▼
PipelineRunner.run_stages([
    CollectorStage(), AnalyzerStage(), GeneratorStage()
], context=PipelineContext(payload))
    │
    ├── 1. CollectorStage.run(ctx)
    │       └─ collect(task_id, source, source_type, project_id)
    │       └─ emit "collector:done" (for external listeners; pipeline itself doesn't subscribe)
    │       └─ return StageResult(CollectorDonePayload)
    │
    ├── 2. AnalyzerStage.run(ctx, prev_result)
    │       └─ analyze(source_text, source_ext, ...) → AnalysisResult
    │       └─ return StageResult(AnalysisResult)
    │
    ├── 3. GeneratorStage.run(ctx, prev_result)
    │       └─ generate(paths, analysis, ...) → list[WikiPage]
    │       └─ enter AtomicContext → write_page + append_to_index + log_event
    │
    └── 4. update_task_status(task_id, APPROVED) + release_in_flight
```

### Old `_dispatch_collector_start` relocation

**Old** (in `src/pipeline/pipeline.py`):
```python
def _dispatch_collector_start(payload):
    coro = _on_collector_start(payload)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(coro)
        return
    loop.create_task(coro)
```

**New** (in `src/pipeline/dispatcher.py`):
```python
def dispatch_collector_start(emitter: EventEmitter, runner: PipelineRunner) -> Callable:
    """Returns a handler bound to event_bus."""
    def _handler(payload):
        coro = runner.run_for_collector_start(payload)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            try:
                asyncio.run(coro)
            except Exception:
                logger.exception("collector chain dispatch failed")
            return
        loop.create_task(coro)
    return _handler
```

### Lock granularity (CRITICAL — do not split)

The current code uses a single module-level `_lock = threading.Lock()` that serializes:
- Reads/writes to `_queue` (queue state)
- Reads/writes to `_in_flight` set
- Reads/writes to `_paused` flag
- Persistence (`_save_queue_unlocked`)
- Loading (`_load_queue_unlocked`)

**The new design MUST preserve this single-lock invariant.** Reason: the `select_next_task` + `tracker.acquire` sequence must be atomic across the whole queue — otherwise two concurrent `enqueue` calls can both see "no in-flight, PENDING" and both emit `collector:start` for the same task. This is exactly what `tests/test_queue/test_lock.py::test_50_concurrent_enqueue_does_not_duplicate_task_id` guards.

**Concretely**: `InMemoryInFlightTracker` and `JsonFileBackend` may have their own internal locks for thread-safety of their own data structures, but **all multi-step orchestration** (snapshot + check + acquire + emit) happens inside a single `with self._service_lock:` block in `QueueService`. The Protocols do not have a "lock" concept — locking is the caller's responsibility.

```python
# service.py
class QueueService:
    def __init__(self, backend, tracker, emitter, retry_policy,
                 circuit_breaker_name="task_queue"):
        self.backend = backend
        self.tracker = tracker
        self.emitter = emitter
        self.retry_policy = retry_policy
        self._breaker = get_circuit_breaker(circuit_breaker_name)
        self._service_lock = threading.Lock()
        self._paused = False

    def advance(self, *, prefer_task_id=None, project_id=None) -> bool:
        with self._service_lock:  # ← service lock serializes the whole sequence
            if self._paused: return False
            if not self._breaker.can_execute(): return False
            task = select_next_task(self.backend, self.tracker,
                                    prefer_task_id=prefer_task_id)
            if task is None: return False
            if not self.tracker.acquire(task.id): return False
            # snapshot of source/source_type/project_id, then release lock
            payload = self._build_collector_payload(task, project_id)
        # lock released; emit is safe to do outside
        self.emitter.emit("collector:start", payload)
        return True
```

**Test impact**: `tests/test_queue/test_lock.py` and its 50-thread concurrency test must continue to pass against the new `QueueService`. The `tracker.is_in_flight()` and `tracker.acquire()` calls inside `select_next_task` are protected by `self._service_lock` — they do not need their own cross-instance lock.

## Error handling

### Error classification (across all layers)

| Error class | Trigger | Handling | Bubble to |
|---|---|---|---|
| `InvalidTransition` | State machine illegal transition (e.g. PENDING→APPROVED) | raise directly, business layer catches → 4xx | route handler |
| `QueueBackendError` | Disk write failure (full disk, permission denied) | entire enqueue fails, HTTP 5xx | route handler |
| `CircuitOpen` | Circuit breaker OPEN, `advance` refuses | silently return False, wait for next advance | scheduler |
| `TaskLostInFlight` | collector started but handler didn't finish | (out of #1 scope, deferred to #2) | — |
| `StageError` | exception inside pipeline stage | stage raises → runner catches → task FAILED → retry | pipeline service |
| `EventHandlerError` | handler raises (EventBus `fail_fast=False`) | log, other handlers continue | EventBus |
| `ProjectNotFound` | invalid project_id | route layer 404 | route handler |

### Retry & dead-letter decision (extracted from `update_task_status`)

**Old** (70 lines coupled in `update_task_status`):
```python
if status == TaskStatus.FAILED:
    task.retry_count += 1
    breaker.record_failure()
    if task.retry_count >= MAX_RETRIES:
        task.status = TaskStatus.DEAD_LETTER
        ...
        if breaker.state == CircuitState.OPEN:
            _pause_queue_unlocked()
    else:
        task.status = TaskStatus.PENDING
        ...
```

**New** (`retry.py::DefaultRetryPolicy`):
```python
@dataclass
class RetryDecision:
    new_status: TaskStatus
    should_emit_dead_letter: bool
    should_pause_queue: bool
    should_record_breaker_failure: bool


class RetryPolicy(Protocol):
    def decide(self, task: KnowledgeTask, attempted_status: TaskStatus,
               error: str | None, breaker: CircuitBreaker) -> RetryDecision: ...


class DefaultRetryPolicy:
    def decide(self, task, attempted_status, error, breaker) -> RetryDecision:
        if attempted_status == TaskStatus.FAILED:
            task.retry_count += 1
            if task.retry_count >= MAX_RETRIES:
                pause = breaker.state == CircuitState.OPEN
                return RetryDecision(
                    new_status=TaskStatus.DEAD_LETTER,
                    should_emit_dead_letter=True,
                    should_pause_queue=pause,
                    should_record_breaker_failure=True,
                )
            return RetryDecision(
                new_status=TaskStatus.PENDING,
                should_emit_dead_letter=False,
                should_pause_queue=False,
                should_record_breaker_failure=True,
            )
        if attempted_status == TaskStatus.TIMEOUT:
            ... # same logic
        if attempted_status == TaskStatus.APPROVED:
            return RetryDecision(
                new_status=TaskStatus.APPROVED,
                should_emit_dead_letter=False,
                should_pause_queue=False,
                should_record_breaker_failure=False,
            )
        ...
```

**Benefits**:
- Decision logic extracted to policy, unit-testable at boundaries (`retry_count == MAX_RETRIES - 1` vs `== MAX_RETRIES`, breaker open/closed, APPROVED shouldn't retry, etc.)
- Future #2 exponential backoff / per-error-class strategies = swap policy implementation

### Stage exception handling (pipeline layer)

**Old** (`_on_collector_start` internal try/except):
```python
try:
    done_payload = await collect(...)
except Exception as exc:
    _logger.exception(...)
    try:
        update_task_status(task_id, FAILED, error=str(exc))
    finally:
        release_in_flight(task_id)
    return
await _on_collector_done(...)
```

**New** (`runner.py::PipelineRunner`):
```python
class PipelineRunner:
    async def run_stages(self, stages: list[PipelineStage],
                        ctx: PipelineContext) -> None:
        prev_result = None
        for stage in stages:
            try:
                result = await stage.run(ctx, prev_result)
                prev_result = result
            except Exception as exc:
                logger.exception("Stage %s failed for %s", stage.name, ctx.task_id)
                self.queue_service.update_status(ctx.task_id, FAILED, error=str(exc))
                if self.queue_service.tracker.is_in_flight(ctx.task_id):
                    self.queue_service.tracker.release(ctx.task_id)
                return
        # all stages succeeded
        self.queue_service.update_status(ctx.task_id, APPROVED)
        self.queue_service.tracker.release(ctx.task_id)
```

**Key improvements**:
- Exception handling centralized in `PipelineRunner`, not scattered
- Any stage failure → same FAILED path + release in-flight
- Test with fake `PipelineStage` (always raises) to verify exception path

### `JsonFileBackend` write failure

```python
class JsonFileBackend(QueueBackend):
    def save(self, task: KnowledgeTask) -> None:
        # Acquire backend lock + queue snapshot under service lock
        # (the service layer holds the service-level lock around all
        # backend operations — see "Lock granularity" below)
        with self._lock:
            data = self._load_unlocked()
            tasks = data.get("tasks", [])
            idx = next((i for i, t in enumerate(tasks) if t["id"] == task.id), None)
            if idx is None:
                tasks.append(asdict(task))
            else:
                tasks[idx] = asdict(task)
            data["tasks"] = tasks
            data["version"] = data.get("version", 0) + 1
            # CRITICAL: use safe_write, NOT direct os.replace.
            # safe_write integrates with AtomicContext (buffers writes
            # when suspended) and accepts DELETE_SENTINEL for deferred
            # deletion. Direct os.replace would break both contracts.
            from ..lib.write_hooks import safe_write
            safe_write(self.path, json.dumps(data, ensure_ascii=False, indent=2))

    def snapshot(self) -> list[KnowledgeTask]:
        # Return current tasks (filter out APPROVED — see below)
        with self._lock:
            data = self._load_unlocked()
            return [KnowledgeTask(**row) for row in data.get("tasks", [])
                    if row.get("status") != TaskStatus.APPROVED.value]
```

**APPROVED filtering invariant**: the current `_save_queue_unlocked` (queue.py:237) excludes APPROVED tasks before persisting (`pending = [t for t in _queue if t.status != TaskStatus.APPROVED]`). The new `JsonFileBackend.snapshot()` must apply the same filter, so the in-memory model matches what's on disk. APPROVED tasks are terminal and re-loading them on next startup would re-process already-completed work.

**Error handling**:
- `safe_write` raises on IO failure → bubbles up as `QueueBackendError`, business layer catches → 5xx
- Atomic write via `*.tmp + os.replace` (handled inside `safe_write` itself) → on any IO error, target file is either old or new version, never half-corrupt
- `safe_write` automatically buffers when `AtomicContext` is suspended — caller inside an AtomicContext gets the same "batched write at commit point" semantics as other wiki IO

### Error propagation path summary

```
Domain error (InvalidTransition)
   ↑ raise
Service layer (QueueService.update_status)
   │ does not catch, lets upper layer handle
   ▼
Route handler (src/server/routes/ingest.py)
   │ try/except → 400/404/500
   ▼
HTTP response

IO error (QueueBackendError)
   ↑ raise
Service layer
   │ does not catch, lets upper layer handle
   ▼
Route handler
   │ 500 + log
   ▼
HTTP response

Stage error (StageError)
   ↑ raise
PipelineRunner
   │ catch → mark FAILED → release in-flight → return
   ▼
(no HTTP impact, completed in background)
```

## Testing strategy

### Test pyramid (under new structure)

```
        ┌──────────────────────┐
        │  E2E tests (few)     │  full ingest flow
        ├──────────────────────┤
        │  Integration (mid)   │  Service + Real Backend + Real EventBus
        ├──────────────────────┤
        │  Unit tests (many)   │  pure functions / fake injection
        └──────────────────────┘
```

### Unit test target (one test file per module)

| Module | Test file | What to test | What to use |
|---|---|---|---|
| `state.py` | `tests/test_queue/test_state.py` | `can_transition` all legal/illegal transitions | no mock, pure assertions |
| `retry.py` | `tests/test_queue/test_retry.py` | `DefaultRetryPolicy.decide` various retry_count + breaker state combos | Fake CircuitBreaker |
| `scheduler.py` | `tests/test_queue/test_scheduler.py` | `select_next_task` priority logic | Fake QueueBackend + Fake InFlightTracker |
| `in_flight.py` | `tests/test_queue/test_in_flight.py` | acquire idempotency, release safety, is_in_flight | no mock |
| `persistence.py` | `tests/test_queue/test_persistence.py` | write/read/atomic rename/corruption recovery | `tmp_path` fixture |
| `service.py` | `tests/test_queue/test_service.py` | `enqueue`/`update_status`/`advance` orchestration | FakeBackend + FakeTracker + FakeEmitter |
| `events.py` | `tests/test_queue/test_events.py` | EventName constant values don't drift | none |
| `ports.py` | (no separate test; Protocol is contract, covered by implementation tests) | — | — |

### Test fixtures (`tests/test_queue/conftest.py` new)

```python
import pytest
from src.queue.ports import QueueBackend, InFlightTracker, EventEmitter
from src.queue.in_flight import InMemoryInFlightTracker
from src.events.event_bus import EventBus


class FakeQueueBackend:
    """In-memory; can assert enqueue/save call order."""
    def __init__(self):
        self._tasks: dict[str, dict] = {}
        self._calls: list[tuple[str, ...]] = []

    def enqueue(self, task): self._calls.append(("enqueue", task.id)); ...
    def save(self, task): self._calls.append(("save", task.id)); ...
    def find(self, task_id): return self._tasks.get(task_id)
    def snapshot(self): return list(self._tasks.values())
    def calls_matching(self, op): return [c for c in self._calls if c[0] == op]


class FakeEventEmitter:
    def __init__(self): self.events: list[tuple[str, Any]] = []
    def emit(self, event, payload): self.events.append((event, payload))


@pytest.fixture
def fake_backend(): return FakeQueueBackend()
@pytest.fixture
def fake_tracker(): return InMemoryInFlightTracker()
@pytest.fixture
def fake_emitter(): return FakeEventEmitter()
@pytest.fixture
def queue_service(fake_backend, fake_tracker, fake_emitter):
    from src.queue.service import QueueService
    from src.queue.retry import DefaultRetryPolicy
    return QueueService(
        backend=fake_backend,
        tracker=fake_tracker,
        emitter=fake_emitter,
        retry_policy=DefaultRetryPolicy(),
    )
```

### Template tests (for future test work)

**A. Pure function test** (`test_scheduler.py`):
```python
def test_select_next_task_prefers_explicit_task_id():
    backend = FakeQueueBackend()
    backend.enqueue(make_task("a", PENDING))
    backend.enqueue(make_task("b", PENDING))
    tracker = InMemoryInFlightTracker()

    result = select_next_task(backend, tracker, prefer_task_id="b")
    assert result.id == "b"

def test_select_next_task_skips_in_flight():
    backend = FakeQueueBackend()
    backend.enqueue(make_task("a", PENDING))
    backend.enqueue(make_task("b", PENDING))
    tracker = InMemoryInFlightTracker()
    tracker.acquire("a")

    result = select_next_task(backend, tracker)
    assert result.id == "b"
```

**B. Service layer test** (`test_service.py`):
```python
def test_enqueue_emits_task_created_and_advances(queue_service, fake_emitter):
    task_id = queue_service.enqueue(
        source="https://example.com", source_type=SourceType.URL,
        task_hash="abc", project_id="p1",
    )
    assert task_id != ""
    event_names = [e[0] for e in fake_emitter.events]
    assert "task:created" in event_names
    assert "collector:start" in event_names
    assert queue_service.backend.calls_matching("enqueue")[0] == ("enqueue", task_id)
    assert queue_service.tracker.is_in_flight(task_id)

def test_update_status_failed_resets_to_pending_under_retry_limit(queue_service):
    task_id = queue_service.enqueue(
        source="x", source_type=SourceType.URL, task_hash="h1",
    )

    queue_service.update_status(task_id, TaskStatus.FAILED, error="LLM timeout")

    task = queue_service.backend.find(task_id)
    assert task.status == TaskStatus.PENDING
    assert task.retry_count == 1

def test_update_status_failed_moves_to_dead_letter_after_max_retries(queue_service):
    """After MAX_RETRIES (3) FAILED transitions, task becomes DEAD_LETTER."""
    task_id = queue_service.enqueue(
        source="x", source_type=SourceType.URL, task_hash="h2",
    )
    for i in range(MAX_RETRIES):
        queue_service.update_status(task_id, TaskStatus.FAILED, error=f"attempt {i}")

    task = queue_service.backend.find(task_id)
    assert task.status == TaskStatus.DEAD_LETTER
    assert task.retry_count == MAX_RETRIES
```

**C. Pipeline test** (`test_runner.py`):
```python
async def test_runner_marks_task_approved_on_all_stages_success(queue_service):
    runner = PipelineRunner(queue_service)
    stages = [FakeStage("collector"), FakeStage("analyzer"), FakeStage("generator")]
    ctx = PipelineContext(task_id="t1", source="x", source_type=SourceType.URL)

    await runner.run_stages(stages, ctx)

    task = queue_service.backend.find("t1")
    assert task.status == TaskStatus.APPROVED
    assert not queue_service.tracker.is_in_flight("t1")

async def test_runner_marks_task_failed_on_stage_exception(queue_service):
    runner = PipelineRunner(queue_service)
    stages = [
        FakeStage("collector"),
        FakeStage("analyzer", raises=RuntimeError("LLM blew up")),
        FakeStage("generator"),
    ]
    ctx = PipelineContext(task_id="t1", source="x", source_type=SourceType.URL)

    await runner.run_stages(stages, ctx)

    task = queue_service.backend.find("t1")
    assert task.status == TaskStatus.PENDING
    assert task.retry_count == 1
    assert not queue_service.tracker.is_in_flight("t1")
```

### Existing 22 queue test handling

| Existing test | After split | Change/keep |
|---|---|---|
| `test_queue.py::test_generate_task_id` | `test_state.py` or `test_service.py` | keep (tests `generate_task_id` function) |
| `test_queue_retry_liveness.py` | `test_service.py` | rewrite with fake_backend, more precise assertions |
| `test_lock.py` | `test_service.py` + `test_in_flight.py` | split, some test tracker lock, some test service serialization |
| `test_save_atomic.py` (7 tests) | `test_persistence.py` | **CRITICAL**: these tests monkeypatch `os.replace` to verify atomic-write failure semantics; the new `JsonFileBackend` MUST use `safe_write` (which itself uses `os.replace`) so these tests pass unchanged. `test_atomic_write_does_not_partial_write` is the canary — if it fails after the refactor, the backend is bypassing `safe_write` |
| `test_update_task_status_transitions.py` (4 tests) | `test_service.py` | rewrite — exercise state machine transitions through `QueueService.update_status` |
| `test_dead_letter.py` | `test_service.py` + `test_retry.py` | split: dead-letter behavior covered by `DefaultRetryPolicy.decide`; service-level emit/transition by `QueueService.update_status` |
| `test_pipeline_terminal_status.py` | `test_runner.py` | rewrite to run runner + fake stages |
| `test_collector_retry_path.py` | `test_runner.py` | same as above |
| `test_pipeline.py::test_collector_done_triggers_run_ingest` | `test_runner.py::test_runner_chains_stages` | rewrite |
| `test_pipeline_event_bus_integration.py` | `test_dispatcher.py` | rewrite with fake emitter; **preserve** `test_event_bus_dispatch_external_listener_runs` (external listener must still receive `collector:done` even though pipeline drives `_on_collector_done` directly) |
| `tests/test_e2e/test_ingest_happy_path.py` | `tests/test_e2e/test_ingest_happy_path.py` | keep — end-to-end test that uses `pause_queue()` / `resume_queue()`; the new service must expose these |
| `tests/test_server/test_service_ingest.py`, `tests/test_server/test_service_ingest_paths.py` | (unchanged) | these test `src.services.ingest`, not queue directly — should not need refactoring |
| remaining `test_queue_*.py` | all rewritten as service layer tests | rewrite |

**Target**: 22 old tests + 30+ new unit tests + 5+ E2E tests = ~60 tests. **All existing assertion input/outputs must be preserved** (only the implementation location changes).

## Verification

```bash
# 1. All tests pass
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest --import-mode=importlib
# Expect: 748 + new tests ≈ 778 passed

# 2. Key subset (fast feedback)
PYTHONPATH=. python -m pytest tests/test_queue/ tests/test_pipeline/ -v
# Expect: 60+ passed

# 3. Compatibility verification (ensure import paths still work)
python -c "from src.queue import enqueue_task, update_task_status, get_queue, pause_queue, resume_queue"
python -c "from src.queue.queue import __reset_for_testing"  # test-only
python -c "from src.pipeline.pipeline import _on_collector_start, run_ingest, _resolve_wiki_paths, _get_provider"
python -c "from src.pipeline.collector import collect"
# Expect: no ImportError

# 4. Server startup verification (regression)
python -m src.cli serve --port 18888 &
sleep 2
curl http://127.0.0.1:18888/health
# Expect: 200 OK

# 5. AtomicContext integration sanity check
python -c "
from src.lib.atomic_ctx import AtomicContext
from src.lib.write_hooks import get_pending_count
from src.queue import enqueue_task
# Inside an AtomicContext, enqueue_task should buffer the queue.json
# write via safe_write rather than touching disk directly.
with AtomicContext():
    enqueue_task('test.txt', None, 'hash-test-atomic')
assert get_pending_count() > 0, 'queue.json write should be buffered under AtomicContext'
print('OK: safe_write integration preserved')
"
# Expect: prints "OK: safe_write integration preserved"
```

## Implementation notes (preserved behavior)

### `_resolve_wiki_paths` and `_get_provider` monkey-patch surface

`tests/test_pipeline/test_pipeline_event_bus_integration.py:126-127` does:
```python
monkeypatch.setattr(pipeline_mod, "_resolve_wiki_paths", lambda project_id=None: tmp_path)
monkeypatch.setattr(pipeline_mod, "_get_provider", lambda: object())
```

These helpers live in `src/pipeline/pipeline.py` today. The refactor must preserve the **patchability** of these helpers. Recommended placement: keep them in `src/pipeline/ingest.py` (or a new `src/pipeline/_helpers.py`) and re-export them from `src/pipeline/pipeline` via the compat layer:

```python
# src/pipeline/__init__.py compat layer
import sys
from .ingest import _resolve_wiki_paths, _get_provider, run_ingest
# Create a stub module so `from src.pipeline.pipeline import _resolve_wiki_paths` works
class _PipelineCompat:
    pass
_pipeline_compat = _PipelineCompat()
_pipeline_compat._resolve_wiki_paths = _resolve_wiki_paths
_pipeline_compat._get_provider = _get_provider
_pipeline_compat.run_ingest = run_ingest
sys.modules.setdefault("src.pipeline.pipeline", _pipeline_compat)
```

When tests monkey-patch `src.pipeline.pipeline._resolve_wiki_paths`, the patch must reach the function actually called. The simplest contract: `src/pipeline/ingest.py` does `from .helpers import _resolve_wiki_paths, _get_provider`, and `src/pipeline/helpers.py` re-defines them. Tests patch the symbol in `src.pipeline.pipeline` (the compat module), and the call sites in `ingest.py` look it up dynamically.

**Alternative (simpler)**: keep `_resolve_wiki_paths` and `_get_provider` as top-level functions in the compat shim module (`src/pipeline/pipeline.py` becomes a thin shim, not deleted), and have the new `src/pipeline/ingest.py` import them from there. Tests keep their existing `monkeypatch.setattr(pipeline_mod, ...)` pattern unchanged.

**Recommended**: the "alternative (simpler)" path. Delete is not strictly required for #1 — the goal is testability, not minimal lines of code. The compat shim can host `_resolve_wiki_paths`, `_get_provider`, and a thin re-export of `run_ingest`. Implementation phase may decide.

### Circuit breaker is a process-level singleton

`src/queue/queue.py:96` does `breaker = get_circuit_breaker(CIRCUIT_BREAKER_NAME)` on every `update_task_status` call. `get_circuit_breaker` is itself a module-level cache (`src/circuit_breaker.py`), so the same `CircuitBreaker` instance is returned every call.

The new `QueueService` must preserve this — store the breaker name (string) in the service, resolve via `get_circuit_breaker` on each call. Do NOT cache the breaker instance on the service, because tests reset breaker state in-place (`tests/test_pipeline/test_pipeline_event_bus_integration.py:49-53` does `breaker.state = CircuitState.CLOSED` etc.) and a cached reference would diverge from the canonical singleton.

```python
# service.py
class QueueService:
    def __init__(self, ..., circuit_breaker_name: str = "task_queue"):
        self._breaker_name = circuit_breaker_name

    def _breaker(self):
        return get_circuit_breaker(self._breaker_name)
```

### `collector:done` event must still be emitted

`src/pipeline/collector.py::collect` emits `EventName.COLLECTOR_DONE` for external listeners (e.g. `tests/test_pipeline/test_pipeline_event_bus_integration.py::test_event_bus_dispatch_external_listener_runs` asserts on this). The pipeline-internal chain drives `_on_collector_done` directly via `await` (not via the bus), but `collect()` must keep emitting.

**Do not** centralize the `await _on_collector_done` in the dispatcher and remove the `collect()` emit — this would break the external listener test. The current arrangement is intentional.

### `_save_queue` is called inside `with _lock:`

The current `update_task_status` does `_save_queue_unlocked()` while holding `_lock`. The new `QueueService.update_status` must call `self.backend.save(task)` while holding `self._service_lock` — otherwise another thread could read state between the in-memory update and the disk write, and a crash in between would lose the in-memory state on reload. This is the same lock contract as the current code, just renamed.

## Definition of Done

1. `src/queue/queue.py` no longer exists (replaced by `src/queue/service.py` + 4 submodules)
2. `src/pipeline/pipeline.py` either no longer exists OR is reduced to a compat shim that re-exports `_resolve_wiki_paths`, `_get_provider`, and `run_ingest` (decision deferred to implementation phase)
3. `from src.queue import enqueue_task, update_task_status, get_queue, pause_queue, resume_queue, generate_task_id` all work
4. `from src.queue.queue import __reset_for_testing` works for tests
5. `from src.pipeline.pipeline import _on_collector_start, run_ingest, _resolve_wiki_paths, _get_provider` all work
6. **All 748 tests still pass** (`pytest --import-mode=importlib`), including the `test_save_atomic` canary that detects safe_write bypass
7. **AtomicContext integration preserved**: a sanity check that `enqueue_task` inside `AtomicContext` buffers via `safe_write` (see Verification #5)
8. **External `collector:done` listener still works**: `test_event_bus_dispatch_external_listener_runs` passes unchanged
9. At least 3 new "Protocol + Fake" example tests, as templates for future test work
10. Implementation broken into 6-10 TDD-driven commits, each commit keeps tests green

## Open questions

None remaining. All design decisions (architecture, module boundaries, data flow, error handling, testing strategy) were approved section-by-section in the brainstorming session before this spec was written.

## References

- [hexagonal architecture (Ports & Adapters)](https://alistair.cockburn.us/hexagonal-architecture/)
- [Protocol (PEP 544)](https://peps.python.org/pep-0544/)
- [pytest fixtures](https://docs.pytest.org/en/stable/explanation/fixtures.html)
- [CLAUDE.md](../../CLAUDE.md) — project conventions
- [atomic-ctx-budgeted-llm-design.md](2026-07-21-atomic-ctx-budgeted-llm-design.md) — similar split pattern applied to lib/
