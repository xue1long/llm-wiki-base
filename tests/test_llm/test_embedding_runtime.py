"""Tests for src.llm.embedding_runtime — process-global embedding provider."""
import pytest

from src.llm.embedding_runtime import (
    set_embedding_provider,
    get_embedding_provider,
    __reset_for_testing,
)


class FakeProvider:
    """Minimal duck-typed provider matching the EmbeddingProvider protocol."""

    def __init__(self, dim: int = 1536) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self.dim for _ in texts]


def setup_function(_):
    """Reset module-level singleton before each test."""
    __reset_for_testing()


def test_get_raises_when_unset():
    """Without set_embedding_provider(), get must raise RuntimeError."""
    with pytest.raises(RuntimeError, match="Embedding provider not configured"):
        get_embedding_provider()


def test_set_then_get():
    p = FakeProvider()
    set_embedding_provider(p)
    assert get_embedding_provider() is p


def test_set_replaces():
    """A second set_embedding_provider() must replace the prior instance."""
    set_embedding_provider(FakeProvider())
    p2 = FakeProvider()
    set_embedding_provider(p2)
    assert get_embedding_provider() is p2


def test_get_returns_latest_after_replacement():
    p1 = FakeProvider(dim=8)
    p2 = FakeProvider(dim=16)
    set_embedding_provider(p1)
    assert get_embedding_provider() is p1
    set_embedding_provider(p2)
    assert get_embedding_provider() is p2


def test_reset_clears_singleton():
    """__reset_for_testing() must clear the cached provider so get raises again."""
    set_embedding_provider(FakeProvider())
    __reset_for_testing()
    with pytest.raises(RuntimeError):
        get_embedding_provider()
