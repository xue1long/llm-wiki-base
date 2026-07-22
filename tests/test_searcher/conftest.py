"""Local test config for test_searcher/.

Restore the real lancedb + pyarrow modules: sibling conftest.py files
install stubs via ``sys.modules.setdefault``. The conftests are loaded
in alphabetical directory order, so an alphabetically-later conftest
(e.g. test_server/, test_wiki/) re-stubs the modules after this one
has restored them. Hooking ``pytest_configure`` runs AFTER all
conftests are loaded, so it is the safe place to fix the real modules
back in. Collection-time error, so it must run before collection.

We also drop any partially-loaded ``src.searcher`` / ``src.vector``
from sys.modules so the import chain re-runs against the real
lancedb + pyarrow. (If src.searcher was imported while the stubs
were active, its ``__init__`` fails and the package ends up in a
broken state in sys.modules.)
"""
import sys


def pytest_configure(config):
    # 1) pyarrow first (lancedb imports pyarrow.dataset at load)
    _pa = sys.modules.get("pyarrow")
    if _pa is not None and getattr(_pa, "__file__", None) is None:
        del sys.modules["pyarrow"]
    import pyarrow  # noqa: F401
    import pyarrow.dataset  # noqa: F401
    import pyarrow.types  # noqa: F401
    import pyarrow.compute  # noqa: F401
    import pyarrow.fs  # noqa: F401

    # 2) lancedb second
    _ldb = sys.modules.get("lancedb")
    if _ldb is not None and getattr(_ldb, "__file__", None) is None:
        del sys.modules["lancedb"]
    import lancedb  # noqa: F401

    # 3) Drop any partially-loaded src modules that depend on lancedb/pyarrow
    # so the test file's import triggers a fresh import against the real ones.
    for mod_name in list(sys.modules):
        if mod_name == "src.searcher" or mod_name.startswith("src.searcher."):
            del sys.modules[mod_name]
        if mod_name == "src.vector" or mod_name.startswith("src.vector."):
            del sys.modules[mod_name]
