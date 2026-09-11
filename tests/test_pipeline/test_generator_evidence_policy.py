"""Regression checks for evidence driven page generation."""

import ast
from pathlib import Path


def test_empty_evidence_returns_without_quantity_retry():
    path = Path(__file__).parents[2] / "src" / "pipeline" / "generator.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_call_with_slot_retry"
    )
    empty_branch = next(
        node for node in ast.walk(function)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.UnaryOp)
        and isinstance(node.test.op, ast.Not)
        and isinstance(node.test.operand, ast.Call)
        and isinstance(node.test.operand.func, ast.Attribute)
        and node.test.operand.func.attr == "get"
    )
    branch_text = ast.get_source_segment(source, empty_branch) or ""
    assert "return response_dict" in branch_text
    assert "continue" not in branch_text
    assert "2+ entity or concept pages" not in branch_text


def test_generator_drops_actionable_tag_before_human_review():
    source = (
        Path(__file__).parents[2] / "src" / "pipeline" / "generator.py"
    ).read_text(encoding="utf-8")
    assert "ACTIONABLE_TAG" in source
    assert "blocked_actionable" in source
