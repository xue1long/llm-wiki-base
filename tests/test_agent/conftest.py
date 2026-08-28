"""Keep agent tests from inheriting sibling dependency stubs."""
import importlib.metadata
import sys


try:
    importlib.metadata.version("lancedb")
    importlib.metadata.version("pyarrow")
except importlib.metadata.PackageNotFoundError:
    pass
else:
    for _name in ("pyarrow", "lancedb"):
        _module = sys.modules.get(_name)
        if _module is not None and getattr(_module, "__file__", None) is None:
            del sys.modules[_name]
    import pyarrow  # noqa: F401
    import lancedb  # noqa: F401
