"""Tests for Knowledge Health Report (B-3 commit 4 — v2.2 重大补位 #2).

路线 v2.2 §B-3 — spec §11 末尾 + §14 A5-8: 知识健康报告.

TDD coverage (3 tests):
1. ``generate_health_report(integrity_reports_with_blocked)`` →
   quality_score < 1.0, gate_failures 含 'evidence'
2. ``generate_health_report(empty_list)`` →
   not_evaluable=False, total_objects=0
3. ``generate_health_report(integrity_reports_with_all_passed)`` →
   quality_score=1.0, not_evaluable=False

集成:
- spec §11 末尾 + §14 A5-8: 知识健康报告
- quality_score: 加权平均分 (硬门槛错误权重 10, 普通 Gate 错误权重 1)
- gate_failures: 各 Gate 失败数 (dict)
- failed_sample_ids: 最多 100 个
- phase_breakdown: 各状态对象数
- v2.2 优化 #7: not_evaluable 标记 (passed_checks=0 时)

Ref: docs/architecture/B-2_11_Gate_design.md §5 + spec §11/§14 A5-8 + v2.2 重大补位 #2.
"""
from __future__ import annotations



from src.kc.integrity.gates import GateVerdict
from src.kc.integrity.orchestrator import (
    GateResult,
    IntegrityReport,
)


# ─── 测试夹具 ──────────────────────────────────────────────────────────────


def _make_gate_result(
    gate_name: str,
    order: int,
    blocked: bool,
    severity: str = "info",
    reasons: tuple = (),
) -> GateResult:
    """构造一个 GateResult — blocked 控制 passed/blocked."""
    if blocked:
        verdict = GateVerdict(
            passed=False,
            severity="block",
            reasons=reasons or (f"{gate_name}_error",),
            blocked=True,
        )
    else:
        verdict = GateVerdict(
            passed=True,
            severity=severity,
            reasons=("pass",),
            blocked=False,
        )
    return GateResult(
        gate_name=gate_name,
        order=order,
        verdict=verdict,
        skipped=False,
    )


def _make_integrity_report(
    object_id: str,
    blocked_gates: list = None,
    warned_gates: list = None,
) -> IntegrityReport:
    """构造一个 IntegrityReport — 模拟 11 Gate 的执行结果.

    Args:
        object_id:    对象 id
        blocked_gates: block 的 gate name 列表 (如 ['evidence', 'schema'])
        warned_gates:  warn 的 gate name 列表 (如 ['relation'])
    """
    blocked_gates = blocked_gates or []
    warned_gates = warned_gates or []

    gate_results = []
    for order, name in enumerate(
        ["schema", "provenance", "mode", "evidence", "identity",
         "granularity", "context", "temporal", "conflict", "relation", "retrieval"],
        start=1,
    ):
        if name in blocked_gates:
            gate_results.append(
                _make_gate_result(name, order, blocked=True, reasons=(f"{name}_reason",))
            )
        elif name in warned_gates:
            gate_results.append(
                _make_gate_result(
                    name, order, blocked=False,
                    severity="warn",
                    reasons=(f"{name}_warn_reason",),
                )
            )
        else:
            gate_results.append(_make_gate_result(name, order, blocked=False))

    blocked = any(r.verdict.blocked for r in gate_results)
    passed = not blocked and all(r.verdict.passed for r in gate_results)
    warnings = tuple(
        reason
        for r in gate_results
        if not r.verdict.blocked and r.verdict.severity == "warn"
        for reason in r.verdict.reasons
    )

    return IntegrityReport(
        object_id=object_id,
        gate_results=tuple(gate_results),
        passed=passed,
        blocked=blocked,
        warnings=warnings,
    )


# ─── TDD 测试 ──────────────────────────────────────────────────────────────


class TestKnowledgeHealthReport:
    """spec §11 末尾 + §14 A5-8 知识健康报告 (v2.2 重大补位 #2)."""

    def test_health_report_with_blocked_reduces_quality_score(self):
        """generate_health_report(integrity_reports_with_blocked) →
        quality_score < 1.0, gate_failures 含 'evidence'.
        """
        from src.kc.integrity.health import generate_health_report

        reports = [
            _make_integrity_report("ko_001", blocked_gates=["evidence"]),
            _make_integrity_report("ko_002", blocked_gates=["evidence", "schema"]),
        ]

        health = generate_health_report(reports)

        # quality_score < 1.0 (有 blocked gate → 降低分数)
        assert health.quality_score < 1.0
        # gate_failures 含 'evidence'
        assert "evidence" in health.gate_failures
        # failed_sample_ids 含 object_id (限 100 个)
        assert "ko_001" in health.failed_sample_ids
        assert "ko_002" in health.failed_sample_ids
        # blocked_checks > 0
        assert health.blocked_checks > 0
        # not_evaluable=False (有 passed_checks)
        assert health.not_evaluable is False

    def test_health_report_empty_list_returns_zero(self):
        """generate_health_report(empty_list) →
        not_evaluable=False, total_objects=0.
        """
        from src.kc.integrity.health import generate_health_report

        health = generate_health_report([])

        assert health.total_objects == 0
        assert health.total_checks == 0
        assert health.passed_checks == 0
        assert health.blocked_checks == 0
        assert health.not_evaluable is False  # 空 list 不算 unevaluable
        # quality_score 默认 1.0 (无 errors)
        assert health.quality_score == 1.0
        assert health.gate_failures == {}

    def test_health_report_all_passed_returns_one(self):
        """generate_health_report(integrity_reports_with_all_passed) →
        quality_score=1.0, not_evaluable=False.
        """
        from src.kc.integrity.health import generate_health_report

        reports = [
            _make_integrity_report("ko_pass_001"),
            _make_integrity_report("ko_pass_002"),
            _make_integrity_report("ko_pass_003"),
        ]

        health = generate_health_report(reports)

        # 全部 pass → quality_score=1.0
        assert health.quality_score == 1.0
        assert health.total_objects == 3
        assert health.total_checks == 33  # 3 reports × 11 gates
        assert health.blocked_checks == 0
        assert health.passed_checks == 33
        # not_evaluable=False (有 passed_checks)
        assert health.not_evaluable is False
        # gate_failures 空
        assert health.gate_failures == {}
