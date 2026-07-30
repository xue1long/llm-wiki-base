"""Deterministic slug generator (CJK-first, 2026-07-26 cut-over).

For the CJK cut-over, the slug generator preserves non-ASCII characters
verbatim (after NFC normalization) rather than transliterating to
pinyin. The pypinyin dependency has been removed: it was a source of
LLM-vs-pipeline slug drift (the transliteration choice was
non-deterministic across calls and dependent on dictionary versions).
CJK-in-slug is now legal per ``docs/guides/wiki-spec.md``.

Algorithm:
- NFC-normalize input (so macOS NFD filenames → canonical).
- Classify each char into one of three kinds: ``cjk`` (basic block
  U+4E00–U+9FFF), ``ascii`` (0x00–0x7F), ``other`` (Latin extended,
  diacritics).
- ASCII runs: lowercase + collapse non-alphanumeric to hyphens.
- CJK / other runs: preserve verbatim.
- Boundary between two ASCII segments: hyphens (but ``_split_runs``
  merges adjacent same-kind runs first).
- Boundary between an ASCII and a CJK segment: hyphen (``混Test合``
  becomes ``混-test-合``).
- Boundary between an ASCII and an ``other`` segment: NO hyphen
  (``café`` stays ``café``, not ``caf-é``); this fusing handles
  single Latin-extended letters that act like diacritics on the
  surrounding ASCII word.

Examples::

    >>> slugify("网络文学")
    '网络文学'
    >>> slugify("Hello World!")
    'hello-world'
    >>> slugify("混Test合")
    '混-test-合'
    >>> slugify("café")
    'café'
    >>> slugify("")
    ''
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable


_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_CJK_BASIC_BLOCK = ("一", "鿿")


def _classify(ch: str) -> str:
    """Return one of 'cjk' | 'ascii' | 'other' for a single char.

    - cjk: U+4E00–U+9FFF (basic CJK / Han ideographs).
    - ascii: 0x00–0x7F printable (the LLM usually keeps these as
      English terms or Latin titles).
    - other: U+0080+ but not CJK — covers Latin extended (é, ñ)
      and diacritics; these typically fuse into the surrounding
      ASCII word without a separator.
    """
    if _CJK_BASIC_BLOCK[0] <= ch <= _CJK_BASIC_BLOCK[1]:
        return "cjk"
    if ord(ch) < 0x80:
        return "ascii"
    return "other"


def _split_runs(text: str) -> list[tuple[str, str]]:
    """Return a list of (kind, segment) tuples covering ``text``.

    Adjacent characters of the same kind merge into a single segment.
    """
    if not text:
        return []
    out: list[tuple[str, str]] = []
    current: list[str] = []
    current_kind: str | None = None
    for ch in text:
        kind = _classify(ch)
        if current_kind is None:
            current_kind = kind
            current.append(ch)
        elif kind == current_kind:
            current.append(ch)
        else:
            out.append((current_kind, "".join(current)))
            current_kind = kind
            current = [ch]
    if current:
        out.append((current_kind, "".join(current)))
    return out


def _preserve(seg: str) -> str:
    """Non-ASCII segment: NFC-normalize and keep verbatim."""
    return unicodedata.normalize("NFC", seg)


def _ascii_to_slug(seg: str) -> str:
    """ASCII segment: lowercase + collapse non-alphanumeric to hyphen."""
    s = seg.lower()
    s = _NON_ALNUM_RE.sub("-", s)
    return s.strip("-")


def slugify(text) -> str:
    """Return a deterministic CJK-friendly slug for ``text``.

    Rules:
    - NFC-normalize the input first (handles macOS HFS+ NFD filenames).
    - Strip leading/trailing whitespace.
    - ASCII runs: lowercase + non-alphanumeric → single hyphen.
    - CJK / other runs: preserve verbatim.
    - ``cjk ↔ ascii`` boundaries get a hyphen separator.
    - ``ascii ↔ other`` boundaries fuse without a separator (so
      ``café`` stays ``café``).
    - Empty result returned for ``None``/empty/whitespace-only input.
    """
    if text is None:
        return ""
    text = unicodedata.normalize("NFC", text).strip()
    if not text:
        return ""
    runs = _split_runs(text)
    out = ""
    for i, (kind, seg) in enumerate(runs):
        if i > 0:
            prev_kind = runs[i - 1][0]
            # CJK is always a separate word, so hyphenate any boundary
            # touching CJK.  ASCII <-> OTHER (diacritic) fuses with
            # no separator.
            insert_sep = prev_kind == "cjk" or kind == "cjk"
            if insert_sep:
                out += "-"
        if kind == "ascii":
            out += _ascii_to_slug(seg)
        else:
            out += _preserve(seg)
    return out.strip("-")


def ensure_unique_slug(slug: str, existing: Iterable[str]) -> str:
    """Return ``slug`` if not in ``existing``; otherwise append ``-2``, ``-3``…

    Used to dedupe when two distinct source titles slugify to the same
    canonical form. After the CJK cut-over this matters more often:
    two source titles can legitimately collapse to the same CJK slug,
    in which case we append ``-2``/``-3``.
    """
    taken = set(existing)
    if slug not in taken:
        return slug
    n = 2
    while f"{slug}-{n}" in taken:
        n += 1
    return f"{slug}-{n}"
