"""Minimal synchronous retry primitive."""
from collections.abc import Callable
from time import sleep as _sleep


class RetryExhausted(Exception):
    def __init__(self, attempts: int, last_exc: BaseException):
        self.attempts = attempts
        self.last_exc = last_exc
        super().__init__(f"retry exhausted after {attempts} attempts: {last_exc}")


def retry_with_backoff(
    operation: Callable[[], object],
    *,
    max_attempts: int = 3,
    base_delay_s: float = 0.1,
    max_delay_s: float = 60.0,
    backoff: float = 2.0,
    retry_on: tuple[type[BaseException], ...] = (OSError,),
    sleep: Callable[[float], None] = _sleep,
) -> object:
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except retry_on as exc:
            if attempt == max_attempts:
                raise RetryExhausted(attempt, exc) from exc
            sleep(min(max_delay_s, base_delay_s * backoff ** (attempt - 1)))
    raise AssertionError("unreachable")
