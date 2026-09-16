"""Tests for the AnalysisView + offset mapping (Task 43)."""
from __future__ import annotations

from src.pipeline.v7_extract.analysis_view import AnalysisView, TextMapping


def test_analysis_view_extracts_text_from_simple_html():
    """<p>hello</p> → rendered_text contains 'hello'."""
    raw = b"<p>hello</p>"
    view = AnalysisView.from_html(raw)
    assert "hello" in view.rendered_text


def test_analysis_view_records_byte_offsets_against_raw_html():
    """At least one TextMapping with raw_byte_start within raw bytes range."""
    raw = b"<p>hello</p>"
    view = AnalysisView.from_html(raw)
    assert len(view.mappings) >= 1
    m = view.mappings[0]
    assert 0 <= m.raw_byte_start < len(raw)
    assert m.raw_byte_start < m.raw_byte_end <= len(raw)


def test_analysis_view_lookup_rendered_offset_returns_correct_index():
    """raw_byte within a mapping returns a non-None rendered offset within range."""
    raw = b"<p>hello</p>"
    view = AnalysisView.from_html(raw)
    m = view.mappings[0]
    mid_raw = (m.raw_byte_start + m.raw_byte_end) // 2
    rendered = view.lookup_rendered_offset(mid_raw)
    assert rendered is not None
    # Returned offset is within the mapping's rendered range.
    assert m.rendered_offset <= rendered < m.rendered_offset + (m.raw_byte_end - m.raw_byte_start) + 1


def test_analysis_view_handles_nested_tags():
    """Nested <div><span>nested</span></div> → rendered contains 'nested'."""
    raw = b"<div><span>nested</span></div>"
    view = AnalysisView.from_html(raw)
    assert "nested" in view.rendered_text


def test_analysis_view_skips_script_and_style():
    """<script>code</script> / <style>css</style> do not enter rendered_text."""
    raw = b"<p>visible</p><script>alert(1)</script><style>body{}</style>"
    view = AnalysisView.from_html(raw)
    assert "visible" in view.rendered_text
    assert "alert" not in view.rendered_text
    assert "body{}" not in view.rendered_text


def test_analysis_view_round_trip_offset_mapping():
    """raw_byte_offset found by lookup_raw_offset(rendered_offset) returns
    a position within the same mapping (round-trip consistent)."""
    raw = b"<p>hello world</p>"
    view = AnalysisView.from_html(raw)
    assert len(view.mappings) >= 1
    m = view.mappings[0]
    mid_rendered = (m.rendered_offset + m.rendered_offset + (m.raw_byte_end - m.raw_byte_start)) // 2
    raw_back = view.lookup_raw_offset(mid_rendered)
    assert raw_back is not None
    # Round-trip: raw_back should be within [m.raw_byte_start, m.raw_byte_end).
    assert m.raw_byte_start <= raw_back < m.raw_byte_end


def test_analysis_view_handles_multiple_block_tags():
    """Two <p> blocks → at least 2 mappings (one per block)."""
    raw = b"<p>first</p><p>second</p>"
    view = AnalysisView.from_html(raw)
    assert len(view.mappings) >= 2
    all_text = "".join(
        view.rendered_text[m.rendered_offset:m.rendered_offset + (m.raw_byte_end - m.raw_byte_start)]
        for m in view.mappings
    )
    assert "first" in all_text
    assert "second" in all_text


def test_analysis_view_empty_input():
    """Empty bytes → empty view, no crash."""
    view = AnalysisView.from_html(b"")
    assert view.rendered_text == ""
    assert view.mappings == []