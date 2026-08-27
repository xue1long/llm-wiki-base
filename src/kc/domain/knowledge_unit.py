"""KnowledgeUnit + identity_key + split/merge helpers (A-1 / G3, spec §4.2 + §5.4 + §4.4).

三层粒度的中层 (spec §4.2):
    Entity/Concept (top) → KnowledgeUnit (mid) → Claim/StructuredFact (bottom)

identity_key 算法 (spec §5 table):
    identity_key = "id-v1:" + sha256({
        "concept_id", "question", "unit_type",
        "knowledge_mode", "context_id", "validity_id"
    })

规范化 (id-v1 algorithm 段):
- NFKC + 去首尾空白 + 折叠连续空白
- 标识符和受控词表值转小写
- 时间转 UTC RFC 3339 (本类型不含时间字段, 直接进入 sha256)
- 数字和对象使用 Canonical JSON
- 无序集合按规范化值排序
- 拼接字段用 sha256 + 'id-v1:' 前缀
"""
from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal


# Unit types (spec §5.4 schema, 8 values)
UnitType = Literal[
    "definition",
    "principle",
    "mechanism",
    "method",
    "process",
    "pattern",
    "case",
    "event",
]

# KU status lifecycle (spec §5.4 schema, 6 values)
KUStatus = Literal[
    "candidate",
    "verified",
    "disputed",
    "stale",
    "deprecated",
    "quarantined",
]

# Resolution actions (spec §5.11)
ResolutionAction = Literal[
    "create",
    "merge",
    "update",
    "link",
    "conflict",
    "supersede",
    "quarantine",
    "split",
    "keep_separate",
]


@dataclass(frozen=True)
class KnowledgeUnit:
    """spec §5.4 KU schema.

    Fields:
        ku_id                  Unique KU identifier.
        concept_id             Linked Concept/Entity (top of granularity pyramid).
        question               spec §4.2: 每个 KU 必须能用一个问题描述.
        title                  KU 标题.
        unit_type              spec §5.4: 8 种 KU 类型.
        knowledge_mode         spec §5.4: observed | synthesized | unknown.
        claim_ids              Associated Claim IDs (1:N Claim → KU).
        structured_fact_ids    Associated Structured Fact IDs (1:N SF → KU).
        context_id             Optional context scope.
        validity_id            Optional validity window.
        confidence             0.0-1.0.
        status                 6-state lifecycle.
        version                Schema version counter.
        created_at / updated_at  Unix ms timestamps.
    """
    ku_id: str
    concept_id: str
    question: str
    title: str
    unit_type: UnitType
    knowledge_mode: Literal["observed", "synthesized", "unknown"] = "unknown"
    claim_ids: tuple[str, ...] = ()
    structured_fact_ids: tuple[str, ...] = ()
    context_id: str | None = None
    validity_id: str | None = None
    confidence: float = 0.0
    status: KUStatus = "candidate"
    version: int = 1
    created_at: int = 0
    updated_at: int = 0
    resolution_event_id: str | None = None  # B-2.5 commit 1: 关联 A-1 commit 2 ResolutionEvent (spec §4.4 + §5.11)

    @property
    def identity_key(self) -> str:
        """id-v1 identity key derived from identity-bearing fields only.

        Stable across processes; ku_id and timestamps are intentionally excluded.
        """
        return compute_ku_identity_key(
            concept_id=self.concept_id,
            question=self.question,
            unit_type=self.unit_type,
            knowledge_mode=self.knowledge_mode,
            context_id=self.context_id,
            validity_id=self.validity_id,
        )


def _normalize(value: str | None) -> str:
    """id-v1 normalization: NFKC + strip + collapse whitespace + lowercase.

    None values are normalized to empty string so the canonical dict is
    deterministic regardless of which optional fields are present.
    """
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", value).strip()
    text = " ".join(text.split())  # collapse consecutive whitespace
    return text.lower()


def compute_ku_identity_key(
    concept_id: str,
    question: str,
    unit_type: str,
    knowledge_mode: str,
    context_id: str | None,
    validity_id: str | None,
) -> str:
    """Deterministic id-v1 identity key for a KU (spec §5 table).

    Hashes the six identity-bearing fields in a stable, order-independent way
    so the same content yields the same key across processes.
    """
    payload = {
        "concept_id": _normalize(concept_id),
        "question": _normalize(question),
        "unit_type": _normalize(unit_type),
        "knowledge_mode": _normalize(knowledge_mode),
        "context_id": _normalize(context_id),
        "validity_id": _normalize(validity_id),
    }
    canonical = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    digest = sha256(canonical.encode("utf-8")).hexdigest()
    return f"id-v1:{digest}"


def should_split_ku(
    claim_count: int,
    internal_questions: int,
    same_platform: bool = True,
    same_audience: bool = True,
    time_ranges_overlap: bool = True,
    update_correlation: float = 1.0,
) -> bool:
    """spec §4.4 KU 拆分条件判定 (任一满足即拆分).

    Split conditions (spec §4.4):
        1. 内部 Claim 回答两个不同问题 (internal_questions > 1)
        2. 平台/受众/领域不同 (not same_platform / same_audience)
        3. 有效时间区间不重叠 (not time_ranges_overlap)
        4. 一部分更新频繁导致其他部分重编译 (update_correlation < 0.5)

    H-5 ADR choice_3 (精准拆分) 决策由此函数支持: 在 novel-wiki 4892 页面
    dry-run (commit e9812664) 中识别 66 叙事类 (1.3%) 应按 KU 拆分.
    """
    if internal_questions > 1:
        return True
    if not same_platform:
        return True
    if not same_audience:
        return True
    if not time_ranges_overlap:
        return True
    if update_correlation < 0.5:
        return True
    return False


def should_merge_ku(
    same_question: bool,
    context_compatible: bool = True,
    time_compatible: bool = True,
    can_stay_independent: bool = True,
    no_hidden_conflict: bool = True,
) -> bool:
    """spec §4.4 KU 合并条件判定 (全部满足才合并).

    Merge conditions (spec §4.4):
        1. 同问题 (same_question)
        2. Context 兼容 (context_compatible)
        3. 时间兼容 (time_compatible)
        4. 合并后仍能独立检索 (can_stay_independent)
        5. 不隐藏冲突 (no_hidden_conflict)

    Identity Resolution 走这条路径合并重复 KU; 一旦任一条件不满足, 走
    keep_separate 或 conflict 路径.
    """
    if not same_question:
        return False
    if not context_compatible:
        return False
    if not time_compatible:
        return False
    if not can_stay_independent:
        return False
    if not no_hidden_conflict:
        return False
    return True


@dataclass(frozen=True)
class ResolutionEvent:
    """spec §5.11 拆分/合并决策记录 (可重放).

    用于 Identity Resolution + Identity 校审:
    - event_id           唯一 ID
    - candidate_ref      当前决策对象 (object_type, object_id)
    - candidate_set      候选集 [(object_type, object_id, score), ...]
    - action             决策动作 (9 种之一)
    - reason_codes       触发原因代码
    - context_policy_version  Context 策略版本 (id-v1)
    - temporal_policy_version  Temporal 策略版本 (id-v1)
    - model / model_version   决策所用模型 (None = 人工)
    - confidence         0.0-1.0
    - approval_id        人工审批 ID (None = 自动)
    - created_at         Unix ms
    """
    event_id: str
    candidate_ref: tuple[str, str]
    candidate_set: tuple[tuple[str, str, float], ...]
    action: ResolutionAction
    reason_codes: tuple[str, ...]
    context_policy_version: str = "id-v1"
    temporal_policy_version: str = "id-v1"
    model: str | None = None
    model_version: str | None = None
    confidence: float = 0.0
    approval_id: str | None = None
    created_at: int = 0
