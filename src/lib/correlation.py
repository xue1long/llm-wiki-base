"""R12 — correlation IDs for the HTTP → Queue → Pipeline → Writer chain.

A contextvar carries the current request_id / task_id / project_id; a
logging.Filter injects them into every log record so operators can trace
one ingest end-to-end without joining logs by hand.

Usage::

    from src.lib.correlation import set_correlation, clear_correlation
    from src.lib.correlation import CorrelationLogFilter

    # in the HTTP middleware / queue handler:
    set_correlation(request_id=..., task_id=..., project_id=...)
    try:
        ...
    finally:
        clear_correlation()

    # attach the filter to the root logger at startup:
    logging.getLogger().addFilter(CorrelationLogFilter())
"""
from __future__ import annotations

import logging
import threading

_corr = threading.local()


def set_correlation(**fields: str) -> None:
    """Set correlation fields (request_id / task_id / project_id)."""
    _corr.data = dict(fields)


def get_correlation() -> dict:
    """Return the current correlation fields (empty dict when unset)."""
    return dict(getattr(_corr, "data", {}))


def clear_correlation() -> None:
    """Drop the correlation fields for the current thread."""
    if hasattr(_corr, "data"):
        del _corr.data


class CorrelationLogFilter(logging.Filter):
    """Attaches request_id / task_id / project_id to every log record.

    When the fields are not set the record is left untouched (no fields,
    no failure) — the filter is a no-op outside a tracked operation.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in get_correlation().items():
            if value:
                setattr(record, key, value)
        return True


__all__ = [
    "set_correlation",
    "get_correlation",
    "clear_correlation",
    "CorrelationLogFilter",
]
