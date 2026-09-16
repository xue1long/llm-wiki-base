"""Stage 4 reviewer for HIGH-risk topic candidates (Task 35).

Plan: ``docs/superpowers/plans/2026-09-17-v7-stage-remediation-task35-stage4-reviewer.md``

The reviewer is a Stage 4 post-processing pass over ``TopicCandidate``
output. Only HIGH-risk titles (numbers / negation / causality /
comparison / applicability) are sent to the LLM for a second opinion;
low-risk titles default to SUPPORTED without consuming any LLM quota.
The verdict vocabulary has four values:

    SUPPORTED    → keep (caller may proceed to Stage 5)
    OVERSTATED   → caller keeps but should down-weight
    CONTRADICTED → caller drops (Stage 4 ``__other__`` bucket or quality gate)
    UNRESOLVED   → technical failure or insufficient evidence

Reviewer-level failure (all ``max_retries`` attempts raise) demotes
every HIGH-risk topic to UNRESOLVED — never raises (Failure Contract §1).

F8 discipline: ``cluster_topics()`` signature is unchanged. The
reviewer is an independently-callable module
(``review_high_risk_topics(candidates, ...)``); Stage 4 caller wiring
is deferred to a follow-up Task.
"""
from __future__ import annotations

import json
import time

import pytest

from src.pipeline.v7_extract.llm_client import FakeLLMClient
from src.pipeline.v7_extract.topic_candidate import (
    TopicCandidate,
    derive_candidate_id,
)
from src.pipeline.v7_extract.topic_reviewer import (
    MAX_TOPICS_PER_REVIEW_CALL,
    PROMPT_KIND,
    TOPIC_ITEM_EXCERPT_BYTES,
    TOPIC_ITEMS_PER_CALL,
    TopicReviewInput,
    TopicReviewerVerdict,
    TopicReviewRecord,
    assess_topic_risk,
    review_high_risk_topics,
)


PROMPT_KIND_NAME = "topic_reviewer"


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _candidate(
    *,
    item_index: int,
    label: str,
    fp: str = "fp-default",
    span_hint: str = "p1",
    local_index: int = 0,
) -> TopicCandidate:
    """Build a TopicCandidate with a script-generated candidate_id."""
    return TopicCandidate(
        candidate_id=derive_candidate_id(
            item_index, local_index,
            span_hint=span_hint, item_fingerprint=fp,
        ),
        item_index=item_index,
        local_index=local_index,
        semantic_label=label,
        evidence_span_hint=span_hint,
        confidence=0.9,
    )


def _input(
    *,
    topic_id: str,
    title: str,
    items: list[str] | None = None,
) -> TopicReviewInput:
    """Build a TopicReviewInput for the reviewer."""
    return TopicReviewInput(
        topic_id=topic_id,
        title=title,
        items=items or ["item text excerpt 1"],
    )


def _script_payload(*, verdicts: list[dict]) -> str:
    """Wrap verdicts in the LLM's expected JSON envelope."""
    return json.dumps({"verdicts": verdicts})


# ---------------------------------------------------------------------------
# Test 1: enum has four values
# ---------------------------------------------------------------------------


def test_topic_review_status_enum_has_four_values() -> None:
    """The reviewer verdict vocabulary is exactly four values.

    Verifies the enum members present (4-value contract from Task 35
    spec §2 / §5). Adding / removing values is a breaking change —
    downstream callers (``extract_pilot`` etc.) will switch on this enum
    and rely on the four labelled states.
    """
    members = {v.value for v in TopicReviewerVerdict}
    assert members == {
        "supported",
        "overstated",
        "contradicted",
        "unresolved",
    }
    # str-Enum — string comparison works (JSON-friendly).
    assert TopicReviewerVerdict.SUPPORTED.value == "supported"
    assert TopicReviewerVerdict.OVERSTATED.value == "overstated"
    assert TopicReviewerVerdict.CONTRADICTED.value == "contradicted"
    assert TopicReviewerVerdict.UNRESOLVED.value == "unresolved"


# ---------------------------------------------------------------------------
# Test 2: low-risk title → LLM never invoked (Bounded Evidence)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_topic_reviewer_only_invoked_for_high_risk_title() -> None:
    """low-risk title (no numbers/negation/causality/comparison/applicability)
    → reviewer skips the LLM entirely; record defaults to SUPPORTED.

    Spec §1.2: Bounded Evidence — the LLM is only charged for HIGH-risk
    titles. LOW-risk titles default to SUPPORTED without consuming any
    LLM calls. The ``FakeLLMClient.calls`` log is the witness: zero
    entries after this call.
    """
    llm = FakeLLMClient()
    # No scripts queued — if the reviewer calls the LLM, the call would
    # return "" and likely raise LLMResponseError during parse.

    low_risk_inputs = [
        _input(topic_id="cand-aaa", title="扩句法"),
        _input(topic_id="cand-bbb", title="世界构建"),
        _input(topic_id="cand-ccc", title="角色塑造"),
    ]

    records = await review_high_risk_topics(low_risk_inputs, llm=llm)

    # All three come back as SUPPORTED with the caller-supplied topic_id.
    assert len(records) == 3
    assert [r.topic_id for r in records] == ["cand-aaa", "cand-bbb", "cand-ccc"]
    assert all(r.status is TopicReviewerVerdict.SUPPORTED for r in records)
    # LLM was NEVER called.
    assert llm.calls == []
    # reviewer's Bounded Evidence: low-risk → reason records the bypass.
    assert all("low-risk" in r.reason for r in records)


# ---------------------------------------------------------------------------
# Test 3: HIGH-risk title + LLM verdict CONTRADICTED → record is CONTRADICTED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_topic_reviewer_rejects_overstated_title() -> None:
    """HIGH-risk title "X 提高 10%" where items lack supporting evidence
    → LLM verdict CONTRADICTED → record carries CONTRADICTED + reason.

    The test deliberately scripts the LLM to reject the title so we
    exercise the verdict-mapping branch (CONTRADICTED must surface
    verbatim — caller will filter this topic out of Stage 5).
    """
    llm = FakeLLMClient()
    llm.script(
        PROMPT_KIND_NAME,
        _script_payload(verdicts=[
            {
                "topic_id": "cand-num",
                "verdict": "contradicted",
                "confidence": 0.9,
                "reason": "items do not mention 10%",
            },
        ]),
    )

    inputs = [
        _input(
            topic_id="cand-num",
            title="准确率提高 10%",
            items=[
                "本方法在测试集上表现稳定",
                "baseline 准确率约为 0.85",
            ],
        ),
    ]

    records = await review_high_risk_topics(inputs, llm=llm)

    assert len(records) == 1
    rec = records[0]
    assert rec.topic_id == "cand-num"
    assert rec.title == "准确率提高 10%"
    assert rec.status is TopicReviewerVerdict.CONTRADICTED
    assert rec.confidence == 0.9
    assert rec.reason  # non-empty
    # Identity is preserved — the script-owned topic_id is round-tripped.
    assert rec.reviewer_fingerprint != ""  # sha1-derived fingerprint present
    assert rec.reviewed_at_ms > 0  # recorded clock value


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

        raise LLMResponseError("topic reviewer LLM exploded")


@pytest.mark.asyncio
async def test_topic_reviewer_failure_marks_all_high_risk_unresolved() -> None:
    """Reviewer LLM fails on every retry → all HIGH-risk topics get
    UNRESOLVED. The function NEVER raises (Failure Contract §1).

    Spec §4 acceptance: "reviewer 整体失败 → 所有 HIGH-risk 标 UNRESOLVED
    （永不抛异常）". The caller still receives a TopicReviewRecord for
    every input — only the status is downgraded.
    """
    llm = _ExplodingLLM()

    inputs = [
        _input(topic_id="cand-1", title="准确率提高 10%"),
        _input(topic_id="cand-2", title="导致收敛变慢"),
        _input(topic_id="cand-3", title="不适用于小数据集"),
    ]

    # MUST NOT raise (Failure Contract §1).
    records = await review_high_risk_topics(inputs, llm=llm)

    # One record per input — no inputs are silently dropped.
    assert len(records) == 3
    # All HIGH-risk records are UNRESOLVED on technical failure.
    assert all(r.status is TopicReviewerVerdict.UNRESOLVED for r in records)
    # Topic_id is preserved verbatim even on failure (Identity Contract).
    assert {r.topic_id for r in records} == {"cand-1", "cand-2", "cand-3"}
    # Each record carries a reason that mentions the failure (operator triage).
    assert all("reviewer" in r.reason or "fail" in r.reason for r in records)
    # Fingerprint + reviewed_at_ms still populated (records are valid).
    assert all(r.reviewer_fingerprint != "" for r in records)
    assert all(r.reviewed_at_ms > 0 for r in records)


# ---------------------------------------------------------------------------
# Test 5: TopicReviewRecord.topic_id matches TopicCandidate identity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_topic_review_record_topic_id_matches_candidate_id() -> None:
    """TopicReviewRecord.topic_id == TopicCandidate.candidate_id (Identity
    Contract §2: the LLM never produces canonical IDs).

    The reviewer is fed ``TopicReviewInput(topic_id=<cand.candidate_id>,
    title=<cand.semantic_label>, items=...)``. The LLM's verdict
    response is parsed but the topic_id we keep is the caller-supplied
    one — even when the LLM fabricates a different topic_id in its
    output, we match verdicts to inputs by caller's topic_id only.
    """
    cand = _candidate(
        item_index=0,
        label="准确率提高 10%",
        fp="fp-article-1",
        span_hint="paragraph 2",
        local_index=0,
    )
    assert cand.candidate_id.startswith("cand-0-0-")  # sanity: script-derived

    llm = FakeLLMClient()
    # LLM fabricates a different topic_id in its response ("fake-from-llm"):
    # the reviewer MUST ignore it and keep cand.candidate_id verbatim.
    llm.script(
        PROMPT_KIND_NAME,
        _script_payload(verdicts=[
            {
                "topic_id": "fake-from-llm",
                "verdict": "supported",
                "confidence": 0.7,
                "reason": "items support title",
            },
        ]),
    )

    inputs = [
        TopicReviewInput(
            topic_id=cand.candidate_id,         # script-owned id, NOT LLM
            title=cand.semantic_label,
            items=["item excerpt one", "item excerpt two"],
        ),
    ]

    records = await review_high_risk_topics(inputs, llm=llm)

    assert len(records) == 1
    rec = records[0]
    # Identity is the caller's — never the LLM's.
    assert rec.topic_id == cand.candidate_id
    assert rec.topic_id != "fake-from-llm"
    # Title was supplied by the caller; reviewer never edits it.
    assert rec.title == cand.semantic_label


# ---------------------------------------------------------------------------
# Bonus tests: assess_topic_risk (used by caller to decide what to feed in)
# ---------------------------------------------------------------------------


def test_assess_topic_risk_detects_numbers_negation_comparison() -> None:
    """assess_topic_risk returns True for HIGH-risk patterns:
    numbers (10%, 3 倍), negation (不是/不能/不适用), causality
    (导致/因为), comparison (优于/高于), applicability (适用于).

    Spec §1.2: HIGH-risk pattern set mirrors Task 17's claim reviewer
    (consistency between stages).
    """
    high_examples = [
        "准确率提高 10%",
        "速度提升 3 倍",
        "扩大 5 倍",
        "X 优于 Y",
        "导致训练变慢",
        "由于噪声引起误差",
        "不适用于小数据集",
        "不适合实时场景",
        "这种方法不是必要的",
        "无法处理长文本",
    ]
    for title in high_examples:
        assert assess_topic_risk(title) is True, (
            f"expected HIGH-risk for {title!r}"
        )


def test_assess_topic_risk_low_risk_titles_return_false() -> None:
    """assess_topic_risk returns False for plain noun phrases — no
    numbers, no negation, no causality, no comparison, no
    applicability markers.

    Spec §1.2: low-risk title does not need a second-opinion reviewer
    call; we trust the clusterer's label.
    """
    low_examples = [
        "扩句法",
        "世界构建",
        "角色塑造",
        "叙事节奏",
        "世界观设定",
        "chapter-3 总结",
    ]
    for title in low_examples:
        assert assess_topic_risk(title) is False, (
            f"expected LOW-risk for {title!r}"
        )


# ---------------------------------------------------------------------------
# Bonus test: reviewer's MAX_TOPICS_PER_REVIEW_CALL budget is enforced
# ---------------------------------------------------------------------------


def test_max_topics_per_review_call_constant_is_eight() -> None:
    """Spec §5.1: MAX_TOPICS_PER_REVIEW_CALL = 8 — the reviewer batches
    high-risk titles to keep the prompt under the budget. Hard
    invariant; downstream prompt builders depend on this shape.
    """
    assert MAX_TOPICS_PER_REVIEW_CALL == 8
    # Sanity: alias constants are reasonable bounded-evidence defaults.
    assert TOPIC_ITEMS_PER_CALL >= 1
    assert TOPIC_ITEM_EXCERPT_BYTES > 0
    # And the prompt_kind is wired to the bundled TOML.
    assert PROMPT_KIND == "topic_reviewer"


# ---------------------------------------------------------------------------
# Bonus test: time.monotonic is NOT used — reviewed_at_ms is wall-clock-ish
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reviewed_at_ms_is_recent_wall_clock() -> None:
    """TopicReviewRecord.reviewed_at_ms is set to a wall-clock-ish
    millisecond value at the moment of review. Sanity check: it is
    within a small window of ``time.time() * 1000``.
    """
    before_ms = int(time.time() * 1000)

    llm = FakeLLMClient()
    # Low-risk input → no LLM call needed, but the record still
    # carries a timestamp.
    inputs = [_input(topic_id="cand-x", title="扩句法")]
    records = await review_high_risk_topics(inputs, llm=llm)

    after_ms = int(time.time() * 1000)
    rec = records[0]
    assert before_ms - 1000 <= rec.reviewed_at_ms <= after_ms + 1000, (
        f"reviewed_at_ms={rec.reviewed_at_ms} outside [{before_ms}, {after_ms}]"
    )