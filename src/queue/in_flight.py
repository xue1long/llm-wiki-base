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
