"""spec §11.2 11 Gate 基类 + Schema Gate (B-2.1 commit 1).

公共契约:
- ``GateVerdict`` (frozen dataclass): 11 Gate 共用的 verdict 值对象
  字段: passed / severity / reasons / blocked
- ``Gate`` (abstract 基类): name + order + check(obj, context)
- ``SchemaGate``: spec §11.2 Gate 1, 验证核心对象必填字段
- ``ProvenanceGate``: spec §11.2 Gate 2 占位 (commit 2 完整实现)

依赖 (spec §11.2 + §5):
- KnowledgeObject / Evidence / StructuredFact / Conflict / ResolutionEvent /
  KnowledgeUnit / Approval — spec §5 各自的 schema
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


# spec §11.2 Gate 输出严重等级
GateSeverity = Literal["info", "warn", "block"]


@dataclass(frozen=True)
class GateVerdict:
    """spec §11.2 Gate 输出契约。

    Attributes:
        passed:    是否通过（True=pass, False=fail/block）
        severity:  info / warn / block（block → 拒绝发布）
        reasons:   触发的检查项列表（rule 名或 violation 描述）
        blocked:   阻断发布（与 severity="block" 同步；方便 caller 快速判断）
    """

    passed: bool
    severity: GateSeverity
    reasons: tuple[str, ...] = field(default_factory=tuple)
    blocked: bool = False

    @classmethod
    def pass_(cls) -> "GateVerdict":
        return cls(passed=True, severity="info", reasons=("pass",), blocked=False)

    @classmethod
    def warn(cls, reasons: list[str]) -> "GateVerdict":
        return cls(passed=True, severity="warn", reasons=tuple(reasons), blocked=False)

    @classmethod
    def block(cls, reasons: list[str]) -> "GateVerdict":
        return cls(passed=False, severity="block", reasons=tuple(reasons), blocked=True)


class Gate:
    """spec §11.2 11 Gate 抽象基类。

    所有 Gate 必须实现 ``check(obj, context)`` 方法, 返回 ``GateVerdict``。
    默认 ``check`` 返回 pass 的占位实现 — 子类按需覆盖。
    """

    name: str = "abstract"
    order: int = 0  # spec §11.2 顺序 (1-11)

    def check(self, obj: Any, context: dict | None = None) -> GateVerdict:
        """检查 obj 是否通过此 Gate。默认 pass。"""
        return GateVerdict.pass_()


class SchemaGate(Gate):
    """spec §11.2 Gate 1: 对象符合版本化 Schema。

    检查 KnowledgeObject / Evidence / StructuredFact / Conflict /
    ResolutionEvent / KnowledgeUnit / Approval 等核心对象的必填字段。
    未知类型视为 pass（不在本 Gate 关注范围）。
    """

    name = "schema"
    order = 1

    # 各对象的必填字段表 (spec §5 各对象 schema)
    REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
        "knowledge_object": (
            "id", "type", "title", "lifecycle", "created_at", "updated_at",
        ),
        "evidence": (
            "evidence_id", "document_id", "block_id", "quote", "quote_hash", "status",
        ),
        "structured_fact": (
            "subject", "field", "value", "value_type", "status",
        ),
        "conflict": (
            "statement_a", "statement_b", "conflict_type", "context_a", "context_b",
        ),
        "resolution_event": (
            "candidate_ref", "action", "context_policy_version", "temporal_policy_version",
        ),
        "knowledge_unit": (
            "ku_id", "concept_id", "question", "title", "unit_type", "knowledge_mode", "status",
        ),
        "approval": (
            "approval_id", "operation", "target_ids", "proposed_event_id", "status",
        ),
    }

    # type(obj).__name__ → REQUIRED_FIELDS key 的映射
    _TYPE_NAME_MAP: dict[str, str] = {
        "knowledgeobject": "knowledge_object",
        "evidence": "evidence",
        "structuredfact": "structured_fact",
        "conflict": "conflict",
        "resolutionevent": "resolution_event",
        "knowledgeunit": "knowledge_unit",
        "approval": "approval",
    }

    def check(self, obj: Any, context: dict | None = None) -> GateVerdict:
        obj_type = type(obj).__name__.lower()
        type_ref = self._TYPE_NAME_MAP.get(obj_type)
        if type_ref is None:
            # 未知类型不强制校验（属于其他 Gate 关注范围）
            return GateVerdict.pass_()

        required = self.REQUIRED_FIELDS.get(type_ref, ())
        # missing = 字段不存在 OR 值为 None OR 值为空字符串
        # 空字符串也视为缺失，因为 dataclass 默认值就是空字符串，
        # 这与"必填但未提供"语义一致（spec §5 schema 拒绝空值）。
        missing = [
            f for f in required
            if not hasattr(obj, f) or getattr(obj, f) is None or getattr(obj, f) == ""
        ]

        if missing:
            reasons = [f"missing_field:{f}" for f in missing]
            return GateVerdict.block(reasons)

        return GateVerdict.pass_()


class ProvenanceGate(Gate):
    """spec §11.2 Gate 2: 能回到 Canonical Document 与 Raw Source。

    检查 4 个维度（B-2.1 commit 2 完整实现）：
    1. KnowledgeObject.evidence_refs 必填（C-0.4 引入；空 → no_evidence_refs）
    2. raw_source_hash 必填（Z-9 延后，spec §3.3 Raw Source 只读精神；
       缺 → no_raw_source_hash）
    3. Correction Record 链完整性（spec §5.1，简化：空 list → 视为通过，
       后续 task 需遍历 chain 验证）
    4. quote 在 block.content 内（spec §6 末段 + C-1 validate_evidence；
       不在内 → quote_not_in_block）

    每条独立触发 reason code；任一违例即 block。所有维度通过 hasattr 探测，
    不强制对象必须含全部字段（按需校验）。
    """

    name = "provenance"
    order = 2

    def check(self, obj: Any, context: dict | None = None) -> GateVerdict:
        reasons: list[str] = []

        # 1. KnowledgeObject.evidence_refs 字段检查（C-0.4 引入）
        if hasattr(obj, "evidence_refs"):
            if not obj.evidence_refs:
                reasons.append("no_evidence_refs")

        # 2. Raw Source 哈希检查（Z-9 延后，spec §3.3 只读精神）
        if hasattr(obj, "raw_source_hash"):
            if not obj.raw_source_hash:
                reasons.append("no_raw_source_hash")

        # 3. Correction Record 链完整性（spec §5.1）
        #    简化：correction_record_ids 为空视为通过
        #    实际实现需遍历 chain 验证（后续 task）
        #    当前不触发任何 reason code（占位实现）

        # 4. Quote 在 block.content 内（spec §6 末段 + C-1 validate_evidence）
        if hasattr(obj, "quote") and hasattr(obj, "block_content"):
            if obj.block_content and obj.quote not in obj.block_content:
                reasons.append("quote_not_in_block")

        if reasons:
            return GateVerdict.block(reasons)
        return GateVerdict.pass_()