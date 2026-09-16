"""Stable page ID generation for V7 control plane (H2 加固).

Cross-OS consistency: convert '\\' to '/' so Windows and POSIX paths
produce the same ID for the same logical source.

The script owns page IDs end-to-end: the LLM never invents them. Stage 5
maps LLM-supplied ``item_index`` integers back to canonical item IDs
(``Topic.item_ids[index]``) so the LLM can't smuggle in a fake reference.

Task 12 (plan 2026-09-17): the second argument is now the script-
generated ``Topic.id`` (via ``derive_topic_id``), NOT the LLM-supplied
title. Both inputs are script-owned and stable across re-runs.
"""
from __future__ import annotations

import hashlib
import re

_SLUG_RE = re.compile(r"[^\w-]+", re.UNICODE)
_MAX_SLUG_LEN = 32


def _slugify(s: str) -> str:
    """Lowercase, replace non-word chars with '-', trim, cap at 32 chars.

    Accepts any string (historically a topic title; now a topic_id or
    display string — the rule is the same either way).
    """
    lowered = _SLUG_RE.sub("-", s.lower()).strip("-")
    return lowered[:_MAX_SLUG_LEN] or "untitled"


def _stable_page_id(relative: str, topic_id: str) -> str:
    """Stable page ID from source relative path + script-generated topic_id.

    Both inputs are script-owned (no LLM dependence — see
    ``derive_topic_id`` and the Canonical Identity Contract §2). The page
    ID is preserved across LLM renames because the topic_id is derived
    from membership, not from the LLM label.
    """
    rel = relative.replace("\\", "/")
    digest = hashlib.md5(rel.encode("utf-8")).hexdigest()[:8]
    slug = _slugify(topic_id)
    return f"{digest}-{slug}"


def validate_page_id(page_id: str) -> None:
    """Raise ValueError if page_id contains path separators or '..'."""
    if not page_id:
        raise ValueError("page id must not be empty")
    if any(char in page_id for char in "/\\") or ".." in page_id:
        raise ValueError(f"page id escapes concept directory: {page_id!r}")
