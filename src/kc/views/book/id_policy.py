"""Book view id generation policy (B-T1, spec §12.5).

Each Book / Chapter / KnowledgeBlock / OutlineProposal identifier has the form
``<prefix>_<uuid8>_<slug>`` where:

* ``prefix`` is one of: ``book``, ``ch``, ``kb``, ``op``.
* ``uuid8`` is the first 8 hex chars of a fresh ``uuid4()`` (random per call).
* ``slug`` is a normalized human-readable suffix (lowercase, [a-z0-9-],
  whitespace collapsed to ``-``, max 40 chars, fallback ``"untitled"`` when
  empty after cleanup).

This module is a policy stub: it only emits ids. It does NOT persist or look
anything up. Persistence and collision handling land in later B-T2+ tasks.
"""
from __future__ import annotations

import re
import uuid
from hashlib import sha256
from typing import Final

# Slug rules: lowercase, [a-z0-9-] only, whitespace -> '-', max 40 chars.
# We do the lower-casing + collapse BEFORE the char filter, so any run of
# non-[a-z0-9-] becomes a single '-'.
_MAX_SLUG_LEN: Final = 40
_FALLBACK_SLUG: Final = "untitled"


def _normalize_slug(slug: str) -> str:
    """Normalize a user-supplied slug fragment.

    Rules:
        1. NFKC normalize (not strictly required for ASCII but matches
           ``src/kc/domain/knowledge_unit.py`` style).
        2. Lowercase.
        3. Collapse whitespace and any non-[a-z0-9-] run to a single ``-``.
        4. Strip leading/trailing ``-``.
        5. Truncate to 40 chars.
        6. Fall back to ``"untitled"`` if the result is empty.
    """
    text = (slug or "").strip().lower()
    # Collapse any run of non-[a-z0-9] (incl. whitespace) to a single '-'.
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    if not text:
        return _FALLBACK_SLUG
    return text[:_MAX_SLUG_LEN]


def _make_id(prefix: str, slug: str) -> str:
    """Build ``<prefix>_<uuid8>_<normalized_slug>``."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}_{_normalize_slug(slug)}"


def generate_book_id(slug: str) -> str:
    """Generate a new Book id with the canonical ``book_<uuid8>_<slug>`` shape."""
    return _make_id("book", slug)


def generate_chapter_id(slug: str) -> str:
    """Generate a new Chapter id with the canonical ``ch_<uuid8>_<slug>`` shape."""
    return _make_id("ch", slug)


def generate_knowledge_block_id(slug: str) -> str:
    """Generate a new KnowledgeBlock id with the ``kb_<uuid8>_<slug>`` shape."""
    return _make_id("kb", slug)


def generate_stable_knowledge_block_id(chapter_id: str, knowledge_unit_id: str) -> str:
    """Return a repeatable block id for one chapter/KU pair."""
    key = f"{chapter_id}:{knowledge_unit_id}".encode("utf-8")
    return f"kb_{sha256(key).hexdigest()[:8]}_block"


def generate_outline_proposal_id(slug: str) -> str:
    """Generate a new OutlineProposal id with the ``op_<uuid8>_<slug>`` shape."""
    return _make_id("op", slug)
