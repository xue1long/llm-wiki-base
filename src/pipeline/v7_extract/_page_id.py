"""Stable page ID generation for V7 control plane (H2 加固).

Cross-OS consistency: convert '\\' to '/' so Windows and POSIX paths
produce the same ID for the same logical source.

The script owns page IDs end-to-end: the LLM never invents them. Stage 5
maps LLM-supplied ``item_index`` integers back to canonical item IDs
(``Topic.item_ids[index]``) so the LLM can't smuggle in a fake reference.
"""
from __future__ import annotations

import hashlib
import re

_SLUG_RE = re.compile(r"[^\w-]+", re.UNICODE)
_MAX_SLUG_LEN = 32


def _slugify(title: str) -> str:
    """Lowercase title, replace non-word chars with '-', trim, cap at 32 chars."""
    s = _SLUG_RE.sub("-", title.lower()).strip("-")
    return s[:_MAX_SLUG_LEN] or "untitled"


def _stable_page_id(relative: str, topic_title: str) -> str:
    """Stable page ID from source relative path + topic title.

    Uses md5(relative)[:8] + slug(topic_title)[:32] joined by '-'.
    """
    rel = relative.replace("\\", "/")
    digest = hashlib.md5(rel.encode("utf-8")).hexdigest()[:8]
    slug = _slugify(topic_title)
    return f"{digest}-{slug}"


def validate_page_id(page_id: str) -> None:
    """Raise ValueError if page_id contains path separators or '..'."""
    if not page_id:
        raise ValueError("page id must not be empty")
    if any(char in page_id for char in "/\\") or ".." in page_id:
        raise ValueError(f"page id escapes concept directory: {page_id!r}")
