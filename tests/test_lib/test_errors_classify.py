"""Classify error taxonomy tests — covers retry/dead-letter routing.

The four explicit taxonomy classes (``RetryableDependencyError``,
``InvalidInputError``, ``DataConsistencyError``, ``ProgrammingError``) are
mapped to non-retryable by ``classify_error``. The fifth non-retryable
class is ``pipeline.retry.PermanentFailure`` — a surface error raised
by the LLM client layer (HTTP 422 content moderation, irrecoverable
response-shape failure). It must NOT be retried by the queue's
DefaultRetryPolicy.

Regression target: prior to this classification, ``PermanentFailure`` was a
``RuntimeError`` (paradoxically retryable). ``format_error_for_queue``
emitted the plain exception text without the ``[no-retry]`` marker,
``DefaultRetryPolicy.decide`` saw a non-no-retry FAILED and retried it 3
times before dead-lettering — burning 3 LLM calls per source before
giving up.
"""

from __future__ import annotations


def test_permanent_failure_classifies_as_no_retry():
    from src.pipeline.retry import PermanentFailure
    from src.lib.errors import classify_error

    exc = PermanentFailure("HTTP 422 content moderation")
    assert classify_error(exc) == "no_retry"


def test_permanent_failure_is_marked_no_retry_in_format_for_queue():
    """``format_error_for_queue`` must prepend the no-retry marker so
    ``DefaultRetryPolicy.decide`` dead-letters on first attempt."""
    from src.pipeline.retry import PermanentFailure
    from src.lib.errors import NO_RETRY_MARKER, format_error_for_queue, is_no_retry

    exc = PermanentFailure("HTTP 422 content moderation — blocked")
    formatted = format_error_for_queue(exc)

    assert formatted.startswith(NO_RETRY_MARKER), (
        f"expected no-retry marker, got {formatted!r}"
    )
    assert is_no_retry(formatted)
    assert "HTTP 422 content moderation" in formatted


def test_explicit_taxonomy_classes_still_classify_correctly():
    """Sanity guard: explicit taxonomy classes keep their classifications
    after the PermanentFailure addition."""
    from src.lib.errors import (
        DataConsistencyError,
        InvalidInputError,
        ProgrammingError,
        RetryableDependencyError,
        classify_error,
    )

    assert classify_error(RetryableDependencyError("transient")) == "retryable"
    assert classify_error(InvalidInputError("bad")) == "invalid_input"
    assert classify_error(DataConsistencyError("drift")) == "data_consistency"
    assert classify_error(ProgrammingError("bug")) == "programming"


def test_unknown_exception_still_defaults_to_retryable():
    """Back-compat: anything not in the taxonomy is retryable."""
    from src.lib.errors import classify_error

    assert classify_error(RuntimeError("mystery")) == "retryable"
    assert classify_error(ValueError("bad input shape")) == "retryable"


def test_permanent_failure_subclasses_count_as_no_retry():
    """``PermanentFailure`` is sometimes wrapped by callers (e.g.
    provider-level catch blocks) — isinstance must walk the MRO."""
    from src.pipeline.retry import PermanentFailure
    from src.lib.errors import classify_error

    class ProviderSpecificBlock(PermanentFailure):
        pass

    assert classify_error(ProviderSpecificBlock("provider says no")) == "no_retry"
