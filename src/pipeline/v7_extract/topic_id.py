"""Stage 4 — script-generated Topic identity (Task 12, plan 2026-09-17).

Canonical Identity Contract §2.1 (Reconciliation) introduces SAME / ALIAS /
CONFLICT for canonical-concept sharing. Stage 4 has no canonical concept
yet, so the analogous rule is: **Topic.id is owned by the script**, not
the LLM. The LLM supplies ``semantic_label`` (mutable, display-only);
the script derives ``Topic.id`` from the stable membership tuple
(``source_id``, ``candidate_ids``) so the same semantic topic produces
the same identity across LLM renames, model swaps, and re-runs.

Identity inputs (deliberately NOT including ``semantic_label``):

  - ``source_id``     — per-source uniqueness; cross-source duplicates
                         (same topic in two different source files) are
                         allowed because page_id adds the source prefix.
  - ``candidate_ids`` — sorted set of canonical item/candidate IDs that
                         belong to the topic. Same set → same identity.

Returns format: ``<source_id>-topic-<16hex>`` (hard invariant).
"""
from __future__ import annotations

import hashlib


def derive_topic_id(
    *,
    source_id: str,
    candidate_ids: list[str],
    semantic_label: str = "",
) -> str:
    """Stable topic ID from source + canonical candidate set.

    Args:
        source_id: per-source identifier (typically the source's relative
            path, e.g. ``raw/sources/article_42.md``). Used as the prefix
            of the returned topic_id so the same semantic topic in two
            different sources does not collide.
        candidate_ids: the canonical item / candidate IDs that belong to
            this topic. Order does not matter (the function sorts before
            hashing); the LLM cannot influence identity by reordering.
        semantic_label: accepted for API symmetry with the plan sketch
            but explicitly **not** part of identity. Passing different
            labels for the same membership yields the same topic_id.

    Returns:
        ``<source_id>-topic-<16hex>`` — script-generated, deterministic.
    """
    del semantic_label  # explicit non-use: identity is membership-only.
    sorted_cands = sorted(candidate_ids)
    identity = f"{source_id}|{'|'.join(sorted_cands)}"
    short = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:16]
    return f"{source_id}-topic-{short}"
