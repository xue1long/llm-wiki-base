"""R8 — fault classification: retryable vs terminal errors.

Audit finding: a broad `except Exception` collapsed configuration errors,
data errors, dependency faults and programming bugs into the same
FAILED→retry path. R8 introduces a minimal taxonomy and wires it into
the queue retry policy:

- RetryableDependencyError   → FAILED (queue retries; network/transient)
- InvalidInputError          → DEAD_LETTER (no retry; deterministic input)
- DataConsistencyError       → DEAD_LETTER (no retry; corrupt/partial state)
- ProgrammingError           → DEAD_LETTER (no retry; a bug, not a fault)

The retry policy reads the error string marker `[no-retry]` set by the
pipeline when it classifies a terminal error, so no schema change to
KnowledgeTask is needed.
"""
import pytest

from src.lib.errors import (
    DataConsistencyError,
    InvalidInputError,
    ProgrammingError,
    RetryableDependencyError,
    classify_error,
    is_no_retry,
    NO_RETRY_MARKER,
)
from src.queue.retry import DefaultRetryPolicy, MAX_RETRIES
from src.types import KnowledgeTask, SourceType, TaskStatus


# ---------------------------------------------------------------------------
# 1. taxonomy
# ---------------------------------------------------------------------------

def test_classify_retryable():
    e = RetryableDependencyError("provider timeout")
    assert classify_error(e) == "retryable"
    assert not is_no_retry(str(e))


def test_classify_invalid_input():
    from src.lib.errors import format_error_for_queue
    e = InvalidInputError("bad source path")
    assert classify_error(e) == "invalid_input"
    assert is_no_retry(format_error_for_queue(e))


def test_classify_data_consistency():
    from src.lib.errors import format_error_for_queue
    e = DataConsistencyError("index out of sync")
    assert classify_error(e) == "data_consistency"
    assert is_no_retry(format_error_for_queue(e))


def test_classify_programming():
    from src.lib.errors import format_error_for_queue
    e = ProgrammingError("NoneType has no attribute")
    assert classify_error(e) == "programming"
    assert is_no_retry(format_error_for_queue(e))


def test_classify_unknown_defaults_retryable():
    """Unknown exceptions default to retryable (fail-open, back-compat)."""
    assert classify_error(RuntimeError("weird")) == "retryable"


def test_retryable_error_inherits_runtimeerror():
    with pytest.raises(RuntimeError):
        raise RetryableDependencyError("boom")


def test_marker_roundtrip():
    msg = NO_RETRY_MARKER + " bad input"
    assert is_no_retry(msg)


# ---------------------------------------------------------------------------
# 2. retry policy honours no-retry marker
# ---------------------------------------------------------------------------

def _task(retries=0):
    return KnowledgeTask(
        id="t1", source="x", source_type=SourceType.FILE,
        status=TaskStatus.FAILED, task_hash="h", created_at=1, updated_at=1,
        retry_count=retries,
    )


class _Breaker:
    class _State:
        value = "closed"
    state = _State()

    def record_failure(self):
        pass


def test_policy_dead_letters_no_retry_immediately():
    """A no-retry error goes straight to DEAD_LETTER, skipping retries."""
    task = _task(retries=0)
    decision = DefaultRetryPolicy().decide(
        task, TaskStatus.FAILED, NO_RETRY_MARKER + " invalid", _Breaker(),
    )
    assert decision.new_status == TaskStatus.DEAD_LETTER
    assert decision.should_emit_dead_letter is True


def test_policy_retries_retryable_error():
    """A retryable error follows the normal retry ladder."""
    task = _task(retries=0)
    decision = DefaultRetryPolicy().decide(
        task, TaskStatus.FAILED, "provider timeout", _Breaker(),
    )
    assert decision.new_status == TaskStatus.PENDING


def test_policy_retryable_exhausts_to_dead_letter():
    """Retryable errors still dead-letter after MAX_RETRIES."""
    task = _task(retries=MAX_RETRIES)
    decision = DefaultRetryPolicy().decide(
        task, TaskStatus.FAILED, "provider timeout", _Breaker(),
    )
    assert decision.new_status == TaskStatus.DEAD_LETTER


# ---------------------------------------------------------------------------
# 3. pipeline integration marker
# ---------------------------------------------------------------------------

def test_format_error_for_queue_marks_terminal():
    """format_error_for_queue adds the no-retry marker for terminal classes."""
    from src.lib.errors import format_error_for_queue

    msg = format_error_for_queue(InvalidInputError("bad input"))
    assert is_no_retry(msg)

    msg2 = format_error_for_queue(RetryableDependencyError("timeout"))
    assert not is_no_retry(msg2)
