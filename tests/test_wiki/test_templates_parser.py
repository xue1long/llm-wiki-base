"""Tests for src/wiki/templates/parser.py (Plan 25 v1)."""
import pytest

from src.wiki.core.types import PageType
from src.wiki.templates.parser import (
    parse,
    render,
    render_for_prompt,
    TemplateParseError,
    validate_type_header,
)


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


# ---------------------------------------------------------------------------
# O-1: shared validate_type_header() helper — used by parser, resolver, CLI
# ---------------------------------------------------------------------------

def test_validate_type_header_accepts_matching_type():
    src = (
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: concept -->\n"
    )
    matched = validate_type_header(src, PageType.CONCEPT)
    assert matched == "concept"


def test_validate_type_header_rejects_missing_header():
    src = "<!-- wiki-template-version: 1.0.0 -->\n"
    with pytest.raises(TemplateParseError, match="wiki-template-type"):
        validate_type_header(src, PageType.CONCEPT)


def test_validate_type_header_rejects_mismatch():
    src = (
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: entity -->\n"
    )
    with pytest.raises(TemplateParseError, match="type mismatch"):
        validate_type_header(src, PageType.CONCEPT)


def test_validate_type_header_ignores_non_first_match():
    """Only the FIRST wiki-template-type header is authoritative.

    A user may legitimately mention the type name in a comment block
    later in the file. The header must be the very first one.
    """
    src = (
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: concept -->\n\n"
        "<!-- wiki-template-type: entity -->\n"
    )
    matched = validate_type_header(src, PageType.CONCEPT)
    assert matched == "concept"
    with pytest.raises(TemplateParseError, match="type mismatch"):
        validate_type_header(src, PageType.ENTITY)


def test_parse_and_validate_type_header_share_semantics():
    """parse() and validate_type_header() must agree on type checking.

    Same input → same error message (modulo prefix).
    """
    bad = "<!-- wiki-template-version: 1.0.0 -->\n<!-- wiki-template-type: entity -->\n"
    parse_err = None
    val_err = None
    try:
        parse(bad, expected_type=PageType.CONCEPT)
    except TemplateParseError as e:
        parse_err = str(e)
    try:
        validate_type_header(bad, PageType.CONCEPT)
    except TemplateParseError as e:
        val_err = str(e)
    assert parse_err is not None and val_err is not None
    # Both errors mention 'type mismatch' (same root issue)
    assert "type mismatch" in parse_err
    assert "type mismatch" in val_err


# ---------------------------------------------------------------------------
# O-7: render_for_prompt() — compact, LLM-facing projection
# ---------------------------------------------------------------------------

def test_render_round_trip_basic():
    """render() must round-trip through parse() for a basic template."""
    src = (
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: concept -->\n\n"
        "## 定义\n\n<!-- slot:definition -->\n\n"
        "## 例子\n\n<!-- slot:examples -->\n"
    )
    ast = parse(src, expected_type=PageType.CONCEPT)
    out = render(ast)
    # Re-parsing the rendered output yields the same section headings + slots
    ast2 = parse(out, expected_type=PageType.CONCEPT)
    assert [s.heading for s in ast2.sections] == [s.heading for s in ast.sections]
    assert [s.name for s in ast2.all_slots] == [s.name for s in ast.all_slots]


def test_render_for_prompt_basic_compact():
    """render_for_prompt() omits blank lines between heading+slots."""
    src = (
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: concept -->\n\n"
        "## 定义\n\n<!-- slot:definition -->\n\n"
        "## 例子\n\n<!-- slot:examples -->\n"
    )
    ast = parse(src, expected_type=PageType.CONCEPT)
    out = render_for_prompt(ast)
    # No double blank lines, headings followed immediately by slots
    assert "## 定义\n<!-- slot:definition -->" in out
    assert "## 例子\n<!-- slot:examples -->" in out
    # No trailing newline
    assert not out.endswith("\n")


def test_render_for_prompt_marks_optional_with_question_mark():
    """Optional slots (slot:NAME?) keep the ? in the prompt output."""
    src = (
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: entity -->\n\n"
        "## 别名\n\n<!-- slot:aliases? -->\n"
    )
    ast = parse(src, expected_type=PageType.ENTITY)
    out = render_for_prompt(ast)
    assert "<!-- slot:aliases? -->  _(optional)_" in out


def test_render_for_prompt_marks_if_block_slots_with_condition():
    """Slots inside an if-block are annotated with their condition label."""
    src = (
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: entity -->\n\n"
        "## 别名\n\n"
        "<!-- if:has_aliases -->\n\n"
        "<!-- slot:aliases -->\n\n"
        "<!-- /if:has_aliases -->\n"
    )
    ast = parse(src, expected_type=PageType.ENTITY)
    out = render_for_prompt(ast)
    assert "<!-- slot:aliases? -->  _(optional, condition: has_aliases)_" in out


def test_render_for_prompt_empty_when_no_sections():
    """An AST with no sections renders to empty string (defensive)."""
    from src.wiki.templates.types import TemplateAST
    ast = TemplateAST(page_type=PageType.SOURCE, version="1.0.0", sections=[])
    assert render_for_prompt(ast) == ""


def test_render_for_prompt_preserves_prose_before_slots():
    """Section bodies with prose (not just slot markers) keep the prose."""
    src = (
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: source -->\n\n"
        "## 来源元数据\n\n"
        "_URL, 作者, 日期 等_\n\n"
        "<!-- slot:source_meta -->\n"
    )
    ast = parse(src, expected_type=PageType.SOURCE)
    out = render_for_prompt(ast)
    assert "_URL, 作者, 日期 等_" in out
    assert "<!-- slot:source_meta -->" in out


def test_render_for_prompt_distinct_from_render():
    """render() and render_for_prompt() produce different output for the same AST.

    Guards against accidentally collapsing the two functions.
    """
    src = (
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: concept -->\n\n"
        "## 定义\n\n<!-- slot:definition -->\n"
    )
    ast = parse(src, expected_type=PageType.CONCEPT)
    r1 = render(ast)
    r2 = render_for_prompt(ast)
    # render() re-emits headers; render_for_prompt() doesn't
    assert "<!-- wiki-template-version:" in r1
    assert "<!-- wiki-template-version:" not in r2