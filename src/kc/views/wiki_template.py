"""WikiTemplate + WikiView dataclasses (路线 v2.2 §A-7 / Z-7, spec §12.4 R-7).

Two frozen dataclasses that pin down the Wiki view contract:

* ``WikiTemplate``  — stable template (default sections = the spec-mandated
  ordering). The template is fixed for this project (spec §12.5 "固定 Book
  Template" applies symmetrically to Wiki). Custom templates are still
  allowed for test isolation, but the default is the source of truth.
* ``WikiView``      — the compiled view value object, carrying enough state
  for the B-3.5 delete-then-rebuild-from-Core contract (publication_version
  parity, knowledge_unit_ids for provenance, rendered_hash for equivalence
  check).

The ``rendered_hash`` is sha256 over a deterministic JSON serialization of
the rendered content + the knowledge_unit_ids + the sections ordering +
the publication_version. Same inputs → same hash, so the rebuild path is
idempotent.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field


# ── template ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class WikiTemplate:
    """Stable Wiki template — fixed for this project (spec §12.5 / §12.4 R-7).

    Default sections (spec §12.4): summary → context_filters → temporal_status
    → knowledge_units → conflicts → evidence_refs. This ordering is the
    public surface that downstream renderers consume; reordering without a
    spec bump is a contract break.
    """

    template_id: str = "default_v1"
    sections: tuple[str, ...] = (
        "summary",
        "context_filters",
        "temporal_status",
        "knowledge_units",
        "conflicts",
        "evidence_refs",
    )


# ── view dataclass ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class WikiView:
    """Compiled Wiki view value object (spec §12.4 schema).

    Fields:
        id                  view identifier (deterministic from topic_scope)
        topic_scope         {"concept_ids": [...], "context_filters": {...}}
        publication_version B-4 publication watermark (must match Core)
        knowledge_unit_ids  tuple of KU ids that contributed to the render
        rendered_hash       sha256 of the deterministic serialized content;
                            same inputs → same hash (B-3.5 rebuild idempotent)
        generated_at        unix-ms timestamp when this view was compiled
        sections_content    dict mapping section name → rendered string.
                            Exposed here for callers / tests; the canonical
                            source of truth is the tuple above + the inputs.
    """

    id: str
    topic_scope: dict
    publication_version: int
    knowledge_unit_ids: tuple[str, ...]
    rendered_hash: str
    generated_at: int
    # Sections content is a dict-of-strings keyed by section name (matches
    # WikiTemplate.sections). Not part of the equality/hashing surface so
    # that two views with byte-identical rendered content but different
    # Python reprs still compare equal — but the hash captures the content.
    sections_content: dict = field(default_factory=dict, compare=False, hash=False)


def compute_rendered_hash(
    *,
    knowledge_unit_ids: tuple[str, ...],
    sections: tuple[str, ...],
    sections_content: dict,
    publication_version: int,
) -> str:
    """Compute the deterministic sha256 hash over the rendered content.

    Hash inputs (all deterministic):
        * publication_version   (B-4 watermark)
        * sections ordering      (template identity)
        * knowledge_unit_ids     (provenance ordering)
        * per-section content    (canonical JSON)

    Returns hex digest string (64 chars).
    """
    payload = {
        "publication_version": publication_version,
        "sections": list(sections),
        "knowledge_unit_ids": list(knowledge_unit_ids),
        "sections_content": sections_content,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


__all__ = [
    "WikiTemplate",
    "WikiView",
    "compute_rendered_hash",
]
