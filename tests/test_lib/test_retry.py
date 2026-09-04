import pytest

from src.lib.retry import RetryExhausted, retry_with_backoff


def test_retries_selected_errors_and_returns_result():
    calls = []
    sleeps = []

    def operation():
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError("busy")
        return "ok"

    assert retry_with_backoff(
        operation, max_attempts=3, base_delay_s=0.1, backoff=2, sleep=sleeps.append
    ) == "ok"
    assert len(calls) == 3
    assert sleeps == [0.1, 0.2]


def test_non_retryable_error_escapes_immediately():
    with pytest.raises(ValueError):
        retry_with_backoff(lambda: (_ for _ in ()).throw(ValueError("bad")))


def test_exhaustion_preserves_attempt_count_and_last_error():
    error = OSError("still busy")

    def operation():
        raise error

    with pytest.raises(RetryExhausted) as caught:
        retry_with_backoff(operation, max_attempts=2, sleep=lambda _: None)
    assert caught.value.attempts == 2
    assert caught.value.last_exc is error
