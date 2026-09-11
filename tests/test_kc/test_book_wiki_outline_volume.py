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

# --- Task 1 review-only additions: behaviour that the fix preserves ---


def _outline_with_empty_volume(tmp_path):
    release = tmp_path / "release"
    release.mkdir()
    payload = [{
        "schema_version": "outline-v1",
        "snapshot_id": "x",
        "volumes": [
            {"volume_id": "v-empty", "title": "v-empty", "chapters": []},
            {"volume_id": "v-full", "title": "v-full", "chapters": [
                {"chapter_id": "v-full:0", "title": "v-full:0",
                 "page_ids": [], "overview_refs": []},
            ]},
        ],
    }]
    (release / "outline.json").write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return release


def _outline_large(tmp_path, n_volumes, n_chapters_per_volume):
    release = tmp_path / "release"
    release.mkdir()
    volumes = []
    for vi in range(n_volumes):
        chapters = [
            {"chapter_id": f"v{vi}:{ci}", "title": f"v{vi}:{ci}",
             "page_ids": [], "overview_refs": []}
            for ci in range(n_chapters_per_volume)
        ]
        volumes.append({"volume_id": f"v{vi}", "title": f"v{vi}", "chapters": chapters})
    payload = [{"schema_version": "outline-v1", "snapshot_id": "x", "volumes": volumes}]
    (release / "outline.json").write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return release


# --- 9. empty chapters list still surfaces the volume (chapter_count = 0) ---


def test_outline_metadata_empty_chapter_list_keeps_volume(tmp_path):
    release = _outline_with_empty_volume(tmp_path)
    volumes, chapters = _book_outline_metadata(release)
    ids = sorted(v["id"] for v in volumes)
    assert ids == ["v-empty", "v-full"]
    assert "v-empty:0" not in chapters
    assert "v-full:0" in chapters


# --- 10. repeated calls return identical, side-effect-free results ---


def test_outline_metadata_is_idempotent_across_calls(tmp_path):
    release = _write_release(
        tmp_path, _sample_outline(chapter_ids=("a:0", "a:1"), volume_id="a")
    )
    first_volumes, first_chapters = _book_outline_metadata(release)
    second_volumes, second_chapters = _book_outline_metadata(release)
    assert first_volumes == second_volumes
    assert first_chapters == second_chapters
    # Alias keys must still resolve after the second call.
    assert second_chapters["a_0"]["volume_id"] == "a"
    assert second_chapters["a_1"]["volume_id"] == "a"


# --- 11. scale matches the real release shape (179 chapters) ---


def test_outline_metadata_scales_to_real_release_shape(tmp_path):
    # 9 volumes x ~20 chapters ~= 180, within 1 of the 179-chapter live release.
    release = _outline_large(tmp_path, n_volumes=9, n_chapters_per_volume=20)
    volumes, chapters = _book_outline_metadata(release)
    assert len(volumes) == 9
    # 180 chapters x 2 key spellings (native + alias) = 360 dict entries.
    assert len(chapters) == 360
    # Distinct chapter ids (native flavor, containing ":") is 180.
    distinct_chapters = {k for k in chapters if ":" in k}
    assert len(distinct_chapters) == 180
    for vid in range(9):
        for ci in range(20):
            assert chapters[f"v{vid}:{ci}"]["volume_id"] == f"v{vid}"
            assert chapters[f"v{vid}_{ci}"]["volume_id"] == f"v{vid}"


# --- 12. integration pin: the alias resolves the lookup that
#         `book_wiki_manifest` performs (src/services/files.py:299-300) ---


def test_book_wiki_manifest_lookup_finds_aliased_chapter_id(tmp_path):
    """`book_wiki_manifest` derives the lookup key by splitting the
    filename stem on `"__"` and taking the right-hand side. Without
    the dual-key alias in `_book_outline_metadata`, that key (the
    underscore flavor) misses every chapter in outline.json.

    This integration pin reproduces that exact lookup against the
    minimal fixture, so any future regression that breaks the
    alias shows up here without needing a full release build.
    """
    # Use a Latin-only volume/chapter so the literal fits in the source
    # file without requiring an escape sequence; the alias mechanism is
    # triggered by any `:` in the chapter_id, not by CJK specifically.
    release = _write_release(
        tmp_path,
        _sample_outline(chapter_ids=("concept-tech:5",), volume_id="concept-tech"),
    )
    _, outline_chapters = _book_outline_metadata(release)

    filename_stem = "concept-tech__concept-tech_5"
    outline_id = filename_stem.split("__", 1)[-1]
    meta = outline_chapters.get(outline_id, outline_chapters.get(filename_stem, {}))
    assert meta.get("volume_id") == "concept-tech"
    assert meta.get("volume_title") == "concept-tech"
