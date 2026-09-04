"""Tests for B-2.5 identity_key consistency validation (v2.2 重大补位 #1, spec §5 表 13 行)."""
from __future__ import annotations


from src.kc.integrity.identity_key import (
    compute_identity_key,
    validate_identity_key,
    IdentityKeyCheck,
    make_operation_id,
)


def _mock(obj_type: str, **fields):
    """Build a mock object whose class name matches obj_type (so
    `type(obj).__name__.lower()` returns the expected dispatch key).
    """
    cls = type(obj_type, (), {})
    obj = cls.__new__(cls)
    for k, v in fields.items():
        setattr(obj, k, v)
    return obj


# ---------- compute_identity_key: 13 行字段 ----------

def test_compute_identity_key_source_deterministic():
    """Source: source_type + canonical_locator → id-v1 确定性."""
    src = _mock("Source", source_type="url", canonical_locator="https://example.com/a.pdf")
    key1 = compute_identity_key(src)
    key2 = compute_identity_key(src)
    assert key1 == key2
    assert key1.startswith("id-v1:")
    assert len(key1) == len("id-v1:") + 64  # sha256 hex


def test_compute_identity_key_raw_source():
    """Raw Source: raw_bytes_hash → id-v1 确定性."""
    raw = _mock("RawSource", raw_bytes_hash="abc123def456")
    key = compute_identity_key(raw)
    assert key.startswith("id-v1:")
    assert compute_identity_key(raw) == key  # 确定性


def test_compute_identity_key_canonical_document():
    """Canonical Document: raw_source_id + parser_name + parser_version + correction_of."""
    doc = _mock(
        "CanonicalDocument",
        raw_source_id="rs_001",
        parser_name="md_parser",
        parser_version="1.0",
        correction_of=None,
    )
    key = compute_identity_key(doc)
    assert key.startswith("id-v1:")
    assert compute_identity_key(doc) == key


def test_compute_identity_key_concept():
    """Concept: concept_type + canonical_name + identity_scope_id."""
    concept = _mock(
        "Concept",
        concept_type="entity",
        canonical_name="MCP",
        identity_scope_id="scope_001",
    )
    key = compute_identity_key(concept)
    assert key.startswith("id-v1:")
    assert compute_identity_key(concept) == key


def test_compute_identity_key_ku_matches_a1():
    """KnowledgeUnit: 复用 A-1 compute_ku_identity_key (同一输入同 key)."""
    ku = _mock(
        "KnowledgeUnit",
        concept_id="concept_001",
        question="What is 期待感?",
        unit_type="definition",
        knowledge_mode="observed",
        context_id=None,
        validity_id=None,
        ku_id="ku_test_001",
    )
    from src.kc.domain.knowledge_unit import compute_ku_identity_key as a1_compute

    expected = a1_compute(
        concept_id="concept_001",
        question="What is 期待感?",
        unit_type="definition",
        knowledge_mode="observed",
        context_id=None,
        validity_id=None,
    )
    assert compute_identity_key(ku) == expected


def test_compute_identity_key_claim():
    """Claim: subject + predicate + object + text + knowledge_mode + context_id + validity_id."""
    claim = _mock(
        "Claim",
        subject="小说",
        predicate="是",
        object="网络文学",
        text="小说是网络文学的一种形式",
        knowledge_mode="observed",
        context_id=None,
        validity_id=None,
    )
    key = compute_identity_key(claim)
    assert key.startswith("id-v1:")
    assert compute_identity_key(claim) == key


def test_compute_identity_key_sf_matches_c45():
    """Structured Fact: 复用 C-4.5 compute_structured_fact_identity_key."""
    from src.kc.contracts.structured_fact import StructuredFact

    # 用真实 C-4.5 StructuredFact dataclass（因为 compute_structured_fact_identity_key 接收对象）
    sf = StructuredFact(
        subject="user.email",
        field="value",
        value="alice@example.com",
        value_type="string",
        context_id=None,
        validity_id=None,
        confidence=0.95,
        evidence_ids=(),
        extraction_run_id="run_001",
        status="candidate",
    )
    from src.kc.contracts.structured_fact import compute_structured_fact_identity_key as c45_compute

    expected = c45_compute(sf)
    assert compute_identity_key(sf) == expected


def test_compute_identity_key_evidence():
    """Evidence: document_id + block_id + source_span + source_hash."""
    ev = _mock(
        "Evidence",
        document_id="doc_001",
        block_id="block_001",
        source_span={"start": 10, "end": 20},
        source_hash="hash_001",
    )
    key = compute_identity_key(ev)
    assert key.startswith("id-v1:")
    assert compute_identity_key(ev) == key


def test_compute_identity_key_context():
    """Context: 9 维度 + policy_version."""
    ctx = _mock(
        "Context",
        domain="novel_writing",
        platform="web",
        audience=None,
        geography=None,
        language="zh",
        goal=None,
        conditions=None,
        perspective=None,
        policy_version="v1",
    )
    key = compute_identity_key(ctx)
    assert key.startswith("id-v1:")
    assert compute_identity_key(ctx) == key


def test_compute_identity_key_validity():
    """Validity: valid_from + valid_to + derivation_policy_version."""
    validity = _mock(
        "Validity",
        valid_from=1633008000000,
        valid_to=None,
        derivation_policy_version="v1",
    )
    key = compute_identity_key(validity)
    assert key.startswith("id-v1:")
    assert compute_identity_key(validity) == key


def test_compute_identity_key_synthesis():
    """Synthesis: output_claim_id + derived_from + method + model + model_version + prompt_version."""
    syn = _mock(
        "Synthesis",
        output_claim_id="claim_001",
        derived_from=["claim_002", "claim_003"],
        method="summarization",
        model="llm-x",
        model_version="1.0",
        prompt_version="prompt_v1",
    )
    key = compute_identity_key(syn)
    assert key.startswith("id-v1:")
    assert compute_identity_key(syn) == key


def test_compute_identity_key_relation():
    """Relation: relation_type + from_ref + to_ref + context_id + validity_id."""
    rel = _mock(
        "Relation",
        relation_type="supports",
        from_ref={"object_type": "claim", "object_id": "claim_001"},
        to_ref={"object_type": "evidence", "object_id": "ev_001"},
        context_id=None,
        validity_id=None,
    )
    key = compute_identity_key(rel)
    assert key.startswith("id-v1:")
    assert compute_identity_key(rel) == key


def test_compute_identity_key_conflict_sorted():
    """Conflict: statement_a_ref/statement_b_ref 排序后 → swap a/b 得到同 key."""
    ref_a = {"object_type": "claim", "object_id": "claim_a"}
    ref_b = {"object_type": "claim", "object_id": "claim_b"}

    conflict_ab = _mock(
        "Conflict",
        statement_a_ref=ref_a,
        statement_b_ref=ref_b,
        context_a_id=None,
        context_b_id=None,
    )
    conflict_ba = _mock(
        "Conflict",
        statement_a_ref=ref_b,
        statement_b_ref=ref_a,
        context_a_id=None,
        context_b_id=None,
    )
    assert compute_identity_key(conflict_ab) == compute_identity_key(conflict_ba)


def test_compute_identity_key_unsupported_fallback():
    """未知类型 → unsupported:<type> 安全降级."""
    unknown = _mock("Foobar", x=1)
    assert compute_identity_key(unknown) == "unsupported:foobar"


# ---------- validate_identity_key ----------

def test_validate_identity_key_matching_passes():
    """identity_key 与计算一致 → passed=True."""
    src = _mock("Source", source_type="url", canonical_locator="https://example.com/a.pdf")
    src.identity_key = compute_identity_key(src)
    check = validate_identity_key(src)
    assert check.passed is True
    assert check.reasons == ()


def test_validate_identity_key_mismatch_fails():
    """identity_key 不匹配 → passed=False + identity_key_mismatch."""
    src = _mock("Source", source_type="url", canonical_locator="https://example.com/a.pdf")
    src.identity_key = "id-v1:deadbeef"  # 篡改
    check = validate_identity_key(src)
    assert check.passed is False
    assert "identity_key_mismatch" in check.reasons


def test_validate_identity_key_missing_field_fails():
    """identity_key 字段缺失 → passed=False + identity_key_field_missing."""
    src = _mock("Source", source_type="url", canonical_locator="https://example.com/a.pdf")
    # 不设置 identity_key
    check = validate_identity_key(src)
    assert check.passed is False
    assert "identity_key_field_missing" in check.reasons


def test_validate_identity_key_returns_dataclass():
    """返回 IdentityKeyCheck dataclass 含 6 字段."""
    src = _mock("Source", source_type="url", canonical_locator="https://example.com/a.pdf")
    src.identity_key = compute_identity_key(src)
    check = validate_identity_key(src)
    assert isinstance(check, IdentityKeyCheck)
    assert check.object_type == "source"
    assert check.object_id == "<unknown>"  # 无 id/ku_id
    assert check.identity_key.startswith("id-v1:")
    assert check.expected_identity_key == check.identity_key


# ---------- make_operation_id ----------

def test_make_operation_id_deterministic():
    """同一组业务输入 → 相同 operation id（跨 run 稳定）."""
    a = make_operation_id("create", "concept", "id-v1:abc", "hash123")
    b = make_operation_id("create", "concept", "id-v1:abc", "hash123")
    assert a == b


def test_make_operation_id_shape():
    """id-v1:<sha256> 形状."""
    op = make_operation_id("create", "concept", "id-v1:abc", "hash123")
    assert op.startswith("id-v1:")
    assert len(op) == len("id-v1:") + 64  # sha256 hex


def test_make_operation_id_normalizes_fields():
    """字符串字段规范化 (NFKC/strip/折叠空白/小写) 不影响 operation id."""
    a = make_operation_id(" Create ", "CONCEPT", "  ID-V1:ABC  ", "Hash")
    b = make_operation_id("create", "concept", "id-v1:abc", "hash")
    assert a == b


def test_make_operation_id_differs_on_business_input():
    """不同业务输入 → 不同 operation id."""
    a = make_operation_id("create", "concept", "id-v1:abc", "hash1")
    b = make_operation_id("create", "concept", "id-v1:abc", "hash2")
    c = make_operation_id("update", "concept", "id-v1:abc", "hash1")
    assert a != b
    assert a != c
