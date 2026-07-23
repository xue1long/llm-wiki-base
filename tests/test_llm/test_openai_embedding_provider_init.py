"""Tests for OpenAIEmbeddingProvider.__init__ attribute layout.

Background: ``OpenAIEmbeddingProvider.__init__`` used to set BOTH
``self._sdk = client`` (canonical storage) AND ``self.client = client``
(redundant alias). The duplicate ``self.client`` attribute is removed;
canonical storage is ``self._sdk``.
"""
import pytest

from src.llm.openai_provider import OpenAIEmbeddingProvider


class _FakeClient:
    """Minimal stand-in for the openai SDK client."""
    def __init__(self):
        self.embeddings_called = False


def test_no_redundant_client_attribute():
    """Canonical storage is ``_sdk``; ``client`` must not exist as an attribute."""
    p = OpenAIEmbeddingProvider(
        api_key="x", model="text-embedding-3-small", client=_FakeClient(),
    )
    # Canonical storage is _sdk (set in __init__)
    assert hasattr(p, "_sdk"), "Expected canonical _sdk attribute to exist"
    assert p._sdk is not None, "Expected _sdk to hold the client"

    # Redundant alias is gone
    assert not hasattr(p, "client"), (
        "Redundant `self.client` attribute should be removed; "
        "use the canonical `self._sdk` instead."
    )


def test_construct_with_no_client_works():
    """No-client construction still works (httpx path)."""
    p = OpenAIEmbeddingProvider(
        api_key="x", model="text-embedding-3-small",
    )
    assert hasattr(p, "_sdk")
    # No client provided -> _sdk is None
    assert p._sdk is None
    # The redundant alias is also absent
    assert not hasattr(p, "client")


def test_embed_call_uses_sdk_attribute():
    """Sanity: the embed() path reads from self._sdk, confirming _sdk is canonical."""
    class _CapturingEmbeddings:
        def __init__(self):
            self.kwargs = None

        def create(self, **kw):
            self.kwargs = kw
            return {"data": [{"embedding": [0.0] * 1536}], "model": "x"}

    class _CapturingClient:
        def __init__(self):
            self.embeddings = _CapturingEmbeddings()

    fake = _CapturingClient()
    p = OpenAIEmbeddingProvider(
        api_key="x", model="text-embedding-3-small", client=fake,
    )
    import asyncio
    out = asyncio.run(p.embed(["hello"]))
    assert fake.embeddings.kwargs is not None
    assert fake.embeddings.kwargs["model"] == "text-embedding-3-small"
    assert len(out) == 1