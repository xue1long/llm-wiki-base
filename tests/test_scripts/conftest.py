"""Shared fixtures for tests/test_scripts/.

Importing ``scripts.batch_build`` executes module-level code: it inserts the
repo root into ``sys.path`` (so ``src`` resolves) and lazily loads dotenv —
both are wrapped defensively in the script. This conftest ensures the repo
root is importable even if the suite runs without PYTHONPATH=, and documents
that the scripts' own import-time side effects are intentional and harmless.
"""
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


@pytest.fixture(autouse=True)
def _restore_real_vector_deps():
    """Restore real vector dependencies after sibling test stubs."""
    for name in ("pyarrow", "lancedb"):
        module = sys.modules.get(name)
        if module is not None and getattr(module, "__file__", None) is None:
            del sys.modules[name]
    import pyarrow
    import lancedb

    try:
        import src.vector.store as store
        store.pa = pyarrow
        store.lancedb = lancedb
    except ImportError:
        pass
    yield
