"""Tests for OpenAIProvider embedding dimension support and validation.

Background: text-embedding-3-* models support a ``dimensions`` parameter
that lets the caller pin a non-default vector size. OpenAIProvider must
(a) send ``dimensions=self.dimension`` when set, and (b) validate the
returned vector length matches ``self.dimension`` when present.
"""
import pytest

from src.llm.openai_provider import OpenAIEmbeddingProvider
from src.llm.base import EmbeddingResponse


class _FakeEmbeddings:
    def __init__(self):
        self.captured = {}

    def create(self, **kw):
        self.captured.update(kw)
        size = kw.get("dimensions", 1536)
        return {"data": [{"embedding": [0.0] * size}], "model": kw["model"]}


class _FakeClient:
    def __init__(self):
        self.embeddings = _FakeEmbeddings()


def test_openai_embedding_dimension_sent():
    """embed() must forward ``dimensions=self.dimension`` when set."""
    p = OpenAIEmbeddingProvider(
        api_key="x", model="text-embedding-3-large", dimension=1024,
        client=_FakeClient(),
    )
    import asyncio
    out = asyncio.run(p.embed(["hello"]))
    assert p._sdk.embeddings.captured.get("dimensions") == 1024
    assert isinstance(out[0], EmbeddingResponse)
    assert len(out[0].embedding) == 1024


def test_openai_embedding_dimension_none_omitted():
    """When dimension is None, the request must not include the key (OpenAI rejects ``dimensions=null``)."""
    p = OpenAIEmbeddingProvider(
        api_key="x", model="text-embedding-3-small", dimension=None,
        client=_FakeClient(),
    )
    import asyncio
    asyncio.run(p.embed(["hello"]))
    assert "dimensions" not in p._sdk.embeddings.captured


def test_openai_embedding_dimension_mismatch_raises():
    """If the model's vector length disagrees with configured dimension, raise RuntimeError."""
    class _WrongEmbeddings:
        def create(self, **kw):
            # Return wrong size: 1536 instead of 1024
            return {"data": [{"embedding": [0.0] * 1536}]}

    class _WrongClient:
        embeddings = _WrongEmbeddings()

    p = OpenAIEmbeddingProvider(
        api_key="x", model="text-embedding-3-large", dimension=1024,
        client=_WrongClient(),  # type: ignore[arg-type]
    )
    import asyncio
    with pytest.raises(RuntimeError, match="dimension"):
        asyncio.run(p.embed(["x"]))
