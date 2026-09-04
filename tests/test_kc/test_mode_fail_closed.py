"""Tests for C-4 Observed/Synthesized Mode tag + K-2 fail-closed truncation.

路线 v2.2 §C-4 / G5 + K-2 加固.

The truncation detector (`detect_truncation`) and the parse helper
(`parse_llm_output_with_mode`) are pure functions operating on a raw LLM JSON
string. They do not touch the existing KnowledgeCandidate dataclass shape —
the existing CandidateStatus (PENDING/VALIDATED/REJECTED/PROMOTED) already
encodes the fail-closed path: any of the 5 K-2 truncation scenarios must
produce REJECTED, never PENDING.
"""
from __future__ import annotations



# ─────────────────────────────────────────────────────────────────────────────
# Imports — all references live under src.kc.contracts.mode
# ─────────────────────────────────────────────────────────────────────────────


# ─── Happy path (5 tests) ───────────────────────────────────────────────────


def test_knowledge_mode_observed_valid():
    """KnowledgeMode='observed' 合法"""
    from src.kc.contracts.mode import parse_knowledge_mode
    assert parse_knowledge_mode("observed") == "observed"


def test_knowledge_mode_synthesized_valid():
    """KnowledgeMode='synthesized' 合法"""
    from src.kc.contracts.mode import parse_knowledge_mode
    assert parse_knowledge_mode("synthesized") == "synthesized"


def test_knowledge_mode_unknown_explicit():
    """KnowledgeMode='unknown' 显式合法（截断兜底）"""
    from src.kc.contracts.mode import parse_knowledge_mode
    assert parse_knowledge_mode("unknown") == "unknown"


def test_detect_truncation_returns_none_for_valid_observed():
    """完整合法 JSON (observed) → None（无截断）"""
    from src.kc.contracts.mode import detect_truncation
    raw = '{"id": "ko_001", "source_id": "src_1", "title": "x", "knowledge_mode": "observed"}'
    assert detect_truncation(raw) is None


def test_parse_llm_output_with_observed_mode():
    """parse_llm_output 正确解析 observed mode → PENDING 候选"""
    from src.kc.contracts.mode import parse_llm_output_with_mode
    raw = (
        '{"id": "ko_001", "source_id": "src_1", "title": "x", '
        '"type": "concept", "claims": [], "evidence": [], '
        '"knowledge_mode": "observed"}'
    )
    candidate = parse_llm_output_with_mode(raw)
    assert candidate.knowledge_mode == "observed"
    assert candidate.id == "ko_001"
    # happy path → not quarantined (PENDING, the default)
    assert candidate.status.value == "pending"


# ─── Fail-closed truncation (5 tests, K-2) ──────────────────────────────────


def test_truncation_json_incomplete():
    """JSON 残缺（如 '{"knowledge_mode": "obser'）→ REJECTED + reason json_truncated"""
    from src.kc.contracts.mode import parse_llm_output_with_mode, detect_truncation
    raw = '{"id": "ko_001", "knowledge_mode": "obser'  # 截断
    candidate = parse_llm_output_with_mode(raw)
    reason = detect_truncation(raw)
    assert candidate.knowledge_mode == "unknown"
    assert candidate.status.value == "rejected"
    assert "json_truncated" in candidate.failure_reason
    assert "json_truncated" in reason


def test_truncation_field_missing():
    """字段缺失（knowledge_mode 字段不存在）→ REJECTED + reason field_missing"""
    from src.kc.contracts.mode import parse_llm_output_with_mode, detect_truncation
    raw = '{"id": "ko_001", "source_id": "src_1"}'  # 无 knowledge_mode
    candidate = parse_llm_output_with_mode(raw)
    reason = detect_truncation(raw)
    assert candidate.knowledge_mode == "unknown"
    assert candidate.status.value == "rejected"
    assert "field_missing" in candidate.failure_reason
    assert "field_missing" in reason


def test_truncation_value_out_of_range():
    """值越界（knowledge_mode='foo' 不在 enum）→ REJECTED + reason value_out_of_range"""
    from src.kc.contracts.mode import parse_llm_output_with_mode, detect_truncation
    raw = '{"id": "ko_001", "knowledge_mode": "foo"}'
    candidate = parse_llm_output_with_mode(raw)
    reason = detect_truncation(raw)
    assert candidate.knowledge_mode == "unknown"
    assert candidate.status.value == "rejected"
    assert "value_out_of_range" in candidate.failure_reason
    assert "value_out_of_range" in reason


def test_truncation_null_or_empty():
    """空白/None（knowledge_mode=null 或 ""）→ REJECTED + reason value_null_or_empty"""
    from src.kc.contracts.mode import parse_llm_output_with_mode, detect_truncation
    raw = '{"id": "ko_001", "knowledge_mode": null}'
    candidate = parse_llm_output_with_mode(raw)
    reason = detect_truncation(raw)
    assert candidate.knowledge_mode == "unknown"
    assert candidate.status.value == "rejected"
    assert "value_null_or_empty" in candidate.failure_reason
    assert "value_null_or_empty" in reason


def test_truncation_list_not_scalar():
    """列表而非单值（knowledge_mode 是数组）→ REJECTED + reason type_mismatch"""
    from src.kc.contracts.mode import parse_llm_output_with_mode, detect_truncation
    raw = '{"id": "ko_001", "knowledge_mode": ["observed"]}'
    candidate = parse_llm_output_with_mode(raw)
    reason = detect_truncation(raw)
    assert candidate.knowledge_mode == "unknown"
    assert candidate.status.value == "rejected"
    assert "type_mismatch" in candidate.failure_reason
    assert "type_mismatch" in reason
