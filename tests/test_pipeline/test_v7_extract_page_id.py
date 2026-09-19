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

import hashlib
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
# 4. Empty / degenerate input fallbacks
# ---------------------------------------------------------------------------

def test_stable_page_id_empty_topic_still_yields_valid_id():
    """An empty topic_id must not blank out the id. Since the 2026-09-19 D7
    fix the readable slug comes from the *source stem* and the trailing
    segment is the topic hash, so an empty topic_id simply hashes — it no
    longer reaches the "untitled" fallback (that now belongs to a
    degenerate source stem, covered below)."""
    page_id = _stable_page_id("raw/sources/a.md", "")
    validate_page_id(page_id)
    assert page_id.endswith(f"-{hashlib.md5(b'').hexdigest()[:8]}")
    assert page_id != _stable_page_id("raw/sources/a.md", "something-else")


def test_stable_page_id_degenerate_stem_uses_untitled_slug():
    """A pathological source stem (punctuation-only) falls back to
    "untitled" for readability, but uniqueness is unaffected: the source
    digest and the topic hash still distinguish the ids."""
    page_id = _stable_page_id("raw/sources/!!!.md", "t")
    assert page_id.split("-")[1] == "untitled"
    validate_page_id(page_id)
    assert page_id != _stable_page_id("raw/sources/??.md", "t")


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
    # Shape contract: <8 hex>-<stem slug>-<8 hex>. The stem slug comes from
    # _slugify, so it may contain CJK ideographs and '_' (both are \w under
    # re.UNICODE); it is capped at _MAX_SLUG_LEN. Path separators and '..'
    # are covered by validate_page_id above.
    assert re.match(r"^[0-9a-f]{8}-[\w-]{1,32}-[0-9a-f]{8}$", page_id), page_id
    assert len(page_id.split("-")) == 3


# ---------------------------------------------------------------------------
# 5b. D7 regression — page_id must be unique per (source, topic)
#
# Bug: _stable_page_id was "<source md5>-<_slugify(topic_id)[:32]>". Because
# topic_id embeds the whole source path ("<rel>-topic-<16hex>"), the 32-char
# slug budget was consumed by the path prefix and the "-topic-<16hex>"
# discriminator was truncated away entirely. Every topic of a source then
# produced the SAME page_id, so the 2nd..Nth concept page silently
# overwrote the first (observed: log said "generated 3 pages", disk had 1).
# ---------------------------------------------------------------------------


def test_stable_page_id_distinguishes_topics_of_same_source():
    """The D7 regression: two topics of one source must not collide."""
    rel = "raw/sources/视频音频转录教程/音频教程/大纲写作技巧.md"
    t1 = "raw/sources/视频音频转录教程/音频教程/大纲写作技巧.md-topic-1bee59b7e87abd47"
    t2 = "raw/sources/视频音频转录教程/音频教程/大纲写作技巧.md-topic-07bb6f49822a5fb6"

    assert t1 != t2
    assert _stable_page_id(rel, t1) != _stable_page_id(rel, t2)


def test_stable_page_id_distinguishes_long_ascii_paths():
    """Collapse was NOT CJK-specific: any source whose slug prefix fills the
    32-char budget collapsed. Pure-ASCII long paths must be distinguished."""
    for rel in (
        "raw/sources/novel/character-growth.md",
        "raw/sources/retrieval-augmentation-notes.md",
        "raw/sources/2026-09-19-v7-pipeline-fix.md",
    ):
        a = _stable_page_id(rel, f"{rel}-topic-1111111111111111")
        b = _stable_page_id(rel, f"{rel}-topic-2222222222222222")
        assert a != b, rel


def test_stable_page_id_distinguishes_same_named_sources():
    """Two different files both named 大纲写作技巧.md exist in this corpus;
    they are different sources and must not share a page_id."""
    rel_a = "raw/sources/视频音频转录教程/02进阶视频教程/大纲写作技巧.md"
    rel_b = "raw/sources/视频音频转录教程/音频教程/大纲写作技巧.md"

    assert _stable_page_id(rel_a, "t") != _stable_page_id(rel_b, "t")


def test_stable_page_id_is_independent_of_topic_order():
    """Identity must be a pure function of (source, topic) — never of the
    order topics happen to appear in a batch (a positional ``-{n}`` suffix
    would break this and churn ids across re-runs)."""
    rel = "raw/sources/视频音频转录教程/音频教程/大纲写作技巧.md"
    topics = [f"{rel}-topic-{h}" for h in ("aa11", "bb22", "cc33")]

    forward = {t: _stable_page_id(rel, t) for t in topics}
    backward = {t: _stable_page_id(rel, t) for t in reversed(topics)}

    assert forward == backward
    assert len(set(forward.values())) == len(topics)


def test_stable_page_id_normalizes_relative_and_absolute_paths(tmp_path):
    """The same file reached via a relative or an absolute path must hash to
    one page_id — otherwise two entry points create two pages for one source."""
    rel = "raw/sources/a.md"
    (tmp_path / "raw" / "sources").mkdir(parents=True)
    (tmp_path / "raw" / "sources" / "a.md").write_text("x", encoding="utf-8")
    abs_path = str(tmp_path / "raw" / "sources" / "a.md")

    from_rel = _stable_page_id(rel, "t", project_root=tmp_path)
    from_abs = _stable_page_id(abs_path, "t", project_root=tmp_path)
    from_win = _stable_page_id(rel.replace("/", "\\"), "t", project_root=tmp_path)

    assert from_rel == from_abs == from_win


def test_stable_page_id_length_is_bounded():
    """id length must stay bounded no matter how long the source name is —
    the id becomes a filename, and an unbounded slug would blow past the
    filesystem component limit inside AtomicContext (rolling back the whole
    batch). 8 + 1 + 32 + 1 + 8 = 50 is the hard ceiling."""
    rel = "raw/sources/" + ("超长文件名" * 40) + ".md"
    page_id = _stable_page_id(rel, "t")

    assert len(page_id) <= 50, len(page_id)
    validate_page_id(page_id)
    assert len(page_id.split("-")[-1]) == 8


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
