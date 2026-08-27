"""Tests for Structured Fact contract + structured extractor (C-4.5 / Z-8).

路线 v2.2 §C-4.5 Claim/Structured Fact 双路径:
- spec §5.6 Structured Fact schema
- spec §5 identity_key table (subject/field/value/value_type/context_id/validity_id)
- spec §3.5 P-5 "Claim 不是强制中间态"
- spec §3.5 "Claim + Structured Fact 必须共享 Evidence 引用"

TDD coverage (4 tests):
1. StructuredFact construction + identity_key determinism (same input → same output)
2. structured_extractor.extract returns List[StructuredFact]
3. Structured Fact shares Evidence reference (no duplication)
4. Claim + Structured Fact coexist on the same KU (via _attach_to_ku)
"""
from __future__ import annotations

import pytest

# These imports intentionally fail before implementation is added — TDD red phase.
from src.kc.contracts import (
    StructuredFact,
    compute_structured_fact_identity_key,
)
from src.kc.contracts.evidence import Evidence, evidence_for_quote
from src.kc.extraction.structured_extractor import (
    StructuredExtractor,
    extract_structured_facts,
)


# ─── Test 1: StructuredFact 构造 + identity_key 确定性 ─────────────────


def test_structured_fact_construction_and_identity_key_is_deterministic():
    """Same input fields → same identity_key (sha256 deterministic)."""
    sf_a = StructuredFact(
        subject="user.email",
        field="value",
        value="alice@example.com",
        value_type="string",
        context_id="ctx-prod",
        validity_id="val-2026",
        confidence=0.95,
        evidence_ids=("ev-1", "ev-2"),
        extraction_run_id="run-001",
    )
    sf_b = StructuredFact(
        subject="user.email",
        field="value",
        value="alice@example.com",
        value_type="string",
        context_id="ctx-prod",
        validity_id="val-2026",
        confidence=0.95,
        evidence_ids=("ev-1", "ev-2"),
        extraction_run_id="run-001",
    )

    # identity_key must be present, deterministic, and identical for same inputs
    key_a = compute_structured_fact_identity_key(sf_a)
    key_b = compute_structured_fact_identity_key(sf_b)
    assert key_a == key_b
    assert key_a.startswith("id-v1:")

    # And different inputs must yield different keys (spec §5 collision-free)
    sf_c = StructuredFact(
        subject="user.email",
        field="value",
        value="bob@example.com",  # different value
        value_type="string",
        context_id="ctx-prod",
        validity_id="val-2026",
        confidence=0.95,
        evidence_ids=("ev-1", "ev-2"),
        extraction_run_id="run-001",
    )
    key_c = compute_structured_fact_identity_key(sf_c)
    assert key_c != key_a


# ─── Test 2: structured_extractor.extract returns List[StructuredFact] ──


def test_structured_extractor_returns_list_of_structured_facts():
    """From a parameter table shape, extract returns List[StructuredFact]."""
    table_data = [
        {
            "subject": "user.email",
            "field": "value",
            "value": "alice@example.com",
            "value_type": "string",
            "context_id": "ctx-prod",
            "validity_id": "val-2026",
            "confidence": 0.95,
            "evidence_ids": ("ev-1",),
        },
        {
            "subject": "user.age",
            "field": "value",
            "value": 30,
            "value_type": "number",
            "context_id": "ctx-prod",
            "validity_id": "val-2026",
            "confidence": 0.90,
            "evidence_ids": ("ev-2",),
        },
    ]

    facts = extract_structured_facts(table_data, run_id="run-002")
    assert isinstance(facts, list)
    assert len(facts) == 2
    assert all(isinstance(f, StructuredFact) for f in facts)
    # run_id propagated
    assert facts[0].extraction_run_id == "run-002"
    assert facts[1].extraction_run_id == "run-002"
    # default status
    assert facts[0].status == "candidate"


# ─── Test 3: Structured Fact shares Evidence reference ──────────────────


def test_structured_fact_shares_evidence_reference_without_duplication():
    """A backing Evidence instance referenced by multiple StructuredFact entries
    must NOT be re-minted — the same Evidence object is referenced by
    evidence_ids (spec §3.5 '共享 Evidence 契约')."""
    shared_evidence = evidence_for_quote(
        document_id="doc-1",
        block_id="blk-1",
        quote="user.email = alice@example.com",
        supports=("user.email",),
    )

    sf1 = StructuredFact(
        subject="user.email",
        field="value",
        value="alice@example.com",
        value_type="string",
        context_id="ctx-prod",
        validity_id="val-2026",
        confidence=0.95,
        evidence_ids=(shared_evidence.evidence_id,),
        extraction_run_id="run-003",
    )
    sf2 = StructuredFact(
        subject="user.email",
        field="format",
        value="rfc5322",
        value_type="string",
        context_id="ctx-prod",
        validity_id="val-2026",
        confidence=0.80,
        evidence_ids=(shared_evidence.evidence_id,),
        extraction_run_id="run-003",
    )

    # Both facts reference the SAME evidence_id — no duplication
    assert sf1.evidence_ids == sf2.evidence_ids
    assert shared_evidence.evidence_id in sf1.evidence_ids
    assert shared_evidence.evidence_id in sf2.evidence_ids

    # The extractor must also reuse evidence_ids as-is, not re-mint new Evidence
    table_data = [
        {
            "subject": "user.email",
            "field": "value",
            "value": "alice@example.com",
            "value_type": "string",
            "context_id": "ctx-prod",
            "validity_id": "val-2026",
            "confidence": 0.95,
            "evidence_ids": (shared_evidence.evidence_id,),
        },
        {
            "subject": "user.email",
            "field": "format",
            "value": "rfc5322",
            "value_type": "string",
            "context_id": "ctx-prod",
            "validity_id": "val-2026",
            "confidence": 0.80,
            "evidence_ids": (shared_evidence.evidence_id,),
        },
    ]
    facts = extract_structured_facts(table_data, run_id="run-003")
    eids = {ev_id for f in facts for ev_id in f.evidence_ids}
    assert eids == {shared_evidence.evidence_id}


# ─── Test 4: Claim + Structured Fact coexist on same KU ─────────────────


def test_claim_and_structured_fact_coexist_on_same_ku():
    """spec §3.5 P-5: Claim + Structured Fact both attach to the same KU
    via _attach_to_ku(kc_ku_id) without overwriting each other."""
    extractor = StructuredExtractor(run_id="run-004")

    sf = StructuredFact(
        subject="user.email",
        field="value",
        value="alice@example.com",
        value_type="string",
        context_id="ctx-prod",
        validity_id="val-2026",
        confidence=0.95,
        evidence_ids=("ev-1",),
        extraction_run_id="run-004",
    )
    extractor.add(sf)

    # Attach a Claim on the same KU — stored separately, not overwritten
    extractor.attach_claim(
        kc_ku_id="ku-001",
        claim={"subject": "user.email", "predicate": "is", "object": "alice@example.com"},
    )
    extractor.attach_structured_fact(kc_ku_id="ku-001", fact=sf)

    # Both Claim and Structured Fact are present on ku-001 (spec §3.5 合并到 KU)
    ku_state = extractor.snapshot_ku("ku-001")
    assert "claim" in ku_state
    assert "structured_facts" in ku_state
    assert ku_state["claim"]["subject"] == "user.email"
    assert sf in ku_state["structured_facts"]