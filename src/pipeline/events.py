"""Re-export pipeline-related event dataclasses from src/events/events.py.

This is a thin shim that lets pipeline code import from
`src.pipeline.events` without taking a direct dependency on
`src.events.events` (which would create a circular import).
"""
from ..events.events import (
    EventName,
    CollectorDonePayload,
)

__all__ = ["EventName", "CollectorDonePayload"]
