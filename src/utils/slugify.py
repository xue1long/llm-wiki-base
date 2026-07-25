"""Deterministic slug generator.

The LLM produces inconsistent slugs for Chinese terms (e.g. ``chuang-kuo``,
``chuangku``, ``chuang-ku-zhong-wen-wang`` all for 创酷中文网). This
helper gives a single canonical answer so identical terms always map to
the same slug, which keeps the wiki graph consistent.

Algorithm:
- Split the input into runs of Chinese vs. non-Chinese characters.
- For Chinese runs: use ``pypinyin`` to get per-character pinyin (no tone
  marks), joined by single hyphens — e.g. ``创酷中文网`` → ``chuang-ku-zhong-wen-wang``.
- For non-Chinese runs: lowercase ASCII and replace any non-alphanumeric
  run with a single hyphen — e.g. ``Hello World!`` → ``hello-world``.
- Adjacent runs of the same kind are merged (single Chinese run); runs
  of different kinds are joined with a hyphen.

This is character-segmented (no jieba dependency) so ``仙侠小说`` →
``xian-xia-xiao-shuo`` is the deterministic output, not the LLM's
ad-hoc per-token transliteration.
"""
from __future__ import annotations

import re
from typing import Iterable

try:
    from pypinyin import Style, lazy_pinyin
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "pypinyin is required for slugify. Install with: pip install pypinyin"
    ) from exc


_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _split_runs(text: str) -> list[tuple[bool, str]]:
    """Return a list of (is_chinese, segment) tuples covering ``text``.

    Adjacent characters of the same kind merge into a single segment.
    """
    if not text:
        return []
    out: list[tuple[bool, str]] = []
    current: list[str] = []
    current_chinese: bool | None = None
    for ch in text:
        chinese = "一" <= ch <= "鿿"
        if current_chinese is None:
            current_chinese = chinese
            current.append(ch)
        elif chinese == current_chinese:
            current.append(ch)
        else:
            out.append((current_chinese, "".join(current)))
            current_chinese = chinese
            current = [ch]
    if current:
        out.append((current_chinese, "".join(current)))
    return out


def _chinese_to_slug(seg: str) -> str:
    pinyins = lazy_pinyin(seg, style=Style.NORMAL)
    return "-".join(p for p in pinyins if p)


def _ascii_to_slug(seg: str) -> str:
    s = seg.lower()
    s = _NON_ALNUM_RE.sub("-", s)
    return s.strip("-")


def slugify(text: str) -> str:
    """Return a deterministic kebab-case ASCII slug for ``text``.

    Examples::

        >>> slugify("创酷中文网")
        'chuang-ku-zhong-wen-wang'
        >>> slugify("Hello World!")
        'hello-world'
        >>> slugify("混Test合")
        'hun-test-he'
        >>> slugify("")
        ''
    """
    if text is None:
        return ""
    text = text.strip()
    if not text:
        return ""
    pieces: list[str] = []
    for chinese, seg in _split_runs(text):
        if chinese:
            pieces.append(_chinese_to_slug(seg))
        else:
            pieces.append(_ascii_to_slug(seg))
    out = "-".join(p for p in pieces if p)
    # Collapse any accidental double-hyphens (paranoia — _split_runs already
    # merges runs, but consecutive segs might each contribute a leading/trailing
    # hyphen in pathological inputs).
    out = re.sub(r"-+", "-", out).strip("-")
    return out


def ensure_unique_slug(slug: str, existing: Iterable[str]) -> str:
    """Return ``slug`` if not in ``existing``; otherwise append ``-2``, ``-3``…

    Used to dedupe when two distinct source titles slugify to the same
    canonical form.
    """
    taken = set(existing)
    if slug not in taken:
        return slug
    n = 2
    while f"{slug}-{n}" in taken:
        n += 1
    return f"{slug}-{n}"