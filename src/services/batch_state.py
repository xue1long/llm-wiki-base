"""Unified ``.index/batch_build_state.json`` reader/writer (plan H①).

Phase 4 落点：三个写者 —— ``src/services/ingest.py``（folder 批次）、
``src/services/files.py``（读）、``scripts/batch_executor.py``（每 raw
状态机）—— 必须共享同一 schema + 文件锁，杜绝并发写丢失更新。

Schema (v2)::

    {
      "schema_version": 2,
      "batch_<n>": {
        "status": "...",              # batch-level status
        "files": [...],
        "gate": "pending_gate",       # Phase 4 批级门禁状态
        "raw_states": {               # 每 raw 状态机（Phase 4 正式枚举）
          "raw/sources/a.md": {
            "status": "pending|in_progress|done|failed|permanent_failed|pending_deletion",
            "round": 1,
            "last_error": "...",
            "ts": "..."
          }
        }
      }
    }

Write discipline:
- 所有写入走 :func:`save_batch_state`（tmp + ``os.replace`` 原子替换）；
- 跨进程互斥走 :class:`batch_state_lock`（Windows msvcrt / POSIX fcntl），
  读-改-写必须整体持锁；
- 读端容忍文件缺失 / 损坏（降级为空 dict），永不抛异常。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from ..wiki.core.paths import WikiPaths

# Phase 4 正式每 raw 状态机枚举（plan guidance #2，pending_deletion 并入；
# Task 0.2 新增 partial_commit —— 单 raw 提交部分失败，带 failed_paths）。
BATCH_STATUSES = (
    "pending",
    "in_progress",
    "done",
    "failed",
    "permanent_failed",
    "pending_deletion",
    "partial_commit",
)

SCHEMA_VERSION = 2

_BATCH_STATE_FILE = "batch_build_state.json"
_DEFAULT_TIMEOUT = 30.0  # 锁等待上限（秒）


def batch_state_path(paths: WikiPaths) -> Path:
    return Path(paths.root) / ".index" / _BATCH_STATE_FILE


# ---------------------------------------------------------------------------
# Cross-process file lock
# ---------------------------------------------------------------------------

class _FileLock:
    """Advisory cross-process lock on the batch-state file.

    Windows uses ``msvcrt.locking`` (byte-range lock); POSIX uses
    ``fcntl.flock``.  Lock file is ``batch_build_state.json.lock`` so the
    state file itself stays a clean JSON document.
    """

    def __init__(self, paths: WikiPaths, timeout: float = _DEFAULT_TIMEOUT,
                 lock_path: Path | None = None):
        if lock_path is not None:
            self._lock_path = Path(lock_path)
        else:
            self._lock_path = Path(str(batch_state_path(paths)) + ".lock")
        self._fd: int | None = None
        self._timeout = timeout

    def acquire(self) -> None:
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self._lock_path), os.O_CREAT | os.O_RDWR)
        try:
            self._lock_impl(fd, blocking=True)
        except OSError:
            os.close(fd)
            raise
        self._fd = fd

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            self._unlock_impl(self._fd)
        finally:
            os.close(self._fd)
            self._fd = None

    def _lock_impl(self, fd: int, blocking: bool) -> None:
        if os.name == "nt":
            import msvcrt
            deadline = time.monotonic() + self._timeout
            while True:
                try:
                    # msvcrt.locking 需要文件至少 1 字节；写入本身也可能因
                    # 另一句柄已持锁而 PermissionError —— 必须在重试循环内。
                    if os.fstat(fd).st_size == 0:
                        os.write(fd, b"\0")
                        os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    return
                except OSError:
                    if not blocking or time.monotonic() > deadline:
                        raise
                    time.sleep(0.05)
        else:
            import fcntl
            flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
            fcntl.flock(fd, flags)

    def _unlock_impl(self, fd: int) -> None:
        if os.name == "nt":
            import msvcrt
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        else:
            import fcntl
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass

    def __enter__(self) -> "_FileLock":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()


def batch_state_lock(paths: WikiPaths, timeout: float = _DEFAULT_TIMEOUT) -> _FileLock:
    """Return a :class:`_FileLock` for the batch-state file (context manager)."""
    return _FileLock(paths, timeout=timeout)


def project_commit_lock(paths: WikiPaths, timeout: float = _DEFAULT_TIMEOUT) -> _FileLock:
    """Cross-process lock over wiki **data** commits (page/index/log/alias/vector).

    Separate lock file (``.index/commit.lock``) from the batch-state lock:
    it guards the data-write phase, not the state JSON. Hold it for the whole
    commit loop so concurrent executors of the same project cannot interleave
    page/index writes (plan Task 0.3). Cross-process on Windows (msvcrt) and
    POSIX (fcntl); advisory only.
    """
    return _FileLock(
        paths,
        timeout=timeout,
        lock_path=Path(str(paths.root)) / ".index" / "commit.lock",
    )


# ---------------------------------------------------------------------------
# Read / write
# ---------------------------------------------------------------------------

def load_batch_state(paths: WikiPaths) -> dict:
    """Read batch state; tolerate missing/corrupt file (never raises)."""
    p = batch_state_path(paths)
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def save_batch_state(paths: WikiPaths, state: dict) -> None:
    """Atomically persist *state* (tmp + os.replace), merging schema_version."""
    p = batch_state_path(paths)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(state)
    payload["schema_version"] = SCHEMA_VERSION
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(str(tmp), str(p))


def update_batch_state(paths: WikiPaths, mutator) -> dict:
    """Read-modify-write under the file lock.

    *mutator* receives the current state dict and returns the (possibly
    new) state dict.  Returns the **persisted** state (with
    ``schema_version`` merged — M1 review).  Serialises concurrent writers
    across processes — the single writer pattern that prevents lost
    updates (H①).
    """
    with batch_state_lock(paths):
        state = load_batch_state(paths)
        new_state = mutator(state)
        save_batch_state(paths, new_state)
        return load_batch_state(paths)


# ---------------------------------------------------------------------------
# Per-raw status helpers (Phase 4 state machine)
# ---------------------------------------------------------------------------

def _ensure_raw_states(state: dict, batch_key: str) -> dict:
    entry = state.setdefault(batch_key, {})
    if not isinstance(entry, dict):
        entry = {}
        state[batch_key] = entry
    raws = entry.setdefault("raw_states", {})
    if not isinstance(raws, dict):
        raws = {}
        entry["raw_states"] = raws
    return raws


def set_raw_status(paths: WikiPaths, batch_key: str, raw_rel: str,
                   status: str, **extra) -> None:
    """Set one raw's state-machine status (atomic, locked)."""
    if status not in BATCH_STATUSES:
        raise ValueError(f"invalid raw status {status!r}; "
                         f"allowed: {BATCH_STATUSES}")

    def _mutate(state: dict) -> dict:
        raws = _ensure_raw_states(state, batch_key)
        entry = raws.setdefault(raw_rel, {})
        # M6 review：status/ts 是状态机保留键，禁止被调用方 extra 覆盖。
        protected = {"status", "ts"}
        for k, v in extra.items():
            if k in protected:
                raise ValueError(f"cannot override reserved key {k!r}")
            entry[k] = v
        entry["status"] = status
        entry["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return state

    update_batch_state(paths, _mutate)


def raw_status(state: dict, batch_key: str, raw_rel: str) -> str:
    """Read one raw's status (default ``"pending"`` when absent)."""
    entry = state.get(batch_key)
    if not isinstance(entry, dict):
        return "pending"
    raws = entry.get("raw_states")
    if not isinstance(raws, dict):
        return "pending"
    rec = raws.get(raw_rel)
    if not isinstance(rec, dict):
        return "pending"
    return rec.get("status", "pending")
