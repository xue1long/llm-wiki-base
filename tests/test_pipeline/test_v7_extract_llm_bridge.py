"""Tests for ProviderAdapter — bridges src.llm.LLMProvider to v7_extract.LLMClient.

The V7 ingest bridge (Task 4) needs to call Stage 1-7 with a
``LLMClient`` instance. The existing ``AnthropicLLMClient`` constructs
its own provider internally; ``ProviderAdapter`` instead wraps an
**already-constructed** ``LLMProvider`` instance, which is what
``src.pipeline.ingest.run_ingest`` passes to the bridge via
``_get_provider(project_id=project_id)``.

This avoids double-constructing the provider and respects the
project-level provider override (when ``RUFLO_LLM_PROVIDER`` env
is set, ``_get_provider`` already routes correctly).
"""
from __future__ import annotations

from typing import Any

import pytest

from src.llm.base import LLMProvider, LLMResponse
from src.pipeline.v7_extract.llm_bridge import ProviderAdapter


# ---------- Test double ----------


class _StubProvider(LLMProvider):
    """In-memory LLMProvider double for unit tests.

    Records every call so assertions can inspect messages / kwargs.
    Returns a configurable response.
    """

    def __init__(self, response_content: str = "ok", model: str = "stub-model") -> None:
        self.response_content = response_content
        self.model = model
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        messages,
        *,
        response_format=None,
        system=None,
        timeout=None,
        **kwargs,
    ) -> LLMResponse:
        self.calls.append({
            "messages": messages,
            "response_format": response_format,
            "system": system,
            "timeout": timeout,
            "kwargs": kwargs,
        })
        return LLMResponse(content=self.response_content, model=self.model)

    async def embed(self, text):
        from src.llm.base import EmbeddingResponse
        return EmbeddingResponse(embedding=[0.0] * 4, model=self.model)


# ---------- basic complete() forwarding ----------


@pytest.mark.asyncio
async def test_complete_returns_response_content_as_str():
    """ProviderAdapter.complete returns str (not LLMResponse)."""
    stub = _StubProvider(response_content="hello world")
    adapter = ProviderAdapter(stub)

    result = await adapter.complete(
        prompt_kind="classify",
        user_prompt="What is this?",
    )

    assert result == "hello world"
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_complete_constructs_user_message():
    """Single user-role message contains the user_prompt verbatim."""
    stub = _StubProvider()
    adapter = ProviderAdapter(stub)

    await adapter.complete(prompt_kind="classify", user_prompt="What is this?")

    assert len(stub.calls) == 1
    messages = stub.calls[0]["messages"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "What is this?"


@pytest.mark.asyncio
async def test_complete_prepends_system_message_when_provided():
    """When system_prompt is non-empty, prepend as a system-role message."""
    stub = _StubProvider()
    adapter = ProviderAdapter(stub)

    await adapter.complete(
        prompt_kind="classify",
        user_prompt="Question?",
        system_prompt="You are a classifier.",
    )

    messages = stub.calls[0]["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "You are a classifier."
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "Question?"


@pytest.mark.asyncio
async def test_complete_omits_system_message_when_empty():
    """When system_prompt is empty, only user message is sent."""
    stub = _StubProvider()
    adapter = ProviderAdapter(stub)

    await adapter.complete(prompt_kind="cluster", user_prompt="x", system_prompt="")

    messages = stub.calls[0]["messages"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"


@pytest.mark.asyncio
async def test_complete_forwards_max_tokens():
    """max_tokens forwarded as kwarg to LLMProvider.complete()."""
    stub = _StubProvider()
    adapter = ProviderAdapter(stub)

    await adapter.complete(
        prompt_kind="classify",
        user_prompt="x",
        max_tokens=2048,
    )

    assert stub.calls[0]["kwargs"].get("max_tokens") == 2048


@pytest.mark.asyncio
async def test_complete_forwards_temperature():
    """temperature forwarded as kwarg to LLMProvider.complete()."""
    stub = _StubProvider()
    adapter = ProviderAdapter(stub)

    await adapter.complete(
        prompt_kind="classify",
        user_prompt="x",
        temperature=0.7,
    )

    assert stub.calls[0]["kwargs"].get("temperature") == 0.7


@pytest.mark.asyncio
async def test_complete_uses_default_max_tokens_when_not_specified():
    """Default max_tokens (4096) is forwarded when caller omits it."""
    stub = _StubProvider()
    adapter = ProviderAdapter(stub)

    await adapter.complete(prompt_kind="classify", user_prompt="x")

    assert stub.calls[0]["kwargs"].get("max_tokens") == 4096


# ---------- calls_count tracking (used by bridge budget checks) ----------


@pytest.mark.asyncio
async def test_calls_count_increments_per_complete():
    """calls_count increments after every complete() call."""
    stub = _StubProvider()
    adapter = ProviderAdapter(stub)
    assert adapter.calls_count == 0

    await adapter.complete(prompt_kind="a", user_prompt="1")
    assert adapter.calls_count == 1

    await adapter.complete(prompt_kind="b", user_prompt="2")
    await adapter.complete(prompt_kind="c", user_prompt="3")
    assert adapter.calls_count == 3


# ---------- health_check passthrough ----------


@pytest.mark.asyncio
async def test_health_check_passes_through_to_provider():
    """health_check() forwards to the wrapped provider's health_check()."""

    class _ProviderWithHealth(_StubProvider):
        def __init__(self):
            super().__init__()
            self.health_calls = 0

        async def health_check(self):
            self.health_calls += 1
            return {"ok": True, "detail": "provider-ok"}

    stub = _ProviderWithHealth()
    adapter = ProviderAdapter(stub)

    result = await adapter.health_check()
    assert result == {"ok": True, "detail": "provider-ok"}
    assert stub.health_calls == 1


# ---------- provider_name passthrough ----------


def test_provider_name_returns_wrapped_provider_name():
    """provider_name reflects the wrapped provider's name (used by AGL, ledger)."""
    from src.llm.openai_provider import OpenAIProvider
    from src.llm.types import ProviderConfig

    provider = OpenAIProvider(
        config=ProviderConfig(
            name="my-provider",
            type="openai",
            base_url="http://localhost:0",
            api_key="x",
            default_chat_model="m",
        )
    )
    adapter = ProviderAdapter(provider)
    # OpenAIProvider exposes the name via .config.name
    assert adapter.provider_name == "my-provider"


# ---------- error propagation ----------


@pytest.mark.asyncio
async def test_provider_error_propagates():
    """Exceptions raised by the wrapped provider propagate unchanged."""

    class _FailingProvider(_StubProvider):
        async def complete(self, *args, **kwargs):
            raise RuntimeError("upstream failed")

    adapter = ProviderAdapter(_FailingProvider())
    with pytest.raises(RuntimeError, match="upstream failed"):
        await adapter.complete(prompt_kind="classify", user_prompt="x")
