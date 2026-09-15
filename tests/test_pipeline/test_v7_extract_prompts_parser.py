"""T1.2: TOML parser + D9 schema validation tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.pipeline.v7_extract.prompts.parser import (
    PromptParseError,
    _ALLOWED_DOC_TYPES,
    parse_prompt,
)


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_parse_minimal_prompt(tmp_path):
    p = _write(tmp_path, "classify.toml", """
[meta]
prompt_kind = "classify"
version = "1.0"

[system]
text = "You are a classifier."

[user]
template = "Classify: {content}"
""")
    ast = parse_prompt(p)
    assert ast.prompt_kind == "classify"
    assert ast.version == "1.0"
    assert ast.system_section == "You are a classifier."
    assert ast.user_section == "Classify: {content}"
    assert ast.output_schema is None


def test_parse_with_output_schema(tmp_path):
    p = _write(tmp_path, "x.toml", """
[meta]
prompt_kind = "classify"
version = "2.0"

[user]
template = "{content}"

[output_schema]
type = "json"
required = ["doc_type", "confidence"]
enum = { doc_type = ["single_method", "multi_section", "list"] }
range = { confidence = [0.0, 1.0] }
""")
    ast = parse_prompt(p)
    assert ast.output_schema["type"] == "json"
    assert ast.output_schema["enum"]["doc_type"] == ["single_method", "multi_section", "list"]


def test_parse_with_slots(tmp_path):
    p = _write(tmp_path, "x.toml", """
[meta]
prompt_kind = "classify"
version = "1.0"

[user]
template = "{content}"

[[slot]]
name = "content"
required = true

[[slot]]
name = "filename_hint"
required = false
default = ""
""")
    ast = parse_prompt(p)
    names = [s.name for s in ast.all_slots]
    assert "content" in names
    assert "filename_hint" in names
    assert "content" in ast.required_slots
    assert "filename_hint" not in ast.required_slots


def test_parse_missing_meta_raises(tmp_path):
    p = _write(tmp_path, "x.toml", """
[user]
template = "x"
""")
    with pytest.raises(PromptParseError, match="meta"):
        parse_prompt(p)


def test_parse_invalid_toml_raises(tmp_path):
    p = _write(tmp_path, "x.toml", "this is not = valid toml ===")
    with pytest.raises(PromptParseError, match="Invalid TOML"):
        parse_prompt(p)


def test_parse_empty_file_raises(tmp_path):
    p = _write(tmp_path, "x.toml", "")
    with pytest.raises(PromptParseError, match="meta"):
        parse_prompt(p)


def test_parse_unknown_doc_type_in_enum_rejected_d9(tmp_path):
    """D9 / A18: a malicious prompt can't smuggle in an unknown doc_type."""
    p = _write(tmp_path, "x.toml", """
[meta]
prompt_kind = "classify"
version = "1.0"

[user]
template = "{content}"

[output_schema]
type = "json"
required = ["doc_type"]
enum = { doc_type = ["single_method", "pwned"] }
""")
    with pytest.raises(PromptParseError, match="unknown doc_type"):
        parse_prompt(p)


def test_parse_all_known_doc_types_accepted(tmp_path):
    """All 7 DocType values must pass D9 validation."""
    all_seven = [
        "single_method", "multi_section", "collection",
        "qa_chat", "list", "tool", "incomplete",
    ]
    p = _write(tmp_path, "x.toml", f"""
[meta]
prompt_kind = "classify"
version = "1.0"

[user]
template = "{{content}}"

[output_schema]
type = "json"
required = ["doc_type"]
enum = {{ doc_type = {all_seven!r} }}
""")
    ast = parse_prompt(p)
    assert set(ast.output_schema["enum"]["doc_type"]) == _ALLOWED_DOC_TYPES


def test_parse_output_schema_no_enum_passes(tmp_path):
    """Schemas without an enum block are still valid."""
    p = _write(tmp_path, "x.toml", """
[meta]
prompt_kind = "x"
version = "1.0"

[user]
template = "{x}"

[output_schema]
type = "text"
""")
    ast = parse_prompt(p)
    assert ast.output_schema == {"type": "text"}


def test_parse_read_error_raises(tmp_path):
    """If the file doesn't exist, raise PromptParseError not OSError.

    We match on the message string rather than on ``PromptParseError``
    directly — pytest's exception class matching is sensitive to
    module-reload races across the 700+ test suite where parser.py can
    be imported via multiple paths.
    """
    target = (tmp_path / "definitely_missing.toml").resolve()
    with pytest.raises(Exception, match="Cannot read prompt file"):
        parse_prompt(target)
