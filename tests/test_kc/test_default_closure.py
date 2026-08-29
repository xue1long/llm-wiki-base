"""Tests for DefaultClosure (B-3 commit 2 — spec §11.3 + §11.4).

路线 v2.2 §B-3 — 默认发布闭包 8 条件 AND 校验 + 10 硬门槛 check.

TDD coverage (5 tests):
1. ``check_default_closure(KO_with_status_verified, passing_integrity_report)`` → passed=True
2. ``check_default_closure(KO_with_status_candidate)`` → passed=False (condition 1 失败)
3. ``check_default_closure(KO_with_synthesized_no_derived_from)`` → passed=False (condition 4 失败)
4. ``check_default_closure(KO_with_integrity_report_unresolved)`` → passed=False (condition 8 失败)
5. ``check_default_closure(KO_pass_all, passing_integrity_report)`` → all checks passed

集成:
- spec §11.3 8 条件 AND 校验 (架构骨架)
  * 1. Unit.status = verified
  * 2. Concept.status = verified
  * 3. Unit.knowledge_mode 与全部可见 Claim/Fact 一致
  * 4. Synthesized: 每个 Claim 有 Provenance + derived_from 非空 + approved
  * 5. 每个可见 Claim.status = verified
  * 6. 每个支撑 Evidence.status = active
  * 7. 每个 Source Trust Profile.status = accepted
  * 8. Context Resolution != unresolved
- spec §11.4 10 硬门槛由 IntegrityGate 11 Gate 覆盖 (commit 1)
- 依赖状态快照与 IntegrityReport 缺失时 fail-closed

Ref: docs/architecture/B-2_11_Gate_design.md §4 + spec §11.3/§11.4.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.kc.integrity.orchestrator import (
    GateResult,
    IntegrityReport,
)


# ─── 测试夹具 ──────────────────────────────────────────────────────────────


@dataclass
class FakeKnowledgeObjectVerified:
    """KO-like 对象 — status=verified + 已知 mode, condition 1-3 通过."""
    id: str = "ko_verified"
    status: str = "verified"
    knowledge_mode: str = "observed"
    claim_ids: list = field(default_factory=list)
    concept_status: str = "verified"
    evidence_refs: list[str] = field(default_factory=lambda: ["ev_001"])
    evidence_statuses: list[str] = field(default_factory=lambda: ["active"])
    source_trust_statuses: list[str] = field(default_factory=lambda: ["accepted"])


@dataclass
class FakeKnowledgeObjectCandidate:
    """KO-like 对象 — status=candidate, condition 1 失败."""
    id: str = "ko_candidate"
    status: str = "candidate"
    knowledge_mode: str = "observed"
    claim_ids: list = field(default_factory=list)
    concept_status: str = "verified"
    evidence_refs: list[str] = field(default_factory=lambda: ["ev_001"])
    evidence_statuses: list[str] = field(default_factory=lambda: ["active"])
    source_trust_statuses: list[str] = field(default_factory=lambda: ["accepted"])


@dataclass
class FakeSynthesizedKOMissingDerived:
    """KO-like 对象 — synthesized 但 derived_from 为空, condition 4 失败."""
    id: str = "ko_synth_no_derived"
    status: str = "verified"
    knowledge_mode: str = "synthesized"
    claim_ids: list = field(default_factory=list)
    concept_status: str = "verified"
    evidence_refs: list[str] = field(default_factory=lambda: ["ev_001"])
    evidence_statuses: list[str] = field(default_factory=lambda: ["active"])
    source_trust_statuses: list[str] = field(default_factory=lambda: ["accepted"])
    synthesis_provenance: str = "src/prov/path"
    derived_from: list = field(default_factory=list)  # 空 → condition 4 失败
    review_status: str = "approved"


@dataclass
class FakeKOPassAll:
    """KO-like 对象 — 全部 8 条件通过 (synthesized + 完整 provenance)."""
    id: str = "ko_pass_all"
    status: str = "verified"
    knowledge_mode: str = "synthesized"
    claim_ids: list = field(default_factory=list)
    concept_status: str = "verified"
    evidence_refs: list[str] = field(default_factory=lambda: ["ev_001"])
    evidence_statuses: list[str] = field(default_factory=lambda: ["active"])
    source_trust_statuses: list[str] = field(default_factory=lambda: ["accepted"])
    synthesis_provenance: str = "src/prov/path"
    derived_from: list = field(default_factory=lambda: ["upstream_001"])
    review_status: str = "approved"


def _passing_integrity_report(object_id: str = "ko_pass") -> IntegrityReport:
    """构造一个真实存在且通过的 IntegrityReport。"""
    from src.kc.integrity.gates import GateVerdict

    gate_results = (
        GateResult(
            gate_name="schema",
            order=1,
            verdict=GateVerdict.pass_(),
            skipped=False,
        ),
    )
    return IntegrityReport(
        object_id=object_id,
        gate_results=gate_results,
        passed=True,
        blocked=False,
        warnings=(),
    )


def _integrity_report_with_unresolved() -> IntegrityReport:
    """构造一个 IntegrityReport — 含 'unresolved' ContextGate reason."""
    # 用真实 IntegrityGate, 通过 ContextGate 自然产生 unresolved
    # 这里直接 mock GateResult 简化测试
    from src.kc.integrity.gates import GateVerdict

    gate_results = (
        GateResult(
            gate_name="context",
            order=7,
            verdict=GateVerdict.block(["unresolved_context:topic_mismatch"]),
            skipped=False,
        ),
    )
    return IntegrityReport(
        object_id="ko_with_unresolved",
        gate_results=gate_results,
        passed=False,
        blocked=True,
        warnings=(),
    )


# ─── TDD 测试 ──────────────────────────────────────────────────────────────


class TestDefaultClosure:
    """spec §11.3 8 默认发布闭包条件 AND 校验."""

    def test_knowledge_object_with_status_verified_passes(self):
        """check_default_closure(KO_with_status_verified) → passed=True.

        完整最小依赖快照 + 通过的 IntegrityReport → passed=True.
        """
        from src.kc.integrity.closure import check_default_closure

        ko = FakeKnowledgeObjectVerified()
        report = check_default_closure(ko, _passing_integrity_report(ko.id))

        assert report.passed is True
        assert report.hard_gates_passed is True
        assert report.get_failed_conditions() == ()

    def test_knowledge_object_with_status_candidate_fails(self):
        """check_default_closure(KO_with_status_candidate) → passed=False (condition 1 失败)."""
        from src.kc.integrity.closure import check_default_closure

        ko = FakeKnowledgeObjectCandidate()
        report = check_default_closure(ko, _passing_integrity_report(ko.id))

        assert report.passed is False
        failed = report.get_failed_conditions()
        assert "unit_status_verified" in failed

    def test_synthesized_ko_without_derived_from_fails(self):
        """check_default_closure(KO_synthesized_no_derived_from) → passed=False (condition 4 失败)."""
        from src.kc.integrity.closure import check_default_closure

        ko = FakeSynthesizedKOMissingDerived()
        report = check_default_closure(ko, _passing_integrity_report(ko.id))

        assert report.passed is False
        failed = report.get_failed_conditions()
        assert "synthesized_full_provenance" in failed

    def test_knowledge_object_with_unresolved_context_fails(self):
        """check_default_closure(KO_with_integrity_report_unresolved) → passed=False (condition 8 失败)."""
        from src.kc.integrity.closure import check_default_closure

        ko = FakeKnowledgeObjectVerified()
        integrity_report = _integrity_report_with_unresolved()
        report = check_default_closure(ko, integrity_report)

        assert report.passed is False
        assert report.hard_gates_passed is False
        failed = report.get_failed_conditions()
        assert "context_resolution_not_unresolved" in failed

    def test_knowledge_object_pass_all(self):
        """check_default_closure(KO_pass_all) → all checks passed."""
        from src.kc.integrity.closure import check_default_closure

        ko = FakeKOPassAll()
        report = check_default_closure(ko, _passing_integrity_report(ko.id))

        assert report.passed is True
        assert report.hard_gates_passed is True
        assert report.get_failed_conditions() == ()
        # 至少有 unit_status_verified + synthesized_full_provenance 等
        assert len(report.checks) >= 2
