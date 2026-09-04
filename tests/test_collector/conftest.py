# tests/test_collector/conftest.py
"""Stub heavy dependencies so collection works without them installed."""
import sys
import pytest

_MISSING = object()

# Stub platformdirs (imported by some src modules)
if "platformdirs" not in sys.modules:
    sys.modules["platformdirs"] = type(sys)("platformdirs")
    sys.modules["platformdirs"].user_config_dir = lambda *_a, **_kw: "/tmp/cfg"
    sys.modules["platformdirs"].user_data_dir = lambda *_a, **_kw: "/tmp/data"
_COLLECTION_PLATFORMDIRS = sys.modules.get("platformdirs", _MISSING)


@pytest.fixture(autouse=True)
def _isolate_platformdirs_stub():
    previous = sys.modules.get("platformdirs", _MISSING)
    if _COLLECTION_PLATFORMDIRS is not _MISSING:
        sys.modules["platformdirs"] = _COLLECTION_PLATFORMDIRS
    try:
        yield
    finally:
        if previous is _MISSING:
            sys.modules.pop("platformdirs", None)
        else:
            sys.modules["platformdirs"] = previous
