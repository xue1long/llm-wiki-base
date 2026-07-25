"""Tests for DefaultRetryPolicy — pure retry/dead-letter decision logic.

The policy decides what happens after a task status change attempt:
- FAILED (or TIMEOUT) under retry_count < MAX_RETRIES  → reset to PENDING
- FAILED (or TIMEOUT) at retry_count >= MAX_RETRIES    → DEAD_LETTER
- APPROVED                                             → stays APPROVED
- Other transitions                                   → stays as attempted
"""
import pytest

from src.queue.retry import DefaultRetryPolicy, RetryDecision, MAX_RETRIES
from src.types import KnowledgeTask, SourceType, TaskStatus


class _FakeBreaker:
    def __init__(self, state_value="closed"):
        self.state = type("S", (), {"value": state_value})()


def _mk_task(retry_count: int = 0) -> KnowledgeTask:
    return KnowledgeTask(
        id="t1", source="x", source_type=SourceType.FILE,
        status=TaskStatus.FAILED, task_hash="h", created_at=0, updated_at=0,
        retry_count=retry_count,
    )


class TestDefaultRetryPolicy:
    def test_first_failed_resets_to_pending(self):
        task = _mk_task(retry_count=0)
        decision = DefaultRetryPolicy().decide(
            task, TaskStatus.FAILED, error="boom", breaker=_FakeBreaker(),
        )
        assert decision.new_status == TaskStatus.PENDING
        assert decision.should_emit_dead_letter is False
        assert decision.should_pause_queue is False
        assert decision.should_record_breaker_failure is True
        assert task.retry_count == 1  # incremented

    def test_failed_at_max_retries_goes_to_dead_letter(self):
        # retry_count starts at MAX_RETRIES-1, then policy increments to MAX_RETRIES
        task = _mk_task(retry_count=MAX_RETRIES - 1)
        decision = DefaultRetryPolicy().decide(
            task, TaskStatus.FAILED, error="again", breaker=_FakeBreaker(),
        )
        assert decision.new_status == TaskStatus.DEAD_LETTER
        assert decision.should_emit_dead_letter is True
        assert decision.should_record_breaker_failure is True
        assert task.retry_count == MAX_RETRIES

    def test_failed_with_open_breaker_pauses_queue(self):
        task = _mk_task(retry_count=MAX_RETRIES - 1)
        decision = DefaultRetryPolicy().decide(
            task, TaskStatus.FAILED, error="again",
            breaker=_FakeBreaker(state_value="open"),
        )
        assert decision.new_status == TaskStatus.DEAD_LETTER
        assert decision.should_pause_queue is True

    def test_timeout_treated_like_failed(self):
        task = _mk_task(retry_count=0)
        decision = DefaultRetryPolicy().decide(
            task, TaskStatus.TIMEOUT, error="timeout", breaker=_FakeBreaker(),
        )
        assert decision.new_status == TaskStatus.PENDING
        assert decision.should_emit_dead_letter is False

    def test_approved_does_not_retry(self):
        task = _mk_task(retry_count=0)
        decision = DefaultRetryPolicy().decide(
            task, TaskStatus.APPROVED, error=None, breaker=_FakeBreaker(),
        )
        assert decision.new_status == TaskStatus.APPROVED
        assert decision.should_emit_dead_letter is False
        assert decision.should_record_breaker_failure is False
        assert task.retry_count == 0  # not incremented

    def test_max_retries_constant_is_three(self):
        # Locked at 3 by historical convention; bumping requires separate
        # change in CLAUDE.md + tests.
        assert MAX_RETRIES == 3
