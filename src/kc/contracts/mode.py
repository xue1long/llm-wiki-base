"""Knowledge Mode + LLM output fail-closed truncation detection (C-4 / G5 + K-2).

路线 v2.2 §C-4 (KnowledgeMode Observed/Synthesized) + K-2 加固 (5 种 LLM
截断场景 fail-closed 兜底)。

Spec §7.1 Mode Gate (compare before/after normalization) + §A2 Gate
(5 截断错误注入 100% 阻止) + §11.4 #3 (Observed/Synthesized 混层 = 0).

Public API:
    KnowledgeMode                Literal["observed" | "synthesized" | "unknown"]
    parse_knowledge_mode(value)  Strict parser; returns "unknown" on any invalid input
    detect_truncation(raw)       5-truncation detector; returns reason string or None
    parse_llm_output_with_mode(raw) → KnowledgeCandidate with fail-closed behavior
"""
from __future__ import annotations

import json
from typing import Any, Literal


# spec §7 Observed vs Synthesized + 路线 K-2 加固截断兜底
KnowledgeMode = Literal["observed", "synthesized", "unknown"]

_VALID_MODES: frozenset[str] = frozenset({"observed", "synthesized", "unknown"})


def parse_knowledge_mode(value: Any) -> KnowledgeMode:
    """Parse knowledge_mode value with strict validation.

    Returns ``"unknown"`` for any invalid input (fail-closed principle).
    Does **not** raise — caller can branch on the return value or use
    ``detect_truncation`` for richer diagnostics.
    """
    if not isinstance(value, str):
        return "unknown"
    if value not in _VALID_MODES:
        return "unknown"
    return value  # type: ignore[return-value]


def detect_truncation(raw_output: str) -> str | None:
    """Detect 5 truncation/failure modes in raw LLM output.

    K-2 加固 5 种场景 (spec §A2 Gate):

    1. ``json_truncated``        — JSON 不完整（截断）
    2. ``field_missing``         — ``knowledge_mode`` 字段缺失
    3. ``type_mismatch``         — ``knowledge_mode`` 不是 string（如 list）
    4. ``value_null_or_empty``   — ``knowledge_mode`` 为 null 或空字符串
    5. ``value_out_of_range``    — ``knowledge_mode`` 值不在 enum

    Returns the failure_reason string, or ``None`` if the output is valid.
    """
    # 1. JSON 残缺
    try:
        data = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        return f"json_truncated: {exc.msg}"

    if not isinstance(data, dict):
        return "json_truncated: not a JSON object"

    # 2. 字段缺失
    if "knowledge_mode" not in data:
        return "field_missing: knowledge_mode"

    mode_value = data["knowledge_mode"]

    # 4. None / 空字符串（先于 type_mismatch 判断，区分 null 与 list）
    if mode_value is None:
        return "value_null_or_empty"

    # 3. 类型不匹配（list/dict 而非 string）
    if not isinstance(mode_value, str):
        return f"type_mismatch: expected string, got {type(mode_value).__name__}"

    # 4. 空字符串
    if mode_value.strip() == "":
        return "value_null_or_empty"

    # 5. 越界值
    if mode_value not in _VALID_MODES:
        return f"value_out_of_range: '{mode_value}' (expected one of {sorted(_VALID_MODES)})"

    return None  # 合法


def parse_llm_output_with_mode(raw_output: str) -> Any:
    """Parse LLM output into a ``KnowledgeCandidate`` with fail-closed truncation.

    On any of the 5 truncation scenarios (K-2 加固), returns a candidate with:

    * ``knowledge_mode = "unknown"``
    * ``status = CandidateStatus.REJECTED``
    * ``failure_reason`` populated with the detector's diagnostic string

    On success, returns a candidate with the parsed ``knowledge_mode`` and
    ``status = CandidateStatus.PENDING`` (the default for downstream review).

    spec §A2 Gate: 5 截断 fail-closed 100% 阻止 — none of the 5 scenarios may
    ever silently produce a PENDING candidate.
    """
    # 延迟 import 避免循环依赖
    from src.knowledge.core.candidate import (
        CandidateStatus,
        KnowledgeCandidate,
        KnowledgeType,
    )

    failure_reason = detect_truncation(raw_output)

    # 尝试提取最小 id / source_id 以便 quarantine 时保留可追溯性
    parsed: dict = {}
    if failure_reason is None or "json_truncated" not in (failure_reason or ""):
        try:
            maybe = json.loads(raw_output)
            if isinstance(maybe, dict):
                parsed = maybe
        except json.JSONDecodeError:
            parsed = {}

    base_fields: dict[str, Any] = {
        "id": str(parsed.get("id", "<truncated>")),
        "source_id": str(parsed.get("source_id", "<truncated>")),
        "type": KnowledgeType.CONCEPT,
        "title": str(parsed.get("title", "<truncated>")),
        "claims": [],
        "confidence": 0.0,
        "evidence": [],
        "raw_llm_output": parsed,
        "status": CandidateStatus.REJECTED,
        "knowledge_mode": "unknown",
        "failure_reason": failure_reason or "unknown",
    }

    if failure_reason is not None:
        return KnowledgeCandidate(**base_fields)

    # 成功路径：尝试识别 KnowledgeType，否则退化为 CONCEPT
    raw_type = parsed.get("type")
    try:
        ktype = KnowledgeType(raw_type) if raw_type else KnowledgeType.CONCEPT
    except ValueError:
        ktype = KnowledgeType.CONCEPT

    return KnowledgeCandidate(
        id=str(parsed.get("id", "")),
        source_id=str(parsed.get("source_id", "")),
        type=ktype,
        title=str(parsed.get("title", "")),
        claims=parsed.get("claims", []) if isinstance(parsed.get("claims"), list) else [],
        confidence=float(parsed.get("confidence", 1.0)) if isinstance(parsed.get("confidence", 0), (int, float)) else 1.0,
        evidence=parsed.get("evidence", []) if isinstance(parsed.get("evidence"), list) else [],
        raw_llm_output=parsed,
        status=CandidateStatus.PENDING,
        knowledge_mode=parse_knowledge_mode(parsed.get("knowledge_mode")),
        failure_reason=None,
    )


__all__ = [
    "KnowledgeMode",
    "parse_knowledge_mode",
    "detect_truncation",
    "parse_llm_output_with_mode",
]