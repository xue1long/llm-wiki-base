"""Tests for src/wiki/templates/renderer.py (Plan 27 v2.3 schema)."""
import re

import pytest

from src.wiki.core.types import PageType
from src.wiki.templates.renderer import (
    compute_slot_fill_status,
    render_body,
    SlotFillStatus,
)


# ---------------------------------------------------------------------------
# Helper: minimal template body covering one required + one optional slot.
# ---------------------------------------------------------------------------

_MINIMAL_BODY = (
    "<!-- wiki-template-version: 2.0.0 -->\n"
    "<!-- wiki-template-type: concept -->\n\n"
    "## 定义\n\n"
    "<!-- slot:definition -->\n\n"
    "## 别名\n\n"
    "<!-- slot:aliases? -->\n"
)


def test_render_full_slots_concatenates_all_headings():
    """Required + optional slots both filled → all headings present + content."""
    out = render_body(
        template_body=_MINIMAL_BODY,
        slots={"definition": "这是 X 的定义。", "aliases": ["A", "B"]},
        page_type=PageType.CONCEPT,
    )
    assert "## 定义" in out
    assert "## 别名" in out
    assert "这是 X 的定义。" in out
    assert "- A" in out
    assert "- B" in out
    assert "<!-- slot:" not in out


def test_render_drops_empty_optional():
    """Optional slot with empty content → entire section (heading + slot) dropped."""
    out = render_body(
        template_body=_MINIMAL_BODY,
        slots={"definition": "d", "aliases": []},
        page_type=PageType.CONCEPT,
    )
    assert "## 定义" in out
    assert "d" in out
    assert "## 别名" not in out
    assert "<!-- slot:aliases" not in out


def test_render_inserts_placeholder_for_empty_required():
    """Required slot with empty content → placeholder inserted under heading."""
    out = render_body(
        template_body=_MINIMAL_BODY,
        slots={"definition": "", "aliases": []},
        page_type=PageType.CONCEPT,
        missing_placeholder="（待补充）",
    )
    assert "## 定义" in out
    assert "（待补充）" in out
    assert "## 别名" not in out


def test_render_handles_list_values():
    """Slot value may be a list[str] → joined as markdown bullets."""
    out = render_body(
        template_body=_MINIMAL_BODY,
        slots={"definition": ["句子 1。", "句子 2。"], "aliases": []},
        page_type=PageType.CONCEPT,
    )
    assert "- 句子 1。" in out
    assert "- 句子 2。" in out


def test_render_no_extra_blank_lines():
    """3+ consecutive blank lines collapse to 2."""
    body = (
        "<!-- wiki-template-version: 2.0.0 -->\n"
        "<!-- wiki-template-type: concept -->\n\n"
        "## 定义\n\n"
        "<!-- slot:definition -->\n\n"
        "## 例子\n\n"
        "<!-- slot:examples -->\n"
    )
    out = render_body(
        template_body=body,
        slots={"definition": "d", "examples": "e"},
        page_type=PageType.CONCEPT,
    )
    assert "\n\n\n" not in out


# ---------------------------------------------------------------------------
# Real bundled templates: round-trip smoke for every PageType.
# ---------------------------------------------------------------------------

from pathlib import Path


def _bundled(name: str) -> str:
    return (Path(__file__).resolve().parents[2]
            / "src" / "wiki" / "templates" / "bundled" / name).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "page_type,filename,slots",
    [
        (PageType.SOURCE, "source.md",
         {"source_meta": "路径: foo.md\n时间: 2026-01-01",
          "summary": "一句话摘要",
          "key_points": ["要点 1", "要点 2"],
          "extracted_concepts": ["概念 A", "概念 B"],
          "main_content": "原始文档完整正文内容。"}),
        (PageType.ENTITY, "entity.md",
         {"basic_info": "人物：X", "summary": "简介", "related": ["→ Y"], "aliases": ["昵称 1"]}),
        (PageType.CONCEPT, "concept.md",
         {"definition": "定义",
          "characteristics": ["特性 1", "特性 2"],
          "examples": ["例 1"],
          "related_concepts": ["相关"],
          "references": ["来源"]}),
        (PageType.SYNTHESIS, "synthesis.md",
         {"comparison_dimensions": ["维度 A"],
          "overview": "综述",
          "involved_concepts": ["c1"],
          "comparison": "| A | B |\n|---|---|\n| 1 | 2 |",
          "conclusion": "结论"}),
    ],
)
def test_render_bundled_template_round_trip(page_type, filename, slots):
    """Each bundled template renders with all required headings present when
    every required slot is filled."""
    body = _bundled(filename)
    out = render_body(template_body=body, slots=slots, page_type=page_type)
    template_headings = re.findall(r"^## (.+)$", body, re.MULTILINE)
    body_headings = set(re.findall(r"^## (.+)$", out, re.MULTILINE))
    for h in template_headings:
        assert h in body_headings, f"missing heading '{h}' in rendered body:\n{out}"


# ---------------------------------------------------------------------------
# SlotFillStatus — used by the Generator's retry loop.
# ---------------------------------------------------------------------------


def test_slot_fill_status_reports_missing():
    """SlotFillStatus separates given vs missing slot names."""
    status = compute_slot_fill_status(
        available={"a": "x", "b": "y", "c": "z"},   # all given, c is extra
        required=["a", "b", "d"],
    )
    assert status.given == ["a", "b"]
    assert status.missing == ["d"]
    assert status.extra == ["c"]


def test_slot_fill_status_empty_values_count_as_missing():
    """Empty strings and empty lists count as missing — not given."""
    status = compute_slot_fill_status(
        available={"a": "", "b": [], "c": "ok", "d": None},
        required=["a", "b", "c", "d"],
    )
    assert status.given == ["c"]
    assert status.missing == ["a", "b", "d"]


# ---------------------------------------------------------------------------
# Section-level optional-empty dropping with all-optional sections.
# ---------------------------------------------------------------------------


def test_render_drops_section_when_only_optional_and_all_empty():
    """A section with only optional slots, all empty → section dropped."""
    # The if-block must lie entirely within one section; that's a parser
    # constraint (per-section conditional_ranges search depends on it).
    body = (
        "<!-- wiki-template-version: 2.0.0 -->\n"
        "<!-- wiki-template-type: source -->\n\n"
        "## 来源元数据\n\n<!-- slot:source_meta -->\n\n"
        "## 摘要\n\n<!-- slot:summary -->\n\n"
        "## 关键观点\n\n"
        "<!-- if:has_key_points -->\n\n"
        "<!-- slot:key_points? -->\n\n"
        "<!-- /if:has_key_points -->\n\n"
        "## 抽取的概念\n\n<!-- slot:extracted_concepts -->\n"
    )
    out = render_body(
        template_body=body,
        slots={"source_meta": "m", "summary": "s", "key_points": [], "extracted_concepts": "ec"},
        page_type=PageType.SOURCE,
    )
    assert "## 来源元数据" in out
    assert "## 摘要" in out
    assert "## 抽取的概念" in out
    # key_points was optional + empty, so its section (heading + slot) is dropped.
    assert "## 关键观点" not in out


def test_render_source_drops_main_content_when_empty():
    """The ## 正文内容 section (optional main_content slot) is dropped when
    the slot value is empty, since all slots in that section are optional."""
    body = _bundled("source.md")
    out = render_body(
        template_body=body,
        slots={
            "source_meta": "meta", "summary": "s",
            "key_points": ["kp"], "extracted_concepts": ["ec"],
            "main_content": "",
        },
        page_type=PageType.SOURCE,
    )
    assert "## 正文内容" not in out
    # Required sections still present
    assert "## 来源元数据" in out
    assert "## 摘要" in out


def test_render_source_never_renders_main_content():
    """The ## 正文内容 section is gone from the source template (RAG: full text
    lives in raw/, source pages carry summary+metadata only). Even if a
    stray main_content key is present in slots, it is NOT rendered — it is
    not a template slot."""
    out = render_body(
        template_body=_bundled("source.md"),
        slots={
            "source_meta": "来源: test.md",
            "summary": "一句话摘要",
            "key_points": ["要点 1"],
            "extracted_concepts": ["c1"],
            "main_content": "# Title\n\nFull text content here.\n",
        },
        page_type=PageType.SOURCE,
    )
    assert "## 正文内容" not in out
    assert "Full text content here." not in out
    assert "<!-- slot:" not in out


# ---------------------------------------------------------------------------
# Fix A — render_body preserves template-version / template-type markers.
# Without this injection, every freshly generated page body misses the
# `<!-- wiki-template-version: ... -->` header that LINT-MISSING-SECTION
# reads raw. Verify render_body prepends when template_version is supplied
# and stays clean when it isn't (backward-compatible for tests that don't
# care about the marker).
# ---------------------------------------------------------------------------


_CONCEPT_BODY = (
    "<!-- wiki-template-version: 2.0.0 -->\n"
    "<!-- wiki-template-type: concept -->\n\n"
    "## 定义\n\n<!-- slot:definition -->\n\n"
    "## 参考来源\n\n<!-- slot:references -->\n"
)


def test_render_body_prepends_template_header_when_version_supplied():
    """Pass template_version='2.0.0' → first line of output is the version marker."""
    out = render_body(
        template_body=_CONCEPT_BODY,
        slots={"definition": "d", "references": "r"},
        page_type=PageType.CONCEPT,
        template_version="2.0.0",
    )
    lines = out.splitlines()
    assert lines[0] == "<!-- wiki-template-version: 2.0.0 -->", (
        f"first line should be template-version marker, got:\n{out[:200]}"
    )
    assert lines[1] == "<!-- wiki-template-type: concept -->", (
        f"second line should be template-type marker, got:\n{out[:200]}"
    )
    # Section heading comes after the marker block (with a blank line between).
    assert lines[3] == "## 定义"


def test_render_body_omits_template_header_when_version_blank():
    """Empty / unset template_version → no marker injection (backward compat)."""
    out = render_body(
        template_body=_CONCEPT_BODY,
        slots={"definition": "d", "references": "r"},
        page_type=PageType.CONCEPT,
        template_version="",
    )
    # First line is still the section heading, not a marker.
    assert out.splitlines()[0] == "## 定义", (
        f"without version, body should start with heading, got:\n{out[:200]}"
    )
