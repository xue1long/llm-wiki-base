"""Stage 4 — TopicCandidate: per-item semantic candidate.

Task 10 (plan 2026-09-17 §4): one item can map to multiple knowledge
topics (e.g. an article on "Embedding + Chunking + Reranking" has three
candidates). ``TopicCandidate`` is the minimum unit of LLM per-item
discovery.

Identity Contract (canonical Identity Contract §2): LLM does NOT
generate canonical IDs. ``candidate_id`` is derived by the script from
the (item_index, local_index, span_hint, item_fingerprint) tuple so
that identity is stable even if the LLM renames ``semantic_label``
across runs.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class TopicCandidate:
    """LLM per-item discovery 的最小单元.

    One item can have 0..N candidates; each candidate represents an
    independent semantic topic that the LLM discovered in the item.
    LLM decides candidate existence + semantic_label; the script
    decides ``candidate_id`` (the identity) from the span fingerprint,
    not the label.
    """

    candidate_id: str           # script-generated (derive_candidate_id)
    item_index: int             # canonical Stage 2 item index
    local_index: int            # 0..N-1 within the item
    semantic_label: str         # LLM-supplied (human-readable, mutable)
    evidence_span_hint: str     # LLM-supplied span pointer (e.g. "paragraphs 2-4")
    confidence: float           # LLM self-reported; metadata only


def derive_candidate_id(
    item_index: int,
    local_index: int,
    *,
    span_hint: str,
    item_fingerprint: str,
) -> str:
    """Stable candidate ID derived from item anchor + local position + span hint.

    The identity does NOT include ``semantic_label``: the label is LLM
    output and may drift across runs / models, but the identity must
    remain stable for the same span fingerprint.
    """
    identity = f"{item_index}|{local_index}|{span_hint}|{item_fingerprint}"
    short = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
    return f"cand-{item_index}-{local_index}-{short}"
