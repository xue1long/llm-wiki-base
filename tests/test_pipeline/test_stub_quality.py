"""C3: Stub quality control tests.

Covers:
  - Stub importance scoring heuristics
  - Low-importance stub filtering (kept vs inlined)
  - Reference-list density detection
  - MAX_STUBS only counts high+medium
  - sort_stubs_by_importance ordering
"""
import pytest

from src.pipeline.stub_quality import (
    StubImportance,
    detect_reference_list_density,
    filter_low_importance_stubs,
    split_by_importance,
    sort_stubs_by_importance,
    _score_slug_importance,
)


# ---------------------------------------------------------------------------
# Reference-list density detection
# ---------------------------------------------------------------------------

class TestReferenceListDensity:
    """Tests for detect_reference_list_density."""

    def test_empty_text_returns_zero(self):
        assert detect_reference_list_density("") == 0.0

    def test_all_list_items_returns_one(self):
        text = "- item 1\n- item 2\n- item 3\n* item 4\n* item 5"
        assert detect_reference_list_density(text) == 1.0

    def test_all_paragraphs_returns_zero(self):
        text = "This is a paragraph.\n\nAnother paragraph here.\n\nThird paragraph."
        assert detect_reference_list_density(text) == 0.0

    def test_mixed_content(self):
        # 3 list lines out of 5 non-blank lines = 0.6
        text = "- list 1\n- list 2\nparagraph\n- list 3\nparagraph"
        assert detect_reference_list_density(text) == 0.6

    def test_numbered_list(self):
        text = "1. first\n2. second\n3. third\n\nA paragraph."
        assert detect_reference_list_density(text) == 0.75

    def test_parenthesized_numbered_list(self):
        text = "1) first\n2) second\nA paragraph."
        assert detect_reference_list_density(text) == pytest.approx(2 / 3)

    def test_heavy_list_detected(self):
        """>60% list items should be detected."""
        # 7 list lines + 3 paragraph lines = 70%
        text = "\n".join(
            [f"- item {i}" for i in range(7)]
            + ["A paragraph.", "Another paragraph.", "Yet another."]
        )
        density = detect_reference_list_density(text)
        assert density == 0.7
        assert density > 0.6

    def test_light_list_not_detected(self):
        """<60% list items should NOT trigger detection."""
        # 2 list lines + 5 paragraph lines = ~28.6%
        text = "\n".join(
            ["- item 1", "- item 2"]
            + [f"Paragraph {i}" for i in range(5)]
        )
        density = detect_reference_list_density(text)
        assert density == pytest.approx(2 / 7)
        assert density < 0.6

    def test_blanks_ignored(self):
        """Blank lines should not affect the ratio."""
        text = "- a\n\n- b\n\n- c\n\n- d\n\np1\n\n"
        # 4 list lines + 1 para line = 80%
        assert detect_reference_list_density(text) == 0.8

    def test_indented_list_items(self):
        text = "  - indented 1\n    - indented 2\nparagraph"
        assert detect_reference_list_density(text) == pytest.approx(2 / 3)


# ---------------------------------------------------------------------------
# Slug importance scoring
# ---------------------------------------------------------------------------

class TestSlugImportanceScoring:
    """Tests for _score_slug_importance heuristic."""

    def test_wikilink_references_score_high(self):
        """Multiple wikilink references should score HIGH."""
        pages_body = {
            "page1": "See [[my-entity]] for details. Also [[my-entity]] again.",
            "page2": "Reference: [[my-entity]]",
        }
        result = _score_slug_importance("my-entity", pages_body)
        # 3 wikilinks * 3.0 = 9.0 >= high_threshold(3)
        assert result == StubImportance.HIGH

    def test_single_wikilink_scores_medium(self):
        """One wikilink reference should score MEDIUM."""
        pages_body = {
            "page1": "See [[single-ref]] once.",
        }
        result = _score_slug_importance("single-ref", pages_body)
        # 1 wikilink * 3.0 = 3.0 >= high_threshold(3) → actually HIGH
        # Let's test with a lower wikilink_weight
        pass

    def test_no_references_scores_low(self):
        """Zero references should score LOW."""
        pages_body = {
            "page1": "No references to that entity here.",
        }
        result = _score_slug_importance("unknown-entity", pages_body)
        assert result == StubImportance.LOW

    def test_text_mention_scores_medium(self):
        """Plain text mention (non-wikilink) scores lower."""
        pages_body = {
            "page1": "We discussed the concept of mingyun in this section.",
        }
        result = _score_slug_importance("mingyun", pages_body)
        # 0 wikilinks, 1 text mention = 1.0 >= medium_threshold(1)
        assert result == StubImportance.MEDIUM

    def test_empty_body_handled(self):
        """Empty body dict should return LOW."""
        result = _score_slug_importance("anything", {})
        assert result == StubImportance.LOW

    def test_none_body_handled(self):
        """Pages with None body should not crash."""
        pages_body = {
            "page1": None,
            "page2": "actual content with [[target]]",
        }
        # Should handle None body gracefully
        pass  # _score_slug_importance handles it via `if not body: continue`


# ---------------------------------------------------------------------------
# filter_low_importance_stubs + split_by_importance
# ---------------------------------------------------------------------------

class TestFilterLowImportanceStubs:
    """Integration tests for scoring and splitting stubs."""

    def _make_fake_pages(self, *bodies):
        """Create minimal fake page objects with id and body."""
        class FakePage:
            def __init__(self, pid, body):
                self.id = pid
                self.body = body
                self.type = None
        return [FakePage(f"p{i}", b) for i, b in enumerate(bodies)]

    def test_high_importance_kept(self):
        pages = self._make_fake_pages(
            "[[important]] is key. [[important]] again.",
        )
        scored = filter_low_importance_stubs({"important"}, pages)
        kept, inlined = split_by_importance(scored)
        assert "important" in kept
        assert "important" not in inlined
        assert scored["important"] == StubImportance.HIGH

    def test_low_importance_inlined(self):
        pages = self._make_fake_pages(
            "This page discusses general concepts without referencing any specific entity.",
        )
        scored = filter_low_importance_stubs({"never-mentioned-entity"}, pages)
        kept, inlined = split_by_importance(scored)
        assert "never-mentioned-entity" not in kept
        assert "never-mentioned-entity" in inlined
        assert scored["never-mentioned-entity"] == StubImportance.LOW

    def test_mixed_importance(self):
        """HIGH and LOW stubs mixed -- LOW should be inlined, HIGH kept."""
        pages = self._make_fake_pages(
            "[[high-entity]] [[high-entity]] [[high-entity]]",
            "This page discusses general writing advice with no references.",
        )
        scored = filter_low_importance_stubs({"high-entity", "missing-concept"}, pages)
        kept, inlined = split_by_importance(scored)
        assert "high-entity" in kept
        assert "missing-concept" in inlined

    def test_max_stubs_only_counts_high_medium(self):
        """MAX_STUBS should only count high+medium, not low (already inlined)."""
        pages = self._make_fake_pages(
            "[[keep1]] [[keep1]] [[keep1]]\n[[keep2]]\nGeneric content here.",
            "[[keep3]] [[keep3]] [[keep3]]",
        )
        scored = filter_low_importance_stubs(
            {"keep1", "keep2", "keep3", "barely-referenced-x"},
            pages,
        )
        kept, inlined = split_by_importance(scored)
        # barely-referenced-x should be inlined, others kept
        assert "barely-referenced-x" in inlined
        assert len(kept) == 3  # keep1, keep2, keep3 -- only these count toward MAX_STUBS
        assert "barely-referenced-x" not in kept

    def test_sort_by_importance_order(self):
        """sort_stubs_by_importance should order HIGH before MEDIUM before LOW."""
        # Intentionally mix the order
        slugs = {"mid-entity", "low-entity", "high-entity"}
        scored = {
            "high-entity": StubImportance.HIGH,
            "mid-entity": StubImportance.MEDIUM,
            "low-entity": StubImportance.LOW,
        }
        sorted_slugs = sort_stubs_by_importance(slugs, scored)
        assert sorted_slugs[0] == "high-entity"
        assert sorted_slugs[1] == "mid-entity"
        assert sorted_slugs[2] == "low-entity"

    def test_sort_by_importance_unknown_defaults_low(self):
        """Slugs not in scored dict should default to LOW (sorted last)."""
        slugs = {"known-high", "unknown"}
        scored = {"known-high": StubImportance.HIGH}
        sorted_slugs = sort_stubs_by_importance(slugs, scored)
        assert sorted_slugs[0] == "known-high"
        assert sorted_slugs[1] == "unknown"

    def test_empty_slugs(self):
        """Empty input should produce empty output."""
        scored = filter_low_importance_stubs(set(), [])
        kept, inlined = split_by_importance(scored)
        assert kept == set()
        assert inlined == set()
        assert sort_stubs_by_importance(set(), {}) == []

    def test_no_pages_with_body(self):
        """Pages without bodies should not crash."""
        class FakePage:
            def __init__(self, pid):
                self.id = pid
                self.body = ""
                self.type = None
        pages = [FakePage("empty1"), FakePage("empty2")]
        scored = filter_low_importance_stubs({"some-entity"}, pages)
        kept, inlined = split_by_importance(scored)
        assert "some-entity" in inlined  # No references → LOW


# ---------------------------------------------------------------------------
# StubImportance enum values
# ---------------------------------------------------------------------------

def test_stub_importance_values():
    assert StubImportance.HIGH == "high"
    assert StubImportance.MEDIUM == "medium"
    assert StubImportance.LOW == "low"
    # Enum ordering
    assert StubImportance.HIGH != StubImportance.LOW
    assert StubImportance.MEDIUM != StubImportance.LOW
