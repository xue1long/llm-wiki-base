"""Local test config for test_project/.

Restore the real platformdirs module: sibling conftest.py files
install a stub via ``sys.modules.setdefault`` at import time. If
``src.project.paths`` is imported while the stub is in place, it
binds the stub's ``user_config_dir`` at module load and never
re-reads it later. Re-binding the attribute on the already-loaded
paths module is enough to make ``config_dir()`` return the real
user-config path.
"""
import sys

import pytest


@pytest.fixture(autouse=True)
def _restore_real_platformdirs():
    previous = sys.modules.get("platformdirs")
    previous_config = None
    try:
        import src.project.paths as _paths
        previous_config = _paths.user_config_dir
    except ImportError:
        _paths = None
    # 1) Make the real platformdirs importable in this process.
    _pd = sys.modules.get("platformdirs")
    if _pd is not None and getattr(_pd, "__file__", None) is None:
        del sys.modules["platformdirs"]
    import platformdirs  # noqa: F401

    # 2) Re-bind the already-imported paths module's reference too.
    try:
        import src.project.paths as _paths
        _paths.user_config_dir = platformdirs.user_config_dir
    except ImportError:
        # src not importable yet (e.g. when this conftest is loaded
        # before src is on sys.path); the real platformdirs is in
        # sys.modules so the normal import path will pick it up.
        pass
    yield
    if previous is None:
        sys.modules.pop("platformdirs", None)
    else:
        sys.modules["platformdirs"] = previous
    if _paths is not None and previous_config is not None:
        _paths.user_config_dir = previous_config
