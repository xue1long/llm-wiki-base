"""R8 — minimal fault taxonomy for retry / dead-letter decisions.

Audit finding: a broad ``except Exception`` collapsed configuration
errors, data errors, dependency faults and programming bugs into the same
FAILED→retry path, so deterministic failures burned retries and opaque
warnings hid real bugs.

Taxonomy (architecture-remediation R8, plan-audit hardening):

- ``RetryableDependencyError`` — transient external/network fault
  (provider timeout, dead-letterable infra). The queue retries it.
- ``InvalidInputError`` — deterministic bad input (unsupported type,
  malformed source, wrong schema). Never retried.
- ``DataConsistencyError`` — corrupt or partially-written state (index
  out of sync, half-committed batch). Never retried; operator action.
- ``ProgrammingError`` — a code bug, not an operational fault. Never
  retried; surface loudly.
- ``pipeline.retry.PermanentFailure`` — surface-level "this will never
  succeed" error raised by the LLM client layer (e.g. HTTP 422 content
  moderation, irrecoverable response-shape failure). Never retried; the
  pipeline maps it to the same no-retry marker as the four explicit
  taxonomy classes above.

Unknown exceptions default to retryable (fail-open, back-compat).

The queue's RetryPolicy has no schema for a "don't retry" flag, so the
pipeline encodes the decision in the error string via ``NO_RETRY_MARKER``;
``is_no_retry()`` lets the policy dead-letter immediately. This keeps the
change local to the error path (no KnowledgeTask schema change).
"""
from __future__ import annotations

# Marker prefix written into task.error for terminal (non-retryable)
# failures. The retry policy checks it and dead-letters immediately.
NO_RETRY_MARKER = "[no-retry] "


class RetryableDependencyError(RuntimeError):
    """Transient external dependency fault — safe to retry."""


class InvalidInputError(ValueError):
    """Deterministic bad input — retrying will not help."""


class DataConsistencyError(RuntimeError):
    """Corrupt / partially-committed state — operator attention required."""


class ProgrammingError(RuntimeError):
    """A bug in the code, not an operational fault — surface loudly."""


def classify_error(exc: BaseException) -> str:
    """Classify an exception into ``retryable``/``invalid_input``/
    ``data_consistency``/``programming``/``no_retry``. Unknown → retryable.

    ``no_retry`` covers ``pipeline.retry.PermanentFailure`` — a non-retryable
    surface error raised by the LLM layer (HTTP 422 content moderation,
    invalid response shape that retries cannot fix). The class is imported
    lazily inside the function to avoid a circular import (pipeline.retry
    imports from this module).
    """
    if isinstance(exc, RetryableDependencyError):
        return "retryable"
    if isinstance(exc, InvalidInputError):
        return "invalid_input"
    if isinstance(exc, DataConsistencyError):
        return "data_consistency"
    if isinstance(exc, ProgrammingError):
        return "programming"
    try:
        from ..pipeline.retry import PermanentFailure
        if isinstance(exc, PermanentFailure):
            return "no_retry"
    except Exception:
        # pipeline.retry not importable in some test contexts (e.g. when
        # only the errors module is loaded in isolation). Fall through to
        # the retryable default.
        pass
    return "retryable"


def is_no_retry(error: str | None) -> bool:
    """True when the error string carries the no-retry marker."""
    return bool(error and error.startswith(NO_RETRY_MARKER))


def format_error_for_queue(exc: BaseException) -> str:
    """Format an exception for task.error, adding the no-retry marker for
    terminal classes so the queue dead-letters instead of retrying."""
    text = str(exc) or type(exc).__name__
    if classify_error(exc) != "retryable":
        return NO_RETRY_MARKER + text
    return text
