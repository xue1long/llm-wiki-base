"""Tests for canonical-relation projection (Task 45)."""
from __future__ import annotations

from src.pipeline.v7_extract.relation_extractor import PageRelation
from src.pipeline.v7_extract.relation_models import (
    RelationAssertion,
    RelationKey,
    RelationPredicate,
    RelationSupportKind,
    RelationSupportStatus,
)
from src.reconciliation.canonical_models import CanonicalConcept, ReconciliationStatus
from src.reconciliation.canonical_registry import CanonicalRegistry
from src.reconciliation.canonical_relations import (
    CanonicalRelation,
    derive_canonical_relation,
)


def _setup_registry(
    registry: CanonicalRegistry,
    *,
    ca_pages: list[str],
    cb_pages: list[str],
) -> None:
    ca = CanonicalConcept(
        canonical_id="c-aaaa1111",
        preferred_label="Alpha",
        member_page_ids=ca_pages,
        status=ReconciliationStatus.ACTIVE,
        resolver_fingerprint="fp",
    )
    cb = CanonicalConcept(
        canonical_id="c-bbbb2222",
        preferred_label="Beta",
        member_page_ids=cb_pages,
        status=ReconciliationStatus.ACTIVE,
        resolver_fingerprint="fp",
    )
    registry._save_concepts({ca.canonical_id: ca, cb.canonical_id: cb})


def test_derive_canonical_relation_resolves_pages_via_registry(tmp_path):
    """page_a (canonical Alpha) --[refines]--> page_b (canonical Beta) →
    CanonicalRelation(Alpha --[refines]--> Beta)."""
    registry = CanonicalRegistry(tmp_path)
    _setup_registry(registry, ca_pages=["page-a"], cb_pages=["page-b"])

    rel = PageRelation(
        source_id="page-a", target_id="page-b", type="refines",
        weight=0.8, context="ok",
    )
    out = derive_canonical_relation(rel, registry=registry)
    assert out is not None
    assert isinstance(out, CanonicalRelation)
    # source_id="page-a" → Alpha; target_id="page-b" → Beta.
    # PageRelation is directional (refines) so no swap.
    assert out.key.canonical_id_a == "c-aaaa1111"
    assert out.key.canonical_id_b == "c-bbbb2222"
    assert out.key.predicate is RelationPredicate.REFINES
    assert out.relation_id.startswith("crel-")


def test_derive_canonical_relation_returns_none_for_unknown_page(tmp_path):
    """page_id not in registry → None (not a crash)."""
    registry = CanonicalRegistry(tmp_path)
    # Empty registry — no pages registered.
    rel = PageRelation(source_id="ghost-page", target_id="another-ghost", type="refines")
    out = derive_canonical_relation(rel, registry=registry)
    assert out is None


def test_derive_canonical_relation_symmetric_canonical_fold(tmp_path):
    """related_to is symmetric: A→B and B→A produce the same canonical_relation_id."""
    registry = CanonicalRegistry(tmp_path)
    _setup_registry(registry, ca_pages=["page-a"], cb_pages=["page-b"])

    rel_ab = PageRelation(source_id="page-a", target_id="page-b", type="related_to")
    rel_ba = PageRelation(source_id="page-b", target_id="page-a", type="related_to")

    out_ab = derive_canonical_relation(rel_ab, registry=registry)
    out_ba = derive_canonical_relation(rel_ba, registry=registry)
    assert out_ab is not None and out_ba is not None
    # Same relation_id (symmetric fold).
    assert out_ab.relation_id == out_ba.relation_id


def test_derive_canonical_relation_skips_intra_canonical_pairs(tmp_path):
    """Both pages in same canonical → None (intra-canonical)."""
    registry = CanonicalRegistry(tmp_path)
    # Both page-a and page-b are members of canonical Alpha.
    ca = CanonicalConcept(
        canonical_id="c-cccc3333",
        preferred_label="Cluster",
        member_page_ids=["page-a", "page-b"],
        status=ReconciliationStatus.ACTIVE,
        resolver_fingerprint="fp",
    )
    registry._save_concepts({ca.canonical_id: ca})

    rel = PageRelation(source_id="page-a", target_id="page-b", type="refines")
    out = derive_canonical_relation(rel, registry=registry)
    assert out is None


def test_derive_canonical_relation_accepts_relation_assertion(tmp_path):
    """RelationAssertion input form also works (not just PageRelation)."""
    registry = CanonicalRegistry(tmp_path)
    _setup_registry(registry, ca_pages=["page-a"], cb_pages=["page-b"])

    key = RelationKey(
        source_page_id="page-b",
        predicate=RelationPredicate.CAUSES,
        target_page_id="page-a",
    )
    assertion = RelationAssertion(
        key=key,
        relation_id=key.relation_id(),
        support_kind=RelationSupportKind.LLM_DIRECT,
        support_status=RelationSupportStatus.SUPPORTED,
        evidence_refs=[],
        claim_ids=[],
        confidence=0.7,
        extractor_fingerprint="fp",
    )
    out = derive_canonical_relation(assertion, registry=registry)
    assert out is not None
    assert out.key.predicate is RelationPredicate.CAUSES
    assert out.confidence == 0.7