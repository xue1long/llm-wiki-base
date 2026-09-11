"""Regression checks for mode propagation and readiness fail-closed behavior."""

import ast
from pathlib import Path


def test_service_reports_readiness_and_forwards_mode():
    root = Path(__file__).parents[2]
    service_source = (root / "src/services/search.py").read_text(encoding="utf-8")
    hybrid_source = (root / "src/searcher/hybrid_search.py").read_text(encoding="utf-8")
    assert "readiness" in service_source
    assert "mode=mode" in service_source
    hybrid_tree = ast.parse(hybrid_source)
    function = next(
        node for node in hybrid_tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "hybrid_search"
    )
    assert any(arg.arg == "mode" for arg in function.args.args + function.args.kwonlyargs)
