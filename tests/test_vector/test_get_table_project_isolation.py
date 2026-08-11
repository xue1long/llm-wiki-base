"""Audit I3 regression: ``get_table(project_paths)`` returns the per-project
handle so multi-project search does not cross-pollute vectors.

Before the fix, ``get_table()`` returned the table for whichever project
was most recently initialised. A search request for project B would
silently read project A's vectors. The fix accepts an explicit
``project_paths`` argument; ``get_table()`` (no arg) still returns the
process-global handle for legacy callers / single-project CLI.
"""
from src.vector.store import (
    get_table,
    init_vector_store_for_paths,
    __reset_for_testing,
)
from src.wiki.core.paths import WikiPaths
from src.wiki.storage.ensure import ensure_knowledge_base


def setup_function(_):
    __reset_for_testing()


def test_get_table_returns_table_for_explicit_project(tmp_path):
    """``get_table(project_paths)`` must return the table for THAT project."""
    project_a = tmp_path / "A"
    project_b = tmp_path / "B"
    ensure_knowledge_base(project_a)
    ensure_knowledge_base(project_b)
    paths_a = WikiPaths(project_a)
    paths_b = WikiPaths(project_b)
    init_vector_store_for_paths(paths_a)
    init_vector_store_for_paths(paths_b)
    # Make B the "current" project.
    init_vector_store_for_paths(paths_b)

    # get_table() (no arg) returns B (current).
    current = get_table()
    # get_table(paths_a) returns A's table even though B is "current".
    a_table = get_table(paths_a)
    b_table = get_table(paths_b)

    # Different handles per project.
    assert a_table is not b_table
    assert current is b_table


def test_get_table_lazy_inits_for_uninitialised_project(tmp_path):
    """Passing an uninitialised project's paths must auto-initialise."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    # No init_vector_store_for_paths() call — get_table() should lazy-init.
    table = get_table(paths)
    assert table is not None


def test_legacy_get_table_raises_when_no_project_active(tmp_path):
    """Legacy callers passing no paths still need an init first."""
    ensure_knowledge_base(tmp_path)
    import pytest
    with pytest.raises(RuntimeError, match="not initialized"):
        get_table()
