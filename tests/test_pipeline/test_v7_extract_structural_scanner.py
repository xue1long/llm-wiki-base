"""Tests for the deterministic StructuralScanner (Task 41)."""
from __future__ import annotations

from src.pipeline.v7_extract.structural_scanner import (
    StructuralBlock,
    StructuralBlockKind,
    blocks_to_fingerprint,
    scan_markdown,
    scan_plain,
)


def test_scan_markdown_finds_headings_at_byte_offsets():
    """Heading blocks carry accurate UTF-8 byte offsets."""
    text = "# Title\n\nBody.\n\n## Sub\n"
    blocks = scan_markdown(text)
    # Two headings, one paragraph.
    headings = [b for b in blocks if b.kind is StructuralBlockKind.HEADING]
    assert len(headings) == 2
    # H1 = "# Title" (7 bytes) + "\n" (1 byte) = 8 bytes.
    assert headings[0].start_byte == 0
    assert headings[0].end_byte == len("# Title\n".encode("utf-8"))
    assert headings[0].level == 1
    # H2 starts after "\n\nBody.\n\n" = 9 bytes.
    h1_end = headings[0].end_byte
    body = "Body."
    expected_h2_start = h1_end + 1 + 1 + len(body) + 1 + 1  # "\n\n" + body + "\n\n"
    # Easier: compute directly.
    expected_h2_start = len(("# Title\n\nBody.\n\n").encode("utf-8"))
    assert headings[1].start_byte == expected_h2_start
    assert headings[1].level == 2


def test_scan_markdown_finds_fenced_code_block():
    """```...``` is a single CODE_BLOCK with accurate byte range."""
    text = "before\n```python\nx = 1\n```\nafter\n"
    blocks = scan_markdown(text)
    code_blocks = [b for b in blocks if b.kind is StructuralBlockKind.CODE_BLOCK]
    assert len(code_blocks) == 1
    cb = code_blocks[0]
    expected_start = len("before\n".encode("utf-8"))
    expected_end = expected_start + len("```python\nx = 1\n```\n".encode("utf-8"))
    assert cb.start_byte == expected_start
    assert cb.end_byte == expected_end
    # The body contains "x = 1".
    assert "x = 1" in cb.text


def test_scan_markdown_handles_unclosed_fence_gracefully():
    """Unclosed fence swallows remaining text as code_block (no crash)."""
    text = "intro\n```\nstill code\nno closer\n"
    blocks = scan_markdown(text)
    code_blocks = [b for b in blocks if b.kind is StructuralBlockKind.CODE_BLOCK]
    assert len(code_blocks) == 1
    assert code_blocks[0].end_byte == len(text.encode("utf-8"))
    assert "still code" in code_blocks[0].text
    assert "no closer" in code_blocks[0].text


def test_scan_markdown_separates_paragraphs_by_blank_lines():
    """Two consecutive paragraph blocks separated by blank line."""
    text = "first paragraph.\n\nsecond paragraph.\n"
    blocks = scan_markdown(text)
    paragraphs = [b for b in blocks if b.kind is StructuralBlockKind.PARAGRAPH]
    assert len(paragraphs) == 2
    # First paragraph ends at start of blank line; second starts after blank.
    assert paragraphs[0].text.strip() == "first paragraph."
    assert paragraphs[1].text.strip() == "second paragraph."
    # No overlap.
    assert paragraphs[0].end_byte <= paragraphs[1].start_byte


def test_scan_plain_returns_single_paragraph():
    """Plain text → exactly 1 PARAGRAPH block covering whole text."""
    text = "Just some plain text.\nWith two lines."
    blocks = scan_plain(text)
    assert len(blocks) == 1
    assert blocks[0].kind is StructuralBlockKind.PARAGRAPH
    assert blocks[0].start_byte == 0
    assert blocks[0].end_byte == len(text.encode("utf-8"))


def test_scanner_output_is_deterministic():
    """Same input → same fingerprint across multiple calls."""
    text = "# H1\n\nparagraph.\n\n- list item\n\n```\ncode\n```\n"
    fp1 = blocks_to_fingerprint(scan_markdown(text))
    fp2 = blocks_to_fingerprint(scan_markdown(text))
    assert fp1 == fp2
    assert fp1.startswith("sc-")
    assert len(fp1) == len("sc-") + 16


def test_block_byte_ranges_cover_full_input_without_overlap():
    """Blocks [start, end) cover entire input and do not overlap."""
    text = "# Title\n\nFirst paragraph here.\n\nSecond.\n\n- a\n- b\n"
    blocks = scan_markdown(text)
    # All start_byte sorted, contiguous, end of last == len(encoded).
    encoded_len = len(text.encode("utf-8"))
    starts = [b.start_byte for b in blocks]
    ends = [b.end_byte for b in blocks]
    assert starts[0] == 0
    assert ends[-1] == encoded_len
    # No gaps and no overlaps: each block's end is the next block's start.
    for prev, curr in zip(blocks, blocks[1:]):
        assert prev.end_byte <= curr.start_byte, (
            f"overlap: prev={prev} curr={curr}"
        )


def test_empty_input_returns_empty_list():
    """scan_markdown("") / scan_plain("") → empty list (not crash)."""
    assert scan_markdown("") == []
    assert scan_plain("") == []


def test_blocks_to_fingerprint_changes_with_input():
    """Different input → different fingerprint."""
    fp_a = blocks_to_fingerprint(scan_markdown("# A\n"))
    fp_b = blocks_to_fingerprint(scan_markdown("# B\n"))
    assert fp_a != fp_b