"""identity_key 一致性校验器 (B-2.5 / v2.2 重大补位 #1, spec §5 表 13 行).

覆盖 spec §5 表的 13 行 identity_key 输入字段:

| 对象 | identity_key 输入字段 |
|---|---|
| Source | `source_type, canonical_locator` |
| Raw Source | `raw_bytes_hash` |
| Canonical Document | `raw_source_id, parser_name, parser_version, correction_of` |
| Concept | `concept_type, canonical_name, identity_scope_id` |
| Knowledge Unit | `concept_id, question, unit_type, knowledge_mode, context_id, validity_id` |
| Claim | `subject, predicate, object, text, knowledge_mode, context_id, validity_id` |
| Structured Fact | `subject, field, value, value_type, context_id, validity_id` |
| Evidence | `document_id, block_id, source_span, source_hash` |
| Context | 9 维度字段 + policy_version |
| Validity | `valid_from, valid_to, derivation_policy_version` |
| Synthesis | `output_claim_id, derived_from, method, model, model_version, prompt_version` |
| Relation | `relation_type, from_ref, to_ref, context_id, validity_id` |
| Conflict | `statement_a_ref, statement_b_ref, context_a_id, context_b_id`（两个 Statement Ref 按规范化值排序） |

id-v1 规范化算法 (spec §5 id-v1 algorithm 段):
- 字符串: UTF-8 NFKC + 去首尾空白 + 折叠连续空白 + 小写
- 数字和对象: Canonical JSON
- 无序集合: 按规范化值排序
- identity_key = "id-v1:" + sha256(Canonical JSON)

KnowledgeUnit / StructuredFact 复用 A-1 (d08534be) / C-4.5 (150ceb26) 已有实现。
"""
from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from ..domain.knowledge_unit import compute_ku_identity_key
from ..contracts.structured_fact import compute_structured_fact_identity_key


@dataclass(frozen=True)
class IdentityKeyCheck:
    """单对象 identity_key 校验结果."""

    object_type: str
    object_id: str
    identity_key: str
    expected_identity_key: str
    passed: bool
    reasons: tuple[str, ...] = ()


def _normalize(value: Any) -> str:
    """id-v1 规范化: NFKC + 去首尾空白 + 折叠连续空白 + 小写.

    None → 空字符串 (与 A-1 `_normalize` 行为一致, 保证可选字段缺失时确定性).
    """
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip()
    text = " ".join(text.split())  # collapse consecutive whitespace
    return text.lower()


def _id_v1(fields: dict[str, Any]) -> str:
    """id-v1 算法: sha256(Canonical JSON of normalized fields)."""
    normalized = {k: _normalize(v) for k, v in fields.items()}
    canonical = json.dumps(
        normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    digest = sha256(canonical.encode("utf-8")).hexdigest()
    return f"id-v1:{digest}"


def compute_identity_key(obj: Any) -> str:
    """根据对象类型计算 identity_key (spec §5 表 13 行).

    未支持类型安全降级: 返回 "unsupported:<type>".
    """
    obj_type = type(obj).__name__.lower()

    # 1. Source
    if obj_type == "source":
        return _id_v1(
            {
                "source_type": getattr(obj, "source_type", ""),
                "canonical_locator": getattr(obj, "canonical_locator", ""),
            }
        )

    # 2. Raw Source
    if obj_type in ("rawsource", "raw_source"):
        return _id_v1(
            {
                "raw_bytes_hash": getattr(obj, "raw_bytes_hash", ""),
            }
        )

    # 3. Canonical Document
    if obj_type in ("canonicaldocument", "canonical_document"):
        return _id_v1(
            {
                "raw_source_id": getattr(obj, "raw_source_id", ""),
                "parser_name": getattr(obj, "parser_name", ""),
                "parser_version": getattr(obj, "parser_version", ""),
                "correction_of": getattr(obj, "correction_of", None),
            }
        )

    # 4. Concept / Entity
    if obj_type in ("concept", "entity"):
        return _id_v1(
            {
                "concept_type": getattr(obj, "concept_type", ""),
                "canonical_name": getattr(obj, "canonical_name", ""),
                "identity_scope_id": getattr(obj, "identity_scope_id", ""),
            }
        )

    # 5. Knowledge Unit (复用 A-1)
    if obj_type == "knowledgeunit":
        return compute_ku_identity_key(
            concept_id=getattr(obj, "concept_id", ""),
            question=getattr(obj, "question", ""),
            unit_type=getattr(obj, "unit_type", ""),
            knowledge_mode=getattr(obj, "knowledge_mode", "unknown"),
            context_id=getattr(obj, "context_id", None),
            validity_id=getattr(obj, "validity_id", None),
        )

    # 6. Claim
    if obj_type == "claim":
        return _id_v1(
            {
                "subject": getattr(obj, "subject", None),
                "predicate": getattr(obj, "predicate", None),
                "object": getattr(obj, "object", None),
                "text": getattr(obj, "text", ""),
                "knowledge_mode": getattr(obj, "knowledge_mode", "unknown"),
                "context_id": getattr(obj, "context_id", None),
                "validity_id": getattr(obj, "validity_id", None),
            }
        )

    # 7. Structured Fact (复用 C-4.5)
    if obj_type == "structuredfact":
        return compute_structured_fact_identity_key(obj)

    # 8. Evidence
    if obj_type == "evidence":
        return _id_v1(
            {
                "document_id": getattr(obj, "document_id", ""),
                "block_id": getattr(obj, "block_id", ""),
                "source_span": getattr(obj, "source_span", None),
                "source_hash": getattr(obj, "source_hash", ""),
            }
        )

    # 9. Context
    if obj_type == "context":
        return _id_v1(
            {
                "domain": getattr(obj, "domain", None),
                "platform": getattr(obj, "platform", None),
                "audience": getattr(obj, "audience", None),
                "geography": getattr(obj, "geography", None),
                "language": getattr(obj, "language", None),
                "goal": getattr(obj, "goal", None),
                "conditions": getattr(obj, "conditions", None),
                "perspective": getattr(obj, "perspective", None),
                "policy_version": getattr(obj, "policy_version", ""),
            }
        )

    # 10. Validity
    if obj_type == "validity":
        return _id_v1(
            {
                "valid_from": getattr(obj, "valid_from", None),
                "valid_to": getattr(obj, "valid_to", None),
                "derivation_policy_version": getattr(obj, "derivation_policy_version", ""),
            }
        )

    # 11. Synthesis
    if obj_type == "synthesis":
        return _id_v1(
            {
                "output_claim_id": getattr(obj, "output_claim_id", ""),
                "derived_from": getattr(obj, "derived_from", None),
                "method": getattr(obj, "method", ""),
                "model": getattr(obj, "model", ""),
                "model_version": getattr(obj, "model_version", ""),
                "prompt_version": getattr(obj, "prompt_version", ""),
            }
        )

    # 12. Relation
    if obj_type == "relation":
        return _id_v1(
            {
                "relation_type": getattr(obj, "relation_type", ""),
                "from_ref": getattr(obj, "from_ref", None),
                "to_ref": getattr(obj, "to_ref", None),
                "context_id": getattr(obj, "context_id", None),
                "validity_id": getattr(obj, "validity_id", None),
            }
        )

    # 13. Conflict (两个 Statement Ref 按规范化值排序)
    if obj_type == "conflict":
        statement_a = getattr(obj, "statement_a_ref", None) or {}
        statement_b = getattr(obj, "statement_b_ref", None) or {}
        refs = sorted(
            [statement_a, statement_b],
            key=lambda r: (
                str(r.get("object_type", "")),
                str(r.get("object_id", "")),
            ),
        )
        return _id_v1(
            {
                "statement_a_ref": refs[0],
                "statement_b_ref": refs[1],
                "context_a_id": getattr(obj, "context_a_id", None),
                "context_b_id": getattr(obj, "context_b_id", None),
            }
        )

    # 未知类型安全降级
    return f"unsupported:{obj_type}"


def make_operation_id(operation, object_type, identity_key, input_hash) -> str:
    """生成确定性的 operation id (id-v1:<sha256>).

    操作键只由规范化业务输入组成 (operation, object_type, identity_key,
    input_hash)，不包含随机 run id；相同业务操作跨 run 得到相同 operation id，
    供 EventStore 幂等去重与审计追溯使用。
    """
    return _id_v1(
        {
            "operation": operation,
            "object_type": object_type,
            "identity_key": identity_key,
            "input_hash": input_hash,
        }
    )


def validate_identity_key(obj: Any) -> IdentityKeyCheck:
    """校验单个对象的 identity_key 一致性.

    - obj.identity_key 缺失 → passed=False, reasons=("identity_key_field_missing",)
    - obj.identity_key != compute_identity_key(obj) → passed=False, reasons=("identity_key_mismatch",)
    - 一致 → passed=True
    """
    obj_type = type(obj).__name__.lower()
    object_id = getattr(obj, "ku_id", None) or getattr(obj, "id", "<unknown>")
    expected = compute_identity_key(obj)
    actual = getattr(obj, "identity_key", None)

    if actual is None:
        return IdentityKeyCheck(
            object_type=obj_type,
            object_id=object_id,
            identity_key="<missing>",
            expected_identity_key=expected,
            passed=False,
            reasons=("identity_key_field_missing",),
        )

    return IdentityKeyCheck(
        object_type=obj_type,
        object_id=object_id,
        identity_key=actual,
        expected_identity_key=expected,
        passed=actual == expected,
        reasons=() if actual == expected else ("identity_key_mismatch",),
    )
