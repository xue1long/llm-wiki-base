# Queue & Pipeline Refactor for Testability — Design Spec

**Date:** 2026-07-25
**Status:** Draft (pending user sign-off)
**Target codebase:** ruflo-kb (Python 3.11+, master @ d59768c, post-M4 cleanup)
**Series:** Optimization sub-project #1 of 4 (predecessor to reliability / throughput / observability)
**Inspired by:** hexagonal architecture (Ports & Adapters) pattern

## Goal

Split `src/queue/queue.py` (350+ lines) and `src/pipeline/pipeline.py` (110+ lines) from monolithic modules with mixed concerns into a **Protocol-bounded, dependency-injectable** structure where business logic is testable in isolation from IO. All 748 existing tests must remain green; all existing public import paths must continue to work.

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
│                  Domain Layer (pure functions)              │
│   src/queue/state.py        can_transition                  │
│   src/queue/persistence.py  JsonFileBackend IO              │
│   src/queue/in_flight.py    InMemoryTracker                 │
│   src/queue/retry.py        DefaultRetryPolicy              │
│   src/queue/scheduler.py    select_next_task (pure)         │
│   src/queue/events.py       EventName + payload dataclass   │
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
| `__init__.py` | `enqueue_task`, `update_task_status`, `release_in_flight`, `_process_next`, `generate_task_id`, `get_default_queue_service` | — | re-export from `service` + `state` |
| `ports.py` | `QueueBackend`, `InFlightTracker`, `EventEmitter`, `RetryPolicy` (Protocol) | — | `typing`, `dataclass` only |
| `events.py` | `EventName` constants, `TaskCreatedPayload`, `TaskStatusChangedPayload`, `TaskDeadLetterPayload` | — | `dataclass` only |
| `state.py` | `can_transition`, `InvalidTransition` | — | `src/types.py::TaskStatus` |
| `persistence.py` | `JsonFileBackend` (implements `QueueBackend`) | `_acquire_file_lock`, `_release_file_lock` | `state`, `events` |
| `in_flight.py` | `InMemoryInFlightTracker` (implements `InFlightTracker`) | — | — |
| `retry.py` | `DefaultRetryPolicy` (implements `RetryPolicy`), `DeadLetter`, `decide_retry_action`, `RetryDecision` dataclass | — | `state`, circuit_breaker |
| `scheduler.py` | `Scheduler` class, `select_next_task` (pure function) | — | `ports`, `state` |
| `service.py` | `QueueService`, `get_default_queue_service` | `_default_service` | all of the above |
| `queue.py` | **DELETED** (replaced by service + submodules) | — | — |

### `src/pipeline/` new structure

| File | Public API | Private | Depends on |
|---|---|---|---|
| `__init__.py` | re-exports `run_ingest`, `PipelineService`, `get_default_pipeline_service`; **compat layer** aliases `src.pipeline.pipeline`, `src.pipeline.collector`, `src.pipeline.analyzer`, `src.pipeline.generator` via `sys.modules` | — | all submodules |
| `ports.py` | `PipelineStage` (Protocol), `StageResult` (dataclass), `PipelineContext` (dataclass) | — | — |
| `events.py` | `EventName` constants, `CollectorStartPayload`, `CollectorDonePayload` | — | `queue.events` constants |
| `dispatcher.py` | `dispatch_collector_start` (sync→async bridge) | — | `ports`, `events` |
| `runner.py` | `PipelineRunner`, `run_stages` (pure function) | — | `ports` |
| `stages/collector.py` | `CollectorStage` (implements `PipelineStage`) | — | `wiki`, `queue.ports` |
| `stages/analyzer.py` | `AnalyzerStage` | — | `llm`, `pipeline.schemas` |
| `stages/generator.py` | `GeneratorStage` | — | `llm`, `pipeline.schemas` |
| `ingest.py` | `run_ingest` (pure function) | — | `stages/`, `wiki.storage` |
| `service.py` | `PipelineService`, `get_default_pipeline_service`, `register_stages` (explicit registration) | — | all of the above |
| `pipeline.py` | **DELETED** | — | — |

### Public vs private principles

**Public** (re-exported from `__init__.py` or top-level):
- All Protocol contracts (`ports.py`)
- Orchestration entry points (`QueueService.enqueue`, `PipelineService.run`)
- Pure functions (`can_transition`, `run_ingest`, `decide_retry_action`)
- Event dataclasses (for external listeners)

**Private** (`_` prefix / not re-exported):
- `_acquire_file_lock` / `_release_file_lock`
- Internal helpers (e.g. `_save_queue_unlocked`)
- Default singleton private variables (e.g. `_default_service`)

**No cross-module private access**:
- `persistence.py` cannot import `service.py` (would create cycle)
- `state.py` cannot import `ports.py` (state machine is pure logic)
- `in_flight.py` doesn't know about backend (independent dimension)

### Key invariants (REFUSE to break)

1. `enqueue_task` signature unchanged: `(source, source_type, task_hash, project_id=None) -> str`
2. `update_task_status` signature unchanged: `(task_id, status, error=None) -> None`, still raises `InvalidTransition`
3. `generate_task_id` signature unchanged: `() -> str`
4. `run_ingest` signature unchanged (verify against all current call sites)
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
        with self._lock, self._open_queue_file() as f:
            data = json.load(f)
            tasks = data.get("tasks", [])
            idx = next((i for i, t in enumerate(tasks) if t["id"] == task.id), None)
            if idx is None:
                tasks.append(asdict(task))
            else:
                tasks[idx] = asdict(task)
            data["tasks"] = tasks
            data["version"] = data.get("version", 0) + 1
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            os.replace(tmp, self.path)
```

**Error handling**:
- `tmp.write_text` failure → tmp file residual, cleaned on next startup
- `os.replace` failure → raise `QueueBackendError`, business layer catches → 5xx
- **Critical invariant**: on any IO error, `.kb-queue.json` is either old or new version, never half-corrupt (atomic rename)

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
    queue_service.enqueue(source="x", source_type=SourceType.URL, task_hash="h1")
    task_id = ...  # get the just-enqueued task

    queue_service.update_status(task_id, TaskStatus.FAILED, error="LLM timeout")

    task = queue_service.backend.find(task_id)
    assert task.status == TaskStatus.PENDING
    assert task.retry_count == 1

def test_update_status_failed_moves_to_dead_letter_after_max_retries(queue_service):
    # 3 FAILED, 3rd should be DEAD_LETTER
    ...
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
    ctx = PipelineContext(task_id="t1", ...)

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
| `test_pipeline_terminal_status.py` | `test_runner.py` | rewrite to run runner + fake stages |
| `test_collector_retry_path.py` | `test_runner.py` | same as above |
| `test_pipeline.py::test_collector_done_triggers_run_ingest` | `test_runner.py::test_runner_chains_stages` | rewrite |
| `test_pipeline_event_bus_integration.py` | `test_dispatcher.py` | rewrite with fake emitter |
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
python -c "from src.queue import enqueue_task, update_task_status"
python -c "from src.pipeline.pipeline import _on_collector_start, run_ingest"
python -c "from src.pipeline.collector import collect"
# Expect: no ImportError

# 4. Server startup verification (regression)
python -m src.cli serve --port 18888 &
sleep 2
curl http://127.0.0.1:18888/health
# Expect: 200 OK
```

## Definition of Done

1. `src/queue/queue.py` no longer exists (replaced by `src/queue/service.py` + 4 submodules)
2. `src/pipeline/pipeline.py` no longer exists (replaced by `src/pipeline/service.py` + stages)
3. `from src.queue import enqueue_task` still works (compat layer in `__init__.py`)
4. `from src.pipeline.pipeline import _on_collector_start` still works (compat layer)
5. **All 748 tests still pass** (`pytest --import-mode=importlib`)
6. At least 3 new "Protocol + Fake" example tests, as templates for future test work
7. Implementation broken into 6-10 TDD-driven commits, each commit keeps tests green

## Open questions

(None remaining — all design decisions approved through 5 design sections.)

## References

- [hexagonal architecture (Ports & Adapters)](https://alistair.cockburn.us/hexagonal-architecture/)
- [Protocol (PEP 544)](https://peps.python.org/pep-0544/)
- [pytest fixtures](https://docs.pytest.org/en/stable/explanation/fixtures.html)
- [CLAUDE.md](../../CLAUDE.md) — project conventions
- [atomic-ctx-budgeted-llm-design.md](2026-07-21-atomic-ctx-budgeted-llm-design.md) — similar split pattern applied to lib/
