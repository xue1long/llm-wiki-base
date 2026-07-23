"""Verify the legacy ``init_vector_store(db_path)`` entry point is gone.

Audit T2 / F3: the parent-walking heuristic in ``init_vector_store(db_path)``
was fragile (it walked up to 3 levels looking for ``.index`` or ``wiki``).
The post-T2 canonical entry point is ``init_vector_store_for_paths(WikiPaths)``
and the legacy ``init_vector_store`` is no longer exported.

Two assertions:
1. ``init_vector_store`` symbol is not importable from ``src.vector.store``
2. ``init_vector_store`` symbol is not re-exported from ``src.vector``
"""
import pytest


def test_init_vector_store_removed_from_store_module():
    """``init_vector_store`` must not be importable from src.vector.store."""
    with pytest.raises((ImportError, AttributeError)):
        from src.vector.store import init_vector_store  # noqa: F401


def test_init_vector_store_removed_from_vector_package():
    """``init_vector_store`` must not be re-exported from src.vector."""
    import src.vector as _v
    assert not hasattr(_v, "init_vector_store"), (
        "init_vector_store should be removed from src.vector public surface; "
        "use init_vector_store_for_paths(WikiPaths) instead"
    )


def test_init_vector_store_removed_from_store_all():
    """The function must not appear in ``dir(src.vector.store)``."""
    from src.vector import store
    assert "init_vector_store" not in dir(store), (
        "init_vector_store should not be a module-level attribute of "
        "src.vector.store; the canonical entry point is "
        "init_vector_store_for_paths(WikiPaths)"
    )
