"""spec §11.3 8 默认发布闭包条件 + §11.4 10 硬门槛 (B-3 commit 2).

Public API:
    ClosureCheck   — 单个 check 的结果 (frozen dataclass)
    ClosureReport  — 8 条件 + 10 硬门槛 check 完整报告 (frozen dataclass)
    check_default_closure(obj, integrity_report=None) → ClosureReport

集成:
- spec §11.3 8 默认发布闭包条件 AND 校验 (架构骨架):
  * 1. Unit.status = verified
  * 2. Concept.status = verified
  * 3. Unit.knowledge_mode 与全部可见 Claim/Fact 一致
  * 4. Synthesized: 每个 Claim 有 Provenance + derived_from 非空 + approved
  * 5. 每个可见 Claim.status = verified
  * 6. 每个支撑 Evidence.status = active
  * 7. 每个 Source Trust Profile.status = accepted
  * 8. Context Resolution != unresolved
- spec §11.4 10 硬门槛由 IntegrityGate 11 Gate 覆盖 (B-3 commit 1),
  本模块不重复实现 — 通过 IntegrityReport.gate_failures 收集
- 发布闭包 fail-closed：依赖状态快照或 IntegrityReport 缺失时拒绝发布

Ref: docs/architecture/B-2_11_Gate_design.md §4 + spec §11.3/§11.4.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .orchestrator import IntegrityReport


@dataclass(frozen=True)
class ClosureCheck:
    """spec §11.3 8 条件 + §11.4 10 硬门槛 check 单项结果.

    Attributes:
        condition_name: 条件名 (如 'unit_status_verified' / 'synthesized_full_provenance')
        spec_ref:       spec 引用 ('§11.3.1' / '§11.4.6')
        passed:         是否通过
        details:        详细信息 (用于 debug)
    """

    condition_name: str
    spec_ref: str
    passed: bool
    details: str = ""


@dataclass(frozen=True)
class ClosureReport:
    """8 条件 + 10 硬门槛 check 完整报告.

    Attributes:
        object_id:         被校验对象的 id
        checks:            8 条件 (可能多) + 10 硬门槛 (已通过 IntegrityGate 覆盖)
        passed:            全部 8 条件 AND 且 hard_gates_passed
        hard_gates_passed: 全部 10 硬门槛 (由 IntegrityGate 11 Gate 覆盖, 本报告标注汇总)
    """

    object_id: str
    checks: tuple[ClosureCheck, ...]
    passed: bool
    hard_gates_passed: bool

    def get_failed_conditions(self) -> tuple[str, ...]:
        """获取所有失败的 condition_name (§11.3 + §11.4 全部)."""
        return tuple(c.condition_name for c in self.checks if not c.passed)

    def get_failed_hard_gates(self) -> tuple[str, ...]:
        """获取所有失败的 §11.4 硬门槛 condition_name."""
        return tuple(
            c.condition_name for c in self.checks
            if not c.passed and c.spec_ref.startswith("§11.4")
        )


def check_default_closure(
    obj: Any,
    integrity_report: IntegrityReport | None = None,
) -> ClosureReport:
    """spec §11.3 8 默认发布闭包条件 AND 校验.

    Args:
        obj:             KnowledgeObject / WikiPage / 待校验对象
        integrity_report: 11 Gate 流水线结果 (用于硬门槛和 condition 8)

    Returns:
        ClosureReport 含 8 条件 + 10 硬门槛 check 结果

    缺失依赖一律 fail-closed，并通过 ``details`` 返回稳定 reason code。
    """
    checks: list[ClosureCheck] = []

    # 1. Unit.status = verified
    unit_status_verified = getattr(obj, "status", None) == "verified"
    checks.append(ClosureCheck(
        condition_name="unit_status_verified",
        spec_ref="§11.3.1",
        passed=unit_status_verified,
        details="" if unit_status_verified else "dependency_not_publishable",
    ))

    # 2. Concept.status = verified
    concept_status_verified = getattr(obj, "concept_status", None) == "verified"
    checks.append(ClosureCheck(
        condition_name="concept_status_verified",
        spec_ref="§11.3.2",
        passed=concept_status_verified,
        details="" if concept_status_verified else "dependency_not_publishable",
    ))

    # 3. Unit.knowledge_mode 与全部可见 Claim/Fact 一致
    knowledge_mode = getattr(obj, "knowledge_mode", None)
    claim_ids = getattr(obj, "claim_ids", None)
    claim_modes = getattr(obj, "claim_modes", None)
    mode_consistent = (
        knowledge_mode is not None
        and claim_ids is not None
        and (
            not claim_ids
            or (
                claim_modes is not None
                and len(claim_modes) == len(claim_ids)
                and all(mode == knowledge_mode for mode in claim_modes)
            )
        )
    )
    checks.append(ClosureCheck(
        condition_name="unit_knowledge_mode_consistent",
        spec_ref="§11.3.3",
        passed=mode_consistent,
        details="" if mode_consistent else "dependency_not_publishable",
    ))

    # 4. Synthesized: Provenance + derived_from + approved
    if hasattr(obj, "knowledge_mode") and obj.knowledge_mode == "synthesized":
        has_provenance = (
            hasattr(obj, "synthesis_provenance") and obj.synthesis_provenance
        )
        has_derived_from = (
            hasattr(obj, "derived_from") and obj.derived_from
        )
        has_approved = (
            hasattr(obj, "review_status") and obj.review_status == "approved"
        )
        passed = bool(has_provenance and has_derived_from and has_approved)
        checks.append(ClosureCheck(
            condition_name="synthesized_full_provenance",
            spec_ref="§11.3.4",
            passed=passed,
            details="" if passed else "missing_provenance",
        ))

    # 5. 每个 Claim.status = verified
    claim_statuses = getattr(obj, "claim_statuses", None)
    claims_verified = (
        claim_ids is not None
        and (
            not claim_ids
            or (
                claim_statuses is not None
                and len(claim_statuses) == len(claim_ids)
                and all(status == "verified" for status in claim_statuses)
            )
        )
    )
    checks.append(ClosureCheck(
        condition_name="all_claim_status_verified",
        spec_ref="§11.3.5",
        passed=claims_verified,
        details="" if claims_verified else "dependency_not_publishable",
    ))

    # 6. 每个 Evidence.status = active
    evidence_refs = getattr(obj, "evidence_refs", None)
    evidence_statuses = getattr(obj, "evidence_statuses", None)
    has_evidence = bool(evidence_refs)
    evidence_active = (
        has_evidence
        and evidence_statuses is not None
        and len(evidence_statuses) == len(evidence_refs)
        and all(status == "active" for status in evidence_statuses)
    )
    checks.append(ClosureCheck(
        condition_name="all_evidence_status_active",
        spec_ref="§11.3.6",
        passed=evidence_active,
        details=(
            "" if evidence_active
            else "missing_evidence" if not has_evidence
            else "dependency_not_publishable"
        ),
    ))

    # 7. 每个 Source Trust Profile.status = accepted
    source_trust_statuses = getattr(obj, "source_trust_statuses", None)
    source_trust_accepted = bool(source_trust_statuses) and all(
        status == "accepted" for status in source_trust_statuses
    )
    checks.append(ClosureCheck(
        condition_name="all_source_trust_accepted",
        spec_ref="§11.3.7",
        passed=source_trust_accepted,
        details="" if source_trust_accepted else "dependency_not_publishable",
    ))

    # 8. Context Resolution != unresolved (依赖 integrity_report)
    if integrity_report is not None:
        has_unresolved = any(
            "unresolved" in reason
            for r in integrity_report.gate_results
            for reason in r.verdict.reasons
        )
        checks.append(ClosureCheck(
            condition_name="context_resolution_not_unresolved",
            spec_ref="§11.3.8",
            passed=not has_unresolved,
            details="" if not has_unresolved else "dependency_not_publishable",
        ))
    else:
        checks.append(ClosureCheck(
            condition_name="context_resolution_not_unresolved",
            spec_ref="§11.3.8",
            passed=False,
            details="missing_integrity_report",
        ))

    hard_gates_passed = bool(
        integrity_report and integrity_report.passed and not integrity_report.blocked
    )
    passed = hard_gates_passed and all(c.passed for c in checks)

    return ClosureReport(
        object_id=(
            getattr(obj, "ku_id", None)
            or getattr(obj, "id", "<unknown>")
        ),
        checks=tuple(checks),
        passed=passed,
        hard_gates_passed=hard_gates_passed,
    )
