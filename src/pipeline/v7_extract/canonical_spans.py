"""Canonical evidence spans — script-generated candidates for Stage 5A.

Bounded Evidence Contract §3.2: each span's byte length <= SPAN_TARGET_BYTES.
"""
from __future__ import annotations

import hashlib
from bisect import bisect_left, bisect_right
from dataclasses import dataclass

from .segmentation import CanonicalItem

SPAN_TARGET_BYTES = 1500
SPAN_OVERLAP_BYTES = 200
MAX_SPANS_PER_ITEM = 20


@dataclass(frozen=True)
class CanonicalSpan:
    """One evidence candidate window inside a CanonicalItem.

    COORDINATE SYSTEM (must not be confused):
      - start_byte / end_byte : SOURCE-ABSOLUTE UTF-8 byte offsets.
        ``source_bytes[span.start_byte:span.end_byte]`` is correct as-is.
      - char_start / char_end : offsets into the OWNING item's decoded
        ``item.text`` (item-local view).
    Both views must describe the SAME text.
    """
    span_id: str
    item_id: str
    item_index: int
    start_byte: int
    end_byte: int
    char_start: int
    char_end: int


def _char_byte_prefix(text: str) -> list[int]:
    """``prefix[i]`` = UTF-8 byte length of ``text[:i]`` (item-local)."""
    prefix = [0]
    total = 0
    for ch in text:
        total += len(ch.encode("utf-8"))
        prefix.append(total)
    return prefix


def _span_id(item_id: str, start_byte: int, end_byte: int) -> str:
    raw = f"{item_id}|{start_byte}|{end_byte}".encode("utf-8")
    return f"span-{hashlib.sha1(raw).hexdigest()[:12]}"


def build_canonical_spans(
    items: list[CanonicalItem],
    *,
    span_target_bytes: int = SPAN_TARGET_BYTES,
    overlap_bytes: int = SPAN_OVERLAP_BYTES,
) -> list[CanonicalSpan]:
    """Fixed-size overlapping windows over each item's text.

    - An item whose byte length <= span_target_bytes yields exactly ONE span.
    - Larger items yield overlapping windows, each with byte length
      <= span_target_bytes (hard-asserted before returning).
    - ponytail: hard cap of MAX_SPANS_PER_ITEM per item — a pathological
      1MB item would otherwise produce hundreds of spans; raise the cap or
      switch to semantic chunking if recall measurably suffers.
    - span_id = f"span-{sha1(item_id|start_byte|end_byte)[:12]}" (deterministic).

    Byte coordinates are computed in CHARACTER space over ``item.text``, then
    shifted by ``item.start_byte`` so the stored offsets are SOURCE-ABSOLUTE.
    """
    spans: list[CanonicalSpan] = []

    for item_index, item in enumerate(items):
        text = item.text
        n_chars = len(text)
        if n_chars == 0:
            continue  # a zero-length item cannot yield a non-zero-length span

        prefix = _char_byte_prefix(text)          # item-local byte offsets
        item_byte_base = item.start_byte          # shift to source-absolute
        item_spans: list[CanonicalSpan] = []

        char_start = 0
        while char_start < n_chars and len(item_spans) < MAX_SPANS_PER_ITEM:
            # Largest char_end whose item-local byte length fits the budget.
            limit = prefix[char_start] + span_target_bytes
            char_end = bisect_right(prefix, limit) - 1
            if char_end <= char_start:
                char_end = char_start + 1          # single char > target: keep it

            start_byte = item_byte_base + prefix[char_start]
            end_byte = item_byte_base + prefix[char_end]
            item_spans.append(
                CanonicalSpan(
                    span_id=_span_id(item.item_id, start_byte, end_byte),
                    item_id=item.item_id,
                    item_index=item_index,
                    start_byte=start_byte,
                    end_byte=end_byte,
                    char_start=char_start,
                    char_end=char_end,
                )
            )

            if char_end >= n_chars:
                break

            # Next window starts overlap_bytes before this one ended.
            target = prefix[char_end] - overlap_bytes
            next_start = bisect_left(prefix, target, char_start + 1)
            if next_start <= char_start:           # zero-or-negative step guard
                next_start = char_end
            char_start = next_start

        spans.extend(item_spans)

    for span in spans:
        byte_len = span.end_byte - span.start_byte
        if byte_len <= 0:
            raise AssertionError(f"zero-length span: {span}")
        if byte_len > span_target_bytes and (span.char_end - span.char_start) != 1:
            raise AssertionError(
                f"span exceeds {span_target_bytes} bytes: {byte_len} ({span})"
            )

    return spans


__all__ = [
    "CanonicalSpan",
    "MAX_SPANS_PER_ITEM",
    "SPAN_OVERLAP_BYTES",
    "SPAN_TARGET_BYTES",
    "build_canonical_spans",
]
