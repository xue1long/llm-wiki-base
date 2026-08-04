"""Rate limiter for LLM API calls with exponential backoff.

Handles 429 Too Many Requests and rate limit errors with automatic retry.

Configuration:
    RUFLO_LLM_MAX_RETRIES: Maximum retry attempts (default: 3)
    RUFLO_LLM_RETRY_BASE_DELAY: Base delay in seconds (default: 1.0)
    RUFLO_LLM_RETRY_MAX_DELAY: Maximum delay cap in seconds (default: 60.0)
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from functools import wraps
from typing import Callable, TypeVar, ParamSpec

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")

# Configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 60.0

# Patterns indicating rate limit errors
RATE_LIMIT_PATTERNS = [
    r"429",
    r"rate.?limit",
    r"too many requests",
    r"requests per minute",
    r"requests per second",
    r"rate limit exceeded",
    r"throttl",
]


def _is_rate_limit_error(error: Exception) -> bool:
    """Check if an error indicates a rate limit issue."""
    error_str = str(error).lower()

    for pattern in RATE_LIMIT_PATTERNS:
        if re.search(pattern, error_str):
            return True

    # Check for specific error types
    error_type = type(error).__name__.lower()
    if "ratelimit" in error_type or "throttle" in error_type:
        return True

    return False


def _extract_retry_after(error: Exception) -> float | None:
    """Extract retry-after delay from error if available."""
    error_str = str(error)

    # Common patterns
    patterns = [
        r"retry.?after[:\s]+(\d+(?:\.\d+)?)",
        r"wait[:\s]+(\d+(?:\.\d+)?)\s*s",
        r"retry in[:\s]+(\d+(?:\.\d+)?)\s*s",
    ]

    for pattern in patterns:
        match = re.search(pattern, error_str, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except (ValueError, IndexError):
                pass

    return None


def with_rate_limit_retry(
    max_retries: int | None = None,
    base_delay: float | None = None,
    max_delay: float | None = None,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorator for automatic rate limit retry with exponential backoff.

    Args:
        max_retries: Maximum retry attempts. None uses env var RUFLO_LLM_MAX_RETRIES
        base_delay: Base delay in seconds. None uses env var RUFLO_LLM_RETRY_BASE_DELAY
        max_delay: Maximum delay cap. None uses env var RUFLO_LLM_RETRY_MAX_DELAY

    Returns:
        Decorated function with retry logic

    Example:
        @with_rate_limit_retry(max_retries=3)
        async def call_llm(prompt: str) -> str:
            return await provider.complete(prompt)
    """
    # Resolve configuration
    _max_retries = max_retries or int(
        os.environ.get("RUFLO_LLM_MAX_RETRIES", str(DEFAULT_MAX_RETRIES))
    )
    _base_delay = base_delay or float(
        os.environ.get("RUFLO_LLM_RETRY_BASE_DELAY", str(DEFAULT_BASE_DELAY))
    )
    _max_delay = max_delay or float(
        os.environ.get("RUFLO_LLM_RETRY_MAX_DELAY", str(DEFAULT_MAX_DELAY))
    )

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            last_error: Exception | None = None

            for attempt in range(_max_retries + 1):
                try:
                    return await func(*args, **kwargs)  # type: ignore[misc]

                except Exception as e:
                    # Check if this is a rate limit error
                    if not _is_rate_limit_error(e):
                        # Not a rate limit error - re-raise immediately
                        raise

                    last_error = e

                    # Check if we've exhausted retries
                    if attempt >= _max_retries:
                        logger.error(
                            "[RateLimit] Max retries (%d) exceeded for %s",
                            _max_retries, func.__name__
                        )
                        raise RuntimeError(
                            f"Rate limit max retries ({_max_retries}) exceeded: {e}"
                        ) from e

                    # Calculate delay with exponential backoff
                    delay = min(_base_delay * (2 ** attempt), _max_delay)

                    # Check for Retry-After header in error
                    retry_after = _extract_retry_after(e)
                    if retry_after is not None:
                        delay = min(retry_after, _max_delay)

                    logger.warning(
                        "[RateLimit] API rate limited, retrying in %.1fs "
                        "(attempt %d/%d): %s",
                        delay, attempt + 1, _max_retries + 1, str(e)[:100]
                    )

                    await asyncio.sleep(delay)

            # Should never reach here, but satisfy type checker
            if last_error:
                raise last_error
            raise RuntimeError("Unexpected state in rate limit retry")

        @wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            """Sync wrapper - not recommended, use async version."""
            raise RuntimeError(
                "with_rate_limit_retry only supports async functions. "
                "Wrap the sync function in async."
            )

        # Return appropriate wrapper based on function type
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        else:
            return sync_wrapper  # type: ignore[return-value]

    return decorator


class RateLimitError(Exception):
    """Raised when rate limit is hit and retries are exhausted."""

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


# Convenience function for manual retry logic
async def retry_with_backoff(
    func: Callable[[], T],
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    is_retryable: Callable[[Exception], bool] | None = None,
) -> T:
    """Execute a function with exponential backoff retry.

    Args:
        func: Async function to execute
        max_retries: Maximum retry attempts
        base_delay: Base delay in seconds
        max_delay: Maximum delay cap
        is_retryable: Optional function to check if error is retryable.
                      Default: check for rate limit errors.

    Returns:
        Result of func()

    Raises:
        Exception: If all retries fail

    Example:
        result = await retry_with_backoff(
            lambda: provider.complete(prompt),
            max_retries=5
        )
    """
    _is_retryable = is_retryable or _is_rate_limit_error
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            result = await func()
            return result

        except Exception as e:
            if not _is_retryable(e):
                raise

            last_error = e

            if attempt >= max_retries:
                raise

            delay = min(base_delay * (2 ** attempt), max_delay)

            retry_after = _extract_retry_after(e)
            if retry_after is not None:
                delay = min(retry_after, max_delay)

            logger.warning(
                "[RetryBackoff] Attempt %d/%d failed, retrying in %.1fs: %s",
                attempt + 1, max_retries + 1, delay, str(e)[:100]
            )

            await asyncio.sleep(delay)

    # Should never reach here
    if last_error:
        raise last_error
    raise RuntimeError("Unexpected state in retry_with_backoff")