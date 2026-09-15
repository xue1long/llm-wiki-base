"""T1 / H2 加固: Stage 5 / extract_pilot page ID generation is script-owned.

Luna-A (Wave 1) — covers ``src/pipeline/v7_extract/_page_id.py``:

  1. ``_stable_page_id`` is deterministic: same (relative, topic_title) → same ID
  2. Different relative → different ID (collision-resistance across sources)
  3. Cross-OS stability: 'raw\\sources\\a.md' and 'raw/sources/a.md' → same ID
  4. Empty title → "untitled" slug (never blank)
  5. ``validate_page_id`` rejects '/', '\\\\', '..'
  6. ``_slugify`` preserves CJK / unicode word characters

The cross-lane page-ID uniqueness contract (same topic slug in two different
sources → different page_id) is exercised via ``tests/fixtures/v7_control_plane``
in ``test_v7_extract_slot_filler.py`` (cross-document fixture).
"""
from __future__ import annotations

import re

import pytest

from src.pipeline.v7_extract import _page_id
from src.pipeline.v7_extract._page_id import (
    _slugify,
    _stable_page_id,
    validate_page_id,
)


# ---------------------------------------------------------------------------
# 1. Determinism
# ---------------------------------------------------------------------------

def test_stable_page_id_same_inputs_same_id():
    a = _stable_page_id("raw/sources/a.md", "writing-techniques")
    b = _stable_page_id("raw/sources/a.md", "writing-techniques")
    assert a == b


# ---------------------------------------------------------------------------
# 2. Different relative → different ID
# ---------------------------------------------------------------------------

def test_stable_page_id_different_relative_same_topic_different_id():
    a = _stable_page_id("raw/sources/source_a.md", "writing-techniques")
    b = _stable_page_id("raw/sources/source_b.md", "writing-techniques")
    assert a != b
    # Both must still validate (no accidental slashes / dots)
    validate_page_id(a)
    validate_page_id(b)


# ---------------------------------------------------------------------------
# 3. Cross-OS stability
# ---------------------------------------------------------------------------

def test_stable_page_id_windows_and_posix_paths_produce_same_id():
    posix_rel = "raw/sources/a.md"
    windows_rel = "raw\\sources\\a.md"
    assert _stable_page_id(posix_rel, "topic-a") == _stable_page_id(windows_rel, "topic-a")


# ---------------------------------------------------------------------------
# 4. Empty title fallback
# ---------------------------------------------------------------------------

def test_stable_page_id_empty_title_uses_untitled_slug():
    page_id = _stable_page_id("raw/sources/a.md", "")
    # The slug portion must be non-empty after slugify; default is "untitled".
    assert page_id.endswith("-untitled")
    validate_page_id(page_id)


def test_slugify_empty_string_returns_untitled():
    assert _slugify("") == "untitled"
    # Stripped-out punctuation-only input also collapses to "untitled".
    assert _slugify("!!!") == "untitled"


# ---------------------------------------------------------------------------
# 5. validate_page_id
# ---------------------------------------------------------------------------

def test_validate_page_id_rejects_path_separators_and_dotdot():
    for bad in ("foo/bar", "foo\\bar", "abc/..", "..\\abc", "abc..def"):
        with pytest.raises(ValueError):
            validate_page_id(bad)


def test_validate_page_id_rejects_empty():
    with pytest.raises(ValueError):
        validate_page_id("")


def test_validate_page_id_accepts_canonical_shape():
    """A real _stable_page_id output must validate (positive test)."""
    page_id = _stable_page_id("raw/sources/source_a.md", "writing-techniques")
    validate_page_id(page_id)  # must not raise
    # Shape contract: <8 hex>-<slug> with no path separators or '..'
    assert re.match(r"^[0-9a-f]{8}-[a-z0-9-]+$", page_id), page_id


# ---------------------------------------------------------------------------
# 6. _slugify — unicode / CJK preservation
# ---------------------------------------------------------------------------

def test_slugify_preserves_cjk_characters():
    # CJK ideographs are \w under re.UNICODE, so they survive unchanged.
    assert _slugify("写作技法") == "写作技法"


def test_slugify_lowercases_and_replaces_punctuation():
    # Latin: lowercase + non-word chars → '-'
    assert _slugify("Hello, World!") == "hello-world"
    # '_' is a \w character and survives intact (matches topic-clusterer
    # item_id shape, e.g. "writing_techniques").
    assert _slugify("a___b") == "a___b"
    # Leading / trailing punctuation trimmed
    assert _slugify("!!!hi!!!") == "hi"


def test_slugify_caps_at_32_chars():
    long = "a" * 64
    out = _slugify(long)
    assert len(out) == 32
    # 32-char cap is a hard ceiling; maxed-out ASCII input never hits the
    # "untitled" fallback (only fully-empty input does).
    assert out != "untitled"


def test_module_exposes_expected_public_api():
    """Surface check: downstream code (slot_filler / extract_pilot) reads
    these names from the module."""
    assert hasattr(_page_id, "_stable_page_id")
    assert hasattr(_page_id, "validate_page_id")
    # _slugify is intentionally _-prefixed (internal) but is part of the
    # cross-lane contract — slot_filler relies on the same slug rule.
    assert hasattr(_page_id, "_slugify")
