"""Tests for KnowledgeUnit dataclass + identity_key + split/merge helpers (A-1 / G3).

路线 v2.2 §A-1 KnowledgeUnit 单独建模 (spec §4.2 + §5.4 + §9 Identity Resolution):
- spec §4.2: KU 是三层粒度的中层 (Entity/Concept → KU → Claim/StructuredFact)
- spec §5.4: KU schema 完整字段 (8 unit_type + 6 status + 8 字段组)
- spec §5 id-v1 identity_key 算法 (sha256 规范化字段)
- spec §4.4: 拆分/合并条件判定 (should_split_ku / should_merge_ku)
- spec §5.11: ResolutionEvent 含 re-play 必需字段

TDD coverage (5 tests):
1. KnowledgeUnit 构造 + identity_key 确定性 (同输入同输出)
2. KnowledgeObject 加 ku_id 字段 back-compat 默认 None (不破坏既有)
3. should_split_ku(claim_count=2, internal_questions=2) -> True (spec §4.4 拆分条件 1)
4. should_merge_ku(context_match=True, same_question=True) -> True (spec §4.4 合并条件)
5. ResolutionEvent 写入拆分/合并决策 (含 spec §4.4 必填字段)
"""
from __future__ import annotations


# These imports intentionally fail before implementation is added — TDD red phase.
from src.kc.domain import (
    KnowledgeUnit,
    compute_ku_identity_key,
    should_split_ku,
    should_merge_ku,
    ResolutionEvent,
)
from src.knowledge.core.object import KnowledgeObject


# ─── Test 1: KnowledgeUnit 构造 + identity_key 确定性 ─────────────────


def test_knowledge_unit_construction_and_identity_key_is_deterministic():
    """Same input fields → same identity_key (sha256 deterministic, id-v1 prefix)."""
    ku_a = KnowledgeUnit(
        ku_id="ku-001",
        concept_id="concept-rag",
        question="What is retrieval-augmented generation?",
        title="RAG Definition",
        unit_type="definition",
        knowledge_mode="observed",
        context_id="ctx-prod",
        validity_id="val-2026",
        confidence=0.95,
        status="verified",
    )
    ku_b = KnowledgeUnit(
        ku_id="ku-002",  # different ku_id, but identity-bearing fields identical
        concept_id="concept-rag",
        question="What is retrieval-augmented generation?",
        title="RAG Definition (dup)",
        unit_type="definition",
        knowledge_mode="observed",
        context_id="ctx-prod",
        validity_id="val-2026",
        confidence=0.95,
        status="verified",
    )

    # identity_key derived from fields (not ku_id) — same input → same output
    assert ku_a.identity_key == ku_b.identity_key
    assert ku_a.identity_key.startswith("id-v1:")

    # And different inputs must yield different keys (spec §5 collision-free)
    ku_c = KnowledgeUnit(
        ku_id="ku-003",
        concept_id="concept-rag",
        question="What is retrieval-augmented generation?",
        title="RAG Definition",
        unit_type="definition",
        knowledge_mode="synthesized",  # different knowledge_mode
        context_id="ctx-prod",
        validity_id="val-2026",
        confidence=0.95,
        status="verified",
    )
    assert ku_c.identity_key != ku_a.identity_key

    # Direct computation must match the property
    direct_key = compute_ku_identity_key(
        concept_id="concept-rag",
        question="What is retrieval-augmented generation?",
        unit_type="definition",
        knowledge_mode="observed",
        context_id="ctx-prod",
        validity_id="val-2026",
    )
    assert ku_a.identity_key == direct_key


# ─── Test 2: KnowledgeObject 加 ku_id 字段 back-compat 默认 None ──────


def test_knowledge_object_ku_id_field_back_compat_default_none():
    """KnowledgeObject adds ku_id field with default None (zero-impact on existing
    construction sites — spec §5.4 KO-KU 1:N 反向引用)."""
    # Existing-style construction without ku_id — must default to None
    from src.knowledge.core.object import KnowledgeType, LifecycleState, Provenance

    prov = Provenance(source_path="/tmp/source.md", ingested_at=1000)
    ko = KnowledgeObject(
        id="ko-001",
        type=KnowledgeType.CONCEPT,
        title="Test Concept",
        content="Body content here.",
        lifecycle=LifecycleState.ACTIVE,
        confidence=0.9,
        provenance=prov,
    )
    # Back-compat: new field defaults to None (no breaking change)
    assert ko.ku_id is None

    # New-style construction with ku_id explicit
    ko_with_ku = KnowledgeObject(
        id="ko-002",
        type=KnowledgeType.CONCEPT,
        title="Concept linked to KU",
        content="Body content.",
        lifecycle=LifecycleState.ACTIVE,
        confidence=0.9,
        provenance=prov,
        ku_id="ku-001",
    )
    assert ko_with_ku.ku_id == "ku-001"


# ─── Test 3: should_split_ku(claim_count=2, internal_questions=2) -> True ─


def test_should_split_ku_internal_questions_gt_one_returns_true():
    """spec §4.4 拆分条件 1: 内部 Claim 回答两个不同问题 (internal_questions > 1)
    即应拆分 — 这是 H-5 ADR 默认 choice_3 (精准拆分) 的核心依据."""
    # internal_questions=2 means Claims cover 2 different questions
    assert should_split_ku(claim_count=2, internal_questions=2) is True

    # Single question, same platform/audience, overlapping time, full correlation
    # → no split
    assert (
        should_split_ku(
            claim_count=4,
            internal_questions=1,
            same_platform=True,
            same_audience=True,
            time_ranges_overlap=True,
            update_correlation=1.0,
        )
        is False
    )


# ─── Test 4: should_merge_ku 合并条件 (spec §4.4 + Identity Resolution) ─


def test_should_merge_ku_same_question_and_context_compatible():
    """spec §4.4 合并条件: 同问题 + Context 兼容 + 时间兼容 + 独立可检 + 不隐冲突.
    满足全部条件才合并 — Identity Resolution 走这条路径合并重复 KU."""
    # All conditions met → merge
    assert (
        should_merge_ku(
            same_question=True,
            context_compatible=True,
            time_compatible=True,
            can_stay_independent=True,
            no_hidden_conflict=True,
        )
        is True
    )

    # Different question → never merge
    assert (
        should_merge_ku(
            same_question=False,
            context_compatible=True,
            time_compatible=True,
            can_stay_independent=True,
            no_hidden_conflict=True,
        )
        is False
    )

    # Hidden conflict blocks merge even if everything else aligned
    assert (
        should_merge_ku(
            same_question=True,
            context_compatible=True,
            time_compatible=True,
            can_stay_independent=True,
            no_hidden_conflict=False,
        )
        is False
    )


# ─── Test 5: ResolutionEvent 写入拆分/合并决策 ──────────────────────


def test_resolution_event_records_split_decision():
    """spec §4.4 + §5.11 ResolutionEvent 含 re-play 必需字段
    (action / reason_codes / context_policy_version / temporal_policy_version /
    model / model_version / confidence / approval_id).

    H-5 ADR choice_3 决策的事件样例：拆分一个内部多个问题的 KU."""
    event = ResolutionEvent(
        event_id="rev-001",
        candidate_ref=("knowledge_unit", "ku-existing-001"),
        candidate_set=(
            ("knowledge_unit", "ku-existing-001", 1.0),
            ("knowledge_unit", "ku-existing-002", 0.92),
        ),
        action="split",
        reason_codes=("internal_questions_gt_1", "time_ranges_overlap_false"),
        context_policy_version="id-v1",
        temporal_policy_version="id-v1",
        model="unknown",
        model_version="n/a",
        confidence=0.88,
        approval_id="hu-review-2026-08-26",
        created_at=1_700_000_000_000,
    )

    # Spec §5.11 mandatory fields all present
    assert event.event_id == "rev-001"
    assert event.action == "split"
    assert "internal_questions_gt_1" in event.reason_codes
    assert event.context_policy_version == "id-v1"
    assert event.temporal_policy_version == "id-v1"
    assert event.confidence == 0.88
    # Action is one of the resolution action literals (spec §5.11)
    assert event.action in {
        "create", "merge", "update", "link", "conflict",
        "supersede", "quarantine", "split", "keep_separate",
    }
    # candidate_set is the full set used for the decision (replayable)
    assert len(event.candidate_set) == 2
    assert event.candidate_set[0][0] == "knowledge_unit"
