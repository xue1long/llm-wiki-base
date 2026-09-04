"""Keep the test suite independent from host-specific RUFLO settings."""
import pytest
import sys


_MODULE_BOUNDARY_NAMES = {
    "platformdirs", "lancedb", "pyarrow", "pypdf", "docx", "openpyxl", "mcp", "tavily",
}


@pytest.fixture(autouse=True)
def _clear_host_llm_provider(monkeypatch):
    monkeypatch.delenv("RUFLO_LLM_PROVIDER", raising=False)


@pytest.fixture(autouse=True)
def _restore_module_boundary():
    """Prevent test-time sys.modules mutations crossing test boundaries."""
    before = {
        name: sys.modules.get(name)
        for name in _MODULE_BOUNDARY_NAMES
    }
    before_scripts = {
        name: module
        for name, module in sys.modules.items()
        if name == "scripts" or name.startswith("scripts.")
    }
    yield
    for name in _MODULE_BOUNDARY_NAMES:
        module = before[name]
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module
    for name in list(sys.modules):
        if name == "scripts" or name.startswith("scripts."):
            if name not in before_scripts:
                del sys.modules[name]
    sys.modules.update(before_scripts)
