"""Filesystem-based optimistic locking for KnowledgeObject writes.

Three write sources need coordination:
1. Pipeline Indexer (Phase 2)
2. Curator (Phase 4)
3. MCP memory.update (Phase 3)

Protocol:
- Each object has a monotonic version counter at .index/locks/{object_id}.version
- Writer reads current version before writing
- Writer includes expected_version in the write
- Writer performs the write; on success increments version to current+1
- On failure the version is left unchanged (no counter corruption)
- If expected_version != current_version -> conflict -> retry (max 3 times)
- MCP memory_update returns version conflict as an error for caller retry
"""
import json
import time
from pathlib import Path


class ConcurrencyError(Exception):
    """Raised when optimistic lock retries are exhausted."""

    def __init__(self, object_id: str, attempts: int):
        self.object_id = object_id
        self.attempts = attempts
        super().__init__(
            f"Concurrency conflict for {object_id} after {attempts} attempts"
        )


class OptimisticLock:
    """Filesystem-based optimistic locking for KnowledgeObject writes.

    Three write sources need coordination:
    1. Pipeline Indexer (Phase 2)
    2. Curator (Phase 4)
    3. MCP memory.update (Phase 3)

    Protocol:
    - Each object has a monotonic version counter at .index/locks/{object_id}.version
    - Writer reads current version before writing
    - Writer includes expected_version in the write
    - If expected_version != current_version -> conflict -> retry (max 3 times)
    - On successful write -> increment version counter
    - MCP memory_update returns version conflict as an error for caller retry
    """

    MAX_RETRIES = 3

    def __init__(self, lock_dir: Path):
        self._lock_dir = Path(lock_dir)
        self._lock_dir.mkdir(parents=True, exist_ok=True)

    def _version_path(self, object_id: str) -> Path:
        """Return the filesystem path for an object's version file."""
        return self._lock_dir / f"{object_id}.version"

    def get_version(self, object_id: str) -> int:
        """Read current version for an object. Returns 0 if never written."""
        vp = self._version_path(object_id)
        if not vp.exists():
            return 0
        try:
            content = vp.read_text(encoding="utf-8").strip()
            return int(content)
        except (ValueError, OSError):
            return 0

    def acquire(self, object_id: str, expected_version: int) -> bool:
        """Check whether expected_version matches current version.

        Returns True if the caller can proceed (no conflict).
        Returns False if version mismatch (conflict — caller should retry).

        Does NOT increment the version — that happens after a successful
        write in :meth:`with_lock`.
        """
        current = self.get_version(object_id)
        return current == expected_version

    def release(self, object_id: str, new_version: int) -> None:
        """Update version counter to *new_version* after a successful write."""
        vp = self._version_path(object_id)
        vp.write_text(str(new_version), encoding="utf-8")

    def with_lock(self, object_id: str, write_fn, *args, **kwargs):
        """Execute write_fn with optimistic locking.

        1. Read current version
        2. Check no conflict (expected_version == current)
        3. Call write_fn(expected_version=current_version)
        4. If write_fn succeeds, increment version to current+1
        5. If version conflict, retry up to MAX_RETRIES times
        6. If all retries exhausted, raise ConcurrencyError

        Returns the result of write_fn.
        """
        for attempt in range(1, self.MAX_RETRIES + 1):
            current = self.get_version(object_id)
            if not self.acquire(object_id, current):
                continue
            try:
                result = write_fn(*args, expected_version=current, **kwargs)
                # Only increment version AFTER a successful write
                self.release(object_id, current + 1)
                return result
            except ConcurrencyError:
                if attempt >= self.MAX_RETRIES:
                    raise
                continue
        raise ConcurrencyError(object_id, self.MAX_RETRIES)

    def get_lock_info(self, object_id: str) -> dict:
        """Return lock metadata for debugging."""
        vp = self._version_path(object_id)
        version = self.get_version(object_id)
        info = {"version": version}
        if vp.exists():
            info["last_modified"] = vp.stat().st_mtime
        return info
