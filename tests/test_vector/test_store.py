# ruflo-kb/tests/test_vector/test_store.py
import pytest
import tempfile
import os
from pathlib import Path
from src.vector.store import init_vector_store, get_table, close_vector_store

def test_init_vector_store():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_vector_store(db_path)

        # Should be able to get the table after init
        table = get_table()
        assert table is not None

        close_vector_store()

def test_vector_store_not_initialized():
    # Before initialization, get_table should raise
    close_vector_store()  # Ensure clean state
    with pytest.raises(RuntimeError, match="not initialized"):
        get_table()
