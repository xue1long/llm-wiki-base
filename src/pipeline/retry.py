"""Per-request retry with exponential backoff for LLM API calls.

C1 optimization (2026-08-03): retry transient errors (server disconnect,
timeout, 5xx) with backoff; respect Retry-After on 429 rate limits;
short-circuit on permanent failures (422 content moderation); coordinate
with the circuit breaker so retries do not triple-count toward the
breaker threshold.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional, TypeVar

import httpx

_logger = logging.getLogger(__name__)

T = TypeVar("T")

# C1 backoff schedule: 2s -> 10s -> 30s (max 3 retries).
_RETRY_DELAYS: tuple[float, float, float] = (2.0, 10.0, 30.0)

# Injectable sleep hook (tests override to skip real waiting and record calls).
_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

def _unwrap_error(exc: BaseException) -> BaseException:
    """Walk the ``__cause__`` chain past ``RuntimeError`` wrappers.

    LLM providers wrap low-level httpx/network errors in
    ``RuntimeError("Xxx complete failed: ...")``.  The retry classifier
    needs to see the root cause to distinguish 429 / 422 / timeout etc.
    """
    inner = exc
    while isinstance(inner, RuntimeError) and inner.__cause__ is not None:
        inner = inner.__cause__
    return inner


def classify_error(exc: BaseException) -> str:
    """Classify an LLM-provider exception into a retry strategy.

    Returns one of:
        ``"transient"`` — server disconnect, timeout, 5xx
        ``"rate_limit"`` — HTTP 429 (wait for Retry-After)
        ``"content_moderation"`` — HTTP 422 (permanent, no retry)
        ``"permanent"`` — anything else (no retry)
    """
    inner = _unwrap_error(exc)

    # httpx.HTTPStatusError carries the response status code.
    if isinstance(inner, httpx.HTTPStatusError):
        status = inner.response.status_code
        if status == 429:
            return "rate_limit"
        if status == 422:
            return "content_moderation"
        if status >= 500:
            return "transient"
        return "permanent"

    # Connection / protocol / timeout errors are always transient.
    if isinstance(
        inner,
        (
            httpx.RemoteProtocolError,
            httpx.ReadError,
            httpx.ConnectError,
            httpx.ReadTimeout,
            httpx.PoolTimeout,
            httpx.ConnectTimeout,
            httpx.NetworkError,
        ),
    ):
        return "transient"

    # Response-body decode anomalies are protocol-level and transient:
    # a truncated mid-multibyte body (finish_reason=length cutting a CJK
    # char) or a GBK-encoded error page surfaced on a 2xx would otherwise
    # classify as permanent and never retry (phase4 batch 14).
    if isinstance(inner, UnicodeDecodeError):
        return "transient"

    # asyncio-level timeout.
    if isinstance(inner, asyncio.TimeoutError):
        return "transient"

    # Low-level OS errors (reset, broken pipe, refused).
    if isinstance(inner, (ConnectionError, OSError)):
        return "transient"

    return "permanent"


def _parse_retry_after(exc: httpx.HTTPStatusError, cap: float = 60.0) -> float:
    """Extract Retry-After header value, clamped to *cap* seconds.

    Returns 5.0 as a sensible default when the header is absent or
    unparseable.
    """
    try:
        header = exc.response.headers.get("Retry-After", "")
    except Exception:
        return 5.0
    if not header:
        return 5.0
    try:
        seconds = float(header)
    except ValueError:
        seconds = 5.0
    return min(seconds, cap)


# ---------------------------------------------------------------------------
# Public exceptions
# ---------------------------------------------------------------------------

class RetryExhausted(Exception):
    """All retry attempts exhausted for a transient error."""


class PermanentFailure(RuntimeError):
    """Non-retryable failure (e.g. HTTP 422 content moderation).

    Subclasses :class:`RuntimeError` so existing callers that catch
    ``RuntimeError`` (generator/analyzer response_format-400 downgrade,
    generic provider-error handling) keep working when a wrapped provider
    surfaces a permanent error.
    """


class CircuitBreakerOpen(Exception):
    """Circuit breaker is OPEN — skip retry, go directly to fallback."""


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

async def retry_with_backoff(
    fn: Callable[[], Awaitable[T]],
    *,
    max_retries: int = 3,
    cb_name: str = "llm",
    max_retry_after: float = 60.0,
    retry_delays: Optional[tuple[float, ...]] = None,
) -> T:
    """Retry an async callable with exponential backoff for transient errors.

    **C1 spec behaviour:**

    * Transient errors (timeout, disconnect, 5xx) → retry with delays
      2 s → 10 s → 30 s (max 3 retries).
    * HTTP 429 → parse ``Retry-After`` header (capped at *max_retry_after*),
      wait, then retry.
    * HTTP 422 → raise :exc:`PermanentFailure` immediately (no retry).
    * Circuit breaker OPEN → raise :exc:`CircuitBreakerOpen` immediately
      (no retry).

    **Circuit breaker coordination:** this helper only *checks* the
    breaker state via ``breaker.can_execute()`` before the first attempt.
    It does **not** call ``record_failure()`` or ``record_success()`` —
    those are managed externally by the caller (``run_ingest``, queue
    worker, etc.).  Retries within a single request do *not* triple-count
    toward the breaker threshold.

    Args:
        fn: Zero-argument async callable (typically a lambda wrapping
            a single LLM provider call).
        max_retries: Maximum number of retries (default 3).
        cb_name: Name of the circuit breaker to check (default ``"llm"``).
        max_retry_after: Upper bound for Retry-After header (default 60 s).
        retry_delays: Override the exponential backoff schedule. Defaults to
            ``_RETRY_DELAYS`` (2s → 10s → 30s).

    Returns:
        The return value of *fn* on success.

    Raises:
        CircuitBreakerOpen: If the circuit breaker is OPEN before the
            first attempt.
        PermanentFailure: If the error is non-retryable (HTTP 422, etc.).
        RetryExhausted: If all retries are exhausted for transient errors.
    """
    from ..circuit_breaker import get_circuit_breaker, CircuitState

    breaker = get_circuit_breaker(cb_name)

    # --- guard: circuit breaker OPEN → no retry, straight to fallback ---
    if breaker is not None and breaker.state == CircuitState.OPEN:
        raise CircuitBreakerOpen(
            f"Circuit breaker '{cb_name}' is OPEN — "
            "skipping retry, falling back to source-only page"
        )

    last_error: BaseException | None = None
    total_attempts = max_retries + 1  # initial call + retries
    delays = _RETRY_DELAYS if retry_delays is None else tuple(retry_delays)

    for attempt in range(total_attempts):
        # Re-check breaker state on each iteration (it could transition
        # from CLOSED/HALF_OPEN to OPEN while we are sleeping).
        if breaker is not None and breaker.state == CircuitState.OPEN:
            if attempt == 0:
                raise CircuitBreakerOpen(
                    f"Circuit breaker '{cb_name}' is OPEN"
                )
            # Already retrying — surface as exhausted.
            raise RetryExhausted(
                f"Circuit breaker '{cb_name}' opened during retry"
            ) from last_error

        try:
            return await fn()
        except (RetryExhausted, PermanentFailure, CircuitBreakerOpen):
            raise
        except Exception as exc:
            last_error = exc
            error_type = classify_error(exc)

            # --- 422: content moderation → permanent, no retry ---
            if error_type == "content_moderation":
                _logger.warning(
                    "[retry] attempt %d/%d: 422 content moderation — permanent",
                    attempt + 1, total_attempts,
                )
                raise PermanentFailure(
                    "HTTP 422 content moderation — source cannot be processed by LLM"
                ) from exc

            # --- permanent (any non-retryable error) ---
            if error_type == "permanent":
                _logger.warning(
                    "[retry] attempt %d/%d: permanent error (%s) — no retry",
                    attempt + 1, total_attempts, type(exc).__name__,
                )
                raise PermanentFailure(str(exc)) from exc

            # --- last attempt: no more retries ---
            if attempt == max_retries:
                _logger.error(
                    "[retry] all %d attempts exhausted (last: %s)",
                    total_attempts, type(exc).__name__,
                )
                raise RetryExhausted(
                    f"All {total_attempts} LLM call attempts exhausted"
                ) from exc

            # --- 429: rate limit → wait for Retry-After ---
            if error_type == "rate_limit":
                inner = _unwrap_error(exc)
                retry_after = 5.0
                if isinstance(inner, httpx.HTTPStatusError):
                    retry_after = _parse_retry_after(inner, cap=max_retry_after)
                _logger.info(
                    "[retry] attempt %d/%d: rate limited (429) — waiting %.1fs",
                    attempt + 1, total_attempts, retry_after,
                )
                await _sleep(retry_after)
                continue

            # --- transient: backoff ---
            delay = delays[attempt] if attempt < len(delays) else 30.0
            _logger.info(
                "[retry] attempt %d/%d: transient (%s) — retrying in %.1fs",
                attempt + 1, total_attempts, type(exc).__name__, delay,
            )
            await _sleep(delay)

    # Safety net (should be unreachable — all paths above either return,
    # continue, or raise).
    raise RetryExhausted(f"All {total_attempts} attempts exhausted") from last_error


# ---------------------------------------------------------------------------
# Provider-layer wrapper — C1 接线点统一封装（plan 1.9 review E）
# ---------------------------------------------------------------------------

class RetryLLMProvider:
    """Wrap any ``LLMProvider`` so ``complete()``/``chat()`` go through
    :func:`retry_with_backoff` (429 Retry-After / 422 permanent / transient
    backoff), with the shared ``"llm"`` circuit breaker.

    Everything else (``embed``, ``health_check``, ``check_response_format``,
    ``close``, ``model``/``config``/``_response_format_ok`` attributes) is
    transparently delegated to the inner provider.  Applying this wrapper in
    ``create_llm_provider`` covers every LLM call point at once — generator,
    analyzer (via ``BudgetedLLM``), ``c_grade_handler`` and ``QualityJudge`` —
    so no per-call-site wiring can be missed (review E / plan 1.9).
    """

    def __init__(
        self,
        inner: object,
        *,
        max_retries: int = 3,
        cb_name: str = "llm",
        max_retry_after: float = 60.0,
        retry_delays: Optional[tuple[float, ...]] = None,
    ):
        self._inner = inner
        self._max_retries = max_retries
        self._cb_name = cb_name
        self._max_retry_after = max_retry_after
        self._retry_delays = retry_delays

    # -- chat entry points go through the same retry path -------------------
    async def complete(self, messages, **kwargs):
        return await retry_with_backoff(
            lambda: self._inner.complete(messages, **kwargs),
            max_retries=self._max_retries,
            cb_name=self._cb_name,
            max_retry_after=self._max_retry_after,
            retry_delays=self._retry_delays,
        )

    async def chat(self, messages, **kwargs):
        return await self.complete(messages, **kwargs)

    # -- everything else delegates to the inner provider --------------------
    def __getattr__(self, name):
        return getattr(self._inner, name)
