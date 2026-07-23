"""Tests for src.vector.store.init_vector_store_for_paths — per-project LanceDB.

Each project has its own LanceDB handle stored in ``_per_project`` keyed on the
project root path. ``get_table()`` resolves the active project handle
(set by the most recent ``init_vector_store_for_paths`` call).
"""
from src.vector.store import (
    init_vector_store_for_paths,
    get_table,
    __reset_for_testing,
)
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.core.paths import WikiPaths


def setup_function(_):
    """Reset module-level state before each test so they are independent."""
    __reset_for_testing()


def test_init_creates_table(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    init_vector_store_for_paths(p)
    assert get_table() is not None


def test_init_for_new_project_does_not_affect_old(tmp_path):
    """Initialising a different project must produce a different table handle
    (and not clobber the previous one)."""
    ensure_knowledge_base(tmp_path)
    p1 = WikiPaths(tmp_path)
    init_vector_store_for_paths(p1)
    t1 = get_table()

    ensure_knowledge_base(tmp_path / "other")
    p2 = WikiPaths(tmp_path / "other")
    init_vector_store_for_paths(p2)
    t2 = get_table()
    assert t1 is not t2


def test_reinit_same_project_returns_same_handle(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    init_vector_store_for_paths(p)
    t1 = get_table()
    # Re-initialising the same project must not produce a fresh object
    init_vector_store_for_paths(p)
    t2 = get_table()
    assert t1 is t2
