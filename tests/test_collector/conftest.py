# tests/test_collector/conftest.py
"""Stub heavy dependencies so collection works without them installed."""
import sys

# Stub platformdirs (imported by some src modules)
if "platformdirs" not in sys.modules:
    sys.modules["platformdirs"] = type(sys)("platformdirs")
    sys.modules["platformdirs"].user_config_dir = lambda *_a, **_kw: "/tmp/cfg"
    sys.modules["platformdirs"].user_data_dir = lambda *_a, **_kw: "/tmp/data"
