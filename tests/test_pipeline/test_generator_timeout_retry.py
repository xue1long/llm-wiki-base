"""Regression tests for the batch-0 hang: LLM call failure convergence.

batch 0 (2026-08-01) hung because a non-timeout LLM exception (empty
``str``) fell into ``_call_with_slot_retry``'s catch-all
``except (ValueError, Exception)`` and was retried 3× with a 600s HTTP
timeout that may never fire — a single file could hang for ~30min.

This locks in:
  1. Non-JSON / non-timeout LLM errors are NOT retried — they propagate
     immediately so the batch runner can fail the file fast.
  2. JSON parse errors ARE retried (up to MAX_GEN_ATTEMPTS) then raise.
  3. ReadTimeout / ConnectError ARE retried (up to MAX_GEN_ATTEMPTS) then
     raise — the existing time-out behaviour is preserved.
"""
import asyncio

import httpx
import pytest

from src.llm.base import LLMResponse
from src.wiki.core.types import PageType
from src.pipeline.generator import _call_with_slot_retry
from src.pipeline.ingest import _with_llm_timeout


class _ScriptedProvider:
    """Provider that replays a script of outcomes, recording call count."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)  # callable or exception
        self.calls = 0

    async def complete(self, messages, **kwargs):
        self.calls += 1
        if not self.outcomes:
            raise RuntimeError("out of scripted outcomes")
        item = self.outcomes.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _default_kwargs():
    return dict(
        base_prompt="test prompt",
        response_format={"type": "json_object"},
        required_slots_by_type={PageType.ENTITY: ["basic_info"]},
        timeout=30.0,
    )


# ---------------------------------------------------------------------------
# 1. Non-JSON / non-timeout errors propagate immediately (no retry)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_provider_runtime_error_not_retried():
    """A non-JSON LLM failure (e.g. ``RuntimeError('OpenAI complete failed')``)
    must propagate on the first call — the batch runner then fails the file
    fast instead of hanging on retries."""
    err = RuntimeError("OpenAI complete failed: ")
    provider = _ScriptedProvider([err, LLMResponse(content="{}", model="m")])
    with pytest.raises(RuntimeError, match="OpenAI complete failed"):
        await _call_with_slot_retry(provider=provider, **_default_kwargs())
    assert provider.calls == 1, "non-JSON error must not be retried"


# ---------------------------------------------------------------------------
# 2. JSON parse errors are retried (up to MAX_GEN_ATTEMPTS) then raise
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_json_parse_error_retried_then_raises():
    """A JSON decode failure (content not parseable) retries up to 3 times,
    then raises."""
    provider = _ScriptedProvider([
        LLMResponse(content="not-json", model="m"),
        LLMResponse(content="still-not-json", model="m"),
        LLMResponse(content="nope", model="m"),
    ])
    with pytest.raises(RuntimeError, match="JSON parse failed"):
        await _call_with_slot_retry(provider=provider, **_default_kwargs())
    assert provider.calls == 3, "JSON errors should be retried to MAX_GEN_ATTEMPTS"


# ---------------------------------------------------------------------------
# 3. ReadTimeout / ConnectError retried then raise (existing behaviour kept)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_timeout_retried_then_raises():
    """HTTP timeouts are retried up to 3 times, then raise (existing
    behaviour preserved by the fix)."""
    provider = _ScriptedProvider([
        httpx.ReadTimeout("read timeout"),
        httpx.ReadTimeout("read timeout"),
        httpx.ReadTimeout("read timeout"),
    ])
    with pytest.raises(RuntimeError, match="timed out"):
        await _call_with_slot_retry(provider=provider, **_default_kwargs())
    assert provider.calls == 3


# ---------------------------------------------------------------------------
# 4. _with_llm_timeout — asyncio-level timeout guard around the LLM phase
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_with_llm_timeout_returns_on_success():
    """A coroutine that finishes in time returns its value normally."""
    async def _fast():
        return "done"

    result = await _with_llm_timeout(_fast(), timeout=5.0, op="test")
    assert result == "done"


@pytest.mark.asyncio
async def test_with_llm_timeout_raises_when_hung():
    """A coroutine that never returns must raise a RuntimeError after the
    timeout, not hang forever — this is the batch-0 hang fix."""
    async def _hung():
        await asyncio.sleep(60)

    with pytest.raises(RuntimeError, match="timed out"):
        await _with_llm_timeout(_hung(), timeout=0.2, op="unified_generate")


@pytest.mark.asyncio
async def test_with_llm_timeout_propagates_inner_error():
    """An inner exception (fast failure) propagates unchanged — only the
    hang case is converted to a timeout error."""
    async def _boom():
        raise ValueError("inner failure")

    with pytest.raises(ValueError, match="inner failure"):
        await _with_llm_timeout(_boom(), timeout=5.0, op="test")
