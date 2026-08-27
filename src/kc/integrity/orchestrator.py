"""spec §11.2 11 Gate 流水线 orchestrator (B-3 commit 1).

Public API:
    GateResult      — 单个 Gate 的执行结果 (frozen dataclass)
    IntegrityReport — 11 Gate 流水线执行报告 (frozen dataclass)
    IntegrityGate   — 11 Gate 流水线 orchestrator (按 spec §11.2 顺序 1-11 执行)

集成:
- 11 Gate 按 spec §11.2 顺序 (Schema → Provenance → Mode → Evidence
  → Identity → Granularity → Context → Temporal → Conflict → Relation
  → Retrieval) 依次执行
- 任一 Gate block → 标记 blocked (fail-closed)
- Gate 异常 → 视为 block (gate_exception:<name>:<ExceptionType>)
- warn → 继续执行 + 收集 reasons (不阻断发布)
- B-3 commit 2: IntegrityGate.check_default_closure() 串联 8 闭包条件 AND 校验

Ref: docs/architecture/B-2_11_Gate_design.md §3-4 + spec §11.2.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .gates import (
    ConflictGate,
    ContextGate,
    EvidenceGate,
    Gate,
    GateVerdict,
    GranularityGate,
    IdentityGate,
    ModeGate,
    ProvenanceGate,
    RelationGate,
    RetrievalGate,
    SchemaGate,
    TemporalGate,
)

if TYPE_CHECKING:
    from .closure import ClosureReport


@dataclass(frozen=True)
class GateResult:
    """单个 Gate 的执行结果.

    Attributes:
        gate_name: Gate 名称 (如 "schema", "evidence" 等)
        order:     Gate 顺序 (spec §11.2 顺序 1-11)
        verdict:   Gate 返回的 GateVerdict
        skipped:   是否跳过 (默认 False; 当前实现所有 Gate 都执行,
                   保留 skipped 字段以便后续扩展 helper 跳过逻辑)
    """

    gate_name: str
    order: int
    verdict: GateVerdict
    skipped: bool = False


@dataclass(frozen=True)
class IntegrityReport:
    """11 Gate 流水线执行报告.

    Attributes:
        object_id:     被校验对象的 id (ku_id / id / "<unknown>")
        gate_results:  11 个 GateResult (顺序: spec §11.2 顺序 1-11)
        passed:        全部 Gate 通过 (True = 全部 pass / warn; False = 至少 1 block)
        blocked:       任一 Gate block (True = 至少 1 block)
        warnings:      所有 warn reasons 汇总 (来自非 block 的 Gate)
    """

    object_id: str
    gate_results: tuple[GateResult, ...]
    passed: bool
    blocked: bool
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def get_blocking_reasons(self) -> tuple[str, ...]:
        """获取所有 block reasons (来自 blocked 的 Gate).

        Returns:
            所有 block 级别的 reason 列表 (含 gate_exception: 异常 reason)
        """
        reasons: list[str] = []
        for result in self.gate_results:
            if result.verdict.blocked:
                reasons.extend(result.verdict.reasons)
        return tuple(reasons)

    def get_warnings(self) -> tuple[str, ...]:
        """获取所有 warn reasons (来自非 block 的 Gate).

        Returns:
            所有 warn 级别的 reason 列表 (severity=warn 但 blocked=False)
        """
        reasons: list[str] = []
        for result in self.gate_results:
            if not result.verdict.blocked and result.verdict.severity == "warn":
                reasons.extend(result.verdict.reasons)
        return tuple(reasons)


class IntegrityGate:
    """spec §11.2 11 Gate 流水线 orchestrator.

    按 spec §11.2 顺序 (1-11) 依次执行:
        Schema → Provenance → Mode → Evidence → Identity → Granularity
        → Context → Temporal → Conflict → Relation → Retrieval

    关键特性:
        - 任一 Gate block → 立即标记 blocked (fail-closed)
        - warn → 继续执行 + 收集 reasons (不阻断)
        - Gate 异常 → 视为 block (gate_exception:<name>:<ExceptionType>)
        - 简化: 当前实现不立即停止, 继续执行其他 Gate 收集完整报告
          (实际部署可选 early return)

    用法:
        gate = IntegrityGate()
        report = gate.check(obj, context={...})
        if report.blocked:
            # 拒绝发布
            ...
        elif report.warnings:
            # warn 不阻断, 记录原因
            ...
    """

    def __init__(self) -> None:
        """初始化 11 Gate (按 spec §11.2 顺序).

        各 Gate 实例化时使用默认参数 (registry=None, semantic_checker=None,
        classifier=None), 满足简化内联判定路径.
        完整部署可注入依赖 (ConflictGate.classifier, RelationGate.registry,
        RetrievalGate.semantic_checker, EvidenceGate.semantic_checker).
        """
        self._gates: tuple[Gate, ...] = (
            SchemaGate(),
            ProvenanceGate(),
            ModeGate(),
            EvidenceGate(),
            IdentityGate(),
            GranularityGate(),
            ContextGate(),
            TemporalGate(),
            ConflictGate(),
            RelationGate(),
            RetrievalGate(),
        )

    def check(self, obj: Any, context: dict | None = None) -> IntegrityReport:
        """依次执行 11 Gate, 收集结果.

        Args:
            obj:     被校验对象 (KnowledgeObject / WikiPage / Claim / etc.)
            context: 可选 context dict (用于 Gate 之间的状态传递,
                     如 query_time, evidences, relations 等)

        Returns:
            IntegrityReport 含 11 Gate 的执行结果 + passed/blocked/warnings 摘要
        """
        results: list[GateResult] = []
        blocked = False

        for gate in self._gates:
            try:
                verdict = gate.check(obj, context)
            except Exception as e:
                # Gate 异常 → 视为 block (fail-closed)
                verdict = GateVerdict.block(
                    [f"gate_exception:{gate.name}:{type(e).__name__}"]
                )

            result = GateResult(
                gate_name=gate.name,
                order=gate.order,
                verdict=verdict,
                skipped=False,
            )
            results.append(result)

            if verdict.blocked:
                blocked = True
                # 简化: 不立即停止, 继续执行其他 Gate 收集完整报告
                # 实际部署可选 early return (本任务聚焦架构完整性)

        passed = not blocked and all(r.verdict.passed for r in results)

        # 收集所有 warn reasons (来自非 block 的 Gate)
        warnings: list[str] = []
        for r in results:
            if not r.verdict.blocked and r.verdict.severity == "warn":
                warnings.extend(r.verdict.reasons)

        return IntegrityReport(
            object_id=(
                getattr(obj, "ku_id", None)
                or getattr(obj, "id", "<unknown>")
            ),
            gate_results=tuple(results),
            passed=passed,
            blocked=blocked,
            warnings=tuple(warnings),
        )

    # ------------------------------------------------------------------
    # B-3 commit 2 集成: check_default_closure()
    # ------------------------------------------------------------------

    def check_default_closure(
        self,
        obj: Any,
        integrity_report: "IntegrityReport | None" = None,
    ) -> "ClosureReport":
        """spec §11.3 8 默认发布闭包条件 AND 校验 (串联 11 Gate 结果).

        Args:
            obj:             KnowledgeObject / WikiPage / 待校验对象
            integrity_report: 11 Gate 流水线结果 (默认先执行 self.check() 获取)

        Returns:
            ClosureReport 含 8 条件 + 10 硬门槛 check 结果

        Notes:
            - 默认会先执行 self.check(obj) 获取 integrity_report
              (如已提供则跳过, 避免重复执行 11 Gate)
            - 简化实现: 8 条件骨架已落地, 完整 data model 集成留 B-3.x 后续
        """
        from .closure import check_default_closure

        if integrity_report is None:
            integrity_report = self.check(obj)
        return check_default_closure(obj, integrity_report)
