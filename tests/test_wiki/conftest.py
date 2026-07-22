"""Local test config for test_wiki/.

Stubs heavy optional dependencies so src.pipeline.__init__ can be imported
lazily from tests that need it (e.g. test_stubs._materialize_one calls into
src.pipeline.generator, which triggers src.pipeline.__init__ which requires
pypdf, lancedb, docx, openpyxl, mcp, pyarrow, platformdirs).
Test-only workaround; production imports still require these (pyproject.toml).
Mirrors tests/test_pipeline/conftest.py.
"""
import sys
import types


# --- pypdf ---
class _StubPdfReader:
    def __init__(self, *args, **kwargs):
        self.pages = []

    @classmethod
    def _create_blank(cls, *args, **kwargs):
        return cls()


_pypdf_stub = types.ModuleType("pypdf")
_pypdf_stub.PdfReader = _StubPdfReader
sys.modules.setdefault("pypdf", _pypdf_stub)


# --- lancedb ---
_lancedb_stub = types.ModuleType("lancedb")
_lancedb_stub.connect = lambda *a, **kw: None
_lancedb_stub.table = lambda *a, **kw: None
_lancedb_stub.LanceDB = type("LanceDB", (), {})
_lancedb_stub.Table = type("Table", (), {})
sys.modules.setdefault("lancedb", _lancedb_stub)


# --- python-docx ---
_docx_stub = types.ModuleType("docx")
_docx_stub.Document = lambda *a, **kw: None
sys.modules.setdefault("docx", _docx_stub)


# --- openpyxl ---
_oxl_stub = types.ModuleType("openpyxl")
_oxl_stub.load_workbook = lambda *a, **kw: None
sys.modules.setdefault("openpyxl", _oxl_stub)


# --- mcp ---
_mcp_stub = types.ModuleType("mcp")
sys.modules.setdefault("mcp", _mcp_stub)


# --- pyarrow ---
_pa_stub = types.ModuleType("pyarrow")
_pa_stub.table = lambda *a, **kw: None
_pa_stub.schema = lambda *a, **kw: None
sys.modules.setdefault("pyarrow", _pa_stub)


# --- platformdirs ---
_pd_stub = types.ModuleType("platformdirs")
_pd_stub.user_cache_dir = lambda *a, **kw: ""
_pd_stub.user_config_dir = lambda *a, **kw: ""
sys.modules.setdefault("platformdirs", _pd_stub)