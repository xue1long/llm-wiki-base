"""DefaultRetryPolicy — pure decision logic for retry / dead-letter.

Extracted from `update_task_status` in src/queue/queue.py:119-168. The
policy does NOT mutate task state beyond incrementing retry_count
(that's the caller's job — the policy returns a decision, the service
applies it).
"""
from __future__ import annotations
from dataclasses import dataclass

from ..types import KnowledgeTask, TaskStatus

MAX_RETRIES = 3


@dataclass
class RetryDecision:
    new_status: TaskStatus
    should_emit_dead_letter: bool
    should_pause_queue: bool
    should_record_breaker_failure: bool


class DefaultRetryPolicy:
    def decide(
        self,
        task: KnowledgeTask,
        attempted_status: TaskStatus,
        error: str | None,
        breaker,  # duck-typed: state.value, record_failure()
    ) -> RetryDecision:
        # R8: terminal (non-retryable) failures dead-letter immediately.
        # The pipeline marks deterministic errors with NO_RETRY_MARKER so a
        # bad input / data inconsistency / programming bug never burns the
        # retry ladder (audit: broad except → opaque retries).
        from ..lib.errors import is_no_retry
        if attempted_status == TaskStatus.FAILED and is_no_retry(error):
            task.retry_count += 1
            pause = getattr(breaker.state, "value", None) == "open"
            return RetryDecision(
                new_status=TaskStatus.DEAD_LETTER,
                should_emit_dead_letter=True,
                should_pause_queue=pause,
                should_record_breaker_failure=True,
            )

        if attempted_status == TaskStatus.FAILED:
            task.retry_count += 1
            if task.retry_count >= MAX_RETRIES:
                pause = getattr(breaker.state, "value", None) == "open"
                return RetryDecision(
                    new_status=TaskStatus.DEAD_LETTER,
                    should_emit_dead_letter=True,
                    should_pause_queue=pause,
                    should_record_breaker_failure=True,
                )
            return RetryDecision(
                new_status=TaskStatus.PENDING,
                should_emit_dead_letter=False,
                should_pause_queue=False,
                should_record_breaker_failure=True,
            )

        if attempted_status == TaskStatus.TIMEOUT:
            task.retry_count += 1
            if task.retry_count >= MAX_RETRIES:
                pause = getattr(breaker.state, "value", None) == "open"
                return RetryDecision(
                    new_status=TaskStatus.DEAD_LETTER,
                    should_emit_dead_letter=True,
                    should_pause_queue=pause,
                    should_record_breaker_failure=True,
                )
            return RetryDecision(
                new_status=TaskStatus.PENDING,
                should_emit_dead_letter=False,
                should_pause_queue=False,
                should_record_breaker_failure=True,
            )

        if attempted_status == TaskStatus.APPROVED:
            return RetryDecision(
                new_status=TaskStatus.APPROVED,
                should_emit_dead_letter=False,
                should_pause_queue=False,
                should_record_breaker_failure=False,
            )

        # Default: accept the attempted status as-is
        return RetryDecision(
            new_status=attempted_status,
            should_emit_dead_letter=False,
            should_pause_queue=False,
            should_record_breaker_failure=False,
        )
