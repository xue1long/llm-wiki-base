# ruflo-kb/tests/test_vector/test_store.py
import pytest
import tempfile
from pathlib import Path
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.core.paths import WikiPaths
from src.vector.store import init_vector_store_for_paths, get_table, close_vector_store, __reset_for_testing


def setup_function(_):
    """Reset module-level state before each test so they are independent."""
    __reset_for_testing()


def test_init_vector_store_for_paths():
    """Canonical entry point: init then get_table returns the table."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ensure_knowledge_base(Path(tmpdir))
        paths = WikiPaths(Path(tmpdir))
        init_vector_store_for_paths(paths)

        # Should be able to get the table after init
        table = get_table()
        assert table is not None

        close_vector_store()


def test_vector_store_not_initialized():
    # Before initialization, get_table should raise
    close_vector_store()  # Ensure clean state
    with pytest.raises(RuntimeError, match="not initialized"):
        get_table()
