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

from ..conflicts.classifier import ConflictClassifier
from ..contracts.evidence import Evidence
from ..contracts.strength_policy import StrengthPolicy
from ..domain.knowledge_unit import (
    KnowledgeUnit,
    should_merge_ku,
    should_split_ku,
)
from ..governance.approval import ApprovalGate
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


class IdentityGate(Gate):
    """spec §11.2 Gate 5: 概念归属和别名解析可解释。

    检查 (B-2.4 简化实现):
    1. KnowledgeUnit.identity_key 格式合法 (id-v1: 前缀) — spec §5.4
    2. 高风险写操作有 approved approval (merge/split/supersede/
       concept_identity_change) — spec §5.11 + §11.4 #4 "无审计 merge/supersede = 0"
    3. 合并条件辅助: 同问题 + 上下文/时间兼容 — spec §4.4
       (完整 should_merge_ku 5 条件由 A-1 helpers 提供, B-2.4 仅做基础探测)

    与既有模块集成:
    - A-1 KnowledgeUnit.identity_key @property (id-v1 算法已实现, 确定性)
    - A-4 ApprovalGate.check_authorization(operation, target_ids)
    - A-1 should_split_ku / should_merge_ku helpers (留 known_limitations)
    - spec §4.4 ResolutionEvent 写入由 B-2.5+ 提供 (留 known_limitations)

    区分 block vs warn:
    - block: invalid_identity_key_format
    - warn: missing_approval:high_risk_operation / merge_questions_missing
    """

    name = "identity"
    order = 5

    # Reason code prefixes that should trigger ``block`` rather than ``warn``.
    # Identity Gate 的 reason code 中 "invalid_" 前缀视为 block。
    _BLOCK_PREFIXES = ("invalid_",)

    def __init__(
        self,
        approval_gate: ApprovalGate | None = None,
    ) -> None:
        """注入 ApprovalGate (默认 None → 不做 approval 检查, 仅做 identity_key 校验).

        实际部署时由 IntegrityGate 流水线注入; 单元测试可直接 mock ApprovalGate.
        """
        self.approval_gate = approval_gate

    def check(self, obj: Any, context: dict | None = None) -> GateVerdict:
        reasons: list[str] = []

        # 1. 仅 KnowledgeUnit 对象进入 Identity Gate 检查
        if not isinstance(obj, KnowledgeUnit):
            return GateVerdict.pass_()  # 非 KU 不适用 (留 Schema/Evidence Gate 处理)

        # 2. identity_key 必填 + 符合 id-v1 算法 (spec §5.4)
        #    identity_key 是 @property 自动从字段计算 — 当字段被手工篡改或绕过
        #    @property 强行写入 __dict__ 时, 这里探测格式合法性
        identity_key = obj.identity_key
        if not identity_key or not identity_key.startswith("id-v1:"):
            return GateVerdict.block(["invalid_identity_key_format"])

        # 3. spec §11.4 #4: 高风险写操作 (verified/disputed/stale/deprecated 状态
        #    隐含已通过 merge/split/supersede) 必须有 approved approval
        #    status in ("quarantined", "candidate") 视为未触发高风险操作, 不检查
        if self.approval_gate is not None:
            if obj.status in ("verified", "disputed", "stale", "deprecated"):
                # 简化检查: merge 操作 + 单一 target_id
                # 实际更精细: 拆分/合并/废弃/identity_change 分别检查
                # (详见 A-4 ApprovalGate.check_authorization 完整实现)
                if not self.approval_gate.check_authorization(
                    "merge", [obj.ku_id]
                ):
                    reasons.append("missing_approval:high_risk_operation")

        # 4. spec §4.4 合并条件辅助检查 (candidate_b 同问题)
        #    完整 should_merge_ku 5 条件由 caller 调用, 此处仅探测 question 缺失
        if context and "candidate_b" in context:
            candidate_b = context["candidate_b"]
            if not isinstance(candidate_b, KnowledgeUnit):
                reasons.append("invalid_candidate_b_type")
            elif identity_key == candidate_b.identity_key:
                # identity_key 相同 → 应该合并, 检查 question 必填
                if not obj.question or not candidate_b.question:
                    reasons.append("merge_questions_missing")

        # 5. 拆分/合并决策应写入 ResolutionEvent (spec §4.4)
        #    当前 KnowledgeUnit 未实现 resolution_event_id 字段 — 留 known_limitations

        if reasons:
            blocking = [
                r for r in reasons
                if any(r.startswith(p) for p in self._BLOCK_PREFIXES)
            ]
            if blocking:
                return GateVerdict.block(reasons)
            return GateVerdict.warn(reasons)

        return GateVerdict.pass_()


class GranularityGate(Gate):
    """spec §11.2 Gate 6: 对象粒度符合三层模型。

    检查 spec §4.2 + §4.4 拆分/合并规则:
    - §4.2 KU 必须能用一个问题描述 (question 字段必填)
    - §4.4 拆分条件 (任一满足即拆):
        1. 内部 Claim 回答两个不同问题 (internal_questions > 1)
        2. 平台/受众/领域不同 (not same_platform / same_audience)
        3. 有效时间区间不同 (not time_ranges_overlap)
        4. 一部分更新频繁导致其他部分重编译 (update_correlation < 0.5)
    - §4.4 合并条件 (全部满足才合):
        1. 同问题 (same_question)
        2. Context 兼容 (context_compatible)
        3. 时间兼容 (time_compatible)
        4. 合并后仍能独立检索 (can_stay_independent)
        5. 不隐藏冲突 (no_hidden_conflict)
    - §4.4 拆分/合并决策写入 resolution_event (A-1 commit 2 已实现持久化,
      B-2.5 commit 1 在 KnowledgeUnit 加了 resolution_event_id 字段)

    集成 A-1 helpers:
    - should_split_ku (4 条件 OR-of)
    - should_merge_ku (5 条件 AND-of)
    - KnowledgeUnit.question 必填 (spec §4.2)
    - KnowledgeUnit.resolution_event_id 关联 A-1 commit 2 ResolutionEvent

    区分 block vs warn:
    - block: missing_question:ku_cannot_be_described /
      split_triggered_no_resolution_event / merge_triggered_no_resolution_event
    - warn: deprecated_without_resolution_event
    """

    name = "granularity"
    order = 6

    # Reason code prefixes that should trigger ``block`` rather than ``warn``.
    _BLOCK_PREFIXES = (
        "missing_",
        "split_",
        "merge_",
    )

    def check(self, obj: Any, context: dict | None = None) -> GateVerdict:
        # 1. obj 是 KnowledgeUnit 才有 granularity 校验
        if not isinstance(obj, KnowledgeUnit):
            return GateVerdict.pass_()  # 非 KU 不适用 (留 Schema/Identity Gate 处理)

        reasons: list[str] = []

        # 2. spec §4.2: KU 必须能用一个问题描述
        if not obj.question or not obj.question.strip():
            return GateVerdict.block(["missing_question:ku_cannot_be_described"])

        # 3. spec §4.4 拆分条件 (任一满足即拆, 触发记录 resolution_event)
        #    should_split_ku 4 条件 OR-of
        #    通过 context["should_split_params"] 传入拆分判定参数
        #    (实际部署由 caller 评估, GranularityGate 仅做关联校验)
        if context and "should_split_params" in context:
            params = context["should_split_params"]
            if should_split_ku(**params):
                # 拆分触发: 要求有 resolution_event_id 关联
                if not obj.resolution_event_id:
                    reasons.append("split_triggered_no_resolution_event")

        # 4. spec §4.4 合并条件 (全部满足才合, 触发记录 resolution_event)
        #    should_merge_ku 5 条件 AND-of
        if context and "should_merge_params" in context:
            params = context["should_merge_params"]
            if should_merge_ku(**params):
                # 合并触发: 要求有 resolution_event_id 关联
                if not obj.resolution_event_id:
                    reasons.append("merge_triggered_no_resolution_event")

        # 5. spec §4.4: deprecated status 应有 resolution_event 留痕
        #    简化检查: status='deprecated' 但无 resolution_event_id → warn (软告警)
        if obj.status == "deprecated" and not obj.resolution_event_id:
            reasons.append("deprecated_without_resolution_event")

        if reasons:
            # 区分 block vs warn:
            # - block: missing_/split_/merge_ 前缀
            # - warn: deprecated_ 前缀 (软告警, 不阻断)
            blocking = [
                r for r in reasons
                if any(r.startswith(p) for p in self._BLOCK_PREFIXES)
            ]
            if blocking:
                return GateVerdict.block(reasons)
            return GateVerdict.warn(reasons)

        return GateVerdict.pass_()


class ContextGate(Gate):
    """spec §11.2 Gate 7: 适用范围明确或标记 unknown.

    检查 spec §5.1 Context 8 维度 + §8.3 5 匹配语义 + §8.2 X-9:

    - §5.1 Context 8 维度: domain / platform / audience / geography / language /
      goal / conditions / perspective (决定性 5 维度: 前 5)
    - §8.3 5 匹配语义: exact / compatible / disjoint / unresolved / ignored
    - §8.2 X-9: 任一决定性维度 unknown + 潜在互斥 → unresolved (warn 阶段;
      实际 unresolved 分类由 Conflict Gate B-2.8 完成)
    - 候选比较对象 context 缺失 → block (无法判定匹配语义)
    - K-5 加固: WikiPage.category / taxonomy_sub 必须映射到 Context.domain /
      Context.platform

    与其他 Gate 协调:
    - Schema Gate 先验证字段存在 (B-2.1)
    - Identity Gate / Granularity Gate 先确认 KU 粒度 (B-2.4/B-2.5)
    - 本 Gate: Context 匹配判定
    - 后续 Temporal Gate (B-2.7) 与 Conflict Gate (B-2.8) 在本 Gate 基础上
      处理 temporal / conflict 维度
    """

    name = "context"
    order = 7

    # spec §5.1 决定性 5 维度 (任意缺失或 unknown 触发 X-9)
    DECISIVE_DIMS: tuple[str, ...] = (
        "domain", "platform", "audience", "geography", "language",
    )

    # Reason code prefixes that should trigger ``block`` rather than ``warn``.
    # Context Gate 的 reason code 中 "missing_candidate_b_" / "no_common_"
    # 前缀视为 block (候选比较对象缺失或候选无共同维度)。
    # 注意: 不使用通用 "missing_" — K-5 映射 (missing_domain_from_k5_taxonomy)
    # 是软告警 (warn), 不阻断。
    _BLOCK_PREFIXES = (
        "missing_candidate_b_",
        "no_common_",
    )

    def __init__(
        self,
        conflict_classifier: ConflictClassifier | None = None,
    ) -> None:
        """注入 ConflictClassifier (默认 None → 仍可独立运行; 集成路径由 B-2.8 接力).

        当前 Gate 不直接调用 ConflictClassifier.classify() (那是 B-2.8 工作);
        仅 import 该模块证明 A-3 集成点存在, 并保留扩展接口 (v2.2 后续可让
        Context Gate 在比较路径直接复用 ConflictClassifier 的
        _has_unknown_dimension 判定)。
        """
        self.conflict_classifier = conflict_classifier or ConflictClassifier()

    def check(self, obj: Any, context: dict | None = None) -> GateVerdict:
        # 1. obj 是否有 context 字段 (KnowledgeObject / WikiPage / Conflict 等)
        #    无 context 字段视为不在本 Gate 关注范围 (helper: 不适用)
        context_a = self._get_context(obj)
        if context_a is None:
            return GateVerdict.pass_()

        reasons: list[str] = []

        # 2. spec §5.1 决定性 5 维度探测: 任一 unknown → warn (X-9)
        for dim in self.DECISIVE_DIMS:
            val = context_a.get(dim)
            if val in (None, "", "unknown"):
                # §8.2 X-9: 任一决定性维度 unknown + 潜在互斥 → unresolved
                # 简化: unknown 决定性维度 → warn (不阻断, 留痕)
                # 实际 unresolved 类由 Conflict Gate 在 B-2.8 接力分类
                reasons.append(f"unknown_decisive_dimension:{dim}")

        # 3. spec §8.3 候选比较路径: 仅在有 candidate_b_context 时触发
        if context and "candidate_b_context" in context:
            context_b = context["candidate_b_context"]
            if context_b is None:
                return GateVerdict.block(["missing_candidate_b_context"])

            # exact 至少 1 维度相同 (共享维度且值相等)
            common = set(context_a.keys()) & set(context_b.keys())
            if not common:
                reasons.append("no_common_dimension")

            # disjoint: domain + platform 都同时 disjoint 才算 disjoint
            # (spec §8.3 — 单维度不同不视为 disjoint, 避免过度阻断)
            for dim in ("domain", "platform"):
                val_a = context_a.get(dim)
                val_b = context_b.get(dim)
                if (
                    val_a
                    and val_b
                    and val_a != val_b
                    and val_a != "unknown"
                    and val_b != "unknown"
                ):
                    reasons.append(f"disjoint_dimension:{dim}")

            # unresolved: 双方在任一决定性维度都 unknown → X-9
            for dim in self.DECISIVE_DIMS:
                val_a = context_a.get(dim)
                val_b = context_b.get(dim)
                if (
                    val_a in (None, "", "unknown")
                    and val_b in (None, "", "unknown")
                ):
                    reasons.append(f"unresolved_dimension:{dim}")

        # 4. K-5 加固: WikiPage.category → Context.domain 必填映射
        #    category/taxonomy_sub 有值时, 对应 Context 维度必填
        if hasattr(obj, "category") and obj.category:
            if "domain" not in context_a:
                reasons.append("missing_domain_from_k5_taxonomy")
        if hasattr(obj, "taxonomy_sub") and obj.taxonomy_sub:
            if "platform" not in context_a:
                reasons.append("missing_platform_from_k5_taxonomy")

        if reasons:
            # 区分 block vs warn:
            # - block: missing_candidate_b_context / no_common_dimension
            # - warn: unknown_decisive_dimension / disjoint_dimension /
            #   unresolved_dimension / missing_domain_from_k5_taxonomy /
            #   missing_platform_from_k5_taxonomy
            blocking = [
                r for r in reasons
                if any(r.startswith(p) for p in self._BLOCK_PREFIXES)
            ]
            if blocking:
                return GateVerdict.block(reasons)
            return GateVerdict.warn(reasons)

        return GateVerdict.pass_()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _get_context(self, obj: Any) -> dict | None:
        """获取 obj 的 context 字典 (兼容 KnowledgeObject / WikiPage / Conflict).

        路径探测顺序:
        1. ``obj.context`` (KnowledgeObject 主流形态)
        2. ``obj.context_a`` (Conflict 对象 — 比较路径的 a 侧)
        3. ``obj._ko_extra["context"]`` (WikiPage 兼容路径 — frontmatter 序列化)
        """
        if hasattr(obj, "context") and isinstance(obj.context, dict):
            return obj.context
        if hasattr(obj, "context_a") and isinstance(obj.context_a, dict):
            return obj.context_a
        if hasattr(obj, "_ko_extra") and isinstance(obj._ko_extra, dict):
            ko_extra = obj._ko_extra or {}
            ctx = ko_extra.get("context")
            if isinstance(ctx, dict):
                return ctx
        return None
