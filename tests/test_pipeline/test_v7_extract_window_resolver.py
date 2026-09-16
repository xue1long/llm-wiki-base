"""Tests for the bounded LLM window resolver (Task 42)."""
from __future__ import annotations

from typing import Any

import pytest

from src.pipeline.v7_extract.llm_client import FakeLLMClient
from src.pipeline.v7_extract.structural_scanner import (
    StructuralBlock,
    StructuralBlockKind,
    scan_markdown,
)
from src.pipeline.v7_extract.window_resolver import (
    MAX_WINDOW_CHARS,
    ResolvedItem,
    ResolverVerdict,
    Window,
    call_window_resolver,
    resolve_windows,
)


def _make_block(text: str, start: int, end: int, kind: StructuralBlockKind = StructuralBlockKind.PARAGRAPH) -> StructuralBlock:
    return StructuralBlock(
        kind=kind, start_byte=start, end_byte=end, level=0, text=text,
    )


def test_resolve_windows_groups_blocks_under_max_chars():
    """Several small blocks are coalesced into one window if they fit."""
    src = b"a" * 100 + b"\n\n" + b"b" * 100 + b"\n\n" + b"c" * 100
    # offsets: block a [0, 100], block b [102, 202], block c [204, 304]
    blocks = [
        _make_block("a" * 100, 0, 100),
        _make_block("b" * 100, 102, 202),
        _make_block("c" * 100, 204, 304),
    ]
    windows = resolve_windows(blocks, source_bytes=src, max_window_chars=MAX_WINDOW_CHARS)
    assert len(windows) == 1
    assert windows[0].block_range == (0, 2)
    assert windows[0].char_count <= MAX_WINDOW_CHARS


def test_resolve_windows_splits_oversized_block():
    """Single block > max_window_chars is split into multiple windows."""
    text = "x" * (MAX_WINDOW_CHARS * 2 + 100)
    encoded = text.encode("utf-8")
    block = _make_block(text, 0, len(encoded))
    windows = resolve_windows([block], source_bytes=encoded, max_window_chars=MAX_WINDOW_CHARS)
    assert len(windows) >= 2
    for w in windows:
        assert w.char_count <= MAX_WINDOW_CHARS


def test_resolve_windows_preserves_byte_ranges():
    """Window [start_byte, end_byte] matches its blocks' union."""
    # Real bytes: "alpha"=5, "\n\n"=2, "beta"=4, "\n\n"=2, "gamma"=5 = 18.
    src = b"alpha\n\nbeta\n\ngamma"
    blocks = [
        _make_block("alpha", 0, 5),
        _make_block("beta", 7, 11),
        _make_block("gamma", 13, 18),
    ]
    windows = resolve_windows(blocks, source_bytes=src, max_window_chars=MAX_WINDOW_CHARS)
    assert len(windows) == 1
    w = windows[0]
    assert w.start_byte == 0
    assert w.end_byte == 18
    # Text is the joined block texts with newline separators.
    assert w.text == "alpha\nbeta\ngamma"


def test_resolver_verdict_enum_has_five_values():
    """KEEP / SPLIT / MERGE / NOISE / UNRESOLVED."""
    expected = {"keep", "split", "merge", "noise", "unresolved"}
    actual = {v.value for v in ResolverVerdict}
    assert actual == expected


@pytest.mark.asyncio
async def test_call_window_resolver_invokes_llm_per_window():
    """One LLM call per window. Each returns the configured verdict."""
    src = b"alpha\n\nbeta\n\ngamma"
    blocks = [
        _make_block("alpha", 0, 5),
        _make_block("beta", 7, 11),
        _make_block("gamma", 13, 18),
    ]
    windows = resolve_windows(blocks, source_bytes=src, max_window_chars=MAX_WINDOW_CHARS)

    fake = FakeLLMClient()
    fake.script("window_resolver", '{"verdict": "keep", "confidence": 0.8, "split_points": []}')

    out = await call_window_resolver(windows, llm=fake, project_root=None)
    assert len(out) == len(windows)
    for item in out:
        assert item.verdict is ResolverVerdict.KEEP
        assert item.confidence == 0.8
    # LLM was called once per window.
    assert len(fake.calls) == len(windows)


@pytest.mark.asyncio
async def test_call_window_resolver_technical_failure_marks_unresolved():
    """LLM raises → window marked UNRESOLVED (fail-closed)."""
    from src.pipeline.v7_extract.window_resolver import (
        _resolve_template,
        resolve_windows,
    )

    src = b"alpha"
    blocks = [_make_block("alpha", 0, 5)]
    windows = resolve_windows(blocks, source_bytes=src, max_window_chars=5)

    class FailingLLM:
        async def complete(self, *, prompt_kind, user_prompt, system_prompt,
                            max_tokens, temperature):
            raise RuntimeError("provider timeout")

    out = await call_window_resolver(windows, llm=FailingLLM(), project_root=None)
    assert len(out) == 1
    assert out[0].verdict is ResolverVerdict.UNRESOLVED


@pytest.mark.asyncio
async def test_call_window_resolver_prompt_resolution_failure_marks_all_unresolved():
    """Prompt template missing → all windows UNRESOLVED without raising.

    Use a tiny max_window_chars to force each block into its own window.
    """
    from src.pipeline.v7_extract.window_resolver import resolve_windows

    src = b"alpha\n\nbeta"
    blocks = [
        _make_block("alpha", 0, 5),
        _make_block("beta", 7, 11),
    ]
    windows = resolve_windows(blocks, source_bytes=src, max_window_chars=5)

    fake = FakeLLMClient()
    out = await call_window_resolver(windows, llm=fake, project_root="/nonexistent/path")
    assert len(out) == 2
    for item in out:
        assert item.verdict is ResolverVerdict.UNRESOLVED


def test_resolve_windows_empty_input():
    """Empty blocks list → empty windows list."""
    assert resolve_windows([], source_bytes=b"", max_window_chars=MAX_WINDOW_CHARS) == []


def test_window_id_is_deterministic_hash():
    """Same block_range → same window_id."""
    blocks = [_make_block("alpha", 0, 5)]
    w1 = resolve_windows(blocks, source_bytes=b"alpha", max_window_chars=MAX_WINDOW_CHARS)[0]
    w2 = resolve_windows(blocks, source_bytes=b"alpha", max_window_chars=MAX_WINDOW_CHARS)[0]
    assert w1.window_id == w2.window_id
    assert w1.window_id.startswith("win-")


def test_resolve_windows_integration_with_scan_markdown():
    """End-to-end: scan_markdown(real md) → resolve_windows → no window > max_chars."""
    md = (
        "# Heading 1\n\n"
        "First paragraph with some content here.\n\n"
        "## Heading 2\n\n"
        "- list item one\n"
        "- list item two\n"
        "- list item three\n\n"
        "Final paragraph.\n"
    )
    blocks = scan_markdown(md)
    src_bytes = md.encode("utf-8")
    windows = resolve_windows(blocks, source_bytes=src_bytes, max_window_chars=MAX_WINDOW_CHARS)
    # No window exceeds the cap.
    for w in windows:
        assert w.char_count <= MAX_WINDOW_CHARS
    # Each window is non-empty.
    assert all(w.text for w in windows)
    # Windows cover the entire source.
    assert windows[0].start_byte == 0
    assert windows[-1].end_byte == len(src_bytes)