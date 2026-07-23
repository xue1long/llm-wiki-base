"""safe_write hook — respects AtomicContext to batch writes.

When NOT inside an AtomicContext, safe_write uses an atomic write pattern
(write to *.tmp then os.replace) so a crash mid-write never produces a torn
target file. This matches the pattern used in src/project/registry.py:89-101.

Inside an AtomicContext, writes are buffered into _pending_writes and only
flushed at the atomic commit point (see flush_pending_writes / AtomicContext).
The DELETE_SENTINEL marker queues a deferred deletion, executed at flush time.
"""
import os
from pathlib import Path
from typing import Union

from .atomic_ctx import is_suspended


DELETE_SENTINEL = "__WIKI_DELETE__"
_pending_writes: dict[Path, str] = {}


def safe_write(path: Union[str, Path], content: str) -> None:
    """Write file, respecting AtomicContext; sentinel content queues deletion.

    Non-suspended path: atomic write via *.tmp + os.replace (no torn writes).
    Suspended path: buffer the (path, content) into _pending_writes for the
    AtomicContext commit point. DELETE_SENTINEL is always buffered while
    suspended; while not suspended it triggers an immediate os.unlink.
    """
    path = Path(path)
    if is_suspended():
        _pending_writes[path] = content
        return
    if content == DELETE_SENTINEL:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def flush_pending_writes() -> int:
    """Flush queued writes and deletions at the atomic commit point.

    Each flushed write uses the same tmp+replace atomic pattern; each
    queued DELETE_SENTINEL triggers an os.unlink (tolerating missing files).
    """
    count = len(_pending_writes)
    for path, content in list(_pending_writes.items()):
        if content == DELETE_SENTINEL:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(content, encoding="utf-8")
            os.replace(tmp, path)
    _pending_writes.clear()
    return count


def get_pending_count() -> int:
    return len(_pending_writes)

