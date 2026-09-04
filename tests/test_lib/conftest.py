"""Local test config for test_lib/.

Stub heavy optional dependencies so test_lib modules can be imported
even when those packages are not installed in the dev environment.
Production imports still require these (pyproject.toml). Test-only workaround.
Mirrors tests/test_cli_ext/conftest.py.
"""
from contextlib import contextmanager
import sys
import types

import pytest


_MISSING = object()
_STUB_NAMES = ("platformdirs", "lancedb", "pyarrow", "pypdf", "docx", "openpyxl", "mcp")
# --- platformdirs ---
_pd_stub = types.ModuleType("platformdirs")
_pd_stub.user_cache_dir = lambda *a, **kw: ""
_pd_stub.user_config_dir = lambda *a, **kw: ""
sys.modules.setdefault("platformdirs", _pd_stub)


# --- lancedb ---
_lancedb_stub = types.ModuleType("lancedb")
_lancedb_stub.connect = lambda *a, **kw: None
_lancedb_stub.table = lambda *a, **kw: None
_lancedb_stub.LanceDB = type("LanceDB", (), {})
_lancedb_stub.Table = type("Table", (), {})
sys.modules.setdefault("lancedb", _lancedb_stub)


# --- pyarrow ---
_pa_stub = types.ModuleType("pyarrow")
_pa_stub.table = lambda *a, **kw: None
_pa_stub.schema = lambda *a, **kw: None
sys.modules.setdefault("pyarrow", _pa_stub)


# --- pypdf ---
_pypdf_stub = types.ModuleType("pypdf")


class _StubPdfReader:
    def __init__(self, *args, **kwargs):
        self.pages = []


_pypdf_stub.PdfReader = _StubPdfReader
sys.modules.setdefault("pypdf", _pypdf_stub)


# --- python-docx ---
_docx_stub = types.ModuleType("docx")
_docx_stub.Document = lambda *a, **kw: None
sys.modules.setdefault("docx", _docx_stub)


# --- openpyxl ---
_openpyxl_stub = types.ModuleType("openpyxl")
_openpyxl_stub.load_workbook = lambda *a, **kw: None
sys.modules.setdefault("openpyxl", _openpyxl_stub)


# --- mcp (Model Context Protocol) ---
_mcp_stub = types.ModuleType("mcp")
sys.modules.setdefault("mcp", _mcp_stub)


_STUBS = {
    "platformdirs": _pd_stub,
    "lancedb": _lancedb_stub,
    "pyarrow": _pa_stub,
    "pypdf": _pypdf_stub,
    "docx": _docx_stub,
    "openpyxl": _openpyxl_stub,
    "mcp": _mcp_stub,
}


@pytest.fixture
def isolated_optional_stubs():
    """Return a context manager for testing an isolated stub boundary."""
    @contextmanager
    def activate():
        previous = {name: sys.modules.get(name, _MISSING) for name in _STUB_NAMES}
        sys.modules.update(_STUBS)
        try:
            yield _STUBS
        finally:
            for name, module in previous.items():
                if module is _MISSING:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module

    return activate


@pytest.fixture(autouse=True)
def _restore_real_platformdirs():
    previous = sys.modules.get("platformdirs", _MISSING)
    paths_module = sys.modules.get("src.project.paths")
    previous_config = getattr(paths_module, "user_config_dir", None)
    if previous is not _MISSING and getattr(previous, "__file__", None) is None:
        del sys.modules["platformdirs"]
    import platformdirs
    if paths_module is not None:
        paths_module.user_config_dir = platformdirs.user_config_dir
    yield
    if previous is _MISSING:
        sys.modules.pop("platformdirs", None)
    else:
        sys.modules["platformdirs"] = previous
    if paths_module is not None and previous_config is not None:
        paths_module.user_config_dir = previous_config
