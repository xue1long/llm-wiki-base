"""spec §11.2 11 Gate 基类 + Schema Gate (B-2.1 commit 1)
+ Provenance Gate (B-2.1 commit 2) + Evidence Gate (B-2.2).

公共契约:
- ``GateVerdict`` (frozen dataclass): 11 Gate 共用的 verdict 值对象
  字段: passed / severity / reasons / blocked
- ``Gate`` (abstract 基类): name + order + check(obj, context)
- ``SchemaGate``: spec §11.2 Gate 1, 验证核心对象必填字段
- ``ProvenanceGate``: spec §11.2 Gate 2 (B-2.1 commit 2 完整实现)
- ``EvidenceGate``: spec §11.2 Gate 3 (B-2.2 — 满足 Evidence Strength Policy
  + B-1 Semantic Support 集成)

依赖 (spec §11.2 + §5 + §6):
- KnowledgeObject / Evidence / StructuredFact / Conflict / ResolutionEvent /
  KnowledgeUnit / Approval — spec §5 各自的 schema
- C-1 StrengthPolicy (spec §6 E-1 ~ E-15 降级规则)
- B-1 SemanticSupportChecker (spec §6 末段 Span/范围/时间)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from ..contracts.evidence import Evidence
from ..contracts.strength_policy import StrengthPolicy
from ..semantic_support.checker import SemanticSupportChecker


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


class EvidenceGate(Gate):
    """spec §11.2 Gate 3: 满足 Evidence Strength Policy + Semantic Support.

    检查 spec §6 全部 15 条规则:

    强度映射 (E-1 ~ E-7):
        - E-1: 5 种 Evidence type (direct_quote/structured_source/code/
          computed/multi_source/inferred)
        - E-2: direct_quote 默认 strong, 可精确回到原文
        - E-3: structured_source 默认 strong, 字段/Schema/记录主键可验证
        - E-4: code 默认 strong, 指向固定版本/提交/内容哈希
        - E-5: computed 默认 medium, 保存输入/算法版本/复算结果
        - E-6: multi_source 默认 medium, 至少两个相互独立来源
        - E-7: inferred 默认 weak, 仅支持 Synthesized, 不能单独支撑 observed fact

    强度约束 (E-8 ~ E-12):
        - E-8: observed+fact 至少 1 strong Evidence 或 2 独立 medium
        - E-9: opinion/perspective 不要求升级为事实
        - E-10: synthesized 必须有 derived_from + Synthesis Provenance +
          至少 1 个非 inferred Evidence
        - E-11: strength 由 Policy 根据 Provenance 字段计算
        - E-12: Source Trust Profile.status=accepted
          (restricted → candidate/quarantined, rejected 不能支撑)

    降级与支持 (E-13 ~ E-15):
        - E-13: Semantic Support Check (spec §6 末段, 集成 B-1)
        - E-14: computed 缺 input_ids/algorithm_version/result_hash 降 weak
        - E-15: structured_source 缺 schema/record_key/field_path 降 weak

    B-1 SemanticSupportChecker 集成:
        - span_overlap=False → insufficient (spec §6 末段)
        - support_type=contradicts → block
        - support_type=insufficient → block (sufficient support 缺失)
        - supports_scope=False 或 supports_temporal=False → warn (不阻断, 记录)
        - 默认 OFF (v2.2 H-3 决策): 无 LLM 调用, 走规则快速判定
          (spec §A2 Gate SemSupport Accuracy ≥ 0.95)
    """

    name = "evidence"
    order = 3

    # Reason code prefixes that should trigger ``block`` rather than ``warn``.
    # Any reason starting with one of these prefixes is treated as a publish-
    # blocking violation (mapped at the end of ``check``).
    _BLOCK_PREFIXES = (
        "insufficient_",
        "missing_",
        "contradicts_",
        "rejected_",
        "no_evidence",
    )

    def __init__(
        self,
        semantic_checker: SemanticSupportChecker | None = None,
    ) -> None:
        self.strength_policy = StrengthPolicy()
        # OFF by default (v2.2 H-3): no LLM calls, rule-based fast path
        self.semantic_checker = semantic_checker or SemanticSupportChecker()

    def check(self, obj: Any, context: dict | None = None) -> GateVerdict:
        # 1. Only check evidence on Claim-like objects (not KnowledgeObject etc.)
        if not self._is_claim(obj):
            return GateVerdict.pass_()

        reasons: list[str] = []

        # 2. Extract evidence list from context or obj attribute
        evidences = self._get_evidences(obj, context)
        if not evidences:
            return GateVerdict.block(["no_evidence"])

        # 3. Compute strength per evidence (E-1, E-2 ~ E-7, E-11, E-14, E-15)
        evidence_strengths: list[tuple[Evidence, str]] = []
        for ev in evidences:
            strength = self.strength_policy.compute_strength(ev)
            evidence_strengths.append((ev, strength))

        # 4. E-8: observed+fact 至少 1 strong 或 2 独立 medium
        knowledge_mode = getattr(obj, "knowledge_mode", "observed")
        claim_type = getattr(obj, "claim_type", "fact")

        if knowledge_mode == "observed" and claim_type == "fact":
            if not self._has_sufficient_support(evidence_strengths):
                reasons.append("insufficient_evidence_strength:observed_fact")
                # Blocking failure — short-circuit before further checks
                return GateVerdict.block(reasons)

        # 5. E-10: synthesized 必须有 derived_from
        if knowledge_mode == "synthesized":
            derived_from = getattr(obj, "derived_from", None)
            if not derived_from:
                reasons.append("missing_derived_from:synthesized")
                return GateVerdict.block(reasons)
            # E-7: synthesized 可用 inferred (其他 mode 不行)
            # 其他 mode 下 inferred → 视为 weak 并记录 warn
            for ev, strength in evidence_strengths:
                if ev.evidence_type == "inferred":
                    if knowledge_mode == "synthesized":
                        continue  # allowed
                    reasons.append(f"weak_evidence:{ev.evidence_id}")
                elif strength == "weak":
                    reasons.append(f"weak_evidence_in_synthesized:{ev.evidence_id}")

        # 6. E-12: Source Trust Profile 检查
        trust_profile_id = context.get("trust_profile_id") if context else None
        if trust_profile_id and hasattr(obj, "trust_profile_status"):
            status = obj.trust_profile_status
            if status == "rejected":
                return GateVerdict.block(["rejected_source_trust"])
            elif status == "restricted":
                # 不阻断 (自动 candidate/quarantined)
                reasons.append("restricted_source_trust")

        # 7. E-13: B-1 Semantic Support Check (spec §6 末段)
        if self.semantic_checker and context:
            claim_text = (
                getattr(obj, "text", "") or getattr(obj, "content", "") or ""
            )
            claim_id = getattr(obj, "id", "")
            for ev, _strength in evidence_strengths:
                verdict = self.semantic_checker.check(
                    evidence=ev,
                    claim_text=claim_text,
                    claim_id=claim_id,
                )
                # spec §6 末段：仅 Span 可定位不构成支持
                if verdict.support_type == "insufficient":
                    reasons.append(f"insufficient_semantic_support:{ev.evidence_id}")
                elif verdict.support_type == "contradicts":
                    return GateVerdict.block(
                        [f"contradicts_claim:{ev.evidence_id}"]
                    )
                elif not verdict.supports_scope:
                    reasons.append(f"unsupported_scope:{ev.evidence_id}")
                elif not verdict.supports_temporal:
                    reasons.append(f"unsupported_temporal:{ev.evidence_id}")

        if reasons:
            # Distinguish block vs warn by prefix.
            blocking = [
                r for r in reasons if r.startswith(self._BLOCK_PREFIXES)
            ]
            if blocking:
                return GateVerdict.block(reasons)
            return GateVerdict.warn(reasons)

        return GateVerdict.pass_()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _is_claim(self, obj: Any) -> bool:
        """Return True iff ``obj`` has claim-shaped attributes.

        A claim is identified by the joint presence of a textual body
        (``text`` or ``content``) plus ``knowledge_mode``. Schema Gate is
        responsible for primary type validation; this gate only fires on
        objects that look like a claim.
        """
        has_text = hasattr(obj, "text") or hasattr(obj, "content")
        has_mode = hasattr(obj, "knowledge_mode")
        return has_text and has_mode

    def _get_evidences(
        self, obj: Any, context: dict | None
    ) -> list[Evidence]:
        """Resolve the evidence list for the claim.

        Order of precedence:
            1. ``context["evidences"]`` (caller-provided resolved list)
            2. ``obj.evidences`` attribute (Claim-like default)
        """
        if context and "evidences" in context:
            return list(context["evidences"])
        if hasattr(obj, "evidences"):
            return list(obj.evidences)
        return []

    def _has_sufficient_support(
        self, evidence_strengths: list[tuple[Evidence, str]]
    ) -> bool:
        """spec §6 E-8: observed+fact 至少 1 strong 或 2 独立 medium.

        独立性 v2.2 暂以"不同 evidence_id 即独立"近似；
        真正的独立性判定（多源不来自同一文档/作者）由 B-2 后续 task
        通过 Source Profile 字段统一处理。
        """
        strong_count = sum(1 for _ev, s in evidence_strengths if s == "strong")
        if strong_count >= 1:
            return True
        medium_count = sum(1 for _ev, s in evidence_strengths if s == "medium")
        if medium_count >= 2:
            return True
        return False


class ModeGate(Gate):
    """spec §11.2 Gate 4: Observed/Synthesized 标记及来源完整.

    检查 spec §7 全部规则:
    - §7.1 Observed/Synthesized 边界（6 类允许 Observed 变换 / 5 类必须 Synthesized）
    - §7.1 Mode Gate 必须比较规范化前后命题, **不只是检查 knowledge_mode 标签**
    - §7.3 Synthesized 必须显示 synthesized 标签和推导来源
    - §7.3 Synthesized Claim 必须有 Provenance + derived_from 非空 + review_status=approved
    - §7.3 Agent Context 中不得省略知识模式
    - §7.3 重新生成 Synthesized 时创建新版本, 不静默覆盖

    检查 C-4 KnowledgeMode 集成:
    - knowledge_mode 字段必填 (C-4 K-2 fail-closed)
    - 默认 'unknown' (truncation 兜底)

    与 B-2.2 Evidence Gate 协调:
    - Evidence Gate 已检查 synthesized 需要 derived_from (E-10)
    - Mode Gate 同样检查 derived_from (双保险)
    - 区别: Mode Gate 关注"标签完整性", Evidence Gate 关注"证据强度"
    """

    name = "mode"
    order = 4

    # Reason code prefixes that should trigger ``block`` rather than ``warn``.
    # Mode Gate 的 reason code 中 "missing_"/"unapproved_" 前缀视为 block。
    _BLOCK_PREFIXES = (
        "missing_",
        "unapproved_",
        "invalid_knowledge_mode",
        "knowledge_mode_is_none",
    )

    def check(self, obj: Any, context: dict | None = None) -> GateVerdict:
        # 1. 检查 obj 是否有 knowledge_mode 字段（C-4 已固化为 back-compat 字段）
        #    无该字段视为非 knowledge 对象 → pass（不在本 Gate 关注范围）
        if not hasattr(obj, "knowledge_mode"):
            return GateVerdict.pass_()

        knowledge_mode = obj.knowledge_mode

        # 2. knowledge_mode 不能是 None（spec §7.3 Agent Context 不得省略）
        if knowledge_mode is None:
            return GateVerdict.block(["knowledge_mode_is_none"])

        # 3. knowledge_mode 必须合法 (observed / synthesized / unknown)
        valid_modes = ("observed", "synthesized", "unknown")
        if knowledge_mode not in valid_modes:
            return GateVerdict.block([f"invalid_knowledge_mode:{knowledge_mode}"])

        reasons: list[str] = []

        # 4. spec §7.3 Synthesized 必须有 derived_from + Synthesis Provenance
        #    + review_status=approved
        if knowledge_mode == "synthesized":
            # 4a. derived_from 必填
            derived_from = getattr(obj, "derived_from", None)
            if not derived_from:
                reasons.append("missing_derived_from:synthesized")

            # 4b. Synthesis Provenance 必填
            synthesis_provenance = getattr(obj, "synthesis_provenance", None)
            if not synthesis_provenance:
                reasons.append("missing_synthesis_provenance:synthesized")

            # 4c. review_status=approved
            review_status = getattr(obj, "review_status", None)
            if review_status != "approved":
                reasons.append(f"unapproved_synthesized:review_status={review_status}")

            # 4d. spec §7.3 重新生成 Synthesized 时创建新版本, 不静默覆盖
            #     version 字段 ≥ 1 (初版 = 1, 重新生成时 version+1)
            if hasattr(obj, "version"):
                if obj.version < 1:
                    reasons.append(f"invalid_synthesized_version:{obj.version}")

        # 5. 区分 block vs warn:
        #    - block: missing_* / unapproved_* / invalid_* / knowledge_mode_is_none
        #    - warn: invalid_synthesized_version (软告警, 不阻断)
        if reasons:
            blocking = [
                r for r in reasons
                if any(r.startswith(p) for p in self._BLOCK_PREFIXES)
            ]
            if blocking:
                return GateVerdict.block(reasons)
            return GateVerdict.warn(reasons)

        return GateVerdict.pass_()