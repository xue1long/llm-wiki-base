"""Regression tests for `_book_outline_metadata` lookup-key compatibility.

Background (Task 0 of `docs/superpowers/plans/2026-09-10-novel-wiki-fullbook-readability.md`):

- The on-disk filename convention is `{safe(volume_id)}__{safe(chapter_id)}.md`
  (compiler.py:708).
- `_safe()` (compiler.py:475-477) replaces `:` with `_`, so an outline
  `chapter_id="concept-写作技法:5"` is written as
  `concept-写作技法__concept-写作技法_5.md`.
- `book_wiki_manifest` reads the stem back and splits on `"__"`, producing
  the underscore-flavored ID `concept-写作技法_5`.
- But `_book_outline_metadata` keys the lookup dict by the raw outline
  `chapter_id`, which still uses `:`. The two flavours never match, so
  every chapter falls through to the file-prefix fallback in
  `web/js/views/book.js` (4 rough buckets instead of the 53 real volumes).

These tests pin down the contract that `book_wiki_manifest` (via
`_book_outline_metadata`) must answer BOTH spellings of a chapter_id, and
that the rest of the manifest (`volumes[].chapter_count`, chapter-level
`volume_id` / `volume_title`) flows through cleanly.

The fix lives in `src/services/files.py::_book_outline_metadata`. The
tests exercise the lookup logic directly (no full `book_wiki_manifest`
round-trip) so they stay cheap and focused.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.services.files import _book_outline_metadata


def _write_release(tmp_path: Path, outline_payload) -> Path:
    """Drop a minimal release directory holding only outline.json."""
    release = tmp_path / "release"
    release.mkdir()
    (release / "outline.json").write_text(
        json.dumps(outline_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return release


def _sample_outline(*, chapter_ids: tuple[str, ...], volume_id: str = "concept-写作技法") -> list:
    return [{
        "schema_version": "outline-v1",
        "snapshot_id": "abc123",
        "volumes": [{
            "volume_id": volume_id,
            "title": volume_id,
            "chapters": [
                {"chapter_id": cid, "title": cid, "page_ids": [], "overview_refs": []}
                for cid in chapter_ids
            ],
        }],
    }]


# --- 1. native ":" key returns the chapter meta (baseline) ---


def test_outline_metadata_returns_native_colon_key(tmp_path):
    release = _write_release(tmp_path, _sample_outline(chapter_ids=("concept-写作技法:5",)))
    volumes, chapters = _book_outline_metadata(release)
    assert chapters["concept-写作技法:5"]["volume_id"] == "concept-写作技法"
    assert chapters["concept-写作技法:5"]["volume_title"] == "concept-写作技法"
    assert len(volumes) == 1
    assert volumes[0]["id"] == "concept-写作技法"


# --- 2. underscore-flavored key also resolves (the actual bug) ---


def test_outline_metadata_returns_underscore_safe_key(tmp_path):
    """This is the regression. `_safe()` rewrites ':' to '_' on disk;
    `book_wiki_manifest` derives the lookup key from the filename, so
    it asks for `concept-写作技法_5`. The metadata must answer it."""
    release = _write_release(tmp_path, _sample_outline(chapter_ids=("concept-写作技法:5",)))
    volumes, chapters = _book_outline_metadata(release)
    assert "concept-写作技法_5" in chapters
    assert chapters["concept-写作技法_5"]["volume_id"] == "concept-写作技法"


# --- 3. each chapter produces at most one entry even with dual keys ---


def test_outline_metadata_does_not_duplicate_when_keys_differ(tmp_path):
    release = _write_release(tmp_path, _sample_outline(chapter_ids=("concept-写作技法:5",)))
    volumes, chapters = _book_outline_metadata(release)
    # Same chapter, two keys — only one logical entry per chapter.
    assert len(chapters) == 2  # native + underscore
    assert chapters["concept-写作技法:5"] == chapters["concept-写作技法_5"]


# --- 4. alias must not shadow the native entry when the two spellings differ ---


def test_outline_metadata_alias_points_to_same_meta_object(tmp_path):
    release = _write_release(tmp_path, _sample_outline(chapter_ids=("entity-人物:0",)))
    volumes, chapters = _book_outline_metadata(release)
    # Native entry must always be present and authoritative.
    assert "entity-人物:0" in chapters
    native_meta = chapters["entity-人物:0"]
    # The safe alias may or may not exist (it equals the native id when
    # `_safe` happens to be idempotent), but when it does exist it must
    # point to the SAME meta dict, not a re-derived copy with stale data.
    if "entity-人物_0" in chapters:
        assert chapters["entity-人物_0"] is native_meta


# --- 5. list-of-proposals (top-level array) shape is preserved ---


def test_outline_metadata_accepts_list_top_level(tmp_path):
    payload = _sample_outline(chapter_ids=("a:0", "a:1"), volume_id="a") + _sample_outline(
        chapter_ids=("b:0",), volume_id="b"
    )
    release = _write_release(tmp_path, payload)
    volumes, chapters = _book_outline_metadata(release)
    volume_ids = sorted(v["id"] for v in volumes)
    assert volume_ids == ["a", "b"]
    # Both native and safe spellings answer.
    assert chapters["a:0"]["volume_id"] == "a"
    assert chapters["a_0"]["volume_id"] == "a"
    assert chapters["b:0"]["volume_id"] == "b"
    assert chapters["b_0"]["volume_id"] == "b"


# --- 6. dict-at-top-level legacy shape still works ---


def test_outline_metadata_accepts_dict_top_level(tmp_path):
    release = _write_release(tmp_path, _sample_outline(chapter_ids=("legacy:0",))[0])
    volumes, chapters = _book_outline_metadata(release)
    assert chapters["legacy:0"]["volume_id"] == "concept-写作技法"
    assert chapters["legacy_0"]["volume_id"] == "concept-写作技法"


# --- 7. missing or malformed outline.json fails closed ---


def test_outline_metadata_missing_file_returns_empty(tmp_path):
    release = tmp_path / "no-such-release"
    release.mkdir()
    volumes, chapters = _book_outline_metadata(release)
    assert volumes == []
    assert chapters == {}


def test_outline_metadata_malformed_json_returns_empty(tmp_path):
    release = tmp_path / "broken-release"
    release.mkdir()
    (release / "outline.json").write_text("{ this is not json", encoding="utf-8")
    volumes, chapters = _book_outline_metadata(release)
    assert volumes == []
    assert chapters == {}
