"""Tests for src/pipeline/quality_gate.py — check_pages() + helpers."""
import pytest
from src.pipeline.quality_gate import (
    check_pages,
    QualityGateResult,
    _has_type_prefix,
    _meaningful_length,
)
from src.wiki.core.types import WikiPage, PageType


def _make_page(id="test-001", title="Test Page", body="Some meaningful content here.", processing_depth="concept", grade="B"):
    return WikiPage(id=id, title=title, type=PageType.CONCEPT, body=body, processing_depth=processing_depth, grade=grade)


class TestHasTypePrefix:
    def test_detects_concept_prefix(self):
        assert _has_type_prefix("concept-穿越小说") is True

    def test_detects_entity_prefix(self):
        assert _has_type_prefix("entity-some-slug") is True

    def test_detects_synthesis_prefix(self):
        assert _has_type_prefix("synthesis-总结") is True

    def test_detects_source_prefix(self):
        assert _has_type_prefix("source-raw-doc") is True

    def test_case_insensitive(self):
        assert _has_type_prefix("Concept-Foo") is True

    def test_no_prefix(self):
        assert _has_type_prefix("穿越小说角色塑造") is False

    def test_no_dash_no_match(self):
        assert _has_type_prefix("concept") is False

    def test_partial_prefix_no_match(self):
        assert _has_type_prefix("conceptual-framework") is False


class TestMeaningfulLength:
    def test_normal_text(self):
        assert _meaningful_length("这是正常的中文内容") == 9

    def test_empty_string(self):
        assert _meaningful_length("") == 0

    def test_only_wikilinks(self):
        assert _meaningful_length("[[link1]] [[link2]]") == 0

    def test_mixed_wikilinks_and_text(self):
        result = _meaningful_length("参见[[链接]]获取更多")
        assert result > 5  # "参见获取更多" = 6

    def test_list_bullets_become_spaces(self):
        result = _meaningful_length("- item1\n- item2")
        # "- " → "  " (2 spaces), so "  item1\n  item2" → strip → "item1\n  item2"
        assert result == 13


class TestCheckPagesNormal:
    def test_all_pages_kept_no_degradation(self):
        pages = [
            _make_page(id="a", title="Page A", body="Some useful content here."),
            _make_page(id="b", title="Page B", body="Another useful page body."),
        ]
        result = check_pages(pages)
        assert len(result.pages) == 2
        assert result.degraded == {}

    def test_quality_gate_result_type(self):
        result = check_pages([])
        assert isinstance(result, QualityGateResult)
        assert isinstance(result.pages, list)
        assert isinstance(result.degraded, dict)


class TestPrefixGhost:
    def test_title_with_concept_prefix_degraded(self):
        pages = [_make_page(id="concept-xxx-abc123", title="concept-穿越小说角色塑造套路")]
        result = check_pages(pages)
        assert len(result.pages) == 1
        assert result.pages[0].grade == "C"
        assert "concept-xxx-abc123" in result.degraded
        assert "prefix_ghost" in result.degraded["concept-xxx-abc123"]

    def test_id_with_entity_prefix_degraded(self):
        pages = [_make_page(id="entity-slug-123", title="Clean Title")]
        result = check_pages(pages)
        assert result.pages[0].grade == "C"
        assert "prefix_ghost" in result.degraded["entity-slug-123"]


class TestEmptyBody:
    def test_empty_body_degraded(self):
        pages = [_make_page(id="empty", title="Empty Page", body="")]
        result = check_pages(pages)
        assert result.pages[0].grade == "C"
        assert "empty_body" in result.degraded["empty"]

    def test_wikilink_only_body_degraded(self):
        pages = [_make_page(id="wl", title="Wikilink Only", body="[[other page]]")]
        result = check_pages(pages)
        assert result.pages[0].grade == "C"
        assert "empty_body" in result.degraded["wl"]

    def test_body_none_skipped(self):
        pages = [_make_page(id="none-body", title="None Body", body=None)]
        result = check_pages(pages)
        assert len(result.pages) == 1
        assert result.degraded == {}

    def test_body_30_chinese_chars_passes(self):
        body = "这是一段包含三十个中文字符的测试内容用于验证质量门控是否正常工作"
        pages = [_make_page(id="ok", title="OK Page", body=body)]
        result = check_pages(pages)
        assert result.degraded == {}
        assert result.pages[0].grade == "B"

    def test_table_only_body_degraded(self):
        body = "| A | B |\n|---|---|"
        pages = [_make_page(id="table", title="Table Only", body=body)]
        result = check_pages(pages)
        assert result.pages[0].grade == "C"
        assert "empty_body" in result.degraded["table"]


class TestIntraBatchDupe:
    def test_identical_bodies_second_removed(self):
        body = "完全相同的内容。"
        pages = [
            _make_page(id="first", title="First", body=body),
            _make_page(id="second", title="Second", body=body),
        ]
        result = check_pages(pages)
        assert len(result.pages) == 1
        assert result.pages[0].id == "first"
        assert "duplicate of first" in result.degraded["second"]

    def test_different_bodies_both_kept(self):
        pages = [
            _make_page(id="a", title="A", body="Content A."),
            _make_page(id="b", title="B", body="Content B."),
        ]
        result = check_pages(pages)
        assert len(result.pages) == 2

    def test_empty_bodies_duplicate_detected(self):
        pages = [
            _make_page(id="e1", title="Empty 1", body=""),
            _make_page(id="e2", title="Empty 2", body=""),
        ]
        result = check_pages(pages)
        assert len(result.pages) == 1


class TestStubExemption:
    def test_stub_short_body_not_degraded(self):
        pages = [_make_page(id="stub-1", title="Stub", body="[[link]]", processing_depth="stub", grade="C")]
        result = check_pages(pages)
        assert result.degraded == {}

    def test_stub_duplicate_not_removed(self):
        body = "stub body"
        pages = [
            _make_page(id="s1", title="Stub 1", body=body, processing_depth="stub"),
            _make_page(id="s2", title="Stub 2", body=body, processing_depth="stub"),
        ]
        result = check_pages(pages)
        assert len(result.pages) == 2

    def test_stub_prefix_ghost_still_degraded(self):
        pages = [_make_page(id="concept-stub-1", title="concept-stub-ghost", processing_depth="stub")]
        result = check_pages(pages)
        assert "prefix_ghost" in result.degraded["concept-stub-1"]


class TestCombined:
    def test_prefix_ghost_and_empty_body_both_reported(self):
        pages = [_make_page(id="concept-bad", title="concept-Bad Page", body="")]
        result = check_pages(pages)
        assert result.pages[0].grade == "C"
        reason = result.degraded["concept-bad"]
        assert "prefix_ghost" in reason
        assert "empty_body" in reason


class TestEmptyInput:
    def test_empty_list(self):
        result = check_pages([])
        assert result.pages == []
        assert result.degraded == {}
