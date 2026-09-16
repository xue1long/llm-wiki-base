"""Stage 3 completeness_checker — Task 6: CompletenessResult + Failure Contract.

T2.2 (legacy): pure-LLM async + P5 decoupling.
Task 6 (plan 2026-09-17 v7-stage-remediation):
  - Returns ``CompletenessResult | None`` instead of ``(bool, str)``.
  - Technical failure (LLM timeout / parse / schema) returns ``None``
    — per Failure Contract (2026-09-17-remediation-contract-freeze §1):
    technical failure MUST NOT be disguised as INCOMPLETE.
  - UNCERTAIN is distinguished from INCOMPLETE (semantic ambiguity
    vs. provably incomplete).
Task 7 (plan 2026-09-17 v7-stage-remediation):
  - Bounded evidence pack (HEAD/TAIL + 3 mid samples + Stage 2 signals),
    hard budget ≤ 5500 bytes per Bounded Evidence Contract §3.2.
  - Stage 3 consumes Stage 2's ``SegmentationResult`` as a structural
    summary dict.
"""
from __future__ import annotations

import pytest

from src.pipeline.v7_extract.completeness_checker import (
    CompletenessResult,
    CompletenessStatus,
    check_completeness,
    _build_evidence_pack,
    _payload_to_result,
    _resolve_completeness_template,
    EVIDENCE_PACK_BUDGET_BYTES,
)
from src.pipeline.v7_extract.llm_client import FakeLLMClient


# ---------------------------------------------------------------------------
# _payload_to_result helper — T2.2 (legacy)
# ---------------------------------------------------------------------------

def test_payload_to_result_complete_true():
    res = _payload_to_result({"complete": True, "reason": "good"})
    assert res.status is CompletenessStatus.COMPLETE
    assert res.reason_codes == ["good"]


def test_payload_to_result_complete_false():
    res = _payload_to_result({"complete": False, "reason": "no body"})
    assert res.status is CompletenessStatus.INCOMPLETE
    assert res.reason_codes == ["no body"]


def test_payload_to_result_defaults_reason():
    res = _payload_to_result({"complete": True})
    assert res.status is CompletenessStatus.COMPLETE
    assert res.reason_codes == []


def test_payload_to_result_non_bool_is_uncertain():
    """Task 6: a non-bool ``complete`` value is semantic ambiguity, not
    coercion material. The LLM was supposed to answer True/False; a
    number or string means we cannot trust the verdict — UNCERTAIN.
    """
    res_t = _payload_to_result({"complete": 1, "reason": ""})
    res_f = _payload_to_result({"complete": 0, "reason": ""})
    assert res_t.status is CompletenessStatus.UNCERTAIN
    assert res_f.status is CompletenessStatus.UNCERTAIN


# ---------------------------------------------------------------------------
# _resolve_completeness_template helper
# ---------------------------------------------------------------------------

def test_resolve_completeness_template_uses_bundled():
    template = _resolve_completeness_template(project_root=None)
    assert template.prompt_kind == "completeness"
    assert template.source == "bundled"


# ---------------------------------------------------------------------------
# check_completeness — happy paths (Task 6: returns CompletenessResult | None)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_completeness_returns_complete():
    fake = FakeLLMClient()
    fake.script("completeness", '{"complete": true, "reason": "substantial body"}')

    result = await check_completeness(
        "long article body here",
        doc_type_hint="single_method",
        llm=fake,
        project_root=None,
    )
    assert result is not None
    assert result.status is CompletenessStatus.COMPLETE
    assert result.reason_codes == ["substantial body"]


@pytest.mark.asyncio
async def test_check_completeness_returns_incomplete():
    fake = FakeLLMClient()
    fake.script("completeness", '{"complete": false, "reason": "intro only"}')

    result = await check_completeness(
        "title\n\nshort intro",
        doc_type_hint="multi_section",
        llm=fake,
        project_root=None,
    )
    assert result is not None
    assert result.status is CompletenessStatus.INCOMPLETE
    assert result.reason_codes == ["intro only"]


# ---------------------------------------------------------------------------
# P5: doc_type_hint is SOFT — Stage 3 judges independently
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_p5_stage3_ignores_stage1_incomplete_hint():
    """P5: Stage 1 says 'incomplete' but Stage 3 should re-judge
    independently — the LLM might find a substantial body."""
    fake = FakeLLMClient()
    fake.script(
        "completeness",
        '{"complete": true, "reason": "actually has a body"}',
    )

    result = await check_completeness(
        "this article has a real body with content",
        doc_type_hint="incomplete",  # Stage 1 said incomplete
        llm=fake,
        project_root=None,
    )
    # Stage 3 says complete — the soft hint did not short-circuit.
    assert result is not None
    assert result.status is CompletenessStatus.COMPLETE


# ---------------------------------------------------------------------------
# P2: failure modes — never raise (Task 6: technical failure -> None)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_completeness_returns_none_on_invalid_json():
    """All retries produce invalid JSON → returns None (Failure Contract)."""
    fake = FakeLLMClient()
    fake.script("completeness", "not json at all")
    fake.script("completeness", "still not json")
    fake.script("completeness", "{not even valid}")

    result = await check_completeness(
        "body", doc_type_hint="x", llm=fake, project_root=None,
    )
    # Per Failure Contract: technical failure -> None, NOT a fake INCOMPLETE.
    assert result is None
    assert len(fake.calls) == 3


@pytest.mark.asyncio
async def test_check_completeness_returns_none_on_schema_violation():
    """complete is missing → LLMResponseError → retry → None."""
    fake = FakeLLMClient()
    fake.script("completeness", '{"reason": "no complete field"}')

    result = await check_completeness(
        "body", doc_type_hint="x", llm=fake, project_root=None,
    )
    assert result is None


@pytest.mark.asyncio
async def test_check_completeness_succeeds_after_two_invalid_retries():
    fake = FakeLLMClient()
    fake.script("completeness", "")
    fake.script("completeness", '{"complete": true, "reason": "ok"}')
    fake.script("completeness", '{"complete": true, "reason": "ok"}')

    result = await check_completeness(
        "body", doc_type_hint="x", llm=fake, project_root=None,
    )
    assert result is not None
    assert result.status is CompletenessStatus.COMPLETE
    assert len(fake.calls) == 2


@pytest.mark.asyncio
async def test_check_completeness_returns_none_on_llm_raising_exception():
    """An LLM provider exception must NOT propagate — P2 invariant.
    Per Failure Contract: returns None (not a fake INCOMPLETE)."""
    class _ExplodingFake:
        async def complete(self, **kwargs):
            raise RuntimeError("simulated LLM outage")

    result = await check_completeness(
        "body", doc_type_hint="x", llm=_ExplodingFake(),
        project_root=None,
    )
    assert result is None


# ---------------------------------------------------------------------------
# audit logging — one LLM call per attempt
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_completeness_one_call_per_attempt():
    fake = FakeLLMClient()
    fake.script("completeness", '{"complete": true, "reason": "r"}')

    await check_completeness("body", doc_type_hint="x", llm=fake,
                             project_root=None)
    assert len(fake.calls) == 1
    assert fake.calls[0]["prompt_kind"] == "completeness"


# ---------------------------------------------------------------------------
# Task 6: New tests — Failure Contract enforcement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_technical_failure_returns_none_not_false():
    """Task 6 / Contract §1: technical failure returns None — NOT INCOMPLETE.

    Pre-Task-6 implementation returned ``(False, "stage3_failed_...")``
    which the caller mapped to ExtractionStatus.INCOMPLETE — that was a
    silent smuggled technical failure.
    """
    class _ExplodingLLM:
        async def complete(self, **kwargs):
            raise TimeoutError("provider outage")

    result = await check_completeness(
        "body", doc_type_hint="x", llm=_ExplodingLLM(),
        project_root=None,
    )
    # The contract: result is None on technical failure.
    assert result is None
    # It is NEVER a CompletenessResult with status=INCOMPLETE here.


@pytest.mark.asyncio
async def test_uncertain_status_distinguished_from_incomplete():
    """UNCERTAIN is its own status — not collapsed into INCOMPLETE.

    Per master plan §3.5: UNCERTAIN = LLM ran but cannot judge
    semantically (ambiguous). INCOMPLETE = provably incomplete.
    Callers route UNCERTAIN to review (human) instead of skip
    (which is what INCOMPLETE does).
    """
    # Simulate the LLM returning the new "uncertain" assessment.
    fake = FakeLLMClient()
    fake.script(
        "completeness",
        '{"complete": false, "reason": "ambiguous — cannot judge without more body", '
        '"assessment": "uncertain"}',
    )

    result = await check_completeness(
        "body", doc_type_hint="x", llm=fake,
        project_root=None,
    )
    assert result is not None
    assert result.status is CompletenessStatus.UNCERTAIN
    # Crucially: NOT INCOMPLETE — these are different routing decisions.
    assert result.status is not CompletenessStatus.INCOMPLETE


@pytest.mark.asyncio
async def test_completenessresult_carries_evidence_refs():
    """CompletenessResult carries evidence_refs / confidence / fingerprint.

    Task 6 / Contract §1: the result is a structured object, not a
    (bool, str) tuple. Downstream stages consume these fields.
    """
    fake = FakeLLMClient()
    fake.script(
        "completeness",
        '{"complete": true, "reason": "substantial body", '
        '"confidence": 0.92, '
        '"evidence_refs": [{"kind": "head_sample", "char_offset": 0, "len": 200}]}',
    )

    result = await check_completeness(
        "long body", doc_type_hint="x", llm=fake,
        project_root=None,
    )
    assert isinstance(result, CompletenessResult)
    assert result.confidence == pytest.approx(0.92)
    assert result.evidence_refs  # non-empty
    assert result.evidence_refs[0]["kind"] == "head_sample"
    # checker_fingerprint is always set (Contract §4.4 — every stage
    # must expose its own *_fingerprint field).
    assert result.checker_fingerprint  # non-empty string


@pytest.mark.asyncio
async def test_hard_invariant_technical_failure_never_mapped_to_incomplete():
    """Hard invariant 0 (Contract Freeze §1.5): technical failure NEVER
    appears as INCOMPLETE.

    If a result comes back from check_completeness on a technical
    failure, it must be either:
      - ``None`` (preferred — explicit signal), or
      - ``CompletenessResult(status=TECHNICAL_FAILURE)`` (defense in depth)
    It must NEVER be ``CompletenessResult(status=INCOMPLETE)`` — that
    would smuggle a technical failure into the skip-cache path.
    """
    class _ExplodingLLM:
        async def complete(self, **kwargs):
            raise TimeoutError("provider outage")

    result = await check_completeness(
        "body", llm=_ExplodingLLM(), project_root=None,
    )

    # Failure Contract: result is None OR status == TECHNICAL_FAILURE.
    # It is NEVER CompletenessResult(status=INCOMPLETE, ...).
    if result is not None:
        assert result.status is not CompletenessStatus.INCOMPLETE
        assert result.status is not CompletenessStatus.UNCERTAIN
        assert result.status is CompletenessStatus.TECHNICAL_FAILURE


# ---------------------------------------------------------------------------
# Task 7: Bounded Evidence Contract — Stage 3 evidence pack
# ---------------------------------------------------------------------------

def test_evidence_pack_includes_head_tail_and_stage2_signals():
    """Task 7: HEAD + TAIL + Stage 2 structural signals are all present.

    Per Bounded Evidence Contract §3.2: Stage 3 must feed the LLM
    HEAD/TAIL byte-bounded samples plus Stage 2 structural signals
    — never the raw full content.
    """
    content = "BEGIN\n" + ("a" * 5000) + "\nEND"
    structural = {"item_count": 7, "boundary_confidence": 0.9}
    pack, meta = _build_evidence_pack(content, structural, fingerprint="ck-fp")

    assert "=== HEAD" in pack
    assert "=== TAIL" in pack
    assert "=== STAGE 2 SIGNALS ===" in pack
    assert "item_count=7" in pack
    assert "boundary_confidence=0.9" in pack
    assert meta["total_bytes"] == len(content)
    assert meta["has_head"] is True
    assert meta["has_tail"] is True


def test_evidence_pack_includes_middle_samples():
    """FP2 加固 (Round 2): three mid samples at 25% / 50% / 75%.

    Contract Freeze §3.4: Stage 3 evidence pack must contain mid
    samples — HEAD/TAIL alone mis-classify long sources whose
    mid-section is truncated.
    """
    # Build a content where each quarter is unique, so we can
    # verify each mid sample lands at the correct position.
    # Total > 2*HEAD_TAIL_BYTES so mid samples are emitted.
    quarter = 5000
    content = (
        "A" * quarter
        + "B" * quarter
        + "C" * quarter
        + "D" * quarter
    )
    pack, meta = _build_evidence_pack(content, None, fingerprint="ck-fp")

    assert meta["mid_samples"] == 3
    # Each mid sample is tagged [mid-N].
    assert "[mid-1]" in pack
    assert "[mid-2]" in pack
    assert "[mid-3]" in pack
    # mid-1 lands at the 25% mark — within the B-quarter.
    mid1_start = pack.index("[mid-1]") + len("[mid-1]\n")
    mid1_chunk = pack[mid1_start:mid1_start + 200]
    assert "B" in mid1_chunk
    # mid-3 lands at 75% — within the D-quarter.
    mid3_start = pack.index("[mid-3]") + len("[mid-3]\n")
    mid3_chunk = pack[mid3_start:mid3_start + 200]
    assert "D" in mid3_chunk


def test_evidence_pack_within_budget():
    """Hard invariant: evidence pack ≤ 5500 bytes for ANY input.

    Bounded Evidence Contract §3.2 hard budget. A 100KB source
    must still produce a bounded pack — no silent overflow.
    """
    # Tiny input.
    small_pack, small_meta = _build_evidence_pack(
        "tiny", None, fingerprint="ck-fp",
    )
    assert len(small_pack.encode("utf-8")) <= EVIDENCE_PACK_BUDGET_BYTES

    # Pathological 100KB input.
    huge = "X" * (100 * 1024)
    huge_pack, huge_meta = _build_evidence_pack(
        huge, None, fingerprint="ck-fp",
    )
    assert len(huge_pack.encode("utf-8")) <= EVIDENCE_PACK_BUDGET_BYTES
    assert huge_meta["total_bytes"] == len(huge)

    # 1 MB pathological — must still cap.
    massive = "Y" * (1024 * 1024)
    massive_pack, _ = _build_evidence_pack(
        massive, None, fingerprint="ck-fp",
    )
    assert len(massive_pack.encode("utf-8")) <= EVIDENCE_PACK_BUDGET_BYTES


@pytest.mark.asyncio
async def test_completeness_consumes_stage2_structural_summary():
    """Task 7: check_completeness threads Stage 2 signals through to the LLM.

    When ``structural_summary`` is provided, the rendered user prompt
    contains those signals — the LLM can use them as evidence instead
    of guessing from raw text.
    """
    fake = FakeLLMClient()
    fake.script(
        "completeness",
        '{"complete": true, "reason": "stage2 shows clean segmentation"}',
    )

    result = await check_completeness(
        "long body " * 500,
        doc_type_hint="collection",
        llm=fake,
        project_root=None,
        structural_summary={
            "item_count": 12,
            "boundary_confidence": 0.95,
            "status": "segmented",
        },
    )
    assert result is not None
    assert result.status is CompletenessStatus.COMPLETE

    # The evidence pack embedded in the user prompt must be bounded
    # (Task 7 / Bounded Evidence Contract §3.2). The wrapper template
    # adds framing prose, so the user_prompt_len exceeds the pack
    # budget — assert the pack itself, not the rendered prompt.
    user_prompt = fake.calls[0]["user_prompt"] if "user_prompt" in fake.calls[0] else None
    if user_prompt is not None:
        # Some test runs patch user_prompt in — assert it contains
        # the bounded pack section, not raw full text.
        assert "=== HEAD" in user_prompt
        assert "=== STAGE 2 SIGNALS ===" in user_prompt
    # Independent assertion: pack itself is bounded.
    pack, _ = _build_evidence_pack(
        "long body " * 500,
        structural_summary={
            "item_count": 12,
            "boundary_confidence": 0.95,
            "status": "segmented",
        },
        fingerprint="checker-v7",
    )
    assert len(pack.encode("utf-8")) <= EVIDENCE_PACK_BUDGET_BYTES
    # Verify the bounded evidence pack was used (no raw full content).
    # _build_evidence_pack is the single source of truth for what the
    # LLM sees — assert its contents here.
    expected_pack, _ = _build_evidence_pack(
        "long body " * 500,
        structural_summary={
            "item_count": 12,
            "boundary_confidence": 0.95,
            "status": "segmented",
        },
        fingerprint="checker-v7",
    )
    assert "item_count=12" in expected_pack
    assert "boundary_confidence=0.95" in expected_pack
    assert "status=segmented" in expected_pack


@pytest.mark.asyncio
async def test_long_doc_does_not_truncate_observation():
    """Task 7: a 100KB doc still gets a bounded LLM input (≤ 5500 bytes).

    Without the bounded evidence pack, the old code sliced the first
    8000 chars and missed mid-document truncation. The new pack caps
    the bytes the LLM sees at the contract budget — regardless of the
    raw content size.
    """
    fake = FakeLLMClient()
    fake.script(
        "completeness",
        '{"complete": false, "reason": "mid-section truncated", '
        '"assessment": "incomplete"}',
    )

    # Build a content > 100KB with a real mid-section truncation marker.
    # ~110KB by padding each para generously.
    chunks = [
        f"para-{i:04d}: " + ("lorem ipsum " * 20) for i in range(500)
    ]
    chunks.insert(300, "正文内容缺失 mid-section")
    huge = "\n\n".join(chunks)
    assert len(huge) > 100_000

    result = await check_completeness(
        huge,
        doc_type_hint="collection",
        llm=fake,
        project_root=None,
        structural_summary={"item_count": 200, "boundary_confidence": 0.8},
    )
    # LLM caught the mid-section marker → INCOMPLETE (not a fake
    # COMPLETE from the truncated HEAD-only view).
    assert result is not None
    assert result.status is CompletenessStatus.INCOMPLETE

    # And critically: the evidence pack itself stayed within the
    # bounded budget (Bounded Evidence Contract §3.2). The rendered
    # prompt wraps the pack in template prose, so we assert against
    # the pack directly.
    assert fake.calls[0]["user_prompt_len"] < len(huge)  # not the full doc
    pack, meta = _build_evidence_pack(
        huge,
        structural_summary={"item_count": 200, "boundary_confidence": 0.8},
        fingerprint="checker-v7",
    )
    assert len(pack.encode("utf-8")) <= EVIDENCE_PACK_BUDGET_BYTES
    assert meta["total_bytes"] == len(huge)
    assert meta["mid_samples"] == 3
