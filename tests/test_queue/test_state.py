"""Tests for queue state machine — pure functions, no IO.

The legal-transition matrix below mirrors `src/queue/state.py:_LEGAL`,
which is the production matrix (same as the previous
`src/orchestrator/state_machine.py:VALID_TRANSITIONS`). Tests cover the
15 legal edges plus the terminal/blocked ones.
"""
import pytest

from src.queue.state import can_transition, InvalidTransition
from src.types import TaskStatus


class TestCanTransition:
    # --- Legal transitions from PENDING ---
    def test_pending_to_running_allowed(self):
        assert can_transition(TaskStatus.PENDING, TaskStatus.RUNNING) is True

    # --- Legal transitions from RUNNING ---
    def test_running_to_waiting_review_allowed(self):
        assert can_transition(TaskStatus.RUNNING, TaskStatus.WAITING_REVIEW) is True

    def test_running_to_approved_allowed(self):
        assert can_transition(TaskStatus.RUNNING, TaskStatus.APPROVED) is True

    def test_running_to_failed_allowed(self):
        assert can_transition(TaskStatus.RUNNING, TaskStatus.FAILED) is True

    # --- Legal transitions from WAITING_REVIEW ---
    def test_waiting_review_to_approved_allowed(self):
        assert can_transition(TaskStatus.WAITING_REVIEW, TaskStatus.APPROVED) is True

    def test_waiting_review_to_rejected_allowed(self):
        assert can_transition(TaskStatus.WAITING_REVIEW, TaskStatus.REJECTED) is True

    # --- Legal transitions from REJECTED ---
    def test_rejected_to_pending_allowed(self):
        assert can_transition(TaskStatus.REJECTED, TaskStatus.PENDING) is True

    def test_rejected_to_archived_allowed(self):
        assert can_transition(TaskStatus.REJECTED, TaskStatus.ARCHIVED) is True

    # --- Legal transitions from APPROVED ---
    def test_approved_to_archived_allowed(self):
        assert can_transition(TaskStatus.APPROVED, TaskStatus.ARCHIVED) is True

    # --- Legal transitions from FAILED ---
    def test_failed_to_pending_allowed(self):
        assert can_transition(TaskStatus.FAILED, TaskStatus.PENDING) is True

    def test_failed_to_archived_allowed(self):
        assert can_transition(TaskStatus.FAILED, TaskStatus.ARCHIVED) is True

    def test_failed_to_dead_letter_allowed(self):
        assert can_transition(TaskStatus.FAILED, TaskStatus.DEAD_LETTER) is True

    # --- Legal transitions from TIMEOUT ---
    def test_timeout_to_pending_allowed(self):
        assert can_transition(TaskStatus.TIMEOUT, TaskStatus.PENDING) is True

    def test_timeout_to_archived_allowed(self):
        assert can_transition(TaskStatus.TIMEOUT, TaskStatus.ARCHIVED) is True

    def test_timeout_to_dead_letter_allowed(self):
        assert can_transition(TaskStatus.TIMEOUT, TaskStatus.DEAD_LETTER) is True

    # --- Illegal / blocked transitions ---
    def test_pending_to_approved_blocked(self):
        assert can_transition(TaskStatus.PENDING, TaskStatus.APPROVED) is False

    def test_approved_to_running_blocked_terminal(self):
        assert can_transition(TaskStatus.APPROVED, TaskStatus.RUNNING) is False

    def test_dead_letter_is_terminal(self):
        for next_status in [TaskStatus.PENDING, TaskStatus.RUNNING,
                            TaskStatus.APPROVED, TaskStatus.FAILED]:
            assert can_transition(TaskStatus.DEAD_LETTER, next_status) is False


class TestInvalidTransition:
    def test_message_includes_all_three(self):
        with pytest.raises(InvalidTransition) as exc_info:
            raise InvalidTransition("task-1", "pending", "approved")
        assert exc_info.value.args == ("task-1", "pending", "approved")

    def test_is_an_exception(self):
        assert issubclass(InvalidTransition, Exception)