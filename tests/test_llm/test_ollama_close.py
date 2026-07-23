"""Tests for OllamaProvider AsyncClient caching: one client per base_url, close() idempotent.

Background: cleanup identified an httpx.AsyncClient leak in OllamaProvider
(an AsyncClient per provider instance). The fix is a process-global cache
keyed by base_url — many OllamaProvider instances pointing at the same URL
share one client; close() closes the cached client exactly once.
"""
import asyncio
import httpx

import pytest

from src.llm.registry import ProviderRegistry
from src.llm.types import ProviderConfig
from src.llm.ollama_provider import OllamaProvider
from src.llm.base import LLMResponse


@pytest.fixture(autouse=True)
def _reset_client_cache():
    """Reset both the global AsyncClient cache and tracked-provider set."""
    if hasattr(OllamaProvider, "_client_cache"):
        OllamaProvider._client_cache.clear()  # type: ignore[attr-defined]
    ProviderRegistry._loaded_providers.clear()
    yield
    if hasattr(OllamaProvider, "_client_cache"):
        OllamaProvider._client_cache.clear()  # type: ignore[attr-defined]
    ProviderRegistry._loaded_providers.clear()


def test_ollama_provider_caches_singleton_per_url():
    """Two OllamaProviders with the same base_url share one cached AsyncClient."""
    cfg = ProviderConfig(
        name="o", type="ollama", base_url="http://x", default_chat_model="m",
    )
    p1 = OllamaProvider(cfg)
    p2 = OllamaProvider(cfg)
    assert p1.client is p2.client
    assert OllamaProvider._client_cache["http://x"] is p1.client  # type: ignore[attr-defined]


def test_ollama_provider_different_urls_separate_clients():
    """Providers with different base_urls must NOT share a client."""
    cfg1 = ProviderConfig(
        name="o1", type="ollama", base_url="http://a", default_chat_model="m",
    )
    cfg2 = ProviderConfig(
        name="o2", type="ollama", base_url="http://b", default_chat_model="m",
    )
    p1 = OllamaProvider(cfg1)
    p2 = OllamaProvider(cfg2)
    assert p1.client is not p2.client
    assert len(OllamaProvider._client_cache) == 2  # type: ignore[attr-defined]


def test_close_clears_cache_and_is_idempotent():
    """close() evicts the cached client; calling it twice on the same provider
    closes the underlying client exactly once."""
    cfg = ProviderConfig(
        name="o", type="ollama", base_url="http://x", default_chat_model="m",
    )
    p = OllamaProvider(cfg)
    captured = []

    orig_aclose = p.client.aclose

    async def counting_aclose():
        captured.append(1)
        await orig_aclose()

    p.client.aclose = counting_aclose  # type: ignore[method-assign]

    asyncio.run(p.close())  # closes
    assert len(captured) == 1
    assert "http://x" not in OllamaProvider._client_cache  # type: ignore[attr-defined]

    # Second close — cache empty, no aclose on (now closed) client
    asyncio.run(p.close())
    assert len(captured) == 1


def test_failed_close_kept_in_registry_across_retry():
    """If close() raises, the failed provider must remain tracked so aclose_all can retry."""
    cfg = ProviderConfig(
        name="o", type="ollama", base_url="http://x", default_chat_model="m",
    )
    p = OllamaProvider(cfg)

    async def fail_close():
        raise RuntimeError("simulated close failure")

    p.close = fail_close  # type: ignore[method-assign]
    asyncio.run(ProviderRegistry.aclose_all())
    # Provider still tracked (close failed; keep ownership reference for retry)
    assert p in ProviderRegistry._loaded_providers

    async def ok_close():
        return None

    p.close = ok_close  # type: ignore[method-assign]
    asyncio.run(ProviderRegistry.aclose_all())
    # After successful close, removed from tracked set
    assert p not in ProviderRegistry._loaded_providers
