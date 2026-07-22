"""Tests for ProviderRegistry.aclose_all() — bulk-close all loaded LLM providers.

Background: OllamaProvider creates an httpx.AsyncClient in __init__ but its
close() was never called by business code paths (chat/embed requests), so
every call to create_llm_provider('ollama') leaked one AsyncClient.

ProviderRegistry.aclose_all() walks all tracked providers and calls
.close() on each. OllamaProvider auto-registers on __init__; other
providers without a close() method are skipped.
"""
import asyncio
import pytest

from src.llm.registry import ProviderRegistry
from src.llm.types import ProviderConfig
from src.llm.ollama_provider import OllamaProvider


@pytest.fixture(autouse=True)
def _reset_tracked_providers():
    """Each test starts with an empty tracked-providers set."""
    ProviderRegistry._loaded_providers.clear()
    yield
    ProviderRegistry._loaded_providers.clear()


def test_aclose_all_calls_close_on_tracked_ollama():
    """When an OllamaProvider is created, it auto-registers. aclose_all() must
    invoke its close() coroutine."""
    cfg = ProviderConfig(
        name="o", type="ollama", base_url="http://x", default_chat_model="m",
    )
    p = OllamaProvider(cfg)

    # The provider should be auto-registered
    assert p in ProviderRegistry._loaded_providers

    # Stub close() to record invocation
    closed = []
    async def fake_close():
        closed.append(p)
    p.close = fake_close  # type: ignore[method-assign]

    # aclose_all() must invoke it
    asyncio.run(ProviderRegistry.aclose_all())
    assert closed == [p]


def test_aclose_all_skips_providers_without_close():
    """A provider that has no close() attribute must not crash aclose_all()."""
    class NoCloseProvider:
        pass

    p = NoCloseProvider()
    ProviderRegistry._loaded_providers.add(p)  # type: ignore[arg-type]

    # Should not raise
    asyncio.run(ProviderRegistry.aclose_all())


def test_aclose_all_continues_after_one_close_raises():
    """If one provider's close() raises, the others must still be closed."""
    cfg1 = ProviderConfig(name="o1", type="ollama", base_url="http://x", default_chat_model="m")
    cfg2 = ProviderConfig(name="o2", type="ollama", base_url="http://x", default_chat_model="m")
    p1 = OllamaProvider(cfg1)
    p2 = OllamaProvider(cfg2)

    closed = []

    async def ok_close():
        closed.append("p2")
    async def bad_close():
        closed.append("p1")
        raise RuntimeError("simulated close failure")

    p1.close = bad_close  # type: ignore[method-assign]
    p2.close = ok_close  # type: ignore[method-assign]

    asyncio.run(ProviderRegistry.aclose_all())
    # Both must have been attempted, in some order
    assert set(closed) == {"p1", "p2"}


def test_aclose_all_clears_tracked_set():
    """After aclose_all(), the tracked set must be empty (idempotent)."""
    cfg = ProviderConfig(name="o", type="ollama", base_url="http://x", default_chat_model="m")
    OllamaProvider(cfg)

    assert len(ProviderRegistry._loaded_providers) == 1
    asyncio.run(ProviderRegistry.aclose_all())
    assert len(ProviderRegistry._loaded_providers) == 0

    # Second call is a no-op (does not raise on empty set)
    asyncio.run(ProviderRegistry.aclose_all())
