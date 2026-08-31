"""Book update coalescing before dispatch to the existing task queue."""
from __future__ import annotations

import threading
from collections.abc import Callable


class BookUpdateScheduler:
    """Coalesce rapid Wiki updates per Book, then invoke one queue callback."""

    def __init__(self, callback: Callable[[str, tuple[str, ...]], None], *, delay: float = 5.0, batch_size: int = 10) -> None:
        if delay < 0 or batch_size < 1:
            raise ValueError("delay must be >= 0 and batch_size must be positive")
        self.callback = callback
        self.delay = delay
        self.batch_size = batch_size
        self._pending: dict[str, set[str]] = {}
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def schedule(self, book_id: str, wiki_id: str) -> None:
        with self._lock:
            pending = self._pending.setdefault(book_id, set())
            pending.add(wiki_id)
            if len(pending) >= self.batch_size:
                self._cancel_locked(book_id)
                batch = self._take_locked(book_id)
            else:
                self._cancel_locked(book_id)
                timer = threading.Timer(self.delay, self._flush, args=(book_id,))
                timer.daemon = True
                self._timers[book_id] = timer
                timer.start()
                return
        self.callback(book_id, batch)

    def flush(self, book_id: str) -> None:
        with self._lock:
            self._cancel_locked(book_id)
            batch = self._take_locked(book_id)
        if batch:
            self.callback(book_id, batch)

    def cancel_all(self) -> None:
        with self._lock:
            for book_id in tuple(self._timers):
                self._cancel_locked(book_id)
            self._pending.clear()

    def _flush(self, book_id: str) -> None:
        self.flush(book_id)

    def _cancel_locked(self, book_id: str) -> None:
        timer = self._timers.pop(book_id, None)
        if timer is not None:
            timer.cancel()

    def _take_locked(self, book_id: str) -> tuple[str, ...]:
        return tuple(sorted(self._pending.pop(book_id, set())))


__all__ = ["BookUpdateScheduler"]
