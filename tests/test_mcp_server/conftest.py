"""Local test config for test_mcp_server/.

Restore the real mcp module: sibling conftest.py files install a stub
``mcp`` via ``sys.modules.setdefault``, but ``src.mcp_server.main``
imports ``from mcp.server import Server`` which the stub does not
expose. Collection-time error, so the fix must run at conftest load
(not inside a per-test fixture).
"""
import sys

_m = sys.modules.get("mcp")
if _m is not None and getattr(_m, "__file__", None) is None:
    del sys.modules["mcp"]
import mcp  # noqa: E402, F401
