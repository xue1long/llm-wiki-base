"""T1.5: built-in prompt TOMLs parse and resolve correctly."""
from __future__ import annotations

import pytest

from src.pipeline.v7_extract.prompts.parser import parse_prompt
from src.pipeline.v7_extract.prompts.resolver import (
    BUNDLED_ROOT,
    PromptNotFoundError,
    resolve,
)


def test_builtin_dir_exists():
    assert BUNDLED_ROOT.is_dir(), f"bundled dir missing: {BUNDLED_ROOT}"


@pytest.mark.parametrize("kind", ["classify", "completeness", "cluster", "fill_slots"])
def test_builtin_prompt_parses(kind):
    path = BUNDLED_ROOT / f"{kind}.toml"
    assert path.is_file(), f"bundled prompt missing: {path}"
    ast = parse_prompt(path)
    assert ast.prompt_kind == kind
    assert ast.version is not None
    assert ast.user_section  # non-empty
    assert ast.output_schema is not None


@pytest.mark.parametrize("kind", ["classify", "completeness", "cluster", "fill_slots"])
def test_resolve_bundled_returns_each_prompt(tmp_path, monkeypatch, kind):
    """No project / user overrides → resolve() returns the bundled prompt."""
    monkeypatch.delenv("TMPDIR", raising=False)
    monkeypatch.delenv("TEMP", raising=False)
    monkeypatch.delenv("TMP", raising=False)
    monkeypatch.setattr(
        "src.pipeline.v7_extract.prompts.resolver._user_root",
        lambda: tmp_path / "user_does_not_exist",
    )
    tpl = resolve(kind)
    assert tpl.source == "bundled"
    assert tpl.prompt_kind == kind
    assert tpl.path == BUNDLED_ROOT / f"{kind}.toml"


def test_resolve_unknown_kind_raises():
    with pytest.raises(PromptNotFoundError, match="never_defined_kind"):
        resolve("never_defined_kind")


def test_classify_prompt_schema_includes_all_7_doctypes():
    """A3: classify.toml's output_schema.enum.doc_type must list all 7 types."""
    ast = parse_prompt(BUNDLED_ROOT / "classify.toml")
    enum = ast.output_schema["enum"]["doc_type"]
    assert set(enum) == {
        "single_method", "multi_section", "collection",
        "qa_chat", "list", "tool", "incomplete",
    }


def test_classify_prompt_has_three_slots():
    """content / filename_hint / content_limit — matches T1.2 schema."""
    ast = parse_prompt(BUNDLED_ROOT / "classify.toml")
    names = [s.name for s in ast.all_slots]
    assert "content" in names
    assert "filename_hint" in names
    assert "content_limit" in names


def test_fill_slots_prompt_requires_two_outputs():
    """fill_slots schema requires both 'slots' and 'evidence' (Stage-5 evidence contract)."""
    ast = parse_prompt(BUNDLED_ROOT / "fill_slots.toml")
    required = ast.output_schema["required"]
    assert "slots" in required
    assert "evidence" in required
