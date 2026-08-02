"""Tests for src/pipeline/retry.py — C1 API retry logic.

Tests cover:
  - classify_error: transient / rate_limit / content_moderation / permanent
  - retry_with_backoff: retry on transient, 429 wait, 422 no-retry,
    circuit-breaker OPEN, all-retries-exhausted
  - Integration: run_ingest creates source-only stub page on LLM failure
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from src.pipeline.retry import (
    classify_error,
    retry_with_backoff,
    RetryExhausted,
    PermanentFailure,
    CircuitBreakerOpen,
)
from src.circuit_breaker import (
    CircuitState,
    _circuit_breakers,
    get_circuit_breaker,
)
from src.llm.base import LLMResponse
from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType
from src.wiki.storage.ensure import ensure_knowledge_base


# ===========================================================================
# Helpers
# ===========================================================================

def _runtime_with_cause(cause: BaseException) -> RuntimeError:
    """Wrap an exception as a RuntimeError (how providers surface errors)."""
    try:
        raise cause
    except Exception as _wrapped:
        _exc = RuntimeError(f"Provider failed: {cause}")
        _exc.__cause__ = _wrapped
        return _exc


def _clear_circuit_breakers():
    """Reset global circuit breaker registry between tests."""
    _circuit_breakers.clear()


# ===========================================================================
# classify_error tests
# ===========================================================================

class TestClassifyError:
    """Unit tests for error classification."""

    def test_transient_read_timeout(self):
        exc = _runtime_with_cause(httpx.ReadTimeout("timeout"))
        assert classify_error(exc) == "transient"

    def test_transient_connect_error(self):
        exc = _runtime_with_cause(httpx.ConnectError("refused"))
        assert classify_error(exc) == "transient"

    def test_transient_remote_protocol(self):
        exc = _runtime_with_cause(httpx.RemoteProtocolError("disconnect"))
        assert classify_error(exc) == "transient"

    def test_transient_500(self):
        resp = httpx.Response(500, request=httpx.Request("POST", "http://x"))
        exc = _runtime_with_cause(httpx.HTTPStatusError("server error", response=resp, request=resp.request))
        assert classify_error(exc) == "transient"

    def test_transient_503(self):
        resp = httpx.Response(503, request=httpx.Request("POST", "http://x"))
        exc = _runtime_with_cause(httpx.HTTPStatusError("unavailable", response=resp, request=resp.request))
        assert classify_error(exc) == "transient"

    def test_transient_asyncio_timeout(self):
        """asyncio.TimeoutError inside RuntimeError -> transient."""
        exc = _runtime_with_cause(asyncio.TimeoutError())
        assert classify_error(exc) == "transient"

    def test_transient_connection_reset(self):
        exc = _runtime_with_cause(ConnectionResetError())
        assert classify_error(exc) == "transient"

    def test_rate_limit_429(self):
        resp = httpx.Response(429, request=httpx.Request("POST", "http://x"))
        exc = _runtime_with_cause(httpx.HTTPStatusError("rate limited", response=resp, request=resp.request))
        assert classify_error(exc) == "rate_limit"

    def test_content_moderation_422(self):
        resp = httpx.Response(422, request=httpx.Request("POST", "http://x"))
        exc = _runtime_with_cause(httpx.HTTPStatusError("moderation", response=resp, request=resp.request))
        assert classify_error(exc) == "content_moderation"

    def test_permanent_400(self):
        resp = httpx.Response(400, request=httpx.Request("POST", "http://x"))
        exc = _runtime_with_cause(httpx.HTTPStatusError("bad request", response=resp, request=resp.request))
        assert classify_error(exc) == "permanent"

    def test_permanent_value_error(self):
        """A ValueError (not httpx-related) is permanent."""
        exc = ValueError("unexpected")
        assert classify_error(exc) == "permanent"

    def test_direct_runtime_error_no_cause(self):
        """Bare RuntimeError with no __cause__ is permanent."""
        exc = RuntimeError("something went wrong")
        assert classify_error(exc) == "permanent"


# ===========================================================================
# retry_with_backoff tests
# ===========================================================================

class TestRetryWithBackoff:
    """Async tests for the retry helper."""

    @pytest.mark.asyncio
    async def test_success_first_attempt(self):
        """Callable succeeds on first attempt -- no retries."""
        call_count = 0

        async def _fn():
            nonlocal call_count
            call_count += 1
            return "ok"

        _clear_circuit_breakers()
        result = await retry_with_backoff(_fn, cb_name="test_success")
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_transient_succeeds_second_attempt(self):
        """Transient error on 1st attempt, succeeds on 2nd."""
        call_count = 0

        async def _fn():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise _runtime_with_cause(httpx.ReadTimeout("timeout"))
            return "ok"

        _clear_circuit_breakers()
        result = await retry_with_backoff(_fn, cb_name="test_transient")
        assert result == "ok"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_422_no_retry(self):
        """HTTP 422 -> PermanentFailure immediately, no retries."""
        call_count = 0

        async def _fn():
            nonlocal call_count
            call_count += 1
            resp = httpx.Response(422, request=httpx.Request("POST", "http://x"))
            raise _runtime_with_cause(
                httpx.HTTPStatusError("moderation", response=resp, request=resp.request)
            )

        _clear_circuit_breakers()
        with pytest.raises(PermanentFailure, match="422"):
            await retry_with_backoff(_fn, cb_name="test_422")
        assert call_count == 1, "422 must not retry"

    @pytest.mark.asyncio
    async def test_429_with_retry_after_header(self):
        """HTTP 429 with Retry-After header -- waits, then retries."""
        call_count = 0

        async def _fn():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                resp = httpx.Response(
                    429,
                    headers={"Retry-After": "0.1"},
                    request=httpx.Request("POST", "http://x"),
                )
                raise _runtime_with_cause(
                    httpx.HTTPStatusError("rate limited", response=resp, request=resp.request)
                )
            return "ok"

        _clear_circuit_breakers()
        result = await retry_with_backoff(_fn, cb_name="test_429")
        assert result == "ok"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_all_retries_exhausted(self):
        """Transient error every time -> RetryExhausted after max_retries+1."""
        call_count = 0

        async def _fn():
            nonlocal call_count
            call_count += 1
            raise _runtime_with_cause(httpx.ReadTimeout("timeout"))

        _clear_circuit_breakers()
        with pytest.raises(RetryExhausted, match="exhausted"):
            await retry_with_backoff(_fn, max_retries=2, cb_name="test_exhaust")
        assert call_count == 3  # initial + 2 retries

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_no_retry(self):
        """Circuit breaker OPEN -> CircuitBreakerOpen immediately."""
        _clear_circuit_breakers()
        breaker = get_circuit_breaker("test_open")
        breaker._transition_to(CircuitState.OPEN)

        call_count = 0

        async def _fn():
            nonlocal call_count
            call_count += 1
            return "should not reach"

        with pytest.raises(CircuitBreakerOpen, match="OPEN"):
            await retry_with_backoff(_fn, cb_name="test_open")
        assert call_count == 0, "must not call fn when breaker is OPEN"

    @pytest.mark.asyncio
    async def test_permanent_error_no_retry(self):
        """A permanent error (400) -> PermanentFailure, no retry."""
        call_count = 0

        async def _fn():
            nonlocal call_count
            call_count += 1
            resp = httpx.Response(400, request=httpx.Request("POST", "http://x"))
            raise _runtime_with_cause(
                httpx.HTTPStatusError("bad request", response=resp, request=resp.request)
            )

        _clear_circuit_breakers()
        with pytest.raises(PermanentFailure):
            await retry_with_backoff(_fn, cb_name="test_perm")
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_does_not_count_toward_circuit_breaker(self):
        """Retry failures do NOT feed the breaker -- it only checks state."""
        _clear_circuit_breakers()
        breaker = get_circuit_breaker("test_nocount")
        assert breaker.failure_count == 0

        call_count = 0

        async def _fn():
            nonlocal call_count
            call_count += 1
            raise _runtime_with_cause(httpx.ReadTimeout("timeout"))

        with pytest.raises(RetryExhausted):
            await retry_with_backoff(_fn, max_retries=2, cb_name="test_nocount")

        # Breaker failure_count must still be 0 -- retry doesn't feed it.
        assert breaker.failure_count == 0
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_exponential_backoff_sequence(self):
        """Retry delays follow the C1 spec: 2s -> 10s -> 30s."""
        call_count = 0

        async def _fn():
            nonlocal call_count
            call_count += 1
            raise _runtime_with_cause(httpx.ReadTimeout("timeout"))

        _clear_circuit_breakers()
        # Intercept asyncio.sleep to record delays without actually waiting.
        sleeps = []

        async def _record(delay):
            sleeps.append(delay)

        with patch("asyncio.sleep", side_effect=_record):
            with pytest.raises(RetryExhausted):
                await retry_with_backoff(_fn, max_retries=3, cb_name="test_delays")

        assert call_count == 4
        assert sleeps == [2.0, 10.0, 30.0], (
            f"Expected [2.0, 10.0, 30.0], got {sleeps}"
        )


# ===========================================================================
# _create_source_only_page helper tests
# ===========================================================================

class TestCreateSourceOnlyPage:
    """Verify the source-only stub page format matches the C1 spec."""

    def test_creates_page_with_correct_format(self, tmp_path: Path):
        """Source-only page: grade=C, processing_depth=stub, body <= 2000 chars."""
        from src.pipeline.ingest import _create_source_only_page

        ensure_knowledge_base(tmp_path)
        paths = WikiPaths(tmp_path)
        raw = tmp_path / "fallback.md"
        raw.write_text("正文内容" * 500, encoding="utf-8")  # long text

        pages = _create_source_only_page(
            paths, raw, raw.read_text(encoding="utf-8"), "kb-fb-001", reason="测试失败"
        )
        assert len(pages) == 1
        page = pages[0]

        assert page.type == PageType.SOURCE
        assert page.grade == "C"
        assert page.processing_depth == "stub"
        assert "## 来源" in page.body
        assert "## 内容" in page.body
        assert "LLM 处理失败" in page.body
        assert "测试失败" in page.body
        # Body text (without metadata) should be <= 2000 chars
        assert len(page.body) < 3000  # metadata + body


# ===========================================================================
# Integration: run_ingest creates source-only stub page on LLM failure
# ===========================================================================

class TestRunIngestRetryFallback:
    """When the LLM fails permanently, run_ingest creates a source-only page."""

    @pytest.fixture(autouse=True)
    def _reset_breakers(self):
        """Reset circuit breakers before AND after each test.

        Prevents state leakage to other test modules that use the same
        breaker name (""ingest_llm"").
        """
        _clear_circuit_breakers()
        yield
        _clear_circuit_breakers()

    @pytest.mark.asyncio
    async def test_all_retries_exhausted_creates_source_only_stub(self, tmp_path: Path):
        """All LLM retries exhausted -> source-only stub (grade=C, depth=stub)."""
        ensure_knowledge_base(tmp_path)
        paths = WikiPaths(tmp_path)
        raw = paths.raw_sources / "retry-fail.md"
        raw.parent.mkdir(parents=True, exist_ok=True)
        source_text = "这是需要LLM处理的测试文档" * 20
        raw.write_text(source_text, encoding="utf-8")

        # Provider that always fails with a transient error.  The outer
        # run_ingest catches the retry failure and creates a stub.
        from src.shared.test_helpers import ScriptedLLMProvider

        class _AlwaysTimeoutProvider(ScriptedLLMProvider):
            async def complete(self, messages=None, **kwargs):
                self.calls.append({"messages": messages} if messages else {})
                raise _runtime_with_cause(httpx.ReadTimeout("timeout"))

        provider = _AlwaysTimeoutProvider([])

        # Patch the in-module retry_with_backoff to use max_retries=0
        # so the test doesn't actually sleep through the backoff delays.
        import src.pipeline.ingest as _ingest_mod
        import src.pipeline.retry as _retry_mod

        async def _fast_exhaust(fn, *, max_retries=0, cb_name="ingest_llm", **kw):
            return await _retry_mod.retry_with_backoff(
                fn, max_retries=0, cb_name=cb_name
            )

        with patch.object(_ingest_mod, "retry_with_backoff", side_effect=_fast_exhaust):
            pages = await _ingest_mod.run_ingest(
                paths=paths,
                source_path=raw,
                source_text=source_text,
                provider=provider,
                task_id="kb-retry-001",
            )

        assert len(pages) == 1
        page = pages[0]
        assert page.type == PageType.SOURCE
        assert page.grade == "C"
        assert page.processing_depth == "stub", (
            f"Expected 'stub', got '{page.processing_depth}'"
        )
        assert "## 来源" in page.body
        assert "## 内容" in page.body

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_creates_source_only_stub(self, tmp_path: Path):
        """Circuit breaker OPEN -> source-only stub without calling LLM."""
        ensure_knowledge_base(tmp_path)
        paths = WikiPaths(tmp_path)
        raw = paths.raw_sources / "cb-open.md"
        raw.parent.mkdir(parents=True, exist_ok=True)
        source_text = "电路断路器开启场景测试" * 20
        raw.write_text(source_text, encoding="utf-8")

        # Force circuit breaker to OPEN state.
        _clear_circuit_breakers()
        breaker = get_circuit_breaker("ingest_llm")
        breaker._transition_to(CircuitState.OPEN)

        from src.shared.test_helpers import ScriptedLLMProvider
        provider = ScriptedLLMProvider([{"pages": []}])

        import src.pipeline.ingest as _ingest_mod

        pages = await _ingest_mod.run_ingest(
            paths=paths,
            source_path=raw,
            source_text=source_text,
            provider=provider,
            task_id="kb-cb-001",
        )

        assert len(pages) == 1
        page = pages[0]
        assert page.type == PageType.SOURCE
        assert page.grade == "C"
        assert page.processing_depth == "stub"

    @pytest.mark.asyncio
    async def test_permanent_422_creates_source_only_stub(self, tmp_path: Path):
        """HTTP 422 content moderation -> source-only stub."""
        ensure_knowledge_base(tmp_path)
        paths = WikiPaths(tmp_path)
        raw = paths.raw_sources / "moderation.md"
        raw.parent.mkdir(parents=True, exist_ok=True)
        source_text = "可能触发审核的内容" * 30
        raw.write_text(source_text, encoding="utf-8")

        from src.shared.test_helpers import ScriptedLLMProvider

        class _ModerationProvider(ScriptedLLMProvider):
            async def complete(self, messages=None, **kwargs):
                self.calls.append({"messages": messages} if messages else {})
                resp = httpx.Response(422, request=httpx.Request("POST", "http://x"))
                raise _runtime_with_cause(
                    httpx.HTTPStatusError("moderation", response=resp, request=resp.request)
                )

        provider = _ModerationProvider([])

        import src.pipeline.ingest as _ingest_mod

        pages = await _ingest_mod.run_ingest(
            paths=paths,
            source_path=raw,
            source_text=source_text,
            provider=provider,
            task_id="kb-mod-001",
        )

        assert len(pages) == 1
        page = pages[0]
        assert page.type == PageType.SOURCE
        assert page.grade == "C"
        assert page.processing_depth == "stub"
