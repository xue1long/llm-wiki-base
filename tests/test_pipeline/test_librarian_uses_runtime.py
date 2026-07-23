"""librarian.py must source its embedding provider from the shared runtime.

Background: previously ``src.pipeline.librarian`` kept a private
``_embedding_provider`` global which could drift out of sync with
``src.searcher.hybrid_search``. After Task 2, both modules must read
from ``src.llm.embedding_runtime`` and raise clearly when unconfigured
rather than silently inserting zero vectors.
"""
import importlib

import pytest

from src.llm.embedding_runtime import (
    set_embedding_provider,
    get_embedding_provider,
    __reset_for_testing,
)


class FakeProvider:
    """Matches the EmbeddingProvider protocol: embed(texts) -> list[list[float]]."""

    def __init__(self, dim: int = 1536) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(texts))] * self.dim for _ in texts]


def setup_function(_):
    __reset_for_testing()


def _lib_module():
    """Return the ``librarian`` *module* (not anything else of the same name)."""
    return importlib.import_module("src.pipeline.librarian")


def test_runtime_provider_is_visible_to_get():
    """Smoke: set_embedding_provider on runtime is what get_embedding_provider reads."""
    p = FakeProvider(dim=4)
    set_embedding_provider(p)
    assert get_embedding_provider() is p


def test_librarian_module_does_not_keep_independent_global():
    """The librarian module must not own a separate ``_embedding_provider``
    global — that was the root cause of audit finding C-2.
    """
    lib = _lib_module()

    assert not hasattr(lib, "_embedding_provider"), (
        "librarian must not keep a private _embedding_provider global; "
        "use src.llm.embedding_runtime.get_embedding_provider() instead."
    )
    assert not hasattr(lib, "set_embedding_provider"), (
        "librarian must not expose its own set_embedding_provider(); "
        "the runtime is the single source of truth."
    )


def test_runtime_provider_reachable_via_module_attribute():
    """The runtime import in librarian is the same module as in tests."""
    lib = _lib_module()
    runtime = importlib.import_module("src.llm.embedding_runtime")

    assert lib.get_embedding_provider is runtime.get_embedding_provider


def test_get_unset_raises_runtime_error_from_librarian_view():
    """When the runtime singleton is unset, the function must raise
    RuntimeError rather than proceed with zero vectors (audit I-vector-9)."""
    lib = _lib_module()

    __reset_for_testing()
    with pytest.raises(RuntimeError):
        lib.get_embedding_provider()
