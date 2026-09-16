"""Stage 4 — TopicDescriptor: bounded per-item representation for Stage 4 LLM.

Task 11 (plan 2026-09-17 §4 Task 11) splits ``cluster_topics`` into two LLM
stages:

  - **Stage 4A (per-item discovery)** — given one item at a time, ask the
    LLM which semantic themes are present in that item. Each theme is a
    ``TopicCandidate`` (Task 10).
  - **Stage 4B (cross-item grouping)** — given all candidates from 4A,
    ask the LLM which candidates belong to the same logical topic.

Stage 4A must NOT see the whole item text — that defeats the Bounded
Evidence Contract (Contract Freeze §3.2: each Stage 4 input ≤ 600 bytes
per item). The LLM only ever sees a ``TopicDescriptor``: HEAD bytes +
TAIL bytes + minimal structural summary. Item-fingerprint-derived,
deterministic, ≤ 600 bytes regardless of source size.

Identity Contract: ``TopicDescriptor`` carries no canonical IDs. The
descriptor is purely a *bounded view* of one item for LLM consumption;
identity (item_id, candidate_id, topic_id) is script-owned.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# Bounded Evidence Contract §3.2 — Stage 4 hard budget per item.
MAX_DESCRIPTOR_BYTES = 600
HEAD_BYTES = 300
TAIL_BYTES = 200


@dataclass
class TopicDescriptor:
    """Bounded per-item representation consumed by Stage 4A LLM.

    The descriptor is a *projection* of one item: HEAD bytes + TAIL bytes
    + a small structural summary. It carries no canonical IDs (those are
    script-owned) — only the metadata needed for the LLM to identify
    which item it is reasoning about.

    The DESCRIPTOR TEXT (bounded_lead + bounded_tail) must fit in
    ``MAX_DESCRIPTOR_BYTES``. ``build_descriptors`` enforces this; tests
    assert it.
    """

    item_index: int
    item_kind: str               # "article" | "section" | "list_item" | ...
    title: str | None
    bounded_lead: str            # first HEAD_BYTES chars (or all if shorter)
    bounded_tail: str            # last TAIL_BYTES chars (empty if item fits in HEAD)
    structural_summary: dict = field(default_factory=dict)
    item_fingerprint: str = ""   # stage-2-derived item fingerprint (script-owned)


def build_descriptors(items: list[dict]) -> list[TopicDescriptor]:
    """Build bounded TopicDescriptor list from item dicts.

    Each descriptor carries:
      - bounded_lead: first HEAD_BYTES chars of item.text
      - bounded_tail: last TAIL_BYTES chars of item.text (empty if item
        fits within HEAD_BYTES + TAIL_BYTES — no need to repeat content)
      - structural_summary: boundary_sources / byte_span / length

    ``bounded_lead + bounded_tail`` is asserted to be within
    ``MAX_DESCRIPTOR_BYTES`` (Bounded Evidence Contract §3.2 — 600 bytes).
    """
    out: list[TopicDescriptor] = []
    for idx, item in enumerate(items):
        text = str(item.get("text", ""))
        n = len(text)
        if n <= HEAD_BYTES:
            lead = text
            tail = ""
        else:
            lead = text[:HEAD_BYTES]
            tail = text[-TAIL_BYTES:] if TAIL_BYTES > 0 else ""
        descriptor_bytes = len(lead.encode("utf-8")) + len(tail.encode("utf-8"))
        # Bounded Evidence Contract §3.2: 600 bytes / item.
        assert descriptor_bytes <= MAX_DESCRIPTOR_BYTES, (
            f"TopicDescriptor for item_index={idx} is {descriptor_bytes} bytes "
            f"(limit {MAX_DESCRIPTOR_BYTES}); HEAD_BYTES={HEAD_BYTES}, "
            f"TAIL_BYTES={TAIL_BYTES}"
        )
        out.append(TopicDescriptor(
            item_index=idx,
            item_kind=str(item.get("kind", "unknown")),
            title=item.get("title"),
            bounded_lead=lead,
            bounded_tail=tail,
            structural_summary={
                "boundary_sources": list(item.get("boundary_sources", [])),
                "byte_span": item.get("byte_span"),
                "length": n,
            },
            item_fingerprint=str(item.get("item_fingerprint", "") or str(item.get("id", ""))),
        ))
    return out


__all__ = [
    "HEAD_BYTES",
    "MAX_DESCRIPTOR_BYTES",
    "TAIL_BYTES",
    "TopicDescriptor",
    "build_descriptors",
]