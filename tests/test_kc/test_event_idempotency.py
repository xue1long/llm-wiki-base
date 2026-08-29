"""Task 3 tests: 统一 identity 和事件幂等 (P0).

Covers the Step 1 scenarios:
  1. same content different run_id → same operation_id + no duplicate event
  2. concurrent duplicate ingest → idempotent (one event)
  3. same operation_id different payload → version_conflict
  4. out-of-order event replay → still idempotent
  5. identity_key change (a field changes) → identity key actually changes (sanity)
  6. repeated create/update on same KnowledgeObject identity → no new VersionRef
"""
from __future__ import annotations

from src.kc.integrity.identity_key import compute_identity_key, make_operation_id
from src.knowledge.core.object import (
    KnowledgeType,
    LifecycleState,
    Provenance,
    KnowledgeObject,
)
from src.knowledge.core.version_manager import VersionManager
from src.knowledge.storage.event_store import JSONLEventStore, compute_payload_hash


def _mock(obj_type: str, **fields):
    """Build a mock object whose class name matches obj_type (so
    `type(obj).__name__.lower()` returns the expected dispatch key).
    """
    cls = type(obj_type, (), {})
    obj = cls.__new__(cls)
    for k, v in fields.items():
        setattr(obj, k, v)
    return obj


def _make_ko(obj_id: str, content: str, title: str = "Test Object") -> KnowledgeObject:
    """Deterministic KnowledgeObject (created_at/updated_at default to 0)."""
    return KnowledgeObject(
        id=obj_id,
        type=KnowledgeType.ENTITY,
        title=title,
        content=content,
        lifecycle=LifecycleState.CREATED,
        confidence=0.9,
        provenance=Provenance(source_path="/test.md"),
    )


# --- Scenario 1: same content, different run_id ------------------------------


def test_same_content_different_run_id_same_operation_id_and_no_duplicate(tmp_path):
    """run_id 不属于 identity 输入 → 相同内容跨 run 得到相同 identity key 和
    operation id；重复 ingest 只写一个事件。"""
    store = JSONLEventStore(index_path=tmp_path)
    payload = {"source_type": "url", "canonical_locator": "https://example.com/a.pdf"}

    run1 = _mock("Source", source_type="url",
                 canonical_locator="https://example.com/a.pdf", run_id="run_1")
    run2 = _mock("Source", source_type="url",
                 canonical_locator="https://example.com/a.pdf", run_id="run_2")

    key1 = compute_identity_key(run1)
    key2 = compute_identity_key(run2)
    assert key1 == key2  # identity 是内容驱动的，run_id 被忽略

    op1 = make_operation_id("ingest", "source", key1, compute_payload_hash(payload))
    op2 = make_operation_id("ingest", "source", key2, compute_payload_hash(payload))
    assert op1 == op2  # 操作键只含规范化业务输入，不含随机 run id

    r1 = store.append_event("src_a", "source_ingested", dict(payload), operation_id=op1)
    r2 = store.append_event("src_a", "source_ingested", dict(payload), operation_id=op2)
    assert r1["status"] == "ok"
    assert r2["status"] == "duplicate"
    assert store.count() == 1
    assert store.count("src_a") == 1


# --- Scenario 2: concurrent duplicate ingest ---------------------------------


def test_concurrent_duplicate_ingest_is_idempotent(tmp_path):
    """两个 store 实例指向同一文件（并发 ingest 模拟）：第二个实例冷启动后
    识别已记录的 operation，不再写入。"""
    payload = {"source": "https://example.com/b.pdf"}
    key = compute_identity_key(_mock("Source", source_type="url",
                                     canonical_locator="https://example.com/b.pdf"))
    op = make_operation_id("ingest", "source", key, compute_payload_hash(payload))

    store1 = JSONLEventStore(index_path=tmp_path)
    r1 = store1.append_event("src_b", "source_ingested", dict(payload), operation_id=op)

    store2 = JSONLEventStore(index_path=tmp_path)  # cold-start on same file
    r2 = store2.append_event("src_b", "source_ingested", dict(payload), operation_id=op)

    assert r1["status"] == "ok"
    assert r2["status"] == "duplicate"
    assert r2["event"]["operation_id"] == op
    assert store1.count() == 1


# --- Scenario 3: same operation_id, different payload ------------------------


def test_same_operation_id_different_payload_returns_version_conflict(tmp_path):
    """同一 operation id 下 payload 不同 → fail-closed version_conflict，
    且不写第二个事件。"""
    store = JSONLEventStore(index_path=tmp_path)
    key = compute_identity_key(_mock("Source", source_type="url",
                                     canonical_locator="https://example.com/a.pdf"))
    op = make_operation_id("ingest", "source", key,
                           compute_payload_hash({"canonical_locator": "https://example.com/a.pdf"}))

    r1 = store.append_event("s", "source_ingested",
                            {"canonical_locator": "https://example.com/a.pdf"}, operation_id=op)
    assert r1["status"] == "ok"

    r2 = store.append_event("s", "source_ingested",
                            {"canonical_locator": "https://example.com/DIFFERENT.pdf"}, operation_id=op)
    assert r2["status"] == "version_conflict"
    assert r2["stored_payload_hash"] == r1["event"]["payload_hash"]
    assert store.count() == 1  # 冲突时不写任何事件


# --- Scenario 4: out-of-order replay -----------------------------------------


def test_out_of_order_event_replay_is_idempotent(tmp_path):
    """较早版本的事件在较新版本已记录之后重放 → 返回原事件，不写重复。"""
    store = JSONLEventStore(index_path=tmp_path)
    key = compute_identity_key(_mock("Concept", concept_type="entity",
                                     canonical_name="MCP", identity_scope_id="scope_001"))
    op_create = make_operation_id("create", "concept", key,
                                  compute_payload_hash({"name": "MCP"}))
    op_update = make_operation_id("update", "concept", key,
                                  compute_payload_hash({"name": "MCP", "note": "x"}))

    r_create = store.append_event("concept_1", "concept_created",
                                  {"name": "MCP"}, operation_id=op_create)
    r_update = store.append_event("concept_1", "concept_updated",
                                  {"name": "MCP", "note": "x"}, operation_id=op_update)
    assert r_create["status"] == "ok"
    assert r_update["status"] == "ok"
    assert r_update["event"]["event_version"] == 2

    # 乱序重放较早的事件
    r_replay = store.append_event("concept_1", "concept_created",
                                  {"name": "MCP"}, operation_id=op_create)
    assert r_replay["status"] == "duplicate"
    assert r_replay["event"]["event_version"] == 1
    assert store.count() == 2


# --- Scenario 5: identity_key change (sanity) --------------------------------


def test_identity_key_changes_when_identity_field_changes():
    """identity 字段变化 → identity key 变化（进而 operation id 变化）——
    sanity：identity 不是常量。"""
    a = _mock("Source", source_type="url", canonical_locator="https://example.com/a.pdf")
    b = _mock("Source", source_type="url", canonical_locator="https://example.com/b.pdf")
    key_a = compute_identity_key(a)
    key_b = compute_identity_key(b)
    assert key_a != key_b

    op_a = make_operation_id("ingest", "source", key_a, "hash")
    op_b = make_operation_id("ingest", "source", key_b, "hash")
    assert op_a != op_b


# --- Scenario 6: repeated create/update on same identity ---------------------


def test_repeated_create_update_same_identity_no_new_versionref(tmp_path):
    """同一 KnowledgeObject identity 的重复 create/update（新实例、规范内容
    相同）不新增 VersionRef。"""
    vm = VersionManager(tmp_path)

    v1 = vm.snapshot(_make_ko("ko-001", content="original"))
    assert len(vm.get_history("ko-001")) == 1

    # 重复 ingest：新实例 + 相同 identity + 相同内容 → 不新增版本
    v2 = vm.snapshot(_make_ko("ko-001", content="original"))
    assert v2.version_id == v1.version_id
    assert len(vm.get_history("ko-001")) == 1

    # 真实内容变化仍产生新版本
    v3 = vm.snapshot(_make_ko("ko-001", content="updated"))
    assert v3.version_id != v1.version_id
    assert len(vm.get_history("ko-001")) == 2

    # 更新的重复版本对最近快照去重
    v4 = vm.snapshot(_make_ko("ko-001", content="updated"))
    assert v4.version_id == v3.version_id
    assert len(vm.get_history("ko-001")) == 2
