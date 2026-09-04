"""Knowledge Health Report (B-3 commit 4 / v2.2 重大补位 #2, spec §11 末尾 + §14 A5-8).

Public API:
    HealthReport            — 知识健康报告 (frozen dataclass)
    generate_health_report  — 生成 Health Report 的函数

集成:
- spec §11 末尾 + §14 A5-8: 知识健康报告
- quality_score: 加权平均分 (硬门槛错误权重 10, 普通 Gate 错误权重 1)
- gate_failures: 各 Gate 失败数 (dict)
- failed_sample_ids: 最多 100 个
- phase_breakdown: 各状态对象数
- v2.2 优化 #7: not_evaluable 标记 (passed_checks=0 时)

Ref: docs/architecture/B-2_11_Gate_design.md §5 + spec §11/§14 A5-8.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .closure import ClosureReport
    from .orchestrator import IntegrityReport


@dataclass(frozen=True)
class HealthReport:
    """spec §11 末尾 + §14 A5-8 知识健康报告 (frozen dataclass).

    Attributes:
        report_date:       报告生成时间 (Unix ms)
        quality_score:     加权平均分 [0.0, 1.0]
                           公式: max(0, 1 - total_weighted_errors / max(1, total_checks))
                           硬门槛错误权重 10, 普通 Gate 错误权重 1
        gate_failures:     各 Gate 失败数 (gate_name → failure_count)
        failed_sample_ids: 失败样本 ID 列表 (限 100 个)
        phase_breakdown:   各状态对象数 (status → count)
        metric_snapshots:  关键指标快照 (metric_name → value)
        total_objects:     校验的对象总数
        total_checks:      执行的 Gate check 总数 (object × gates)
        passed_checks:     通过的 check 数
        blocked_checks:    block 的 check 数
        warned_checks:     warn 的 check 数
        not_evaluable:     True if passed_checks=0 (无法评估质量)
    """

    report_date: int
    quality_score: float
    gate_failures: dict[str, int]
    failed_sample_ids: tuple[str, ...]
    phase_breakdown: dict[str, int]
    metric_snapshots: dict[str, float]
    total_objects: int
    total_checks: int
    passed_checks: int
    blocked_checks: int
    warned_checks: int
    not_evaluable: bool = False


def generate_health_report(
    integrity_reports: list["IntegrityReport"],
    closure_reports: list["ClosureReport"] | None = None,
    phase_counts: dict[str, int] | None = None,
) -> HealthReport:
    """生成 Health Report.

    Args:
        integrity_reports: 11 Gate 流水线执行报告列表
        closure_reports:   DefaultClosure 检查报告列表 (可选)
        phase_counts:      各状态对象数 (status → count, 可选)

    Returns:
        HealthReport 含 quality_score + gate_failures + 各类统计
    """
    gate_failures: dict[str, int] = {}
    failed_sample_ids: list[str] = []
    total_checks = 0
    passed_checks = 0
    blocked_checks = 0
    warned_checks = 0

    for report in integrity_reports:
        for result in report.gate_results:
            total_checks += 1
            if result.verdict.passed and not result.verdict.blocked:
                passed_checks += 1
            if result.verdict.blocked:
                blocked_checks += 1
                gate_failures[result.gate_name] = (
                    gate_failures.get(result.gate_name, 0) + 1
                )
                if len(failed_sample_ids) < 100:
                    failed_sample_ids.append(report.object_id)
            if result.verdict.severity == "warn":
                warned_checks += 1

    # closure failures (硬门槛) — 来自 DefaultClosure §11.4
    if closure_reports:
        for cr in closure_reports:
            for check in cr.checks:
                if not check.passed and check.spec_ref.startswith("§11.4"):
                    gate_name = f"closure_{check.condition_name}"
                    gate_failures[gate_name] = (
                        gate_failures.get(gate_name, 0) + 1
                    )

    # quality_score 加权计算
    # 硬门槛 (closure_*) 错误权重 10, 普通 Gate 错误权重 1
    total_weighted_errors = 0
    for name, count in gate_failures.items():
        if name.startswith("closure_"):
            total_weighted_errors += count * 10
        else:
            total_weighted_errors += count
    max_possible_errors = max(1, total_checks)
    quality_score = max(
        0.0,
        1.0 - (total_weighted_errors / max_possible_errors),
    )

    # not_evaluable 标记 (v2.2 优化 #7)
    not_evaluable = (passed_checks == 0 and total_checks > 0)

    return HealthReport(
        report_date=int(time.time() * 1000),
        quality_score=quality_score,
        gate_failures=gate_failures,
        failed_sample_ids=tuple(failed_sample_ids),
        phase_breakdown=phase_counts or {},
        metric_snapshots={},
        total_objects=len(integrity_reports),
        total_checks=total_checks,
        passed_checks=passed_checks,
        blocked_checks=blocked_checks,
        warned_checks=warned_checks,
        not_evaluable=not_evaluable,
    )
