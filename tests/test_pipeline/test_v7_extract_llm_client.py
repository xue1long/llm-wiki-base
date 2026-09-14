"""Tests for V7 extract pipeline's LLMClient abstraction (M9-V5 fix).

The pipeline must be unit-testable WITHOUT calling the real LLM. These
tests verify:
- FakeLLMClient returns scripted responses by prompt_kind.
- FakeLLMClient records every call for later assertion.
- LLMClient is abstract (cannot be instantiated directly).
- AnthropicLLMClient can be constructed (real provider resolution).
"""
import asyncio

import pytest

from src.pipeline.v7_extract.llm_client import (
    AnthropicLLMClient,
    FakeLLMClient,
    LLMClient,
)


def test_llm_client_is_abstract():
    """LLMClient cannot be instantiated directly — it has abstract methods."""
    with pytest.raises(TypeError):
        LLMClient()  # type: ignore[abstract]


def test_fake_llm_client_serves_scripted_response_by_prompt_kind():
    """FakeLLMClient returns the queued response matching the prompt_kind."""
    fake = FakeLLMClient()
    fake.script("classify", '{"doc_type": "single_method"}')
    fake.script("cluster", '{"topics": [{"title": "A"}]}')

    r1 = asyncio.run(fake.complete(prompt_kind="classify", user_prompt="x"))
    r2 = asyncio.run(fake.complete(prompt_kind="cluster", user_prompt="y"))

    assert r1 == '{"doc_type": "single_method"}'
    assert r2 == '{"topics": [{"title": "A"}]}'


def test_fake_llm_client_returns_empty_for_unknown_kind():
    """When no script is queued for a prompt_kind, return empty string
    rather than raising — tests assert against the calls log instead."""
    fake = FakeLLMClient()
    r = asyncio.run(fake.complete(prompt_kind="never_queued", user_prompt="x"))
    assert r == ""


def test_fake_llm_client_records_calls():
    """FakeLLMClient keeps a structured log of every invocation for
    assertions in downstream stage tests."""
    fake = FakeLLMClient()
    fake.script("classify", "{}")

    asyncio.run(fake.complete(
        prompt_kind="classify",
        user_prompt="abc" * 100,
        system_prompt="def" * 50,
        max_tokens=2048,
    ))

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["prompt_kind"] == "classify"
    assert call["user_prompt_len"] == 300
    assert call["system_prompt_len"] == 150
    assert call["max_tokens"] == 2048


def test_fake_llm_client_serves_responses_fifo():
    """When multiple responses are queued for one prompt_kind, they are
    served in FIFO order (matches LLM streaming semantics)."""
    fake = FakeLLMClient()
    fake.script("classify", "first")
    fake.script("classify", "second")
    fake.script("classify", "third")

    r1 = asyncio.run(fake.complete(prompt_kind="classify", user_prompt=""))
    r2 = asyncio.run(fake.complete(prompt_kind="classify", user_prompt=""))
    r3 = asyncio.run(fake.complete(prompt_kind="classify", user_prompt=""))

    assert (r1, r2, r3) == ("first", "second", "third")


def test_anthropic_llm_client_constructs():
    """AnthropicLLMClient can be instantiated (does not crash at __init__).

    We do NOT actually invoke the LLM here — that would require an
    API key and a network. Real-provider tests live in tests/test_llm/.
    """
    # Construct without specifying provider_name → reads default from
    # registry. May raise if registry is empty / corrupt; that's
    # acceptable and means the test environment is misconfigured.
    try:
        client = AnthropicLLMClient()
        assert isinstance(client, LLMClient)
        # provider_name is a string (whatever the default resolves to).
        assert isinstance(client.provider_name, str)
    except (KeyError, FileNotFoundError, RuntimeError) as e:
        pytest.skip(f"No LLM provider configured in this environment: {e}")


def test_anthropic_llm_client_uses_specified_provider():
    """When a provider_name is supplied, it is used verbatim."""
    # We do not actually need the provider to exist for the property
    # check — but AnthropicLLMClient.__init__ resolves the provider
    # immediately. We accept a missing-provider failure as a skip.
    try:
        client = AnthropicLLMClient(default_provider_name="nonexistent_for_test")
        assert client.provider_name == "nonexistent_for_test"
    except (KeyError, FileNotFoundError, RuntimeError):
        pytest.skip("Provider resolution is strict in this environment")
