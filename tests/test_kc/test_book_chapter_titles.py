"""Tests for `generate_chapter_titles` (Task 3).

Background (Task 3 of
`docs/superpowers/plans/2026-09-10-novel-wiki-fullbook-readability.md`):

- A one-shot LLM call produces a chapter_id -> friendly_title map
  for every chapter in a release (179 chapters in the live release).
- Titles must be <=14 chars, no markdown noise, no collisions inside
  the same volume (resolved via "-2"/"-3"/... suffix).
- When no provider is reachable, the function degrades to per-page
  title heuristics so the pipeline stays testable offline.

These tests exercise the contract directly without a real network call.
The function is async, so they use `asyncio.run`.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.kc.views.book.wiki.polish_llm import (
    ChapterTitleResult,
    _disambiguate,
    _fallback_title,
    _sanitize_title,
    generate_chapter_titles,
)


def _run(coro):
    return asyncio.run(coro)


# ─── Pure-function sanity (sync) ─────────────────────────────────


def test_sanitize_title_strips_markdown_and_caps_length():
    assert _sanitize_title("**踩坑指南#1**") == "踩坑指南1"
    assert _sanitize_title("[主角塑造](主角)") == "主角塑造主角"
    # Cap at 14 chars (CJK = 1 char each).
    long = "这是一个非常非常长的标题超过了十四个字符"
    assert len(_sanitize_title(long)) == 14
    # Non-string / empty inputs collapse to "".
    assert _sanitize_title(None) == ""
    assert _sanitize_title(123) == ""
    assert _sanitize_title("   ") == ""
    # Pure markdown symbols collapse to "".
    assert _sanitize_title("#*_`>") == ""


def test_disambiguate_appends_suffix_to_collisions_within_volume():
    titles = {"a:0": "人物塑造", "a:1": "人物塑造", "a:2": "人物塑造"}
    renames = _disambiguate(titles)
    # a:0 keeps base; a:1 -> "-2"; a:2 must skip "-2" (taken) -> "-3".
    assert sorted(titles.values()) == ["人物塑造", "人物塑造-2", "人物塑造-3"]
    assert renames == 3


def test_disambiguate_does_not_collide_across_volumes():
    titles = {"a:0": "X", "b:0": "X"}
    renames = _disambiguate(titles)
    # Different volumes share no collision check, both keep base title.
    assert titles == {"a:0": "X", "b:0": "X"}
    assert renames == 0


def test_fallback_title_prefers_outline_title():
    assert _fallback_title({"title": "主角塑造", "first_page_title": "X"}) == "主角塑造"
    assert _fallback_title({"title": "", "first_page_title": "配角设计"}) == "配角设计"


# ─── Async behaviour with no provider (offline fallback) ────────


def test_generate_chapter_titles_with_no_provider_uses_fallback():
    chapters = [
        {"chapter_id": "v:0", "title": "人物塑造", "first_page_title": "主角人设"},
        {"chapter_id": "v:1", "title": "情节节奏", "first_page_title": "主线设计"},
    ]
    result = _run(generate_chapter_titles(chapters, None))
    assert isinstance(result, ChapterTitleResult)
    assert result.titles == {"v:0": "人物塑造", "v:1": "情节节奏"}
    # No provider -> every chapter fell back.
    assert result.failed == 2
    assert result.renamed == 0
    assert result.truncated == 0


def test_generate_chapter_titles_strips_markdown_in_fallback():
    chapters = [
        {"chapter_id": "x:0", "title": "[**踩坑**指南#1]", "first_page_title": "入门"},
    ]
    result = _run(generate_chapter_titles(chapters, None))
    assert result.titles["x:0"] == "踩坑指南1"


# ─── Async behaviour with fake provider (online path) ───────────


class _FakeProvider:
    def __init__(self, content: str, *, fail: bool = False):
        self._content = content
        self._fail = fail
        self.calls = 0

    async def complete(self, messages, response_format=None):
        self.calls += 1
        if self._fail:
            raise ConnectionError("offline")
        return SimpleNamespace(content=self._content)


def test_generate_chapter_titles_with_provider_returns_llm_titles():
    provider = _FakeProvider(
        '{"v:0": "主角欲望", "v:1": "反派设计", "v:2": "配角成长"}'
    )
    chapters = [
        {"chapter_id": "v:0", "title": "X", "first_page_title": "X"},
        {"chapter_id": "v:1", "title": "X", "first_page_title": "X"},
        {"chapter_id": "v:2", "title": "X", "first_page_title": "X"},
    ]
    result = _run(generate_chapter_titles(chapters, provider))
    assert result.titles == {"v:0": "主角欲望", "v:1": "反派设计", "v:2": "配角成长"}
    assert result.failed == 0
    assert result.renamed == 0
    assert result.truncated == 0


def test_generate_chapter_titles_truncates_overlong_llm_output():
    provider = _FakeProvider(
        '{"v:0": "这是一个非常非常长的标题超过了十四个字符"}'
    )
    chapters = [{"chapter_id": "v:0", "title": "X", "first_page_title": "X"}]
    result = _run(generate_chapter_titles(chapters, provider))
    assert result.titles["v:0"] == "这是一个非常非常长的标题超过了十四个字符"[:14]
    assert result.truncated == 1
    assert result.failed == 0


def test_generate_chapter_titles_with_broken_provider_falls_back():
    provider = _FakeProvider("", fail=True)
    chapters = [
        {"chapter_id": "v:0", "title": "主角人设", "first_page_title": "X"},
        {"chapter_id": "v:1", "title": "配角设计", "first_page_title": "Y"},
    ]
    result = _run(generate_chapter_titles(chapters, provider))
    # Provider raised -> every chapter fell back to its outline title.
    assert result.titles == {"v:0": "主角人设", "v:1": "配角设计"}
    assert result.failed == 2
    # Retries=1 means up to 2 calls.
    assert provider.calls == 2


def test_generate_chapter_titles_partial_llm_response_mixes_fallback():
    """Provider returns titles for some chapters only. Missing ones
    must fall back rather than disappear from the map."""
    provider = _FakeProvider('{"v:0": "主角设计"}')
    chapters = [
        {"chapter_id": "v:0", "title": "X", "first_page_title": "X"},
        {"chapter_id": "v:1", "title": "配角塑造", "first_page_title": "Y"},
    ]
    result = _run(generate_chapter_titles(chapters, provider))
    assert result.titles["v:0"] == "主角设计"
    assert result.titles["v:1"] == "配角塑造"
    assert result.failed == 1


def test_generate_chapter_titles_collision_across_volumes_not_disambiguated():
    """Two different volumes may legitimately share a title (e.g. each
    has its own 主角塑造 chapter). Disambiguation only fires within a
    volume to keep cross-volume titles independent."""
    provider = _FakeProvider('{"a:0": "主角塑造", "b:0": "主角塑造"}')
    chapters = [
        {"chapter_id": "a:0", "title": "X", "first_page_title": "X"},
        {"chapter_id": "b:0", "title": "X", "first_page_title": "X"},
    ]
    result = _run(generate_chapter_titles(chapters, provider))
    assert result.titles == {"a:0": "主角塑造", "b:0": "主角塑造"}
    assert result.renamed == 0


def test_generate_chapter_titles_malformed_json_response_falls_back():
    """If the provider returns text that isn't JSON, the function must
    not crash and must fall back rather than return partial data."""
    provider = _FakeProvider("not json")
    chapters = [
        {"chapter_id": "v:0", "title": "主角人设", "first_page_title": "X"},
    ]
    result = _run(generate_chapter_titles(chapters, provider))
    assert result.titles["v:0"] == "主角人设"
    assert result.failed == 1
