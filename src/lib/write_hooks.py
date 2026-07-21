"""safe_write hook — respects AtomicContext to batch writes."""
from pathlib import Path
from typing import Union

from .atomic_ctx import is_suspended


_pending_writes: dict[Path, str] = {}


def safe_write(path: Union[str, Path], content: str) -> None:
    """Write file, respecting AtomicContext.

    If suspended: accumulate in _pending_writes.
    Else: write directly.
    """
    path = Path(path)
    if is_suspended():
        _pending_writes[path] = content
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def flush_pending_writes() -> int:
    """Write all pending files. Called by AtomicContext.flush_callback.

    Returns number of files written.
    """
    count = len(_pending_writes)
    for path, content in list(_pending_writes.items()):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _pending_writes.clear()
    return count


def get_pending_count() -> int:
    return len(_pending_writes)
