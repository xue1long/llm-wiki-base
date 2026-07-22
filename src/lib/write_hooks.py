"""safe_write hook — respects AtomicContext to batch writes."""
import os
from pathlib import Path
from typing import Union

from .atomic_ctx import is_suspended


DELETE_SENTINEL = "__WIKI_DELETE__"
_pending_writes: dict[Path, str] = {}


def safe_write(path: Union[str, Path], content: str) -> None:
    """Write file, respecting AtomicContext; sentinel content queues deletion."""
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
    path.write_text(content, encoding="utf-8")


def flush_pending_writes() -> int:
    """Flush queued writes and deletions at the atomic commit point."""
    count = len(_pending_writes)
    for path, content in list(_pending_writes.items()):
        if content == DELETE_SENTINEL:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    _pending_writes.clear()
    return count


def get_pending_count() -> int:
    return len(_pending_writes)
