"""Local test config for test_vector/.

Restore the real pyarrow + lancedb modules: sibling conftest.py files
install stubs via ``sys.modules.setdefault`` at import time. The
stubs do not expose attributes that ``src.vector.store`` needs
(``pyarrow.string``, ``lancedb.connect`` returning a real object).
Re-bind the already-imported store module's references too.
"""
import sys

import pytest


@pytest.fixture(autouse=True)
def _restore_real_vector_deps():
    # pyarrow
    _pa = sys.modules.get("pyarrow")
    if _pa is not None and getattr(_pa, "__file__", None) is None:
        del sys.modules["pyarrow"]
    import pyarrow  # noqa: F401

    # lancedb
    _ldb = sys.modules.get("lancedb")
    if _ldb is not None and getattr(_ldb, "__file__", None) is None:
        del sys.modules["lancedb"]
    import lancedb  # noqa: F401

    # Re-bind the already-imported store module's references too.
    try:
        import src.vector.store as _store
        _store.pa = pyarrow
        _store.lancedb = lancedb
    except ImportError:
        pass
    yield
