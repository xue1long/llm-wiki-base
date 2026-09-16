"""Stage 6R semantic reviewer for HIGH-risk relations (Task 36).

Plan: ``docs/superpowers/plans/2026-09-17-v7-stage-remediation-task36-stage6r-reviewer.md``

The Stage 6R ``RelationAssertion`` produced by ``relation_extractor`` may
have a HIGH-risk predicate (``CAUSES`` / ``REQUIRES`` / ``CONTRADICTS`` /
``DEPENDS_ON`` / ``EXTENDS`` / ``BROADER`` / ``NARROWER``). For those
relations we ask the LLM to re-check the semantic honesty of the
relation against the cited evidence. The verdict vocabulary has four
values, mirroring Task 17 (claim reviewer) and Task 35 (topic reviewer):

    SUPPORTED    → caller keeps the relation
    OVERSTATED   → caller keeps but should down-weight
    CONTRADICTED → caller drops (filter_substantive_relations gate)
    UNRESOLVED   → technical failure or insufficient evidence

Reviewer-level failure (all ``max_retries`` attempts raise) marks every
HIGH-risk relation UNRESOLVED — never raises (Failure Contract §1).

F8 discipline: ``relation_extractor`` / ``relation_models`` /
``relation_store`` / ``candidate_retrieval`` / ``claim_validator`` /
``claim_reviewer`` are untouched. The reviewer is an independently-
callable module (``review_high_risk_relations(assertions, ...)``);
Stage 6R caller wiring is deferred to a follow-up Task.
"""
from __future__ import annotations

import json

import pytest

from src.pipeline.v7_extract.claim import EvidenceRef
from src.pipeline.v7_extract.llm_client import FakeLLMClient
from src.pipeline.v7_extract.relation_models import (
    RelationAssertion,
    RelationKey,
    RelationSupportKind,
    RelationSupportStatus,
)
from src.pipeline.v7_extract.relation_reviewer import (
    MAX_RELATIONS_PER_REVIEW_CALL,
    PROMPT_KIND,
    RelationReviewInput,
    RelationReviewRecord,
    RelationReviewStatus,
    is_high_risk_predicate,
    review_high_risk_relations,
)
from src.pipeline.v7_extract.relation_ontology import RelationPredicate


PROMPT_KIND_NAME = "relation_reviewer"


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _assertion(
    *,
    source_page_id: str,
    target_page_id: str,
    predicate: RelationPredicate,
    evidence_excerpts: list[str] | None = None,
    confidence: float = 0.9,
) -> RelationAssertion:
    """Build a RelationAssertion with a script-generated relation_id."""
    key = RelationKey(
        source_page_id=source_page_id,
        predicate=predicate,
        target_page_id=target_page_id,
    )
    refs: list[EvidenceRef] = []
    if evidence_excerpts:
        cursor = 0
        for idx, excerpt in enumerate(evidence_excerpts):
            start = cursor
            end = cursor + len(excerpt.encode("utf-8"))
            refs.append(EvidenceRef(
                item_id=f"item-{idx}",
                item_index=idx,
                span_index=0,
                start_byte=start,
                end_byte=end,
            ))
            cursor = end + 1  # +1 to keep starts monotonic across refs
    return RelationAssertion(
        key=key,
        relation_id=key.relation_id(),
        support_kind=RelationSupportKind.LLM_DIRECT,
        support_status=RelationSupportStatus.SUPPORTED,
        evidence_refs=refs,
        claim_ids=[],
        confidence=confidence,
        extractor_fingerprint="relation_extractor.v2",
    )


def _script_payload(*, verdicts: list[dict]) -> str:
    """Wrap verdicts in the LLM's expected JSON envelope."""
    return json.dumps({"verdicts": verdicts})


# ---------------------------------------------------------------------------
# Test 1: enum has four values
# ---------------------------------------------------------------------------


def test_relation_review_status_enum_has_four_values() -> None:
    """The reviewer verdict vocabulary is exactly four values.

    Verifies the enum members present (4-value contract from Task 36
    spec §2 / §5). Adding / removing values is a breaking change —
    downstream callers (``filter_substantive_relations`` + the new
    review-aware gate) will switch on this enum and rely on the four
    labelled states.
    """
    members = {v.value for v in RelationReviewStatus}
    assert members == {
        "supported",
        "overstated",
        "contradicted",
        "unresolved",
    }
    # str-Enum — string comparison works (JSON-friendly).
    assert RelationReviewStatus.SUPPORTED.value == "supported"
    assert RelationReviewStatus.OVERSTATED.value == "overstated"
    assert RelationReviewStatus.CONTRADICTED.value == "contradicted"
    assert RelationReviewStatus.UNRESOLVED.value == "unresolved"


# ---------------------------------------------------------------------------
# Test 2: only HIGH-risk predicate → LLM; low-risk → bypass
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_relation_reviewer_only_invoked_for_high_risk_predicate() -> None:
    """LOW-risk predicate (refines / supported_by / instance_of /
    related_to / similar_to / co_occurs_with / paired_with) → reviewer
    skips the LLM entirely; record defaults to SUPPORTED.

    Spec §1.2: Bounded Evidence — the LLM is only charged for HIGH-risk
    relations. LOW-risk relations default to SUPPORTED without
    consuming any LLM calls. The ``FakeLLMClient.calls`` log is the
    witness: zero entries after this call.
    """
    llm = FakeLLMClient()
    # No scripts queued — if the reviewer calls the LLM, the call would
    # return "" and likely raise LLMResponseError during parse.

    low_risk_predicates = [
        RelationPredicate.REFINES,
        RelationPredicate.SUPPORTED_BY,
        RelationPredicate.INSTANCE_OF,
        RelationPredicate.RELATED_TO,
        RelationPredicate.SIMILAR_TO,
        RelationPredicate.CO_OCCURS_WITH,
        RelationPredicate.PAIRED_WITH,
    ]
    assertions = [
        _assertion(
            source_page_id=f"src-{i}",
            target_page_id=f"tgt-{i}",
            predicate=p,
            evidence_excerpts=[f"excerpt for {p.value}"],
        )
        for i, p in enumerate(low_risk_predicates)
    ]

    # Map by relation_id (source_bytes lookup keys by source page).
    source_bytes = {a.key.source_page_id: b"x" * 1024 for a in assertions}

    records = await review_high_risk_relations(
        assertions, source_bytes=source_bytes, llm=llm,
    )

    # Every assertion comes back as a record (in same order).
    assert len(records) == len(assertions)
    assert [r.relation_id for r in records] == [a.relation_id for a in assertions]
    # All records are SUPPORTED.
    assert all(r.status is RelationReviewStatus.SUPPORTED for r in records)
    # LLM was NEVER called.
    assert llm.calls == []
    # Reason records the bypass.
    assert all("low-risk" in r.reason for r in records)


# ---------------------------------------------------------------------------
# Test 3: HIGH-risk relation + LLM verdict CONTRADICTED → record is CONTRADICTED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_relation_reviewer_rejects_overstated_causal_relation() -> None:
    """HIGH-risk ``causes`` predicate where evidence does not contain a
    causal claim → LLM verdict CONTRADICTED → record carries CONTRADICTED.

    The test deliberately scripts the LLM to reject the relation so we
    exercise the verdict-mapping branch (CONTRADICTED must surface
    verbatim — caller will drop this relation from
    ``filter_substantive_relations``).
    """
    llm = FakeLLMClient()
    a = _assertion(
        source_page_id="src-a",
        target_page_id="tgt-b",
        predicate=RelationPredicate.CAUSES,
        evidence_excerpts=[
            "baseline accuracy is 0.85",
            "we report run-to-run variance",
        ],
    )
    llm.script(
        PROMPT_KIND_NAME,
        _script_payload(verdicts=[{
            "relation_id": a.relation_id,
            "verdict": "contradicted",
            "confidence": 0.92,
            "reason": "evidence has no causal claim",
        }]),
    )

    source_bytes = {a.key.source_page_id: b"x" * 4096}
    records = await review_high_risk_relations(
        [a], source_bytes=source_bytes, llm=llm,
    )

    assert len(records) == 1
    rec = records[0]
    # Identity preserved (Identity Contract §2).
    assert rec.relation_id == a.relation_id
    assert rec.predicate is RelationPredicate.CAUSES
    assert rec.source_page_id == "src-a"
    assert rec.target_page_id == "tgt-b"
    # Verdict surfaces verbatim.
    assert rec.status is RelationReviewStatus.CONTRADICTED
    assert rec.confidence == pytest.approx(0.92)
    assert rec.reason  # non-empty
    # Audit fields are populated.
    assert rec.reviewer_fingerprint != ""
    assert rec.reviewed_at_ms > 0


# ---------------------------------------------------------------------------
# Test 4: reviewer total failure → all HIGH-risk UNRESOLVED, never raises
# ---------------------------------------------------------------------------


class _ExplodingLLM(FakeLLMClient):
    """FakeLLMClient that raises LLMResponseError on every call (the
    scripted queue is empty, so the parser also fails — either path
    must converge on UNRESOLVED)."""

    async def complete(
        self,
        *,
        prompt_kind: str,
        user_prompt: str,
        system_prompt: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> str:
        from src.pipeline.v7_extract.prompts.renderer import LLMResponseError

        raise LLMResponseError("relation reviewer LLM exploded")


@pytest.mark.asyncio
async def test_relation_reviewer_failure_marks_all_high_risk_unresolved() -> None:
    """Reviewer LLM fails on every retry → all HIGH-risk relations get
    UNRESOLVED. The function NEVER raises (Failure Contract §1).

    Spec §4 acceptance: "reviewer 整体失败 → 所有 HIGH-risk 标 UNRESOLVED
    （永不抛异常）". The caller still receives a ``RelationReviewRecord``
    for every input — only the status is downgraded.

    LOW-risk inputs are mixed in too; they must remain SUPPORTED even
    when the LLM is broken (they bypass the LLM entirely).
    """
    llm = _ExplodingLLM()

    high_risk = [
        _assertion(
            source_page_id="src-h1",
            target_page_id="tgt-h1",
            predicate=RelationPredicate.CAUSES,
        ),
        _assertion(
            source_page_id="src-h2",
            target_page_id="tgt-h2",
            predicate=RelationPredicate.REQUIRES,
        ),
        _assertion(
            source_page_id="src-h3",
            target_page_id="tgt-h3",
            predicate=RelationPredicate.CONTRADICTS,
        ),
    ]
    low_risk = [
        _assertion(
            source_page_id="src-l1",
            target_page_id="tgt-l1",
            predicate=RelationPredicate.REFINES,
        ),
    ]
    assertions = high_risk + low_risk

    source_bytes = {a.key.source_page_id: b"x" * 1024 for a in assertions}

    # MUST NOT raise (Failure Contract §1).
    records = await review_high_risk_relations(
        assertions, source_bytes=source_bytes, llm=llm,
    )

    # One record per input — no inputs are silently dropped.
    assert len(records) == len(assertions)
    # All HIGH-risk records are UNRESOLVED on technical failure.
    high_records = [r for r in records if r.predicate in (
        RelationPredicate.CAUSES,
        RelationPredicate.REQUIRES,
        RelationPredicate.CONTRADICTS,
    )]
    assert all(r.status is RelationReviewStatus.UNRESOLVED for r in high_records)
    # LOW-risk record keeps SUPPORTED even when the LLM is broken.
    assert records[-1].predicate is RelationPredicate.REFINES
    assert records[-1].status is RelationReviewStatus.SUPPORTED
    # Identity is preserved verbatim even on failure.
    assert {r.relation_id for r in records} == {a.relation_id for a in assertions}
    # Each HIGH-risk record carries a reason mentioning the failure.
    assert all(
        "reviewer" in r.reason or "fail" in r.reason for r in high_records
    )
    # Fingerprint + reviewed_at_ms still populated (records are valid).
    assert all(r.reviewer_fingerprint != "" for r in records)
    assert all(r.reviewed_at_ms > 0 for r in records)


# ---------------------------------------------------------------------------
# Test 5: RelationReviewRecord.relation_id matches RelationAssertion.relation_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_relation_review_record_relation_id_matches_assertion_id() -> None:
    """``RelationReviewRecord.relation_id == RelationAssertion.relation_id``
    (Identity Contract §2: the LLM never produces canonical IDs).

    The LLM fabricates a different ``relation_id`` in its response
    (``"fake-from-llm"``): the reviewer MUST ignore it and keep
    ``RelationAssertion.relation_id`` verbatim (which is the script-
    owned ``rel-<sha1>[:12]>`` identity, derived from
    ``key.canonical().relation_id()``).
    """
    a = _assertion(
        source_page_id="src-x",
        target_page_id="tgt-y",
        predicate=RelationPredicate.DEPENDS_ON,
        evidence_excerpts=["evidence 1"],
    )
    assert a.relation_id.startswith("rel-")  # sanity: script-derived
    assert a.relation_id == a.key.relation_id()

    llm = FakeLLMClient()
    # LLM fabricates a different relation_id in its response.
    llm.script(
        PROMPT_KIND_NAME,
        _script_payload(verdicts=[{
            "relation_id": "fake-from-llm",
            "verdict": "supported",
            "confidence": 0.7,
            "reason": "evidence supports",
        }]),
    )

    source_bytes = {a.key.source_page_id: b"x" * 4096}
    records = await review_high_risk_relations(
        [a], source_bytes=source_bytes, llm=llm,
    )

    assert len(records) == 1
    rec = records[0]
    # Identity is the caller's — never the LLM's.
    assert rec.relation_id == a.relation_id
    assert rec.relation_id != "fake-from-llm"


# ---------------------------------------------------------------------------
# Bonus: is_high_risk_predicate covers the spec tuple
# ---------------------------------------------------------------------------


def test_is_high_risk_predicate_matches_spec_tuple() -> None:
    """is_high_risk_predicate returns True exactly for the predicates
    in ``_HIGH_RISK_PREDICATES`` that exist in the current
    ``RelationPredicate`` enum: CAUSES / REQUIRES / CONTRADICTS /
    DEPENDS_ON / EXTENDS.

    Spec §5.1: these are the predicates that imply causation or strict
    ordering and therefore need a second-opinion reviewer pass. The
    spec also lists ``BROADER`` / ``NARROWER``; those are not yet in
    the enum (Task 23's ontology), so the module coerces them
    through ``UNRESOLVED`` and drops them from the set — when Task 23
    adds them, they automatically become HIGH-risk without an edit
    here.
    """
    high = {
        RelationPredicate.CAUSES,
        RelationPredicate.REQUIRES,
        RelationPredicate.CONTRADICTS,
        RelationPredicate.DEPENDS_ON,
        RelationPredicate.EXTENDS,
    }
    low = {
        RelationPredicate.REFINES,
        RelationPredicate.SUPPORTED_BY,
        RelationPredicate.INSTANCE_OF,
        RelationPredicate.RELATED_TO,
        RelationPredicate.SIMILAR_TO,
        RelationPredicate.CO_OCCURS_WITH,
        RelationPredicate.PAIRED_WITH,
        RelationPredicate.UNRESOLVED,
    }
    for p in high:
        assert is_high_risk_predicate(p) is True, (
            f"expected HIGH-risk for {p!r}"
        )
    for p in low:
        assert is_high_risk_predicate(p) is False, (
            f"expected LOW-risk for {p!r}"
        )


# ---------------------------------------------------------------------------
# Bonus: MAX_RELATIONS_PER_REVIEW_CALL budget is enforced
# ---------------------------------------------------------------------------


def test_max_relations_per_review_call_constant_is_twelve() -> None:
    """Spec §5.1: MAX_RELATIONS_PER_REVIEW_CALL = 12 — the reviewer
    batches HIGH-risk relations to keep the prompt under budget.

    Hard invariant (12 — slightly more than Task 35's 8 because each
    relation carries evidence_refs, not just a single title).
    """
    assert MAX_RELATIONS_PER_REVIEW_CALL == 12
    # And the prompt_kind is wired to the bundled TOML.
    assert PROMPT_KIND == "relation_reviewer"
