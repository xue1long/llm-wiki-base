"""Stage 3 completeness_checker — Task 6: CompletenessResult + Failure Contract.

T2.2 (legacy): pure-LLM async + P5 decoupling.
Task 6 (plan 2026-09-17 v7-stage-remediation):
  - Returns ``CompletenessResult | None`` instead of ``(bool, str)``.
  - Technical failure (LLM timeout / parse / schema) returns ``None``
    — per Failure Contract (2026-09-17-remediation-contract-freeze §1):
    technical failure MUST NOT be disguised as INCOMPLETE.
  - UNCERTAIN is distinguished from INCOMPLETE (semantic ambiguity
    vs. provably incomplete).
"""
from __future__ import annotations

import pytest

from src.pipeline.v7_extract.completeness_checker import (
    CompletenessResult,
    CompletenessStatus,
    check_completeness,
    _payload_to_result,
    _resolve_completeness_template,
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
