"""Canonical-relation projection layer (Task 45).

Projects page-level relations (Stage 6R output) into canonical-level
relations using the Phase 1 identity reconciliation registry.

Pure-function projection; no LLM, no IO beyond what the caller passes.

Use case: after Stage 6R produces ``RelationAssertion(source_id=page_a,
target_id=page_b, predicate=refines)``, the canonical layer wants to
know "which canonical concept did page_a belong to, and which did
page_b belong to?" and produce a relation keyed by those canonical_ids.

Pairs whose source and target canonical are the same are skipped (intra-
canonical relations are not Stage 6R's job — that would just be
"canonical X is related to canonical X", which is meaningless).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from src.pipeline.v7_extract.relation_extractor import PageRelation
from src.pipeline.v7_extract.relation_models import (
    RelationAssertion,
    RelationKey,
    RelationPredicate,
    RelationSupportStatus,
)
from src.reconciliation.canonical_registry import CanonicalRegistry


@dataclass(frozen=True)
class CanonicalRelationKey:
    canonical_id_a: str
    canonical_id_b: str
    predicate: RelationPredicate

    def relation_id(self) -> str:
        identity = f"{self.canonical_id_a}|{self.predicate.value}|{self.canonical_id_b}"
        return "crel-" + hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]


@dataclass
class CanonicalRelation:
    key: CanonicalRelationKey
    relation_id: str
    confidence: float = 0.0
    source_page_ids: list[str] = field(default_factory=list)
    target_page_ids: list[str] = field(default_factory=list)
    support_status: RelationSupportStatus = RelationSupportStatus.SUPPORTED


def _extract_page_ids(assertion: RelationAssertion | PageRelation) -> tuple[str, str]:
    if isinstance(assertion, RelationAssertion):
        return (assertion.key.source_page_id, assertion.key.target_page_id)
    return (assertion.source_id, assertion.target_id)


def _extract_predicate(assertion: RelationAssertion | PageRelation) -> RelationPredicate:
    if isinstance(assertion, RelationAssertion):
        return assertion.key.predicate
    return RelationPredicate(assertion.type)


def _extract_confidence(assertion: RelationAssertion | PageRelation) -> float:
    if isinstance(assertion, RelationAssertion):
        return float(assertion.confidence)
    return float(assertion.weight)


def _extract_support_status(
    assertion: RelationAssertion | PageRelation,
) -> RelationSupportStatus:
    if isinstance(assertion, RelationAssertion):
        return assertion.support_status
    return RelationSupportStatus.SUPPORTED


def _canonical_for_page(
    registry: CanonicalRegistry, page_id: str
) -> str | None:
    """Return the canonical_id whose member_page_ids contains ``page_id``.

    Falls back to alias lookup (page_id == alias_text).
    """
    if not page_id:
        return None
    concepts = registry.load_concepts()
    for canonical_id, concept in concepts.items():
        if page_id in concept.member_page_ids:
            return canonical_id
    # Alias fallback: page_id may itself be an alias for some canonical.
    alias_hit = registry.get_by_alias(page_id)
    if alias_hit is not None:
        return alias_hit.canonical_id
    return None


def derive_canonical_relation(
    assertion: RelationAssertion | PageRelation,
    *,
    registry: CanonicalRegistry,
) -> CanonicalRelation | None:
    """Project a page-level relation into a canonical-level relation.

    Returns ``None`` when either side cannot be resolved to a canonical_id
    in the registry, or when both sides resolve to the SAME canonical
    (intra-canonical — out of scope).
    """
    source_page_id, target_page_id = _extract_page_ids(assertion)
    source_canonical = _canonical_for_page(registry, source_page_id)
    target_canonical = _canonical_for_page(registry, target_page_id)
    if source_canonical is None or target_canonical is None:
        return None
    if source_canonical == target_canonical:
        return None

    predicate = _extract_predicate(assertion)
    confidence = _extract_confidence(assertion)
    support_status = _extract_support_status(assertion)

    spec = predicate  # Already a RelationPredicate enum.
    # Symmetric predicates: canonicalize order.
    # Use RelationPredicate.coerce pattern via the ontology module.
    from src.pipeline.v7_extract.relation_ontology import get_spec
    relation_spec = get_spec(spec)
    if relation_spec.symmetric:
        a, b = sorted([source_canonical, target_canonical])
    else:
        a, b = source_canonical, target_canonical

    key = CanonicalRelationKey(
        canonical_id_a=a,
        canonical_id_b=b,
        predicate=spec,
    )
    relation_id = key.relation_id()

    return CanonicalRelation(
        key=key,
        relation_id=relation_id,
        confidence=confidence,
        source_page_ids=[source_page_id],
        target_page_ids=[target_page_id],
        support_status=support_status,
    )


def canonical_relations_path(root: Path | str) -> Path:
    """<.index/reconciliation/canonical_relations.jsonl>"""
    p = Path(root) / ".index" / "reconciliation" / "canonical_relations.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


__all__ = [
    "CanonicalRelation",
    "CanonicalRelationKey",
    "canonical_relations_path",
    "derive_canonical_relation",
]