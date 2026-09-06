"""Fail-closed checks for the optional editorial polishing stage."""
from __future__ import annotations

import hashlib
import re
from collections import Counter

from .aggregator import ChapterDraft

_WIKILINK = re.compile(r"\[\[([^]|]+)(?:\|[^]]*)?\]\]")


def canonical_body(draft: ChapterDraft) -> str:
    return "\n\n".join(block.body for block in draft.blocks)


def body_sha256(draft: ChapterDraft) -> str:
    return hashlib.sha256(canonical_body(draft).encode("utf-8")).hexdigest()


def _refs(text: str) -> Counter[str]:
    return Counter(match.group(1).strip() for match in _WIKILINK.finditer(text))


def validate_polished_chapter(draft: ChapterDraft, polished: object) -> tuple[str, ...]:
    """Return stable error codes; any error means callers must use ``draft``."""
    errors: list[str] = []
    if getattr(polished, "chapter_id", None) != draft.chapter_id:
        errors.append("chapter_id_mismatch")

    order = tuple(getattr(polished, "block_order", ()))
    expected_pages = tuple(draft.intra_chapter_order or draft.page_ids)
    expected_blocks = tuple(draft.block_ids)
    if Counter(order) not in (Counter(expected_pages), Counter(expected_blocks)):
        errors.append("block_order_mismatch")

    supplied_body = getattr(polished, "body", None)
    if supplied_body is not None:
        expected = canonical_body(draft)
        if hashlib.sha256(supplied_body.encode("utf-8")).hexdigest() != body_sha256(draft):
            errors.append("body_hash_mismatch")
        if _refs(supplied_body) != _refs(expected):
            errors.append("wikilink_mismatch")

    valid_ids = set(draft.block_ids)
    for field in ("transition_in", "transition_out"):
        value = getattr(polished, field, None)
        if value is not None:
            cited = {block_id for block_id in valid_ids
                     if re.search(rf"(?<![\w:-]){re.escape(block_id)}(?![\w:-])", value)}
            if not cited:
                errors.append(f"{field}_invalid_reference")

    for section in tuple(getattr(polished, "editorial_sections", ())):
        if _refs(section) - _refs(canonical_body(draft)):
            errors.append("new_wikilink")
            break
    return tuple(dict.fromkeys(errors))


__all__ = ["body_sha256", "canonical_body", "validate_polished_chapter"]
