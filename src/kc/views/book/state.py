"""Separate Book publication state from compilation job state."""
from __future__ import annotations

from enum import StrEnum


class BookPublicationState(StrEnum):
    AVAILABLE = "available"
    OUTDATED = "outdated"


class BookJobState(StrEnum):
    IDLE = "idle"
    COMPILING = "compiling"
    RETRYING = "retrying"
    FAILED = "failed"


def can_transition_publication(prev: BookPublicationState, next_: BookPublicationState) -> bool:
    return (prev, next_) in {
        (BookPublicationState.AVAILABLE, BookPublicationState.OUTDATED),
        (BookPublicationState.OUTDATED, BookPublicationState.AVAILABLE),
    }


def can_transition_job(prev: BookJobState, next_: BookJobState) -> bool:
    return (prev, next_) in {
        (BookJobState.IDLE, BookJobState.COMPILING),
        (BookJobState.COMPILING, BookJobState.IDLE),
        (BookJobState.COMPILING, BookJobState.RETRYING),
        (BookJobState.COMPILING, BookJobState.FAILED),
        (BookJobState.RETRYING, BookJobState.COMPILING),
        (BookJobState.RETRYING, BookJobState.FAILED),
        (BookJobState.FAILED, BookJobState.RETRYING),
    }


__all__ = [
    "BookJobState", "BookPublicationState",
    "can_transition_job", "can_transition_publication",
]
