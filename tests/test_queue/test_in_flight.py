"""Tests for InMemoryInFlightTracker — the default InFlightTracker impl.

The tracker is used inside QueueService to gate task selection: a task
in tracker.snapshot() is excluded from select_next_task. The contract is:
- acquire(task_id) returns False if already in flight (idempotent)
- release(task_id) is a no-op if not in flight
- is_in_flight(task_id) reflects current state
- snapshot() returns a copy of the set (caller-side mutation is safe)
"""

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
