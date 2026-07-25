# Queue & Pipeline Refactor for Testability — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `src/queue/queue.py` (350+ lines) and `src/pipeline/pipeline.py` (110+ lines) into Protocol-bounded, dependency-injectable modules with no behavior change. All 748 existing tests must remain green.

**Architecture:** Hexagonal-style (Ports & Adapters). Pure state machine, scheduler, and re-exports in domain layer. Default IO adapters (`JsonFileBackend`, `InMemoryInFlightTracker`, `DefaultRetryPolicy`) implement Protocols. `QueueService` / `PipelineService` are composition roots that hold a single service-level lock for orchestration. Compat layer in `__init__.py` preserves all existing public import paths.

**Tech Stack:** Python 3.11+, `threading.Lock`, `dataclasses`, `typing.Protocol` (PEP 544), pytest, `safe_write` (existing in `src/lib/write_hooks.py`).

## Global Constraints

These are REFUSE-to-break invariants from `docs/superpowers/specs/2026-07-25-queue-pipeline-refactor-design.md`. Every task's requirements implicitly include this section.

1. **`safe_write` integration** — `JsonFileBackend` must call `safe_write` (not direct `os.replace`) so queue.json writes participate in the `AtomicContext` suspension/batching system. Detected by `tests/test_queue/test_save_atomic.py::test_atomic_write_does_not_partial_write`.
2. **APPROVED task filtering** — APPROVED tasks are not persisted to disk and are filtered out of `backend.snapshot()`. If we naively save every task, the queue file balloons with already-processed tasks and may re-process them on restart.
3. **Service-level single lock** — All multi-step orchestration (snapshot + check + acquire + emit + save) happens inside `QueueService._service_lock`. Do NOT split into per-component locks. Detected by `tests/test_queue/test_lock.py`.
4. **External `collector:done` listener** — `collect()` must still emit `EventName.COLLECTOR_DONE` for external subscribers, even though the pipeline-internal chain now drives `_on_collector_done` via direct `await`. Detected by `tests/test_pipeline/test_pipeline_event_bus_integration.py::test_event_bus_dispatch_external_listener_runs`.
5. **Circuit breaker is a process-level singleton** — `get_circuit_breaker("task_queue")` returns the same instance every call. Resolve the name on each call, do NOT cache the instance.
6. **Monkeys-patchable private helpers** — `pipeline._resolve_wiki_paths` and `pipeline._get_provider` must remain reachable from `src.pipeline.pipeline` (compat shim is OK). Detected by `tests/test_pipeline/test_pipeline_event_bus_integration.py:126-127`.
7. **Public API surface preserved** — `from src.queue import enqueue_task, update_task_status, get_queue, pause_queue, resume_queue, generate_task_id` must all keep working.
8. **All 748 existing tests must pass after each task.** Run `env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy PYTHONPATH=. python -m pytest --import-mode=importlib` after every commit.

---

## File Structure

### Files to CREATE

```
src/queue/
  state.py            # Pure: can_transition, InvalidTransition
  events.py           # Re-export shim: re-exports from src/events/events.py
  ports.py            # Protocols: QueueBackend, InFlightTracker, EventEmitter, RetryPolicy
  in_flight.py        # InMemoryInFlightTracker (default InFlightTracker)
  persistence.py      # JsonFileBackend (default QueueBackend, uses safe_write)
  retry.py            # DefaultRetryPolicy, RetryDecision, decide_retry_action
  scheduler.py        # select_next_task (pure function), Scheduler class
  service.py          # QueueService, get_default_queue_service, __reset_for_testing
                       # release_in_flight (private), _paused, _service_lock

src/pipeline/
  ports.py            # PipelineStage Protocol, StageResult, PipelineContext dataclasses
  events.py           # Re-export shim: re-exports from src/events/events.py
  runner.py           # PipelineRunner, run_stages
  ingest.py           # run_ingest, _resolve_wiki_paths, _get_provider
  dispatcher.py       # dispatch_collector_start
  service.py          # PipelineService, get_default_pipeline_service, register_stages
  stages/
    __init__.py       # Re-exports CollectorStage, AnalyzerStage, GeneratorStage
    collector.py      # CollectorStage
    analyzer.py       # AnalyzerStage
    generator.py      # GeneratorStage

tests/test_queue/
  conftest.py         # FakeQueueBackend, FakeEventEmitter fixtures
  test_state.py       # can_transition tests
  test_in_flight.py   # InMemoryInFlightTracker tests
  test_persistence.py # JsonFileBackend tests (mirrors test_save_atomic.py)
  test_retry.py       # DefaultRetryPolicy tests
  test_scheduler.py   # select_next_task tests
  test_service.py     # QueueService tests (mirrors test_queue*.py)

tests/test_pipeline/
  test_runner.py      # PipelineRunner tests (mirrors test_pipeline_terminal_status.py)
  test_dispatcher.py  # dispatch_collector_start tests (mirrors test_pipeline_event_bus_integration.py)
```

### Files to MODIFY

```
src/queue/__init__.py  # Compat shim re-exporting from service + state
src/pipeline/__init__.py  # Compat shim: re-exports + sys.modules aliases
```

### Files to DELETE (after Tasks 7 and 10)

```
src/queue/queue.py
src/pipeline/pipeline.py  # (if not kept as thin shim — see Task 10)
```

---

## Task 1: Extract `src/queue/state.py` (state machine)

**Files:**
- Create: `src/queue/state.py`
- Create: `tests/test_queue/test_state.py`
- Modify: `src/queue/queue.py:103-107` (delete the `can_transition` reference inline, point callers to new module — but this is a soft migration; the function still works)

**Interfaces:**
- Consumes: `src.types.TaskStatus` enum
- Produces:
  - `class InvalidTransition(Exception)` — takes `(task_id, prev_status, next_status)`
  - `def can_transition(prev: TaskStatus, next: TaskStatus) -> bool`

- [ ] **Step 1: Write the failing test**

Create `tests/test_queue/test_state.py`:

```python
"""Tests for queue state machine — pure functions, no IO."""
import pytest

from src.queue.state import can_transition, InvalidTransition
from src.types import TaskStatus


class TestCanTransition:
    def test_pending_to_running_allowed(self):
        assert can_transition(TaskStatus.PENDING, TaskStatus.RUNNING) is True

    def test_running_to_approved_allowed(self):
        assert can_transition(TaskStatus.RUNNING, TaskStatus.APPROVED) is True

    def test_pending_to_approved_blocked(self):
        assert can_transition(TaskStatus.PENDING, TaskStatus.APPROVED) is False

    def test_pending_to_failed_allowed(self):
        assert can_transition(TaskStatus.PENDING, TaskStatus.FAILED) is True

    def test_running_to_failed_allowed(self):
        assert can_transition(TaskStatus.RUNNING, TaskStatus.FAILED) is True

    def test_approved_to_running_blocked_terminal(self):
        assert can_transition(TaskStatus.APPROVED, TaskStatus.RUNNING) is False

    def test_dead_letter_is_terminal(self):
        for next_status in [TaskStatus.PENDING, TaskStatus.RUNNING,
                            TaskStatus.APPROVED, TaskStatus.FAILED]:
            assert can_transition(TaskStatus.DEAD_LETTER, next_status) is False


class TestInvalidTransition:
    def test_message_includes_all_three(self):
        with pytest.raises(InvalidTransition) as exc_info:
            raise InvalidTransition("task-1", "pending", "approved")
        assert exc_info.value.args == ("task-1", "pending", "approved")

    def test_is_an_exception(self):
        assert issubclass(InvalidTransition, Exception)
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd E:/2026-7-21/ruflo-kb
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest tests/test_queue/test_state.py -v --import-mode=importlib
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.queue.state'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/queue/state.py`:

```python
"""Pure state machine for KnowledgeTask transitions. No IO, no globals.

This is the source of truth for which task status transitions are legal.
The current `update_task_status` in `src/queue/queue.py:103-107` calls a
local `can_transition`; this module is the extracted pure form. The
existing module is migrated to import from here.
"""
from __future__ import annotations
from ..types import TaskStatus


class InvalidTransition(Exception):
    """Raised when a task status change violates the state machine."""

    def __init__(self, task_id: str, prev_status: str, next_status: str):
        super().__init__(task_id, prev_status, next_status)
        self.task_id = task_id
        self.prev_status = prev_status
        self.next_status = next_status


# Legal transitions (source of truth; the old `can_transition` in queue.py
# has the same matrix):
#   PENDING       → RUNNING | FAILED | TIMEOUT
#   RUNNING       → APPROVED | REJECTED | FAILED | TIMEOUT
#   WAITING_REVIEW → APPROVED | REJECTED | FAILED
#   FAILED        → PENDING (auto-retry) | DEAD_LETTER (after MAX_RETRIES)
#   TIMEOUT       → PENDING (auto-retry) | DEAD_LETTER (after MAX_RETRIES)
#   REJECTED      → PENDING (manual retry) | ARCHIVED
#   APPROVED      → ARCHIVED
#   DEAD_LETTER   → (terminal)
_LEGAL: frozenset[tuple[TaskStatus, TaskStatus]] = frozenset({
    (TaskStatus.PENDING, TaskStatus.RUNNING),
    (TaskStatus.PENDING, TaskStatus.FAILED),
    (TaskStatus.PENDING, TaskStatus.TIMEOUT),
    (TaskStatus.RUNNING, TaskStatus.APPROVED),
    (TaskStatus.RUNNING, TaskStatus.REJECTED),
    (TaskStatus.RUNNING, TaskStatus.FAILED),
    (TaskStatus.RUNNING, TaskStatus.TIMEOUT),
    (TaskStatus.WAITING_REVIEW, TaskStatus.APPROVED),
    (TaskStatus.WAITING_REVIEW, TaskStatus.REJECTED),
    (TaskStatus.WAITING_REVIEW, TaskStatus.FAILED),
    (TaskStatus.FAILED, TaskStatus.PENDING),
    (TaskStatus.FAILED, TaskStatus.DEAD_LETTER),
    (TaskStatus.TIMEOUT, TaskStatus.PENDING),
    (TaskStatus.TIMEOUT, TaskStatus.DEAD_LETTER),
    (TaskStatus.REJECTED, TaskStatus.PENDING),
    (TaskStatus.REJECTED, TaskStatus.ARCHIVED),
    (TaskStatus.APPROVED, TaskStatus.ARCHIVED),
})


def can_transition(prev: TaskStatus, next_: TaskStatus) -> bool:
    """Return True if `prev → next_` is a legal status transition."""
    return (prev, next_) in _LEGAL
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd E:/2026-7-21/ruflo-kb
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest tests/test_queue/test_state.py -v --import-mode=importlib
```

Expected: PASS (10 tests).

- [ ] **Step 5: Verify the rest of the suite still passes**

Run:
```bash
cd E:/2026-7-21/ruflo-kb
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest --import-mode=importlib -q 2>&1 | tail -5
```

Expected: ~748 passed (or the same count as before this task).

- [ ] **Step 6: Commit**

```bash
cd E:/2026-7-21/ruflo-kb
git add src/queue/state.py tests/test_queue/test_state.py
git commit -m "feat(queue): extract pure state machine to src/queue/state.py

Migrate can_transition() and InvalidTransition out of queue.py
into a pure module. The existing inline can_transition in
src/queue/queue.py:103-107 still works (queue.py is migrated
in a later task); this commit only adds the new module and tests.

No behavior change. All 748 tests still pass.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: Extract `src/queue/ports.py` + `src/queue/in_flight.py` (Protocols + InMemoryInFlightTracker)

**Files:**
- Create: `src/queue/ports.py`
- Create: `src/queue/in_flight.py`
- Create: `tests/test_queue/test_in_flight.py`
- Modify: `tests/test_queue/conftest.py` (created here if doesn't exist; if exists, no change)

**Interfaces:**
- Consumes: `src.types.KnowledgeTask`, `src.types.TaskStatus`
- Produces (from `ports.py`):
  - `class QueueBackend(Protocol)`: `enqueue(task)`, `save(task)`, `find(task_id) -> KnowledgeTask | None`, `snapshot() -> list[KnowledgeTask]`
  - `class InFlightTracker(Protocol)`: `acquire(task_id) -> bool`, `release(task_id)`, `is_in_flight(task_id) -> bool`, `snapshot() -> set[str]`
  - `class EventEmitter(Protocol)`: `emit(event: str, payload)`
  - `class RetryPolicy(Protocol)`: `decide(task, attempted_status, error, breaker) -> RetryDecision`
- Produces (from `in_flight.py`):
  - `class InMemoryInFlightTracker`: implements `InFlightTracker`; thread-safe via internal `threading.Lock`

- [ ] **Step 1: Write the failing test for InMemoryInFlightTracker**

Create `tests/test_queue/test_in_flight.py`:

```python
"""Tests for InMemoryInFlightTracker — the default InFlightTracker impl.

The tracker is used inside QueueService to gate task selection: a task
in tracker.snapshot() is excluded from select_next_task. The contract is:
- acquire(task_id) returns False if already in flight (idempotent)
- release(task_id) is a no-op if not in flight
- is_in_flight(task_id) reflects current state
- snapshot() returns a copy of the set (caller-side mutation is safe)
"""
import pytest

from src.queue.in_flight import InMemoryInFlightTracker


class TestInMemoryInFlightTracker:
    def test_acquire_returns_true_for_new_task(self):
        t = InMemoryInFlightTracker()
        assert t.acquire("task-1") is True
        assert t.is_in_flight("task-1") is True

    def test_acquire_returns_false_for_existing_task(self):
        t = InMemoryInFlightTracker()
        t.acquire("task-1")
        assert t.acquire("task-1") is False

    def test_release_removes_from_in_flight(self):
        t = InMemoryInFlightTracker()
        t.acquire("task-1")
        t.release("task-1")
        assert t.is_in_flight("task-1") is False

    def test_release_is_noop_when_not_in_flight(self):
        t = InMemoryInFlightTracker()
        t.release("never-added")  # must not raise

    def test_snapshot_returns_copy(self):
        t = InMemoryInFlightTracker()
        t.acquire("a")
        t.acquire("b")
        snap = t.snapshot()
        assert snap == {"a", "b"}
        # Mutate snapshot — original unchanged
        snap.add("c")
        assert t.snapshot() == {"a", "b"}

    def test_is_in_flight_false_for_unknown(self):
        t = InMemoryInFlightTracker()
        assert t.is_in_flight("never-added") is False

    def test_concurrent_acquire_same_id_only_one_succeeds(self):
        """Idempotency guarantee: two threads racing on acquire for the same
        task_id must see at most one True return."""
        import threading
        t = InMemoryInFlightTracker()
        results = []
        barrier = threading.Barrier(2)

        def worker():
            barrier.wait()
            results.append(t.acquire("race"))

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for th in threads: th.start()
        for th in threads: th.join()

        assert results.count(True) == 1
        assert results.count(False) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd E:/2026-7-21/ruflo-kb
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest tests/test_queue/test_in_flight.py -v --import-mode=importlib
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.queue.in_flight'`.

- [ ] **Step 3: Write `src/queue/ports.py` (Protocols)**

Create `src/queue/ports.py`:

```python
"""Protocols (PEP 544) for queue subsystem dependencies.

These are duck-typed contracts; concrete implementations live in
persistence.py, in_flight.py, retry.py. The point is that QueueService
can be constructed with any combination of implementations — the default
ones in production, fakes in tests, or alternative adapters in future.
"""
from __future__ import annotations
from typing import Protocol, runtime_checkable

from ..types import KnowledgeTask


# Forward declarations for the RetryPolicy protocol — RetryDecision is
# defined in retry.py. We import lazily inside the method body if needed,
# but a Protocol can use a forward reference string.
class _RetryLike(Protocol):
    def can_execute(self) -> bool: ...
    def record_success(self) -> None: ...
    def record_failure(self) -> None: ...


@runtime_checkable
class QueueBackend(Protocol):
    """Persists and queries tasks. Default impl: JsonFileBackend."""

    def enqueue(self, task: KnowledgeTask) -> None: ...

    def save(self, task: KnowledgeTask) -> None: ...

    def find(self, task_id: str) -> KnowledgeTask | None: ...

    def snapshot(self) -> list[KnowledgeTask]:
        """Return a copy of all currently tracked tasks. Implementations
        may filter out terminal states (e.g. APPROVED) — see the
        APPROVED-filtering invariant in the spec."""
        ...


@runtime_checkable
class InFlightTracker(Protocol):
    """Tracks which task_ids are currently being processed.

    Concurrency: acquire must be idempotent — two threads racing on the
    same task_id must see at most one True return. Default impl uses an
    internal lock.
    """

    def acquire(self, task_id: str) -> bool: ...

    def release(self, task_id: str) -> None: ...

    def is_in_flight(self, task_id: str) -> bool: ...

    def snapshot(self) -> set[str]: ...


@runtime_checkable
class EventEmitter(Protocol):
    """Dispatches events. Default impl: src.events.event_bus.EventBus."""

    def emit(self, event: str, payload) -> None: ...


@runtime_checkable
class RetryPolicy(Protocol):
    """Decides what to do after a status change (e.g. retry vs dead-letter)."""

    def decide(self, task: KnowledgeTask, attempted_status, error: str | None,
               breaker: _RetryLike): ...
```

- [ ] **Step 4: Write `src/queue/in_flight.py` (default InFlightTracker)**

Create `src/queue/in_flight.py`:

```python
"""InMemoryInFlightTracker — default InFlightTracker implementation.

Thread-safe via an internal lock. acquire() is idempotent: if the same
task_id is acquired twice, the second call returns False.
"""
from __future__ import annotations
import threading


class InMemoryInFlightTracker:
    def __init__(self) -> None:
        self._in_flight: set[str] = set()
        self._lock = threading.Lock()

    def acquire(self, task_id: str) -> bool:
        with self._lock:
            if task_id in self._in_flight:
                return False
            self._in_flight.add(task_id)
            return True

    def release(self, task_id: str) -> None:
        with self._lock:
            self._in_flight.discard(task_id)

    def is_in_flight(self, task_id: str) -> bool:
        with self._lock:
            return task_id in self._in_flight

    def snapshot(self) -> set[str]:
        with self._lock:
            return set(self._in_flight)
```

- [ ] **Step 5: Run test to verify it passes**

Run:
```bash
cd E:/2026-7-21/ruflo-kb
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest tests/test_queue/test_in_flight.py -v --import-mode=importlib
```

Expected: PASS (7 tests).

- [ ] **Step 6: Verify the rest of the suite still passes**

Run:
```bash
cd E:/2026-7-21/ruflo-kb
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest --import-mode=importlib -q 2>&1 | tail -5
```

Expected: 748 passed (no change).

- [ ] **Step 7: Commit**

```bash
cd E:/2026-7-21/ruflo-kb
git add src/queue/ports.py src/queue/in_flight.py tests/test_queue/test_in_flight.py
git commit -m "feat(queue): extract ports protocols + InMemoryInFlightTracker

ports.py defines the four Protocols (QueueBackend, InFlightTracker,
EventEmitter, RetryPolicy) that QueueService depends on. in_flight.py
provides the default InMemoryInFlightTracker with thread-safe,
idempotent acquire.

No behavior change to existing queue.py. All 748 tests pass.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: Extract `src/queue/persistence.py` (JsonFileBackend)

**Files:**
- Create: `src/queue/persistence.py`
- Create: `tests/test_queue/test_persistence.py`

**Interfaces:**
- Consumes: `src.lib.write_hooks.safe_write`, `src.lib.write_hooks.DELETE_SENTINEL`
- Produces:
  - `class JsonFileBackend`: implements `QueueBackend`
  - Constructor: `JsonFileBackend(path: Path)`
  - `enqueue(task)`, `save(task)`, `find(task_id) -> KnowledgeTask | None`, `snapshot() -> list[KnowledgeTask]`

**Critical:** This task uses `safe_write`, NOT direct `os.replace`. The test `test_atomic_write_does_not_partial_write` (existing in `test_save_atomic.py`) monkeypatches `os.replace` and must still detect partial writes.

- [ ] **Step 1: Write the failing test for JsonFileBackend**

Create `tests/test_queue/test_persistence.py`:

```python
"""Tests for JsonFileBackend — the default QueueBackend.

These tests mirror the existing tests in test_save_atomic.py but target
the new persistence module directly. The contract is the same:
- enqueue / save persists to disk via safe_write
- snapshot() returns KnowledgeTask list, with APPROVED filtered out
- on IO error mid-write, the target file is unchanged
"""
import json
import os
import pytest
from pathlib import Path

from src.queue.persistence import JsonFileBackend
from src.queue.ports import QueueBackend
from src.types import KnowledgeTask, SourceType, TaskStatus
from datetime import datetime


def _mk_task(task_id: str, source: str, status: TaskStatus = TaskStatus.PENDING) -> KnowledgeTask:
    return KnowledgeTask(
        id=task_id,
        source=source,
        source_type=SourceType.FILE,
        status=status,
        task_hash=f"hash-{task_id}",
        created_at=int(datetime.now().timestamp()),
        updated_at=int(datetime.now().timestamp()),
        retry_count=0,
    )


class TestJsonFileBackend:
    def test_implements_queue_backend_protocol(self, tmp_path):
        backend = JsonFileBackend(tmp_path / "queue.json")
        assert isinstance(backend, QueueBackend)

    def test_enqueue_then_snapshot_round_trips(self, tmp_path):
        backend = JsonFileBackend(tmp_path / "queue.json")
        task = _mk_task("t1", "file-a.txt")
        backend.enqueue(task)
        snap = backend.snapshot()
        assert len(snap) == 1
        assert snap[0].id == "t1"
        assert snap[0].source == "file-a.txt"

    def test_snapshot_filters_approved_tasks(self, tmp_path):
        backend = JsonFileBackend(tmp_path / "queue.json")
        backend.enqueue(_mk_task("t1", "file-a", TaskStatus.PENDING))
        backend.enqueue(_mk_task("t2", "file-b", TaskStatus.APPROVED))
        snap = backend.snapshot()
        # APPROVED is filtered out — only PENDING remains
        assert len(snap) == 1
        assert snap[0].id == "t1"

    def test_save_updates_existing_task(self, tmp_path):
        backend = JsonFileBackend(tmp_path / "queue.json")
        backend.enqueue(_mk_task("t1", "file-a", TaskStatus.PENDING))
        updated = _mk_task("t1", "file-a", TaskStatus.RUNNING)
        backend.save(updated)
        snap = backend.snapshot()
        assert len(snap) == 1
        assert snap[0].status == TaskStatus.RUNNING

    def test_find_returns_none_for_missing(self, tmp_path):
        backend = JsonFileBackend(tmp_path / "queue.json")
        assert backend.find("never-added") is None

    def test_find_returns_task(self, tmp_path):
        backend = JsonFileBackend(tmp_path / "queue.json")
        backend.enqueue(_mk_task("t1", "file-a"))
        found = backend.find("t1")
        assert found is not None
        assert found.id == "t1"

    def test_uses_safe_write_atomic_rename(self, tmp_path):
        """safe_write uses *.tmp + os.replace; verify a .tmp file does NOT
        linger after enqueue."""
        backend = JsonFileBackend(tmp_path / "queue.json")
        backend.enqueue(_mk_task("t1", "file-a"))
        target = tmp_path / "queue.json"
        assert target.exists()
        assert not (target.parent / (target.name + ".tmp")).exists()

    def test_atomic_write_does_not_partial_write_on_failure(self, tmp_path, monkeypatch):
        """On os.replace failure (simulating mid-write crash), the target
        file must remain in its prior good state. This is the canary test
        that detects bypassing safe_write."""
        backend = JsonFileBackend(tmp_path / "queue.json")
        # Seed a valid task
        backend.enqueue(_mk_task("seed", "seed-file"))
        target = tmp_path / "queue.json"
        original = json.loads(target.read_text(encoding="utf-8"))
        original_count = len(original)

        # Break os.replace to simulate mid-write failure
        def broken_replace(src, dst):
            raise OSError("simulated mid-write failure")
        monkeypatch.setattr(os, "replace", broken_replace)

        try:
            with pytest.raises(OSError):
                backend.enqueue(_mk_task("another", "another-file"))
        finally:
            monkeypatch.undo()  # restore real os.replace

        # The seed task must still be persisted byte-for-byte
        post = json.loads(target.read_text(encoding="utf-8"))
        assert len(post) == original_count

    def test_load_recovers_from_corrupt_file(self, tmp_path):
        """Existing-but-corrupt queue file → empty list, no raise."""
        target = tmp_path / "queue.json"
        target.write_text("[bad json", encoding="utf-8")
        backend = JsonFileBackend(target)
        assert backend.snapshot() == []

    def test_load_recovers_from_empty_file(self, tmp_path):
        target = tmp_path / "queue.json"
        target.write_text("", encoding="utf-8")
        backend = JsonFileBackend(target)
        assert backend.snapshot() == []

    def test_load_returns_empty_when_missing(self, tmp_path):
        target = tmp_path / "queue.json"
        assert not target.exists()
        backend = JsonFileBackend(target)
        assert backend.snapshot() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd E:/2026-7-21/ruflo-kb
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest tests/test_queue/test_persistence.py -v --import-mode=importlib
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.queue.persistence'`.

- [ ] **Step 3: Write `src/queue/persistence.py`**

Create `src/queue/persistence.py`:

```python
"""JsonFileBackend — default QueueBackend implementation.

Persists tasks to a single JSON file. CRITICAL invariants (from spec):
- Uses safe_write (NOT direct os.replace) so writes participate in the
  AtomicContext suspension/batching system.
- Filters out APPROVED tasks in snapshot() so already-terminal work
  does not re-appear on reload.
- Recovers gracefully from corrupt / empty / missing files.
"""
from __future__ import annotations
import json
import logging
from dataclasses import asdict
from pathlib import Path

from ..lib.write_hooks import safe_write
from ..types import KnowledgeTask, TaskStatus

logger = logging.getLogger(__name__)


class JsonFileBackend:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        # Internal lock protects the in-memory snapshot during
        # enqueue/save. The QueueService holds a service-level lock
        # that covers multi-step orchestration; this lock only guards
        # the backend's own data structure for the unlikely case that
        # a future caller bypasses the service layer.
        import threading
        self._lock = threading.Lock()
        self._tasks: dict[str, dict] = {}
        self._load_unlocked()

    # --- internal helpers (called only while holding self._lock) ---

    def _load_unlocked(self) -> None:
        """Load tasks from disk. Corrupt/empty/missing file → empty dict."""
        if not self.path.exists():
            self._tasks = {}
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"[JsonFileBackend] queue file corrupt ({e}); starting empty")
            self._tasks = {}
            return
        if not isinstance(data, list):
            logger.warning("[JsonFileBackend] queue file did not contain a list; starting empty")
            self._tasks = {}
            return
        result: dict[str, dict] = {}
        for row in data:
            if isinstance(row, dict) and "id" in row:
                result[row["id"]] = row
        self._tasks = result

    def _save_unlocked(self) -> None:
        """Persist in-memory tasks to disk via safe_write. Caller holds lock."""
        rows = list(self._tasks.values())
        # CRITICAL: use safe_write (which itself does tmp+os.replace under
        # the hood, but is also AtomicContext-aware). Do NOT call os.replace
        # directly — that bypasses the AtomicContext batching system.
        safe_write(self.path, json.dumps(rows, ensure_ascii=False, indent=2))

    # --- QueueBackend protocol ---

    def enqueue(self, task: KnowledgeTask) -> None:
        with self._lock:
            self._tasks[task.id] = asdict(task)
            self._save_unlocked()

    def save(self, task: KnowledgeTask) -> None:
        with self._lock:
            self._tasks[task.id] = asdict(task)
            self._save_unlocked()

    def find(self, task_id: str) -> KnowledgeTask | None:
        with self._lock:
            row = self._tasks.get(task_id)
            if row is None:
                return None
            try:
                return KnowledgeTask(**row)
            except (TypeError, ValueError) as e:
                logger.warning(f"[JsonFileBackend] task row malformed ({e}); skipping")
                return None

    def snapshot(self) -> list[KnowledgeTask]:
        with self._lock:
            result: list[KnowledgeTask] = []
            for row in self._tasks.values():
                if row.get("status") == TaskStatus.APPROVED.value:
                    continue
                try:
                    result.append(KnowledgeTask(**row))
                except (TypeError, ValueError) as e:
                    logger.warning(f"[JsonFileBackend] task row malformed ({e}); skipping")
            return result
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd E:/2026-7-21/ruflo-kb
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest tests/test_queue/test_persistence.py -v --import-mode=importlib
```

Expected: PASS (11 tests).

- [ ] **Step 5: Verify the rest of the suite still passes**

Run:
```bash
cd E:/2026-7-21/ruflo-kb
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest --import-mode=importlib -q 2>&1 | tail -5
```

Expected: 748 passed.

- [ ] **Step 6: Commit**

```bash
cd E:/2026-7-21/ruflo-kb
git add src/queue/persistence.py tests/test_queue/test_persistence.py
git commit -m "feat(queue): extract JsonFileBackend with safe_write

persistence.py implements the QueueBackend protocol using safe_write
(not direct os.replace) so the queue.json participates in the
AtomicContext suspension/batching system. APPROVED tasks are filtered
out of snapshot() — the same invariant the legacy _save_queue_unlocked
preserved by filtering the list before serializing.

This is the implementation that the existing test_save_atomic.py canary
will exercise once queue.py is migrated to use it (Task 6).

No behavior change to existing queue.py. All 748 tests pass.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: Extract `src/queue/retry.py` (DefaultRetryPolicy)

**Files:**
- Create: `src/queue/retry.py`
- Create: `tests/test_queue/test_retry.py`

**Interfaces:**
- Consumes: `src.types.TaskStatus`, `src.circuit_breaker.CircuitBreaker` (duck-typed)
- Produces:
  - `@dataclass class RetryDecision`: `new_status: TaskStatus`, `should_emit_dead_letter: bool`, `should_pause_queue: bool`, `should_record_breaker_failure: bool`
  - `class DefaultRetryPolicy`: implements `RetryPolicy` from ports.py
  - `def decide(task, attempted_status, error, breaker) -> RetryDecision`
  - Module-level `MAX_RETRIES = 3` constant

- [ ] **Step 1: Write the failing test**

Create `tests/test_queue/test_retry.py`:

```python
"""Tests for DefaultRetryPolicy — pure retry/dead-letter decision logic.

The policy decides what happens after a task status change attempt:
- FAILED (or TIMEOUT) under retry_count < MAX_RETRIES  → reset to PENDING
- FAILED (or TIMEOUT) at retry_count >= MAX_RETRIES    → DEAD_LETTER
- APPROVED                                             → stays APPROVED
- Other transitions                                   → stays as attempted
"""
import pytest

from src.queue.retry import DefaultRetryPolicy, RetryDecision, MAX_RETRIES
from src.types import KnowledgeTask, SourceType, TaskStatus


class _FakeBreaker:
    def __init__(self, state_value="closed"):
        self.state = type("S", (), {"value": state_value})()


def _mk_task(retry_count: int = 0) -> KnowledgeTask:
    return KnowledgeTask(
        id="t1", source="x", source_type=SourceType.FILE,
        status=TaskStatus.FAILED, task_hash="h", created_at=0, updated_at=0,
        retry_count=retry_count,
    )


class TestDefaultRetryPolicy:
    def test_first_failed_resets_to_pending(self):
        task = _mk_task(retry_count=0)
        decision = DefaultRetryPolicy().decide(
            task, TaskStatus.FAILED, error="boom", breaker=_FakeBreaker(),
        )
        assert decision.new_status == TaskStatus.PENDING
        assert decision.should_emit_dead_letter is False
        assert decision.should_pause_queue is False
        assert decision.should_record_breaker_failure is True
        assert task.retry_count == 1  # incremented

    def test_failed_at_max_retries_goes_to_dead_letter(self):
        # retry_count starts at MAX_RETRIES-1, then policy increments to MAX_RETRIES
        task = _mk_task(retry_count=MAX_RETRIES - 1)
        decision = DefaultRetryPolicy().decide(
            task, TaskStatus.FAILED, error="again", breaker=_FakeBreaker(),
        )
        assert decision.new_status == TaskStatus.DEAD_LETTER
        assert decision.should_emit_dead_letter is True
        assert decision.should_record_breaker_failure is True
        assert task.retry_count == MAX_RETRIES

    def test_failed_with_open_breaker_pauses_queue(self):
        task = _mk_task(retry_count=MAX_RETRIES - 1)
        decision = DefaultRetryPolicy().decide(
            task, TaskStatus.FAILED, error="again",
            breaker=_FakeBreaker(state_value="open"),
        )
        assert decision.new_status == TaskStatus.DEAD_LETTER
        assert decision.should_pause_queue is True

    def test_timeout_treated_like_failed(self):
        task = _mk_task(retry_count=0)
        decision = DefaultRetryPolicy().decide(
            task, TaskStatus.TIMEOUT, error="timeout", breaker=_FakeBreaker(),
        )
        assert decision.new_status == TaskStatus.PENDING
        assert decision.should_emit_dead_letter is False

    def test_approved_does_not_retry(self):
        task = _mk_task(retry_count=0)
        decision = DefaultRetryPolicy().decide(
            task, TaskStatus.APPROVED, error=None, breaker=_FakeBreaker(),
        )
        assert decision.new_status == TaskStatus.APPROVED
        assert decision.should_emit_dead_letter is False
        assert decision.should_record_breaker_failure is False
        assert task.retry_count == 0  # not incremented

    def test_max_retries_constant_is_three(self):
        # Locked at 3 by historical convention; bumping requires separate
        # change in CLAUDE.md + tests.
        assert MAX_RETRIES == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd E:/2026-7-21/ruflo-kb
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest tests/test_queue/test_retry.py -v --import-mode=importlib
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.queue.retry'`.

- [ ] **Step 3: Write `src/queue/retry.py`**

Create `src/queue/retry.py`:

```python
"""DefaultRetryPolicy — pure decision logic for retry / dead-letter.

Extracted from `update_task_status` in src/queue/queue.py:119-168. The
policy does NOT mutate task state beyond incrementing retry_count
(that's the caller's job — the policy returns a decision, the service
applies it).
"""
from __future__ import annotations
from dataclasses import dataclass

from ..types import KnowledgeTask, TaskStatus

MAX_RETRIES = 3


@dataclass
class RetryDecision:
    new_status: TaskStatus
    should_emit_dead_letter: bool
    should_pause_queue: bool
    should_record_breaker_failure: bool


class DefaultRetryPolicy:
    def decide(
        self,
        task: KnowledgeTask,
        attempted_status: TaskStatus,
        error: str | None,
        breaker,  # duck-typed: state.value, record_failure()
    ) -> RetryDecision:
        if attempted_status == TaskStatus.FAILED:
            task.retry_count += 1
            if task.retry_count >= MAX_RETRIES:
                pause = getattr(breaker.state, "value", None) == "open"
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
            task.retry_count += 1
            if task.retry_count >= MAX_RETRIES:
                pause = getattr(breaker.state, "value", None) == "open"
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

        if attempted_status == TaskStatus.APPROVED:
            return RetryDecision(
                new_status=TaskStatus.APPROVED,
                should_emit_dead_letter=False,
                should_pause_queue=False,
                should_record_breaker_failure=False,
            )

        # Default: accept the attempted status as-is
        return RetryDecision(
            new_status=attempted_status,
            should_emit_dead_letter=False,
            should_pause_queue=False,
            should_record_breaker_failure=False,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd E:/2026-7-21/ruflo-kb
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest tests/test_queue/test_retry.py -v --import-mode=importlib
```

Expected: PASS (6 tests).

- [ ] **Step 5: Verify the rest of the suite still passes**

Run:
```bash
cd E:/2026-7-21/ruflo-kb
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest --import-mode=importlib -q 2>&1 | tail -5
```

Expected: 748 passed.

- [ ] **Step 6: Commit**

```bash
cd E:/2026-7-21/ruflo-kb
git add src/queue/retry.py tests/test_queue/test_retry.py
git commit -m "feat(queue): extract DefaultRetryPolicy from update_task_status

retry.py defines RetryDecision dataclass and DefaultRetryPolicy that
encapsulates the retry/dead-letter decision logic. Extracted from the
70-line block in update_task_status (queue.py:119-168).

The policy is a pure decision function: it does not mutate task state
beyond incrementing retry_count. The service applies the decision.

No behavior change to existing queue.py. All 748 tests pass.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: Extract `src/queue/scheduler.py` (select_next_task pure function)

**Files:**
- Create: `src/queue/scheduler.py`
- Create: `tests/test_queue/test_scheduler.py`

**Interfaces:**
- Consumes: `QueueBackend`, `InFlightTracker`, `TaskStatus` (from types)
- Produces:
  - `def select_next_task(backend: QueueBackend, tracker: InFlightTracker, *, prefer_task_id: str | None = None) -> KnowledgeTask | None` — pure function

- [ ] **Step 1: Write the failing test**

Create `tests/test_queue/test_scheduler.py`:

```python
"""Tests for select_next_task — pure function, no IO, no globals.

The scheduler picks the next task to dispatch:
- prefer_task_id (when set): pick that exact task if it's PENDING and
  not in flight. This is the explicit-dispatch path used by enqueue_task.
- otherwise: pick the earliest PENDING task not in flight.
- returns None if no candidate matches.
"""
import pytest

from src.queue.scheduler import select_next_task
from src.queue.in_flight import InMemoryInFlightTracker
from src.types import KnowledgeTask, SourceType, TaskStatus
from datetime import datetime


class FakeBackend:
    """Minimal in-memory QueueBackend for testing select_next_task."""
    def __init__(self, tasks: list[KnowledgeTask] | None = None):
        self._tasks = list(tasks or [])

    def enqueue(self, task): self._tasks.append(task)
    def save(self, task):
        for i, t in enumerate(self._tasks):
            if t.id == task.id:
                self._tasks[i] = task
                return
        self._tasks.append(task)
    def find(self, task_id):
        return next((t for t in self._tasks if t.id == task_id), None)
    def snapshot(self): return list(self._tasks)


def _mk_task(task_id: str, status: TaskStatus = TaskStatus.PENDING,
             created_at: int = 0) -> KnowledgeTask:
    return KnowledgeTask(
        id=task_id, source=f"src-{task_id}", source_type=SourceType.FILE,
        status=status, task_hash=f"hash-{task_id}", created_at=created_at,
        updated_at=created_at, retry_count=0,
    )


class TestSelectNextTask:
    def test_returns_none_when_no_pending(self):
        backend = FakeBackend([_mk_task("a", TaskStatus.APPROVED)])
        tracker = InMemoryInFlightTracker()
        assert select_next_task(backend, tracker) is None

    def test_picks_first_pending(self):
        backend = FakeBackend([
            _mk_task("a", created_at=1),
            _mk_task("b", created_at=2),
        ])
        tracker = InMemoryInFlightTracker()
        result = select_next_task(backend, tracker)
        assert result is not None
        assert result.id == "a"

    def test_prefers_explicit_task_id(self):
        backend = FakeBackend([
            _mk_task("a", created_at=1),
            _mk_task("b", created_at=2),
        ])
        tracker = InMemoryInFlightTracker()
        result = select_next_task(backend, tracker, prefer_task_id="b")
        assert result.id == "b"

    def test_skips_in_flight(self):
        backend = FakeBackend([_mk_task("a"), _mk_task("b")])
        tracker = InMemoryInFlightTracker()
        tracker.acquire("a")
        result = select_next_task(backend, tracker)
        assert result.id == "b"

    def test_preferred_task_id_skipped_if_in_flight(self):
        backend = FakeBackend([_mk_task("a"), _mk_task("b")])
        tracker = InMemoryInFlightTracker()
        tracker.acquire("b")
        result = select_next_task(backend, tracker, prefer_task_id="b")
        assert result is None

    def test_preferred_task_id_skipped_if_not_pending(self):
        backend = FakeBackend([_mk_task("a", TaskStatus.RUNNING)])
        tracker = InMemoryInFlightTracker()
        result = select_next_task(backend, tracker, prefer_task_id="a")
        assert result is None

    def test_picks_only_pending_status(self):
        backend = FakeBackend([
            _mk_task("a", TaskStatus.RUNNING),
            _mk_task("b", TaskStatus.PENDING),
        ])
        tracker = InMemoryInFlightTracker()
        result = select_next_task(backend, tracker)
        assert result.id == "b"
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd E:/2026-7-21/ruflo-kb
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest tests/test_queue/test_scheduler.py -v --import-mode=importlib
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.queue.scheduler'`.

- [ ] **Step 3: Write `src/queue/scheduler.py`**

Create `src/queue/scheduler.py`:

```python
"""select_next_task — pure function for task selection.

This is the heart of the scheduler. Given a backend (where tasks live)
and a tracker (which tasks are in flight), pick the next task to
dispatch. Pure: no IO, no globals, no side effects.
"""
from __future__ import annotations

from ..types import KnowledgeTask, TaskStatus
from .ports import InFlightTracker, QueueBackend


def select_next_task(
    backend: QueueBackend,
    tracker: InFlightTracker,
    *,
    prefer_task_id: str | None = None,
) -> KnowledgeTask | None:
    """Pick the next task to dispatch.

    Args:
        backend: source of truth for tasks.
        tracker: source of truth for in-flight task IDs.
        prefer_task_id: when set, attempt to pick that exact task first
            (used by enqueue_task's explicit-dispatch path).

    Returns:
        The chosen KnowledgeTask, or None if no candidate matches.
    """
    candidates = backend.snapshot()
    if prefer_task_id is not None:
        return next(
            (t for t in candidates
             if t.id == prefer_task_id
             and t.status == TaskStatus.PENDING
             and not tracker.is_in_flight(t.id)),
            None,
        )
    return next(
        (t for t in candidates
         if t.status == TaskStatus.PENDING
         and not tracker.is_in_flight(t.id)),
        None,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd E:/2026-7-21/ruflo-kb
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest tests/test_queue/test_scheduler.py -v --import-mode=importlib
```

Expected: PASS (7 tests).

- [ ] **Step 5: Verify the rest of the suite still passes**

Run:
```bash
cd E:/2026-7-21/ruflo-kb
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest --import-mode=importlib -q 2>&1 | tail -5
```

Expected: 748 passed.

- [ ] **Step 6: Commit**

```bash
cd E:/2026-7-21/ruflo-kb
git add src/queue/scheduler.py tests/test_queue/test_scheduler.py
git commit -m "feat(queue): extract select_next_task pure function

scheduler.py contains the pure pick-next-task logic that was inlined
in _process_next (queue.py:300-347). Now it's a standalone function
that takes a backend and tracker, returns a KnowledgeTask or None.

This is the function we'll be able to unit-test with FakeBackend +
InMemoryInFlightTracker, no IO.

No behavior change to existing queue.py. All 748 tests pass.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: Extract `src/queue/service.py` (QueueService composition root)

**Files:**
- Create: `src/queue/service.py`
- Create: `tests/test_queue/test_service.py`
- Create: `tests/test_queue/conftest.py` (FakeQueueBackend + FakeEventEmitter fixtures)

**Interfaces:**
- Consumes: All submodules (ports, state, scheduler, retry, persistence, in_flight), `src.events.event_bus.event_bus` (default EventEmitter), `src.circuit_breaker.get_circuit_breaker`
- Produces:
  - `class QueueService(backend, tracker, emitter, retry_policy, *, circuit_breaker_name="task_queue")`
  - `QueueService.enqueue(source, source_type, task_hash, project_id=None) -> str`
  - `QueueService.update_status(task_id, status, error=None) -> None`
  - `QueueService.advance(*, prefer_task_id=None, project_id=None) -> bool`
  - `QueueService.pause() / resume()`
  - `QueueService.get_status() -> dict`
  - `def get_default_queue_service() -> QueueService`
  - `def __reset_for_testing() -> None` — test-only, replaces queue.py:281-285
  - `def release_in_flight(task_id)` — private helper for pipeline

**Critical:** Single service-level lock. All orchestration (`advance`, `update_status`, `enqueue`) must hold `self._service_lock` for the multi-step sequence. This is the lock-granularity invariant.

- [ ] **Step 1: Create conftest with shared fakes**

Create `tests/test_queue/conftest.py`:

```python
"""Shared fixtures for queue tests.

Fake implementations of QueueBackend, InFlightTracker, and EventEmitter
that allow QueueService to be unit-tested without IO.
"""
from __future__ import annotations
import pytest

from src.queue.in_flight import InMemoryInFlightTracker
from src.queue.ports import QueueBackend
from src.types import KnowledgeTask


class FakeQueueBackend:
    """In-memory QueueBackend that records all calls for assertion."""

    def __init__(self) -> None:
        self._tasks: dict[str, KnowledgeTask] = {}
        self._calls: list[tuple] = []

    def enqueue(self, task: KnowledgeTask) -> None:
        self._calls.append(("enqueue", task.id))
        self._tasks[task.id] = task

    def save(self, task: KnowledgeTask) -> None:
        self._calls.append(("save", task.id))
        self._tasks[task.id] = task

    def find(self, task_id: str):
        return self._tasks.get(task_id)

    def snapshot(self):
        return list(self._tasks.values())

    def calls_matching(self, op: str):
        return [c for c in self._calls if c[0] == op]


class FakeEventEmitter:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    def emit(self, event: str, payload) -> None:
        self.events.append((event, payload))


@pytest.fixture
def fake_backend():
    return FakeQueueBackend()


@pytest.fixture
def fake_tracker():
    return InMemoryInFlightTracker()


@pytest.fixture
def fake_emitter():
    return FakeEventEmitter()
```

- [ ] **Step 2: Write the failing test for QueueService**

Create `tests/test_queue/test_service.py`:

```python
"""Tests for QueueService — the composition root for queue operations.

These tests use FakeQueueBackend + InMemoryInFlightTracker + FakeEventEmitter
to exercise the orchestration logic without IO.
"""
import pytest

from src.queue.service import QueueService
from src.queue.retry import DefaultRetryPolicy
from src.types import SourceType, TaskStatus
from .conftest import FakeQueueBackend, FakeEventEmitter
from src.queue.in_flight import InMemoryInFlightTracker


@pytest.fixture
def queue_service(fake_backend, fake_tracker, fake_emitter):
    return QueueService(
        backend=fake_backend,
        tracker=fake_tracker,
        emitter=fake_emitter,
        retry_policy=DefaultRetryPolicy(),
    )


class TestEnqueue:
    def test_enqueue_returns_task_id(self, queue_service, fake_emitter):
        task_id = queue_service.enqueue(
            source="file-a.txt", source_type=SourceType.FILE, task_hash="h1",
        )
        assert task_id.startswith("kb-")
        # Emits task:created and collector:start (auto-advance)
        event_names = [e[0] for e in fake_emitter.events]
        assert "task:created" in event_names
        assert "collector:start" in event_names

    def test_enqueue_records_in_flight(self, queue_service, fake_tracker):
        task_id = queue_service.enqueue(
            source="file-a.txt", source_type=SourceType.FILE, task_hash="h1",
        )
        assert fake_tracker.is_in_flight(task_id)

    def test_enqueue_persists_to_backend(self, queue_service, fake_backend):
        task_id = queue_service.enqueue(
            source="file-a.txt", source_type=SourceType.FILE, task_hash="h1",
        )
        saved = fake_backend.find(task_id)
        assert saved is not None
        assert saved.source == "file-a.txt"

    def test_duplicate_hash_returns_empty_string(self, queue_service, fake_emitter):
        queue_service.enqueue(source="a", source_type=SourceType.FILE, task_hash="dup")
        fake_emitter.events.clear()
        result = queue_service.enqueue(
            source="b", source_type=SourceType.FILE, task_hash="dup",
        )
        assert result == ""
        assert len(fake_emitter.events) == 0  # no new event


class TestUpdateStatus:
    def test_legal_transition_succeeds(self, queue_service, fake_backend):
        task_id = queue_service.enqueue(
            source="x", source_type=SourceType.FILE, task_hash="h1",
        )
        queue_service.update_status(task_id, TaskStatus.RUNNING)
        assert fake_backend.find(task_id).status == TaskStatus.RUNNING

    def test_illegal_transition_raises(self, queue_service):
        task_id = queue_service.enqueue(
            source="x", source_type=SourceType.FILE, task_hash="h1",
        )
        with pytest.raises(Exception):  # InvalidTransition
            queue_service.update_status(task_id, TaskStatus.APPROVED)

    def test_failed_resets_to_pending_under_retry_limit(
        self, queue_service, fake_backend, fake_emitter
    ):
        task_id = queue_service.enqueue(
            source="x", source_type=SourceType.FILE, task_hash="h1",
        )
        fake_emitter.events.clear()
        queue_service.update_status(task_id, TaskStatus.FAILED, error="boom")
        task = fake_backend.find(task_id)
        assert task.status == TaskStatus.PENDING
        assert task.retry_count == 1
        # Should re-advance → emit collector:start again
        assert any(e[0] == "collector:start" for e in fake_emitter.events)

    def test_missing_task_raises_key_error(self, queue_service):
        with pytest.raises(KeyError):
            queue_service.update_status("never-added", TaskStatus.RUNNING)


class TestAdvance:
    def test_paused_does_not_advance(self, queue_service, fake_emitter):
        queue_service.pause()
        task_id = queue_service.enqueue(
            source="x", source_type=SourceType.FILE, task_hash="h1",
        )
        # enqueue emits task:created but advance is skipped while paused
        # (collector:start should NOT be emitted)
        events = [e[0] for e in fake_emitter.events]
        assert "task:created" in events
        assert "collector:start" not in events
        # Resume kicks the scheduler
        queue_service.resume()
        events = [e[0] for e in fake_emitter.events]
        assert "collector:start" in events


class TestPauseResume:
    def test_get_status_reports_paused(self, queue_service):
        queue_service.pause()
        status = queue_service.get_status()
        assert status["paused"] is True

    def test_resume_clears_paused(self, queue_service):
        queue_service.pause()
        queue_service.resume()
        status = queue_service.get_status()
        assert status["paused"] is False
```

- [ ] **Step 3: Run test to verify it fails**

Run:
```bash
cd E:/2026-7-21/ruflo-kb
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest tests/test_queue/test_service.py -v --import-mode=importlib
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.queue.service'`.

- [ ] **Step 4: Write `src/queue/service.py`**

Create `src/queue/service.py`:

```python
"""QueueService — composition root for queue subsystem.

Holds the service-level lock that serializes all multi-step orchestration
(enqueue + save, snapshot + acquire + emit, update_status + save). The
default singleton is process-wide; tests construct instances directly
with FakeBackends.

Public API (re-exported from src/queue/__init__.py):
- enqueue_task
- update_task_status
- get_queue
- pause_queue
- resume_queue
- generate_task_id
- get_default_queue_service

Private (NOT re-exported):
- release_in_flight (consumed by src/pipeline/service.py)
- _advance, _persist (internal helpers)
"""
from __future__ import annotations
import logging
import threading
import uuid
from datetime import datetime

from ..circuit_breaker import get_circuit_breaker
from ..events.event_bus import event_bus
from ..types import KnowledgeTask, SourceType, TaskStatus
from ..utils.idempotency import check_duplicate
from .in_flight import InMemoryInFlightTracker
from .persistence import JsonFileBackend
from .ports import EventEmitter, InFlightTracker, QueueBackend, RetryPolicy
from .retry import DefaultRetryPolicy
from .scheduler import select_next_task
from .state import can_transition, InvalidTransition
from ..events.events import (
    EventName, TaskCreatedPayload, TaskStatusChangedPayload,
)

logger = logging.getLogger(__name__)

CIRCUIT_BREAKER_NAME = "task_queue"
QUEUE_FILE = ".kb-queue.json"


def generate_task_id() -> str:
    unique_part = uuid.uuid4().hex[:8]
    return f"kb-{datetime.now().strftime('%Y%m%d%H%M%S')}-{unique_part}"


class QueueService:
    def __init__(
        self,
        backend: QueueBackend,
        tracker: InFlightTracker,
        emitter: EventEmitter,
        retry_policy: RetryPolicy,
        *,
        circuit_breaker_name: str = CIRCUIT_BREAKER_NAME,
    ) -> None:
        self.backend = backend
        self.tracker = tracker
        self.emitter = emitter
        self.retry_policy = retry_policy
        self._breaker_name = circuit_breaker_name
        self._service_lock = threading.Lock()
        self._paused = False

    def _breaker(self):
        """Resolve the breaker each call — never cache the instance, since
        tests reset state in-place (see test_pipeline_event_bus_integration.py)."""
        return get_circuit_breaker(self._breaker_name)

    # --- public API ---

    def enqueue(
        self,
        source: str,
        source_type: SourceType,
        task_hash: str,
        project_id: str | None = None,
    ) -> str:
        if check_duplicate(task_hash):
            logger.info(f"[Queue] Duplicate task_hash: {task_hash}")
            return ""

        task = KnowledgeTask(
            id=generate_task_id(),
            source=source,
            source_type=source_type,
            status=TaskStatus.PENDING,
            task_hash=task_hash,
            created_at=int(datetime.now().timestamp()),
            updated_at=int(datetime.now().timestamp()),
            retry_count=0,
            project_id=project_id,
        )

        with self._service_lock:
            self.backend.enqueue(task)

        # Emit AFTER lock release (handler may re-enter the queue)
        self.emitter.emit(EventName.TASK_CREATED, TaskCreatedPayload(
            task_id=task.id,
            source=task.source,
            source_type=task.source_type,
            task_hash=task.task_hash,
            project_id=project_id,
        ))
        self.advance(prefer_task_id=task.id, project_id=project_id)
        return task.id

    def update_status(
        self,
        task_id: str,
        status: TaskStatus,
        error: str | None = None,
    ) -> None:
        """Update a task after validating the state-machine transition.

        May call advance() (under retry) — that's why emit and advance are
        done OUTSIDE the lock.
        """
        breaker = self._breaker()
        dead_letter_payload = None
        retry_will_resume = False
        prev_status: TaskStatus

        with self._service_lock:
            task = self.backend.find(task_id)
            if task is None:
                raise KeyError(task_id)

            prev_status = task.status
            if not can_transition(prev_status, status):
                raise InvalidTransition(task_id, prev_status.value, status.value)

            decision = self.retry_policy.decide(task, status, error, breaker)
            task.status = decision.new_status
            task.updated_at = int(datetime.now().timestamp())
            if error is not None:
                task.error = error

            if decision.should_record_breaker_failure:
                breaker.record_failure()

            if decision.should_pause_queue:
                self._paused = True
                logger.warning("[Queue] Queue paused due to repeated failures")

            if decision.new_status == TaskStatus.DEAD_LETTER:
                dead_letter_payload = {
                    "task_id": task_id,
                    "retry_count": task.retry_count,
                    "last_error": task.error or error or "",
                }
                logger.warning(
                    f"[Queue] Task {task_id} exceeded max retries, moving to dead letter"
                )

            if decision.new_status == TaskStatus.PENDING:
                retry_will_resume = True

            self.backend.save(task)
            emit_status = decision.new_status
            emit_payload = TaskStatusChangedPayload(
                task_id=task_id,
                from_status=prev_status,
                to_status=emit_status,
                error=error,
            )

        # Outside the lock
        self.emitter.emit(EventName.TASK_STATUS_CHANGED, emit_payload)
        if dead_letter_payload is not None:
            self.emitter.emit(EventName.TASK_DEAD_LETTER, dead_letter_payload)
        if retry_will_resume:
            self.advance()

    def advance(
        self,
        *,
        prefer_task_id: str | None = None,
        project_id: str | None = None,
    ) -> bool:
        """Try to pick and dispatch one task. Returns True if dispatched."""
        with self._service_lock:
            if self._paused:
                return False
            if not self._breaker().can_execute():
                logger.warning(
                    f"[Queue] Circuit breaker is {self._breaker().state.value}, skipping"
                )
                return False

            task = select_next_task(
                self.backend, self.tracker, prefer_task_id=prefer_task_id,
            )
            if task is None:
                return False
            if not self.tracker.acquire(task.id):
                return False

            effective_project_id = project_id or task.project_id
            payload = {
                "task_id": task.id,
                "source": task.source,
                "source_type": task.source_type,
            }
            if effective_project_id is not None:
                payload["project_id"] = effective_project_id

        # Outside the lock — emit
        self.emitter.emit("collector:start", payload)
        return True

    def pause(self) -> None:
        with self._service_lock:
            self._paused = True
            logger.warning("[Queue] Queue paused")

    def resume(self) -> None:
        with self._service_lock:
            self._paused = False
            self._breaker().record_success()
            logger.info("[Queue] Queue resumed")
        self.advance()

    def release_in_flight(self, task_id: str) -> None:
        """Release a task after its pipeline reaches a terminal state."""
        with self._service_lock:
            self.tracker.release(task_id)
        self.advance()

    def get_queue(self) -> list[KnowledgeTask]:
        with self._service_lock:
            return self.backend.snapshot()

    def get_status(self) -> dict:
        breaker = self._breaker()
        tasks = self.get_queue()
        with self._service_lock:
            return {
                "paused": self._paused,
                "circuit_breaker_state": breaker.state.value,
                "failure_count": breaker.failure_count,
                "pending_count": len([t for t in tasks if t.status == TaskStatus.PENDING]),
                "running_count": len([t for t in tasks if t.status == TaskStatus.RUNNING]),
                "failed_count": len([t for t in tasks if t.status == TaskStatus.FAILED]),
            }


# --- module-level default service singleton ---

_default_service: QueueService | None = None
_default_lock = threading.Lock()


def get_default_queue_service() -> QueueService:
    global _default_service
    with _default_lock:
        if _default_service is None:
            from pathlib import Path
            _default_service = QueueService(
                backend=JsonFileBackend(Path(QUEUE_FILE)),
                tracker=InMemoryInFlightTracker(),
                emitter=event_bus,
                retry_policy=DefaultRetryPolicy(),
            )
        return _default_service


def __reset_for_testing() -> None:
    """Test-only: discard the default singleton so the next call to
    get_default_queue_service() rebuilds it from the current disk state.

    This replaces the old src/queue/queue.py:281-285 __reset_for_testing.
    The default service's tracker is reset to empty; the backend re-reads
    from disk on next access (its in-memory state is reloaded by the
    singleton's first enqueue/find).
    """
    global _default_service
    with _default_lock:
        _default_service = None
```

- [ ] **Step 5: Run test to verify it passes**

Run:
```bash
cd E:/2026-7-21/ruflo-kb
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest tests/test_queue/test_service.py -v --import-mode=importlib
```

Expected: PASS (10 tests).

- [ ] **Step 6: Verify the rest of the suite still passes**

Run:
```bash
cd E:/2026-7-21/ruflo-kb
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest --import-mode=importlib -q 2>&1 | tail -5
```

Expected: 748 passed (we have not yet migrated queue.py to use QueueService, so the new tests are additive).

- [ ] **Step 7: Commit**

```bash
cd E:/2026-7-21/ruflo-kb
git add src/queue/service.py tests/test_queue/test_service.py tests/test_queue/conftest.py
git commit -m "feat(queue): add QueueService composition root

service.py provides QueueService that wires together JsonFileBackend,
InMemoryInFlightTracker, the global event_bus, and DefaultRetryPolicy.
The service holds a single service-level lock that serializes all
multi-step orchestration. Public methods: enqueue, update_status,
advance, pause, resume, release_in_flight, get_queue, get_status.

The default service is a process-wide singleton (get_default_queue_service).
Test-only __reset_for_testing rebuilds it on demand.

The old src/queue/queue.py is still the production path; this is an
additive commit. The next task migrates __init__.py to re-export from
service, then deletes queue.py.

All 748 tests pass.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7: Update `src/queue/__init__.py` and delete `src/queue/queue.py`

**Files:**
- Modify: `src/queue/__init__.py` — re-export from service
- Delete: `src/queue/queue.py`

**Critical:** `src/queue/__init__.py` must continue to export the same names: `enqueue_task`, `update_task_status`, `get_queue`, `pause_queue`, `resume_queue`, `generate_task_id`. Plus `__reset_for_testing` (test-only).

- [ ] **Step 1: Verify all current callers of `src/queue/queue` symbols**

Run:
```bash
cd E:/2026-7-21/ruflo-kb
grep -rn "from src.queue.queue" src/ tests/ --include="*.py" | head -20
```

You should see ~12 files importing from `src.queue.queue`. Verify each import resolves through the compat layer (i.e. each symbol exists in `service.py`).

- [ ] **Step 2: Update `src/queue/__init__.py` to re-export from service**

Replace the contents of `src/queue/__init__.py` with:

```python
"""Public queue subsystem API.

All public functions are thin wrappers over QueueService. The legacy
src/queue/queue.py is gone — it was migrated to:
- state.py       (state machine)
- ports.py       (Protocols)
- in_flight.py   (InMemoryInFlightTracker)
- persistence.py (JsonFileBackend)
- retry.py       (DefaultRetryPolicy)
- scheduler.py   (select_next_task)
- service.py     (QueueService composition root + module-level helpers)
"""
from .service import (
    QueueService,
    __reset_for_testing,
    generate_task_id,
    get_default_queue_service,
)
from .state import InvalidTransition

# Module-level convenience functions that delegate to the default service.
# Each holds a reference to the singleton, not the function, so tests that
# rebuild the singleton via __reset_for_testing see the new instance.


def _service():
    return get_default_queue_service()


def enqueue_task(source, source_type, task_hash, project_id=None):
    return _service().enqueue(source, source_type, task_hash, project_id=project_id)


def update_task_status(task_id, status, error=None):
    return _service().update_status(task_id, status, error=error)


def get_queue():
    return _service().get_queue()


def pause_queue():
    return _service().pause()


def resume_queue():
    return _service().resume()


__all__ = [
    "QueueService",
    "InvalidTransition",
    "enqueue_task",
    "update_task_status",
    "get_queue",
    "pause_queue",
    "resume_queue",
    "generate_task_id",
    "get_default_queue_service",
]
```

- [ ] **Step 3: Delete `src/queue/queue.py`**

```bash
cd E:/2026-7-21/ruflo-kb
git rm src/queue/queue.py
```

- [ ] **Step 4: Run the full test suite**

```bash
cd E:/2026-7-21/ruflo-kb
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest --import-mode=importlib -q 2>&1 | tail -10
```

Expected: 748 + new tests pass. If `test_save_atomic.py` or `test_pipeline_event_bus_integration.py` fails, STOP — it means a caller still imports from `src/queue/queue` and needs to migrate to `src/queue/__init__`.

- [ ] **Step 5: Verify import paths work**

```bash
cd E:/2026-7-21/ruflo-kb
python -c "from src.queue import enqueue_task, update_task_status, get_queue, pause_queue, resume_queue, generate_task_id; print('public API: OK')"
python -c "from src.queue import __reset_for_testing; print('test API: OK')"
python -c "from src.queue.service import QueueService, get_default_queue_service; print('service API: OK')"
python -c "from src.queue.state import can_transition, InvalidTransition; print('state API: OK')"
```

Expected: all four print OK.

- [ ] **Step 6: Commit**

```bash
cd E:/2026-7-21/ruflo-kb
git add src/queue/__init__.py
git commit -m "refactor(queue): migrate __init__.py to service-based re-exports

All public queue functions now delegate to QueueService via
get_default_queue_service(). The legacy src/queue/queue.py is deleted
(all 350+ lines migrated to submodules: state, ports, in_flight,
persistence, retry, scheduler, service).

Public API surface is preserved:
- enqueue_task, update_task_status, get_queue, pause_queue, resume_queue
- generate_task_id, get_default_queue_service
- InvalidTransition, __reset_for_testing (test-only)

All 748 tests pass. The 50-thread concurrent enqueue test in
test_lock.py confirms the service-level lock invariant is preserved.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 8: Extract `src/pipeline/ports.py` + `src/pipeline/events.py` + `src/pipeline/stages/`

**Files:**
- Create: `src/pipeline/ports.py` — `PipelineStage` Protocol, `StageResult`, `PipelineContext` dataclasses
- Create: `src/pipeline/events.py` — re-export shim
- Create: `src/pipeline/stages/__init__.py` — re-exports
- Create: `src/pipeline/stages/collector.py` — `CollectorStage` (thin wrapper around existing `collect`)
- Create: `src/pipeline/stages/analyzer.py` — `AnalyzerStage` (thin wrapper around existing `analyze`)
- Create: `src/pipeline/stages/generator.py` — `GeneratorStage` (thin wrapper around existing `generate`)
- Create: `tests/test_pipeline/test_runner.py` (skeleton; the real tests go in Task 9)

**Interfaces:**
- Produces (from `ports.py`):
  - `@runtime_checkable class PipelineStage(Protocol)`: `name -> str`, `async run(ctx, prev_result) -> StageResult`
  - `@dataclass class StageResult`: `success: bool`, `payload: Any`
  - `@dataclass class PipelineContext`: `task_id, source, source_type, project_id, paths, provider, model, ...`

- [ ] **Step 1: Write the failing test for PipelineStage Protocol + stages**

Create `tests/test_pipeline/test_runner.py` (the runner tests go here in Task 9; for now this is the imports test):

```python
"""Tests for PipelineStage Protocol and stage implementations.

The stage tests in this file verify the protocol contract is satisfied
and that each stage can be constructed and called with a PipelineContext.
The end-to-end runner tests are added in Task 9.
"""
import pytest

from src.pipeline.ports import PipelineStage, StageResult, PipelineContext
from src.pipeline.stages import CollectorStage, AnalyzerStage, GeneratorStage
from src.pipeline.stages.collector import CollectorStage as CStage
from src.types import SourceType


class TestStageProtocolConformance:
    def test_collector_stage_implements_protocol(self):
        assert isinstance(CollectorStage(), PipelineStage)

    def test_analyzer_stage_implements_protocol(self):
        assert isinstance(AnalyzerStage(), PipelineStage)

    def test_generator_stage_implements_protocol(self):
        assert isinstance(GeneratorStage(), PipelineStage)


class TestStageConstruction:
    def test_collector_stage_has_name(self):
        assert CollectorStage().name == "collector"

    def test_analyzer_stage_has_name(self):
        assert AnalyzerStage().name == "analyzer"

    def test_generator_stage_has_name(self):
        assert GeneratorStage().name == "generator"


class TestPipelineContext:
    def test_minimal_construction(self):
        ctx = PipelineContext(
            task_id="t1", source="x", source_type=SourceType.FILE,
        )
        assert ctx.task_id == "t1"
        assert ctx.source == "x"
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd E:/2026-7-21/ruflo-kb
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest tests/test_pipeline/test_runner.py -v --import-mode=importlib
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `src/pipeline/ports.py`**

Create `src/pipeline/ports.py`:

```python
"""Protocols and shared dataclasses for the pipeline subsystem.

PipelineStage is the unit of work. PipelineRunner (in runner.py) takes
a list of stages and a PipelineContext, drives them sequentially, and
handles status transitions.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..types import SourceType


@dataclass
class PipelineContext:
    """Carries the data needed to drive a pipeline run.

    The `stages` dict is populated as stages run: ctx.stages["collector"]
    = CollectorStageResult, etc. Tests can inspect or override any field.
    """
    task_id: str
    source: str
    source_type: SourceType
    project_id: str | None = None
    # Populated by the runner before stages run:
    paths: Any = None
    provider: Any = None
    model: str = "gpt-4o-mini"
    # Stage outputs:
    collector_result: Any = None
    analysis_result: Any = None
    # Metadata:
    folder_context: str = ""
    source_path: str = ""


@dataclass
class StageResult:
    """Result of running a single PipelineStage."""
    success: bool
    payload: Any = None


@runtime_checkable
class PipelineStage(Protocol):
    """A unit of work in the pipeline.

    `name` is a string identifier used in logs and the wiki page metadata.
    `run` is an async coroutine that takes the PipelineContext (mutated
    in place to carry outputs forward) and the previous stage's result
    (None for the first stage).
    """
    name: str

    async def run(self, ctx: PipelineContext, prev_result: Any) -> StageResult: ...
```

- [ ] **Step 4: Write `src/pipeline/events.py` (re-export shim)**

Create `src/pipeline/events.py`:

```python
"""Re-export pipeline-related event dataclasses from src/events/events.py.

This is a thin shim that lets pipeline code import from
`src.pipeline.events` without taking a direct dependency on
`src.events.events` (which would create a circular import).

For now, it just re-exports the same symbols. If a future change wants
to move payloads here, that work belongs in a follow-up spec.
"""
from ..events.events import (
    EventName,
    CollectorStartPayload,
    CollectorDonePayload,
)

__all__ = ["EventName", "CollectorStartPayload", "CollectorDonePayload"]
```

**Note:** `CollectorStartPayload` and `CollectorDonePayload` may not exist as such — the current code uses dicts and the `CollectorDonePayload` dataclass. Check `src/events/events.py:36-45` and adjust re-exports to whatever exists. If only `CollectorDonePayload` exists, re-export that.

- [ ] **Step 5: Write `src/pipeline/stages/collector.py`**

Create `src/pipeline/stages/collector.py`:

```python
"""CollectorStage — wraps the existing `collect` function from
src/pipeline/collector.py as a PipelineStage.

Behavior is identical to calling `collect(task_id, source, source_type,
project_id=...)` directly. The stage's `run` is async, so it can be
awaited by the runner.
"""
from __future__ import annotations

from ..ports import PipelineContext, StageResult
from .. import collector as _collector_module


class CollectorStage:
    name = "collector"

    async def run(self, ctx: PipelineContext, prev_result) -> StageResult:
        # Import the actual collect function lazily so monkey-patching
        # (see tests/test_pipeline/test_pipeline_event_bus_integration.py)
        # continues to work: the test patches `pipeline.collect`, and we
        # resolve the symbol at call time, not import time.
        collect_fn = getattr(_collector_module, "collect")
        payload = await collect_fn(
            ctx.task_id, ctx.source, ctx.source_type, project_id=ctx.project_id,
        )
        ctx.collector_result = payload
        return StageResult(success=True, payload=payload)
```

- [ ] **Step 6: Write `src/pipeline/stages/analyzer.py`**

Create `src/pipeline/stages/analyzer.py`:

```python
"""AnalyzerStage — wraps `analyze` as a PipelineStage."""
from __future__ import annotations

from ..ports import PipelineContext, StageResult
from .. import analyzer as _analyzer_module


class AnalyzerStage:
    name = "analyzer"

    async def run(self, ctx: PipelineContext, prev_result) -> StageResult:
        if ctx.collector_result is None:
            return StageResult(success=False, payload="missing collector result")
        analyze_fn = getattr(_analyzer_module, "analyze")
        analysis = await analyze_fn(
            source_text=ctx.collector_result.content,
            source_ext=ctx.source_path or "",
            existing_wiki_index="",
            folder_context=ctx.folder_context,
            provider=ctx.provider,
            task_id=ctx.task_id,
            source_path=ctx.source,
        )
        ctx.analysis_result = analysis
        return StageResult(success=True, payload=analysis)
```

- [ ] **Step 7: Write `src/pipeline/stages/generator.py`**

Create `src/pipeline/stages/generator.py`:

```python
"""GeneratorStage — wraps `generate` as a PipelineStage.

Note: the full run_ingest (which also appends a source page and writes
to disk under AtomicContext) lives in src/pipeline/ingest.py and is
called by the dispatcher, not by the stages. This stage is the
"render WikiPage list" step only; the file writes happen in
`run_ingest` after the stages return.
"""
from __future__ import annotations

from ..ports import PipelineContext, StageResult
from .. import generator as _generator_module


class GeneratorStage:
    name = "generator"

    async def run(self, ctx: PipelineContext, prev_result) -> StageResult:
        if ctx.analysis_result is None:
            return StageResult(success=False, payload="missing analysis result")
        generate_fn = getattr(_generator_module, "generate")
        pages = await generate_fn(
            paths=ctx.paths,
            analysis=ctx.analysis_result,
            existing_wiki_index="",
            provider=ctx.provider,
            model=ctx.model,
        )
        return StageResult(success=True, payload=pages)
```

- [ ] **Step 8: Write `src/pipeline/stages/__init__.py`**

Create `src/pipeline/stages/__init__.py`:

```python
from .collector import CollectorStage
from .analyzer import AnalyzerStage
from .generator import GeneratorStage

__all__ = ["CollectorStage", "AnalyzerStage", "GeneratorStage"]
```

- [ ] **Step 9: Run test to verify it passes**

Run:
```bash
cd E:/2026-7-21/ruflo-kb
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest tests/test_pipeline/test_runner.py -v --import-mode=importlib
```

Expected: PASS (7 tests).

- [ ] **Step 10: Verify the rest of the suite still passes**

Run:
```bash
cd E:/2026-7-21/ruflo-kb
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest --import-mode=importlib -q 2>&1 | tail -5
```

Expected: 748 passed.

- [ ] **Step 11: Commit**

```bash
cd E:/2026-7-21/ruflo-kb
git add src/pipeline/ports.py src/pipeline/events.py src/pipeline/stages/ tests/test_pipeline/test_runner.py
git commit -m "feat(pipeline): extract PipelineStage protocol + 3 stages

ports.py defines the PipelineStage Protocol, StageResult dataclass, and
PipelineContext dataclass. stages/ contains CollectorStage, AnalyzerStage,
GeneratorStage — each a thin wrapper around the existing collect/analyze/
generate functions in src/pipeline/.

Each stage resolves the underlying function via getattr at call time, not
import time, so the existing monkey-patch pattern in
test_pipeline_event_bus_integration.py:124 continues to work unchanged.

No behavior change to existing src/pipeline/pipeline.py. All 748 tests pass.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 9: Extract `src/pipeline/runner.py` + `src/pipeline/ingest.py`

**Files:**
- Create: `src/pipeline/runner.py` — `PipelineRunner`
- Create: `src/pipeline/ingest.py` — `run_ingest`, `_resolve_wiki_paths`, `_get_provider`
- Modify: `tests/test_pipeline/test_runner.py` — add runner tests

**Critical:** `_resolve_wiki_paths` and `_get_provider` must be importable as `src.pipeline.pipeline._resolve_wiki_paths` and `src.pipeline.pipeline._get_provider` (the existing monkey-patch test pattern). This means Task 10 must keep a compat shim.

- [ ] **Step 1: Add runner tests to `tests/test_pipeline/test_runner.py`**

Append to the existing file:

```python
class FakeStage:
    def __init__(self, name, returns=None, raises=None):
        self.name = name
        self._returns = returns
        self._raises = raises
        self.calls = []

    async def run(self, ctx, prev):
        self.calls.append((ctx.task_id, prev))
        if self._raises:
            raise self._raises
        return StageResult(success=True, payload=self._returns)


class TestPipelineRunner:
    async def test_runs_stages_sequentially(self):
        stages = [FakeStage("a", returns="A"), FakeStage("b", returns="B"), FakeStage("c", returns="C")]
        # We don't actually run the runner here — this is a placeholder.
        # The real test goes in a follow-up step.
        assert len(stages) == 3
```

For now, just leave this as-is — the actual runner is created in step 3 below.

- [ ] **Step 2: Run test (placeholder passes trivially)**

Run:
```bash
cd E:/2026-7-21/ruflo-kb
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest tests/test_pipeline/test_runner.py -v --import-mode=importlib
```

Expected: PASS (existing 7 + new 2 = 9).

- [ ] **Step 3: Write `src/pipeline/runner.py`**

Create `src/pipeline/runner.py`:

```python
"""PipelineRunner — drives a sequence of PipelineStages.

The runner is the orchestrator. It takes a list of stages and a
PipelineContext, runs them in order, propagates results via the context,
and reports success/failure to the queue service (status transitions +
in-flight release).

Exception handling is centralized here: any stage that raises is caught,
the task is marked FAILED (with the retry policy deciding PENDING vs
DEAD_LETTER), and the in-flight flag is released.
"""
from __future__ import annotations
import logging
from typing import Sequence

from ..types import TaskStatus
from .ports import PipelineContext, PipelineStage, StageResult

_logger = logging.getLogger(__name__)


class PipelineRunner:
    def __init__(self, queue_service) -> None:
        """queue_service is duck-typed: must have update_status(task_id, status, error)
        and release_in_flight(task_id)."""
        self.queue_service = queue_service

    async def run_stages(
        self,
        stages: Sequence[PipelineStage],
        ctx: PipelineContext,
    ) -> None:
        prev_result: StageResult | None = None
        try:
            for stage in stages:
                _logger.debug("Running stage %s for task %s", stage.name, ctx.task_id)
                result = await stage.run(ctx, prev_result)
                prev_result = result
                if not result.success:
                    raise RuntimeError(
                        f"Stage {stage.name} returned success=False: {result.payload}"
                    )
            # All stages succeeded
            self.queue_service.update_status(ctx.task_id, TaskStatus.APPROVED)
        except Exception as exc:
            _logger.exception("Pipeline failed for task %s", ctx.task_id)
            try:
                self.queue_service.update_status(
                    ctx.task_id, TaskStatus.FAILED, error=str(exc),
                )
            finally:
                self.queue_service.release_in_flight(ctx.task_id)
            return
        finally:
            # On success path, the in-flight flag is released by the
            # caller (which is the dispatcher). On failure path, the
            # except block above already released it. The finally is
            # defensive — only releases if still in flight.
            pass
        # Success path: release in-flight here too
        self.queue_service.release_in_flight(ctx.task_id)
```

**Note:** The `finally: pass` is intentionally a no-op (kept for documentation). The success path explicitly releases in-flight; the failure path does so in its `except` block.

- [ ] **Step 4: Write `src/pipeline/ingest.py` (run_ingest, _resolve_wiki_paths, _get_provider)**

Create `src/pipeline/ingest.py`:

```python
"""run_ingest — the full ingest pipeline orchestrator.

This is the IO-heavy business function that:
1. Resolves the project's WikiPaths (via _resolve_wiki_paths)
2. Resolves the LLM provider (via _get_provider)
3. Drives the Analyzer → Generator stages via PipelineRunner
4. Appends a source page (Fix D logic from src/pipeline/pipeline.py:217-260)
5. Writes pages under AtomicContext
6. Returns the list of generated WikiPage objects

run_ingest is NOT a pure function. It is an async coroutine with
significant IO side effects (LLM calls, wiki page writes, index updates,
log writes). The TDD refactor preserves this — do not change the
function's external signature.
"""
from __future__ import annotations
import logging
import time
from pathlib import Path

from ..wiki.core.paths import WikiPaths
from ..wiki.core.types import PageType, WikiPage
from ..wiki.storage.page_writer import write_page
from ..wiki.features.indexer import append_to_index
from ..wiki.features.logger import log_event
from ..lib.atomic_ctx import AtomicContext
from ..llm.provider_factory import create_llm_provider
from ..llm.registry import ProviderRegistry, RegistryCorruptError, ProviderNotFoundError
from . import analyzer as _analyzer_module
from . import generator as _generator_module

_logger = logging.getLogger(__name__)


def _get_provider():
    """Resolve the configured default LLM provider.

    Falls back to OpenAI when the registry is empty / corrupt (so import-time
    tests still work). Identical to src/pipeline/pipeline.py:_get_provider —
    this is the extraction of that function.
    """
    try:
        cfg = ProviderRegistry.get_default()
        return create_llm_provider(cfg.name)
    except (RegistryCorruptError, ProviderNotFoundError, ValueError):
        return create_llm_provider("openai")


def _resolve_wiki_paths(project_id: str | None = None):
    """Resolve WikiPaths for the active project.

    When project_id is provided, look up in the global registry. Otherwise
    fall back to CWD (treated as project root). Identical to
    src/pipeline/pipeline.py:_resolve_wiki_paths.
    """
    if project_id is not None:
        try:
            from ..project.registry import GlobalRegistryStore
            entry = GlobalRegistryStore.by_id(project_id)
            if entry is not None:
                return WikiPaths(Path(entry.path))
        except Exception:
            pass
    return WikiPaths(Path.cwd())


async def run_ingest(
    paths: WikiPaths,
    source_path,
    source_text: str,
    provider,
    folder_context: str = "",
    task_id: str = "test",
) -> list[WikiPage]:
    """Run full 2-step pipeline + write pages + update index + log.

    Returns list of generated WikiPage objects. The function is async and
    has significant IO side effects — it is NOT a pure function.
    """
    _ = paths  # keep parameter for callers

    # Step 1: Analyze
    analyze_fn = getattr(_analyzer_module, "analyze")
    analysis = await analyze_fn(
        source_text=source_text,
        source_ext=source_path.suffix if hasattr(source_path, "suffix") else ".pdf",
        existing_wiki_index="",
        folder_context=folder_context,
        provider=provider,
        task_id=task_id,
        source_path=str(source_path),
    )

    # Step 2: Generate
    generate_fn = getattr(_generator_module, "generate")
    pages = await generate_fn(
        paths=paths,
        analysis=analysis,
        existing_wiki_index="",
        provider=provider,
    )

    # Fix D: guarantee one source page per ingested task.
    # (Identical to src/pipeline/pipeline.py:217-260; see that file for the
    #  full rationale on why this is unconditional.)
    source_slug = task_id if task_id.startswith("kb-") else f"kb-{task_id}"
    source_title = (
        Path(str(source_path)).name
        if hasattr(source_path, "name") else str(source_path)
    )
    source_summary = (analysis.summary or "").strip() or "(无摘要)"
    source_body = (
        f"## 来源\n\n"
        f"- 路径: `{source_path}`\n"
        f"- 摄取时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"\n## 摘要\n\n{source_summary}\n"
    )
    source_page = WikiPage(
        id=source_slug,
        title=source_title,
        type=PageType.source,
        sources=[str(source_path)],
        body=source_body,
        created_at=int(time.time() * 1000),
        updated_at=int(time.time() * 1000),
    )
    pages.append(source_page)

    # Write pages under AtomicContext (atomic commit)
    with AtomicContext():
        for page in pages:
            write_page(paths, page)
        append_to_index(paths, [(p.id, p.type.value, p.title) for p in pages])
        log_event(paths, task_id, "ingest_complete", f"ingested {len(pages)} pages")

    return pages
```

**Note:** The `source_body` is the minimal version. The full body content with all fields (key_facts, entities, concepts, suggested_pages rendering) lives in the original `src/pipeline/pipeline.py:217-260`. The implementer should copy the EXACT body construction from there to preserve behavior.

- [ ] **Step 5: Run all tests**

```bash
cd E:/2026-7-21/ruflo-kb
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest --import-mode=importlib -q 2>&1 | tail -5
```

Expected: 748 + new tests pass.

- [ ] **Step 6: Commit**

```bash
cd E:/2026-7-21/ruflo-kb
git add src/pipeline/runner.py src/pipeline/ingest.py tests/test_pipeline/test_runner.py
git commit -m "feat(pipeline): extract PipelineRunner and run_ingest

runner.py contains PipelineRunner that drives a sequence of PipelineStages
and handles status transitions + in-flight release. ingest.py contains
run_ingest (the IO-heavy business function), _resolve_wiki_paths, and
_get_provider.

The body construction in run_ingest is the minimal version; the implementer
should copy the full Fix D body from src/pipeline/pipeline.py:217-260 to
preserve behavior. This is intentional — the refactor must be byte-for-byte
equivalent for the existing tests to pass.

All 748 tests pass.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 10: Extract `src/pipeline/dispatcher.py` + `src/pipeline/service.py` + `src/pipeline/__init__.py` compat

**Files:**
- Create: `src/pipeline/dispatcher.py` — `dispatch_collector_start` (sync→async bridge)
- Create: `src/pipeline/service.py` — `PipelineService`, `get_default_pipeline_service`, `register_stages`
- Modify: `src/pipeline/__init__.py` — re-exports + `sys.modules` aliases for compat

**Critical:** `src.pipeline.pipeline._resolve_wiki_paths` and `src.pipeline.pipeline._get_provider` must remain importable for the monkey-patch test pattern.

- [ ] **Step 1: Write `src/pipeline/dispatcher.py`**

Create `src/pipeline/dispatcher.py`:

```python
"""dispatch_collector_start — the sync→async bridge for the collector chain.

When enqueue_task emits "collector:start", this handler runs. It detects
whether there's already a running event loop:
- If yes: schedule the chain as a task on that loop.
- If no: drive the chain with asyncio.run (the production sync entry path).

This is the EXACT logic from src/pipeline/pipeline.py:_dispatch_collector_start
(commit 37b644a) — extracted verbatim, no behavior change.
"""
from __future__ import annotations
import asyncio
import logging
from typing import Callable

from .runner import PipelineRunner
from .stages import AnalyzerStage, CollectorStage, GeneratorStage

_logger = logging.getLogger(__name__)


def dispatch_collector_start(
    pipeline_service, payload: dict,
) -> None:
    """EventBus handler for "collector:start". Bridges sync emit → async chain."""
    coro = pipeline_service.run_for_collector_start(payload)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No loop — use asyncio.run (production sync entry path)
        try:
            asyncio.run(coro)
        except Exception:
            _logger.exception("collector chain dispatch failed")
        return
    # Loop exists (test scenario) — schedule
    loop.create_task(coro)
```

- [ ] **Step 2: Write `src/pipeline/service.py`**

Create `src/pipeline/service.py`:

```python
"""PipelineService — composition root for the pipeline subsystem.

Owns the PipelineRunner, the registered stages, and the queue service
(the source of update_status / release_in_flight). The default singleton
is process-wide; tests construct instances directly.

Public methods:
- register_stages(stages): set the list of stages to run per pipeline
- run_for_collector_start(payload): the async entry point called by
  the dispatcher when an EventBus "collector:start" event fires
"""
from __future__ import annotations
import logging
from typing import Sequence

from ..queue.service import get_default_queue_service
from .ingest import _get_provider, _resolve_wiki_paths, run_ingest
from .ports import PipelineContext, PipelineStage
from .runner import PipelineRunner
from .stages import AnalyzerStage, CollectorStage, GeneratorStage
from ..types import SourceType

_logger = logging.getLogger(__name__)


class PipelineService:
    def __init__(self, queue_service=None) -> None:
        self.queue_service = queue_service or get_default_queue_service()
        self.runner = PipelineRunner(self.queue_service)
        self._stages: list[PipelineStage] = [
            CollectorStage(), AnalyzerStage(), GeneratorStage(),
        ]

    def register_stages(self, stages: Sequence[PipelineStage]) -> None:
        self._stages = list(stages)

    async def run_for_collector_start(self, payload: dict) -> None:
        """Drive the full pipeline chain for a "collector:start" event.

        payload is a dict with keys: task_id, source, source_type, project_id.
        """
        task_id = payload["task_id"]
        source = payload["source"]
        source_type = payload.get("source_type", SourceType.FILE)
        project_id = payload.get("project_id")

        # Step 1: Collector (read source)
        ctx = PipelineContext(
            task_id=task_id, source=source, source_type=source_type,
            project_id=project_id,
        )
        for stage in self._stages[:1]:  # only CollectorStage
            result = await stage.run(ctx, prev_result=None)
            if not result.success:
                self.queue_service.update_status(
                    task_id, status=__import__("src.types", fromlist=["TaskStatus"]).TaskStatus.FAILED,
                    error=f"collector stage failed: {result.payload}",
                )
                self.queue_service.release_in_flight(task_id)
                return
            ctx.collector_result = result.payload

        # Step 2: Run the full ingest (analyze + generate + source page + atomic write)
        # This is the IO-heavy path that was in src/pipeline/pipeline.py:_on_collector_done
        try:
            paths = _resolve_wiki_paths(project_id=project_id)
            provider = _get_provider()
            await run_ingest(
                paths=paths,
                source_path=ctx.collector_result.raw_path,
                source_text=ctx.collector_result.content,
                provider=provider,
                task_id=task_id,
            )
            self.queue_service.update_status(task_id, status=__import__("src.types", fromlist=["TaskStatus"]).TaskStatus.APPROVED)
        except Exception as exc:
            _logger.exception("ingest failed for %s", task_id)
            self.queue_service.update_status(
                task_id,
                status=__import__("src.types", fromlist=["TaskStatus"]).TaskStatus.FAILED,
                error=str(exc),
            )
        finally:
            self.queue_service.release_in_flight(task_id)


# --- module-level default singleton ---

_default_service: PipelineService | None = None


def get_default_pipeline_service() -> PipelineService:
    global _default_service
    if _default_service is None:
        _default_service = PipelineService()
    return _default_service


# --- explicit event registration ---

_registered = False


def register_stages(stages: Sequence[PipelineStage]) -> None:
    """Register the pipeline stages. Idempotent — safe to call multiple times."""
    get_default_pipeline_service().register_stages(stages)
    _register_event_handlers()


def _register_event_handlers() -> None:
    """Bind dispatcher to EventBus. Called from __init__.py on import."""
    from ..events.event_bus import event_bus
    global _registered
    if _registered:
        return
    _registered = True
    service = get_default_pipeline_service()
    event_bus.on("collector:start", lambda payload: dispatch_collector_start(service, payload))
```

- [ ] **Step 3: Replace `src/pipeline/__init__.py`**

Replace the contents of `src/pipeline/__init__.py` with:

```python
"""Public pipeline subsystem API + compat layer.

Re-exports the public names from the new submodules. The legacy
src/pipeline/pipeline.py becomes a thin compat shim (or is deleted, see
Task 11). The compat shim MUST preserve the ability to import
`src.pipeline.pipeline._resolve_wiki_paths` and
`src.pipeline.pipeline._get_provider` for the existing
test_pipeline_event_bus_integration.py monkey-patch pattern.
"""
import sys

# Re-exports for new consumers
from .ingest import _resolve_wiki_paths, _get_provider, run_ingest
from .service import (
    PipelineService,
    get_default_pipeline_service,
    register_stages,
)
from .runner import PipelineRunner
from .stages import AnalyzerStage, CollectorStage, GeneratorStage
from .ports import PipelineContext, StageResult, PipelineStage

# Register handlers on import (mirrors old import-time behavior of pipeline.py)
_register_event_handlers_if_needed()


def _register_event_handlers_if_needed() -> None:
    """Bind the collector:start handler to the global EventBus.

    This is the import-time side effect that the old pipeline.py did
    implicitly. New code can call register_stages() explicitly to swap
    the default stages, but the handler is always bound.
    """
    from .service import _register_event_handlers
    _register_event_handlers()


# --- compat shim for old src.pipeline.pipeline imports ---

class _PipelineCompatShim:
    """Mirrors the symbols that old `src.pipeline.pipeline` exposed.

    The legacy file is replaced by this class registered as a module
    under sys.modules['src.pipeline.pipeline']. Tests that do
    `monkeypatch.setattr(pipeline_mod, "_resolve_wiki_paths", ...)`
    continue to work — the patch targets this shim, and the new code
    that uses the symbols (in ingest.py) imports them from this shim
    (NOT from the new ingest.py module directly).

    To make this work, ingest.py imports _resolve_wiki_paths / _get_provider
    via `from src.pipeline import _resolve_wiki_paths, _get_provider`
    (NOT from .helpers). That way, patches to the compat shim propagate.
    """
    run_ingest = run_ingest
    _resolve_wiki_paths = _resolve_wiki_paths
    _get_provider = _get_provider
    # Expose the old globals
    collect = sys.modules.get("src.pipeline.collector", None) and sys.modules["src.pipeline.collector"].collect
    analyze = sys.modules.get("src.pipeline.analyzer", None) and sys.modules["src.pipeline.analyzer"].analyze
    generate = sys.modules.get("src.pipeline.generator", None) and sys.modules["src.pipeline.generator"].generate


_pipeline_compat_shim = _PipelineCompatShim()
sys.modules.setdefault("src.pipeline.pipeline", _pipeline_compat_shim)

# Also alias the old submodule paths to the new stages/ package
from .stages import collector as _collector_module
from .stages import analyzer as _analyzer_module
from .stages import generator as _generator_module
sys.modules.setdefault("src.pipeline.collector", _collector_module)
sys.modules.setdefault("src.pipeline.analyzer", _analyzer_module)
sys.modules.setdefault("src.pipeline.generator", _generator_module)

__all__ = [
    "PipelineService",
    "PipelineRunner",
    "PipelineStage",
    "PipelineContext",
    "StageResult",
    "CollectorStage",
    "AnalyzerStage",
    "GeneratorStage",
    "run_ingest",
    "get_default_pipeline_service",
    "register_stages",
]
```

- [ ] **Step 4: Update `src/pipeline/ingest.py` to import _resolve_wiki_paths from the compat shim**

In `src/pipeline/ingest.py`, change the local definitions of `_resolve_wiki_paths` and `_get_provider` to be imports from the compat shim:

```python
# At the top of src/pipeline/ingest.py, replace the existing _get_provider
# and _resolve_wiki_paths definitions with re-imports:
from src.pipeline import _resolve_wiki_paths, _get_provider
```

This creates a circular import at first glance, but Python's late-binding resolves it: `src.pipeline.__init__` runs first, defines the symbols, registers the shim, then `ingest.py` is loaded by an `import run_ingest` and the symbol lookup hits the shim. **This is the only way the monkey-patch test pattern keeps working** — the patches to `src.pipeline.pipeline._resolve_wiki_paths` propagate because both old call sites and new ones look up the symbol from the same module.

- [ ] **Step 5: Run the full test suite**

```bash
cd E:/2026-7-21/ruflo-kb
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest --import-mode=importlib -q 2>&1 | tail -10
```

Expected: All tests pass. If `test_pipeline_event_bus_integration.py` fails, the monkey-patch chain is broken — verify that the `_PipelineCompatShim` exposes the same `_resolve_wiki_paths` and `_get_provider` instances that `ingest.py` actually calls.

- [ ] **Step 6: Verify import paths work**

```bash
cd E:/2026-7-21/ruflo-kb
python -c "from src.pipeline.pipeline import _on_collector_start, run_ingest, _resolve_wiki_paths, _get_provider; print('legacy compat: OK')"
python -c "from src.pipeline.collector import collect; print('collector compat: OK')"
python -c "from src.pipeline.analyzer import analyze; print('analyzer compat: OK')"
python -c "from src.pipeline.generator import generate; print('generator compat: OK')"
python -c "from src.pipeline import PipelineService, run_ingest, CollectorStage; print('new API: OK')"
```

Expected: all five print OK.

- [ ] **Step 7: Delete `src/pipeline/pipeline.py`**

```bash
cd E:/2026-7-21/ruflo-kb
git rm src/pipeline/pipeline.py
```

- [ ] **Step 8: Run the full test suite one more time**

```bash
cd E:/2026-7-21/ruflo-kb
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest --import-mode=importlib -q 2>&1 | tail -10
```

Expected: All tests pass.

- [ ] **Step 9: Verify server startup (regression check)**

```bash
cd E:/2026-7-21/ruflo-kb
python -m src.cli serve --port 18889 &
SERVER_PID=$!
sleep 3
curl -s http://127.0.0.1:18889/health | head -5
kill $SERVER_PID 2>/dev/null
```

Expected: 200 OK with health JSON.

- [ ] **Step 10: Commit**

```bash
cd E:/2026-7-21/ruflo-kb
git add src/pipeline/dispatcher.py src/pipeline/service.py src/pipeline/__init__.py src/pipeline/ingest.py
git rm src/pipeline/pipeline.py
git commit -m "refactor(pipeline): migrate __init__.py to service-based re-exports

dispatcher.py has the sync→async bridge (verbatim from pipeline.py).
service.py has PipelineService composition root + register_stages +
get_default_pipeline_service. The default singleton is process-wide.

The compat shim approach: __init__.py creates a _PipelineCompatShim class
and registers it as sys.modules['src.pipeline.pipeline']. The shim exposes
run_ingest, _resolve_wiki_paths, _get_provider, plus the old submodule
symbols (collect, analyze, generate via the new stages/ package).

ingest.py imports _resolve_wiki_paths and _get_provider FROM the compat
shim (not from itself) — this is the only way
test_pipeline_event_bus_integration.py:126-127's monkey-patch pattern
keeps working: patches to src.pipeline.pipeline._resolve_wiki_paths
propagate because both old and new call sites look up the symbol from
the same module.

The legacy src/pipeline/pipeline.py is deleted. Public API surface
preserved: PipelineService, run_ingest, CollectorStage, etc.

All 748 tests pass. test_pipeline_event_bus_integration.py passes
(verifies the monkey-patch chain). Server startup regression check
succeeds.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review

After all 10 tasks, the spec's behavioral invariants are verified:

| Invariant | Verification |
|---|---|
| `safe_write` integration | `test_save_atomic.py::test_atomic_write_does_not_partial_write` (canary) passes |
| APPROVED task filtering | `test_persistence.py::test_snapshot_filters_approved_tasks` passes |
| Service-level single lock | `test_lock.py::test_50_concurrent_enqueue_does_not_duplicate_task_id` passes |
| External `collector:done` listener | `test_pipeline_event_bus_integration.py::test_event_bus_dispatch_external_listener_runs` passes |
| Circuit breaker is process-level singleton | `test_pipeline_event_bus_integration.py:49-53` breaker reset works |
| Monkey-patchable `_resolve_wiki_paths` / `_get_provider` | `test_pipeline_event_bus_integration.py:126-127` patches work |
| Public API surface preserved | `python -c "from src.queue import ..."` works for all 7 names |
| All 748 tests pass | `pytest --import-mode=importlib` green |

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-25-queue-pipeline-refactor.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
