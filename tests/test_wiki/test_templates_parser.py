"""Tests for src/wiki/templates/parser.py (Plan 25 v1)."""
import pytest

from src.wiki.core.types import PageType
from src.wiki.templates.parser import parse, TemplateParseError


def _concept_template() -> str:
    return (
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: concept -->\n\n"
        "## 定义\n\n"
        "<!-- slot:definition -->\n\n"
        "## 例子\n\n"
        "<!-- slot:examples -->\n"
    )


def test_parse_extracts_version():
    ast = parse(_concept_template(), expected_type=PageType.CONCEPT)
    assert ast.version == "1.0.0"
    assert ast.page_type == PageType.CONCEPT


def test_parse_extracts_sections():
    ast = parse(_concept_template(), expected_type=PageType.CONCEPT)
    assert len(ast.sections) == 2
    assert ast.sections[0].heading == "## 定义"
    assert ast.sections[1].heading == "## 例子"


def test_parse_extracts_slot_markers():
    ast = parse(_concept_template(), expected_type=PageType.CONCEPT)
    slots = ast.all_slots
    assert len(slots) == 2
    assert slots[0].name == "definition"
    assert slots[1].name == "examples"
    assert all(not s.is_optional for s in slots)


def test_parse_optional_slot_marked():
    src = (
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: entity -->\n\n"
        "## 别名\n\n"
        "<!-- slot:aliases? -->\n"
    )
    ast = parse(src, expected_type=PageType.ENTITY)
    slot = ast.all_slots[0]
    assert slot.is_optional
    assert slot.name == "aliases"


def test_parse_if_block_marks_slot_optional():
    src = (
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: entity -->\n\n"
        "## 别名\n\n"
        "<!-- if:has_aliases -->\n\n"
        "<!-- slot:aliases -->\n\n"
        "<!-- /if:has_aliases -->\n"
    )
    ast = parse(src, expected_type=PageType.ENTITY)
    slot = ast.all_slots[0]
    assert slot.is_optional
    assert slot.condition_label == "has_aliases"


def test_parse_missing_version_raises():
    src = (
        "<!-- wiki-template-type: concept -->\n\n"
        "## 定义\n\n<!-- slot:definition -->\n"
    )
    with pytest.raises(TemplateParseError, match="wiki-template-version"):
        parse(src, expected_type=PageType.CONCEPT)


def test_parse_type_mismatch_raises():
    src = (
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: entity -->\n\n"
        "## foo\n"
    )
    with pytest.raises(TemplateParseError, match="type mismatch"):
        parse(src, expected_type=PageType.CONCEPT)


def test_parse_unclosed_if_raises():
    src = (
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: concept -->\n\n"
        "## foo\n\n<!-- if:bar -->\n<!-- slot:x -->\n"
    )
    with pytest.raises(TemplateParseError, match="Unclosed"):
        parse(src, expected_type=PageType.CONCEPT)


def test_parse_empty_raises():
    with pytest.raises(TemplateParseError, match="empty"):
        parse("", expected_type=PageType.CONCEPT)


def test_parse_extracts_include():
    src = (
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: concept -->\n\n"
        "<!-- include:_base.md -->\n\n"
        "## 定义\n\n<!-- slot:definition -->\n"
    )
    ast = parse(src, expected_type=PageType.CONCEPT)
    assert len(ast.sections) == 1


# ---------------------------------------------------------------------------
# Phase 2: conditional slots (Bug 4/5 fix: <!-- if:X --> ≡ <!-- slot:? -->)
# ---------------------------------------------------------------------------

def test_parse_if_block_with_multiple_slots():
    """An if block can contain multiple slots, all marked optional."""
    src = (
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: entity -->\n\n"
        "## 引用\n\n"
        "<!-- if:has_citations -->\n\n"
        "<!-- slot:citations -->\n\n"
        "<!-- slot:footnotes -->\n\n"
        "<!-- /if:has_citations -->\n"
    )
    ast = parse(src, expected_type=PageType.ENTITY)
    slots = ast.all_slots
    assert len(slots) == 2
    for s in slots:
        assert s.is_optional
        assert s.condition_label == "has_citations"


def test_parse_mix_optional_and_required_slots():
    """Slots inside an if-block are optional; outside they're required."""
    src = (
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: entity -->\n\n"
        "## 简介\n\n"
        "<!-- slot:summary -->\n\n"
        "## 别名\n\n"
        "<!-- if:has_aliases -->\n\n"
        "<!-- slot:aliases -->\n\n"
        "<!-- /if:has_aliases -->\n"
    )
    ast = parse(src, expected_type=PageType.ENTITY)
    assert len(ast.all_slots) == 2
    assert ast.all_slots[0].name == "summary"
    assert not ast.all_slots[0].is_optional
    assert ast.all_slots[1].name == "aliases"
    assert ast.all_slots[1].is_optional


def test_parse_slot_question_mark_stored_as_optional():
    """`<!-- slot:NAME? -->` is parsed with is_optional=True and condition_label=None."""
    src = (
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: entity -->\n\n"
        "## 别名\n\n"
        "<!-- slot:aliases? -->\n"
    )
    ast = parse(src, expected_type=PageType.ENTITY)
    s = ast.all_slots[0]
    assert s.is_optional
    assert s.condition_label is None
    assert s.name == "aliases"


# ---------------------------------------------------------------------------
# Phase 2: template inheritance via <!-- include: -->
# ---------------------------------------------------------------------------

def test_parse_includes_are_tracked_in_ast():
    src = (
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: concept -->\n\n"
        "<!-- include:_base.md -->\n\n"
        "## 定义\n\n<!-- slot:definition -->\n"
    )
    # Note: include extraction in AST is implicit (parser does NOT
    # explicitly track Include nodes — it's the resolver that expands
    # them). Just verify the body has the include marker preserved.
    ast = parse(src, expected_type=PageType.CONCEPT)
    assert "<!-- include:_base.md -->" in ast.raw