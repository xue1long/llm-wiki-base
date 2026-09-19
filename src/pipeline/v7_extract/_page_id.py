"""Stable page ID generation for V7 control plane (H2 加固).

Cross-OS consistency: convert '\\' to '/' so Windows and POSIX paths
produce the same ID for the same logical source.

The script owns page IDs end-to-end: the LLM never invents them. Stage 5
maps LLM-supplied ``item_index`` integers back to canonical item IDs
(``Topic.item_ids[index]``) so the LLM can't smuggle in a fake reference.

Task 12 (plan 2026-09-17): the second argument is now the script-
generated ``Topic.id`` (via ``derive_topic_id``), NOT the LLM-supplied
title. Both inputs are script-owned and stable across re-runs.

Format (2026-09-19, D7 fix): ``<source md5[:8]>-<stem slug[:32]>-<topic md5[:8]>``.

The old format was ``<source md5[:8]>-<_slugify(topic_id)[:32]>``. Because
``topic_id`` embeds the *entire* source path (``<source_id>-topic-<16hex>``),
``_slugify`` spent its whole 32-char budget on the path prefix and truncated
the ``-topic-<16hex>`` discriminator away. Every topic of a source therefore
produced the **same** page_id, and the 2nd..Nth concept page silently
overwrote the first. Observed live: ``wiki/log.md`` recorded
"generated 3 pages" while only one concept file reached disk, and the source
stub carried two identical ``references`` edges.

The discriminator now sits outside the truncation budget, so uniqueness no
longer depends on how long the source path happens to be (this was never
CJK-specific — any source whose slug prefix reached 32 chars collapsed).
"""
from __future__ import annotations

import hashlib
import posixpath
import re
import unicodedata
from pathlib import PurePosixPath

_SLUG_RE = re.compile(r"[^\w-]+", re.UNICODE)
_MAX_SLUG_LEN = 32

# <8 hex>-<up to 32 slug>-<8 hex>
_MAX_PAGE_ID_LEN = 8 + 1 + _MAX_SLUG_LEN + 1 + 8


def _slugify(s: str) -> str:
    """Lowercase, replace non-word chars with '-', trim, cap at 32 chars.

    Accepts any string (historically a topic title; now a topic_id or
    display string — the rule is the same either way).
    """
    lowered = _SLUG_RE.sub("-", s.lower()).strip("-")
    return lowered[:_MAX_SLUG_LEN] or "untitled"


def _canonical_rel(relative: str, project_root: object | None = None) -> str:
    """Normalize a source path so one file yields one page_id.

    Without ``project_root`` this is lexical only: backslashes → '/', ``.``/
    ``..``/duplicate separators collapsed, NFC-normalized. With a root it
    delegates to ``canonical_raw_key``, which additionally makes an absolute
    path and its project-relative spelling hash identically — entry points
    that pass absolute paths (the HTTP route) and ones that pass relative
    paths must not create two pages for one source.

    Case is intentionally NOT folded: raw paths in this repo are
    manifest-generated with consistent case (same policy as
    ``canonical_raw_key``).
    """
    if project_root is not None:
        try:
            from src.utils.path import canonical_raw_key

            return canonical_raw_key(relative, project_root)
        except ValueError:
            # Path escapes the project root; fall through to lexical form.
            pass
    rel = str(relative).replace("\\", "/")
    if not rel:
        return rel
    return unicodedata.normalize("NFC", posixpath.normpath(rel))


def _stable_page_id(
    relative: str,
    topic_id: str,
    *,
    project_root: object | None = None,
) -> str:
    """Stable page ID from source relative path + script-generated topic_id.

    Both inputs are script-owned (no LLM dependence — see
    ``derive_topic_id`` and the Canonical Identity Contract §2). The page
    ID is preserved across LLM renames because the topic_id is derived
    from membership, not from the LLM label.

    Uniqueness is carried by the trailing ``md5(topic_id)[:8]``, which sits
    outside the slug's truncation budget; the stem slug is present only for
    human readability. Collision probability is ~2**-32 per (source, topic)
    pair — negligible at this corpus scale but not zero, so the bridge also
    enforces within-run uniqueness on the assembled page ids.
    """
    rel = _canonical_rel(relative, project_root)
    digest = hashlib.md5(rel.encode("utf-8")).hexdigest()[:8]
    stem_slug = _slugify(PurePosixPath(rel).stem)[:_MAX_SLUG_LEN]
    topic_hash = hashlib.md5(topic_id.encode("utf-8")).hexdigest()[:8]
    return f"{digest}-{stem_slug}-{topic_hash}"


def validate_page_id(page_id: str) -> None:
    """Raise ValueError if page_id contains path separators or '..'."""
    if not page_id:
        raise ValueError("page id must not be empty")
    if any(char in page_id for char in "/\\") or ".." in page_id:
        raise ValueError(f"page id escapes concept directory: {page_id!r}")
