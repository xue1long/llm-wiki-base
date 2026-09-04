import sys
import types

import pytest


def test_stub_fixture_installs_and_restores_missing_module(isolated_optional_stubs):
    original = sys.modules.pop("lancedb", None)
    try:
        with isolated_optional_stubs() as stubs:
            assert sys.modules["lancedb"] is stubs["lancedb"]
        assert "lancedb" not in sys.modules
    finally:
        if original is not None:
            sys.modules["lancedb"] = original


def test_stub_fixture_restores_existing_module_after_exception(isolated_optional_stubs):
    original = types.ModuleType("lancedb-original")
    sys.modules["lancedb"] = original
    with pytest.raises(RuntimeError):
        with isolated_optional_stubs():
            assert sys.modules["lancedb"].__name__ != "lancedb-original"
            raise RuntimeError("exercise teardown")
    assert sys.modules["lancedb"] is original


def test_dependent_cached_module_survives_stub_restore(isolated_optional_stubs):
    original = sys.modules.pop("lancedb", None)
    dependent = types.ModuleType("test-dependent")
    try:
        with isolated_optional_stubs():
            dependent.lancedb = sys.modules["lancedb"]
            sys.modules[dependent.__name__] = dependent
        assert sys.modules[dependent.__name__] is dependent
        assert "lancedb" not in sys.modules
    finally:
        sys.modules.pop(dependent.__name__, None)
        if original is not None:
            sys.modules["lancedb"] = original
