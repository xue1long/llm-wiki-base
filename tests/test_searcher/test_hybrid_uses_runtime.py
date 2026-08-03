"""hybrid_search.py must source its embedding provider from the shared runtime.

Background: previously ``src.searcher.hybrid_search`` kept a private
``_embedding_provider`` global that was set independently of
``src.pipeline.librarian``'s, so the two modules could disagree.
"""
import importlib

import pytest

from src.llm.embedding_runtime import (
    set_embedding_provider,
    __reset_for_testing,
)


class FakeProvider:
    def __init__(self, dim: int = 1536) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self.dim for _ in texts]


def setup_function(_):
    __reset_for_testing()


def _hs_module():
    """Return the actual ``hybrid_search`` *module*, not the function of the
    same name exported via ``src.searcher.__init__``."""
    return importlib.import_module("src.searcher.hybrid_search")


def test_hybrid_module_does_not_keep_independent_global():
    """hybrid_search must not own a private ``_embedding_provider`` global
    (audit C-2)."""
    hs = _hs_module()

    assert not hasattr(hs, "_embedding_provider"), (
        "hybrid_search must not keep a private _embedding_provider global; "
        "use src.llm.embedding_runtime.get_embedding_provider() instead."
    )
    assert not hasattr(hs, "set_embedding_provider")


def test_runtime_provider_visible_via_hybrid_get():
    """The runtime import in hybrid_search is the same module used by tests."""
    hs = _hs_module()
    runtime = importlib.import_module("src.llm.embedding_runtime")

    assert hs.get_embedding_provider is runtime.get_embedding_provider


def test_set_provider_then_get_returns_same_instance():
    """A provider set via the runtime is what hybrid_search.get_embedding_provider
    will see (no separate global per module)."""
    hs = _hs_module()

    p = FakeProvider(dim=4)
    set_embedding_provider(p)
    assert hs.get_embedding_provider() is p


def test_runtime_unset_raises_runtime_error():
    """When unset, hybrid_search.get_embedding_provider must raise RuntimeError
    (audit fix: no silent fallback to keyword-only search at the provider layer)."""
    hs = _hs_module()

    __reset_for_testing()
    with pytest.raises(RuntimeError):
        hs.get_embedding_provider()
