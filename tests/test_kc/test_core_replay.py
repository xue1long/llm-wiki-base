"""Task 4 tests: 真实 Core 回放、备份和恢复 (P0).

Covers the 6 Step 1 scenarios from the plan:

1. Replay at latest version returns a KnowledgeObject equal to the snapshot.
2. Replay at an older version returns that older state (event-replay from
   the older snapshot's data, NOT the events between it and the latest).
3. snapshot_from_storage(paths) enumerates objects from VersionManager and
   reads events.jsonl; the identity_keys set is deterministic.
4. restore_snapshot returns a RestoreReport with identity_keys, event_hash
   (post-restore), version_count, and empty reason_codes on success.
5. Restore with a tampered events.jsonl → reason_codes contains
   "restore_mismatch" and live storage is untouched.
6. Idempotent restore: two consecutive restore_snapshot calls produce the
   same identity_keys set and the same event_hash; the second call adds no
   new events.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from src.knowledge.core.object import (
    KnowledgeObject,
    KnowledgeType,
    LifecycleState,
    Provenance,
)
from src.knowledge.core.version_manager import VersionManager, _deserialize_object
from src.wiki.storage.ensure import ensure_knowledge_base


# ── helpers ───────────────────────────────────────────────────────────────


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


def _sha256_file(path) -> str:
    """sha256 of a file's bytes; missing file → hash of empty bytes."""
    data = path.read_bytes() if path.exists() else b""
    return hashlib.sha256(data).hexdigest()


def _write_sample_events(paths, n: int = 3, stream_id: str | None = None) -> None:
    """Write *n* deterministic events to the durable events.jsonl stream."""
    events_dir = paths.index / "knowledge_graph"
    events_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps({
            "action": "ko.snapshot",
            "stream_id": stream_id or f"obj-{i}",
            "event_version": i,
            "timestamp": i * 1000,
        })
        for i in range(1, n + 1)
    ]
    (events_dir / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── Scenario 1: replay at latest == snapshot ──────────────────────────────


def test_replay_latest_returns_object_equal_to_snapshot(tmp_path):
    """replay_object(None) 重构出的对象与最新版本快照反序列化结果相等."""
    from src.knowledge.kernel import KnowledgeKernel

    paths = ensure_knowledge_base(tmp_path)
    vm = VersionManager(paths.root)
    vm.snapshot(_make_ko("ko-replay-1", content="alpha"))
    vm.snapshot(_make_ko("ko-replay-1", content="beta"))

    kernel = KnowledgeKernel(paths.root)
    result = kernel.replay_object("ko-replay-1")

    assert result.object_id == "ko-replay-1"
    assert result.version == 2  # latest
    assert result.reason_codes == ()
    assert result.object is not None

    history = vm.get_history("ko-replay-1")
    latest = history[-1]
    latest_data = vm._load_version_data("ko-replay-1", latest.version_id)
    assert result.object == _deserialize_object(latest_data)
    assert result.object.content == "beta"


# ── Scenario 2: replay at an older version returns that older state ───────


def test_replay_older_version_returns_older_state_not_events_between(tmp_path):
    """replay_object(id, version=1) 从旧版快照数据重放，返回旧状态；
    events.jsonl 中该对象的后续事件不得改变旧版本状态."""
    from src.knowledge.kernel import KnowledgeKernel

    paths = ensure_knowledge_base(tmp_path)
    vm = VersionManager(paths.root)
    vm.snapshot(_make_ko("ko-replay-2", content="alpha"))
    vm.snapshot(_make_ko("ko-replay-2", content="beta"))

    # 事件流中已有该对象在 v1 之后的事件——重放 v1 时不得应用它们
    _write_sample_events(paths, n=2, stream_id="ko-replay-2")

    kernel = KnowledgeKernel(paths.root)
    old = kernel.replay_object("ko-replay-2", version=1)
    latest = kernel.replay_object("ko-replay-2")

    assert old.version == 1
    assert old.reason_codes == ()
    assert old.object is not None
    assert old.object.content == "alpha"

    history = vm.get_history("ko-replay-2")
    v1 = history[0]
    v1_data = vm._load_version_data("ko-replay-2", v1.version_id)
    assert old.object == _deserialize_object(v1_data)
    # 不是"事件之间"的重放结果（即不是最新状态）
    assert old.object != latest.object
    assert latest.object.content == "beta"


# ── Scenario 3: snapshot_from_storage enumerates durable storage ──────────


def test_snapshot_from_storage_enumerates_from_version_manager(tmp_path):
    """snapshot_from_storage 从 VersionManager 的 _version_index.json 枚举对象，
    读取 events.jsonl；identity_keys 集合确定."""
    from src.kc.backup.core_snapshot import snapshot_from_storage

    paths = ensure_knowledge_base(tmp_path)
    vm = VersionManager(paths.root)
    vm.snapshot(_make_ko("ko-s1", content="a"))
    vm.snapshot(_make_ko("ko-s2", content="b"))
    vm.snapshot(_make_ko("ko-s1", content="a2"))  # ko-s1 的第二个版本
    _write_sample_events(paths, n=3)

    snap = snapshot_from_storage(paths)

    # 枚举自 VersionManager：ko-s1、ko-s2（无调用者传入对象）
    assert sorted(snap.identity_keys) == ["ko-s1", "ko-s2"]
    assert snap.object_count == 2
    # events.jsonl 的行数被记录为版本数
    assert snap.version_count == 3
    assert snap.spec_compliance == "Knowledge_Compiler_v2.1_§5.13_Publication_Batch"

    # snapshot.json 存的是每个对象的最新状态
    backup_dir = paths.llm_wiki / "backups" / snap.snapshot_id
    snapshot_data = json.loads((backup_dir / "snapshot.json").read_text(encoding="utf-8"))
    assert snapshot_data["ko-s1"]["content"] == "a2"

    # identity_keys 集合确定：再次 snapshot 得到相同集合 + 相同 after_hash
    snap2 = snapshot_from_storage(paths)
    assert snap2.identity_keys == snap.identity_keys
    assert snap2.after_hash == snap.after_hash


# ── Scenario 4: restore returns RestoreReport (success) ───────────────────


def test_restore_returns_restore_report_and_recovers_live_storage(tmp_path):
    """restore_snapshot 返回 RestoreReport：identity_keys、event_hash（恢复后）、
    version_count、reason_codes 为空；live 存储被恢复."""
    from src.kc.backup.core_snapshot import restore_snapshot, snapshot_from_storage

    paths = ensure_knowledge_base(tmp_path)
    vm = VersionManager(paths.root)
    vm.snapshot(_make_ko("ko-r1", content="a"))
    vm.snapshot(_make_ko("ko-r2", content="b"))
    _write_sample_events(paths, n=3)

    snap = snapshot_from_storage(paths)
    stored_hash = _sha256_file(
        paths.llm_wiki / "backups" / snap.snapshot_id / "version_events.jsonl"
    )

    # 破坏 live 存储：删除 versions 树 + events.jsonl
    shutil.rmtree(paths.root / "versions")
    events_file = paths.index / "knowledge_graph" / "events.jsonl"
    events_file.unlink()

    report = restore_snapshot(snap.snapshot_id, paths)

    assert report.snapshot_id == snap.snapshot_id
    assert report.reason_codes == ()
    assert report.identity_keys == sorted(snap.identity_keys)
    assert report.event_hash == stored_hash
    assert report.version_count == 3

    # live 存储已恢复：versions 树 + events.jsonl 字节一致
    assert (paths.root / "versions" / "ko-r1").is_dir()
    assert (paths.root / "versions" / "ko-r2").is_dir()
    assert events_file.exists()
    assert _sha256_file(events_file) == stored_hash


# ── Scenario 5: tampered events.jsonl → restore_mismatch, no overwrite ────


def test_restore_with_tampered_events_returns_mismatch_and_leaves_live_untouched(tmp_path):
    """篡改 events.jsonl 后 restore → reason_codes 含 restore_mismatch，
    且 live 存储不被覆盖."""
    from src.kc.backup.core_snapshot import restore_snapshot, snapshot_from_storage

    paths = ensure_knowledge_base(tmp_path)
    vm = VersionManager(paths.root)
    vm.snapshot(_make_ko("ko-t1", content="a"))
    _write_sample_events(paths, n=2)

    snap = snapshot_from_storage(paths)

    # 破坏 versions 树，再篡改 events.jsonl
    shutil.rmtree(paths.root / "versions")
    events_file = paths.index / "knowledge_graph" / "events.jsonl"
    tampered = '{"action":"TAMPERED"}\n'
    events_file.write_text(tampered, encoding="utf-8")
    tampered_bytes = events_file.read_bytes()

    report = restore_snapshot(snap.snapshot_id, paths)

    assert "restore_mismatch" in report.reason_codes
    # DO NOT overwrite live storage：versions 仍缺失、events.jsonl 仍是被篡改的内容
    assert not (paths.root / "versions").exists()
    assert events_file.read_bytes() == tampered_bytes
    # 报告仍携带 snapshot 的 identity_keys + 恢复时刻（被篡改）的 event_hash
    assert report.identity_keys == sorted(snap.identity_keys)
    assert report.event_hash == hashlib.sha256(tampered_bytes).hexdigest()


# ── Scenario 6: idempotent restore ────────────────────────────────────────


def test_restore_is_idempotent_no_new_events(tmp_path):
    """连续两次 restore_snapshot 产生相同 identity_keys 集合和相同 event_hash；
    第二次调用不新增事件."""
    from src.kc.backup.core_snapshot import restore_snapshot, snapshot_from_storage

    paths = ensure_knowledge_base(tmp_path)
    vm = VersionManager(paths.root)
    vm.snapshot(_make_ko("ko-i1", content="a"))
    _write_sample_events(paths, n=3)

    snap = snapshot_from_storage(paths)
    stored_hash = _sha256_file(
        paths.llm_wiki / "backups" / snap.snapshot_id / "version_events.jsonl"
    )

    shutil.rmtree(paths.root / "versions")
    (paths.index / "knowledge_graph" / "events.jsonl").unlink()

    r1 = restore_snapshot(snap.snapshot_id, paths)
    events_file = paths.index / "knowledge_graph" / "events.jsonl"
    first_hash = _sha256_file(events_file)
    first_count = sum(1 for _ in events_file.open(encoding="utf-8"))

    r2 = restore_snapshot(snap.snapshot_id, paths)

    assert r1.reason_codes == ()
    assert r2.reason_codes == ()
    assert set(r1.identity_keys) == set(r2.identity_keys)
    assert r1.event_hash == r2.event_hash
    assert first_hash == stored_hash

    # 第二次调用不新增事件：行数与字节 hash 均不变
    second_count = sum(1 for _ in events_file.open(encoding="utf-8"))
    assert second_count == first_count
    assert _sha256_file(events_file) == first_hash


# ---------------------------------------------------------------------------
# OPEN-4: real event-source replay (replay_object_from_events)
# ---------------------------------------------------------------------------


def _write_replay_events(events_dir, events: list[dict]) -> Path:
    """Write *events* as JSON lines to events.jsonl under *events_dir*.

    The schema mirrors what ``JSONLEventStore.append_event`` writes:
    ``action`` carries the event type, ``stream_id`` keys the object,
    ``event_version`` is the per-object counter, ``timestamp`` is epoch ms,
    and the remaining keys are the spread payload.
    """
    events_dir.mkdir(parents=True, exist_ok=True)
    events_file = events_dir / "events.jsonl"
    lines = [json.dumps(ev, ensure_ascii=False) for ev in events]
    events_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return events_file


def test_replay_object_from_events_returns_initial_state(tmp_path):
    """Single ``kc.object.created`` event → replay returns that payload.

    Verifies the new event-source replay surface in
    ``src.kc.integrity.replay`` — distinct from the existing snapshot-based
    ``KnowledgeKernel.replay_object`` so we can drop the
    ``event_replay_stub`` reason_code while preserving prior contracts.
    """
    from src.kc.integrity.replay import replay_object_from_events

    events_dir = tmp_path / "knowledge_graph"
    _write_replay_events(
        events_dir,
        [
            {
                "action": "kc.object.created",
                "stream_id": "ku-001",
                "event_version": 1,
                "timestamp": 1_700_000_000_000,
                "object_id": "ku-001",
                "object_type": "KnowledgeUnit",
                "content": "alpha",
                "title": "KU One",
            }
        ],
    )

    state = replay_object_from_events(
        "ku-001", target_version=1, events_dir=events_dir
    )

    assert state["object_id"] == "ku-001"
    assert state["object_type"] == "KnowledgeUnit"
    assert state["content"] == "alpha"
    assert state["title"] == "KU One"
    assert state["version"] == 1


def test_replay_object_from_events_applies_updates_in_order(tmp_path):
    """Multiple events applied in event_version order yield the correct
    state at any intermediate target_version."""
    from src.kc.integrity.replay import replay_object_from_events

    events_dir = tmp_path / "knowledge_graph"
    _write_replay_events(
        events_dir,
        [
            {
                "action": "kc.object.created",
                "stream_id": "ku-002",
                "event_version": 1,
                "timestamp": 1_700_000_001_000,
                "object_id": "ku-002",
                "object_type": "KnowledgeUnit",
                "content": "v1",
                "confidence": 0.5,
            },
            {
                "action": "kc.object.updated",
                "stream_id": "ku-002",
                "event_version": 2,
                "timestamp": 1_700_000_002_000,
                "object_id": "ku-002",
                "object_type": "KnowledgeUnit",
                "content": "v2",
            },
            {
                "action": "kc.object.updated",
                "stream_id": "ku-002",
                "event_version": 3,
                "timestamp": 1_700_000_003_000,
                "object_id": "ku-002",
                "object_type": "KnowledgeUnit",
                "confidence": 0.9,
            },
        ],
    )

    state_v1 = replay_object_from_events("ku-002", 1, events_dir=events_dir)
    state_v2 = replay_object_from_events("ku-002", 2, events_dir=events_dir)
    state_v3 = replay_object_from_events("ku-002", 3, events_dir=events_dir)

    # v1: initial state
    assert state_v1["content"] == "v1"
    assert state_v1["confidence"] == 0.5
    assert state_v1["version"] == 1

    # v2: content updated, confidence unchanged
    assert state_v2["content"] == "v2"
    assert state_v2["confidence"] == 0.5
    assert state_v2["version"] == 2

    # v3: confidence updated, content retained
    assert state_v3["content"] == "v2"
    assert state_v3["confidence"] == 0.9
    assert state_v3["version"] == 3


def test_replay_object_from_events_raises_when_object_deleted_before_target(tmp_path):
    """If a ``kc.object.deleted`` event was recorded at version K and the
    caller asks for ``target_version >= K``, replay raises — never returns
    a state the object was no longer in."""
    from src.kc.integrity.replay import (
        ObjectDeletedBeforeTargetVersion,
        replay_object_from_events,
    )

    events_dir = tmp_path / "knowledge_graph"
    _write_replay_events(
        events_dir,
        [
            {
                "action": "kc.object.created",
                "stream_id": "ev-9",
                "event_version": 1,
                "timestamp": 1_700_000_010_000,
                "object_id": "ev-9",
                "object_type": "Evidence",
                "content": "alive",
            },
            {
                "action": "kc.object.deleted",
                "stream_id": "ev-9",
                "event_version": 2,
                "timestamp": 1_700_000_011_000,
                "object_id": "ev-9",
                "object_type": "Evidence",
            },
        ],
    )

    # target_version == 1: still alive (deletion hasn't been observed yet)
    state_v1 = replay_object_from_events("ev-9", 1, events_dir=events_dir)
    assert state_v1["content"] == "alive"

    # target_version >= 2: deletion takes effect — must raise.
    for bad_version in (2, 3, 5):
        with pytest.raises(ObjectDeletedBeforeTargetVersion) as excinfo:
            replay_object_from_events("ev-9", bad_version, events_dir=events_dir)
        assert "ev-9" in str(excinfo.value)
        assert str(bad_version) in str(excinfo.value)


def test_replay_object_from_events_raises_when_target_version_exceeds_history(tmp_path):
    """When ``target_version`` is greater than the number of events for
    the object, replay raises a clear exception (distinct from the
    deletion case) so callers can distinguish the two error modes."""
    from src.kc.integrity.replay import (
        TargetVersionBeyondHistory,
        replay_object_from_events,
    )

    events_dir = tmp_path / "knowledge_graph"
    _write_replay_events(
        events_dir,
        [
            {
                "action": "kc.object.created",
                "stream_id": "sf-1",
                "event_version": 1,
                "timestamp": 1_700_000_020_000,
                "object_id": "sf-1",
                "object_type": "StructuredFact",
                "content": "fact",
            }
        ],
    )

    with pytest.raises(TargetVersionBeyondHistory) as excinfo:
        replay_object_from_events("sf-1", 2, events_dir=events_dir)
    assert "sf-1" in str(excinfo.value)
    assert "1" in str(excinfo.value)  # actual history length


def test_replay_object_from_events_returns_none_when_object_unknown(tmp_path):
    """Unknown object_id → ``None`` (consistent with the snapshot
    surface's ``unknown_object_id`` reason code)."""
    from src.kc.integrity.replay import replay_object_from_events

    events_dir = tmp_path / "knowledge_graph"
    _write_replay_events(
        events_dir,
        [
            {
                "action": "kc.object.created",
                "stream_id": "ku-known",
                "event_version": 1,
                "timestamp": 1_700_000_030_000,
                "object_id": "ku-known",
                "object_type": "KnowledgeUnit",
                "content": "x",
            }
        ],
    )

    assert replay_object_from_events("ku-missing", 1, events_dir=events_dir) is None


def test_replay_object_from_events_supports_multiple_object_types(tmp_path):
    """The event-source replay surface must accept the same
    ``KnowledgeUnit`` / ``Evidence`` / ``StructuredFact`` / ``Approval``
    / ``PublicationBatch`` shape — the dispatch happens by the
    ``object_type`` field on each event, not by hardcoded branches."""
    from src.kc.integrity.replay import replay_object_from_events

    events_dir = tmp_path / "knowledge_graph"
    _write_replay_events(
        events_dir,
        [
            {
                "action": "kc.object.created",
                "stream_id": "ku-A",
                "event_version": 1,
                "timestamp": 1_700_000_040_000,
                "object_id": "ku-A",
                "object_type": "KnowledgeUnit",
                "content": "ku",
            },
            {
                "action": "kc.object.created",
                "stream_id": "ev-A",
                "event_version": 1,
                "timestamp": 1_700_000_041_000,
                "object_id": "ev-A",
                "object_type": "Evidence",
                "content": "ev",
            },
            {
                "action": "kc.object.created",
                "stream_id": "sf-A",
                "event_version": 1,
                "timestamp": 1_700_000_042_000,
                "object_id": "sf-A",
                "object_type": "StructuredFact",
                "content": "sf",
            },
            {
                "action": "kc.object.created",
                "stream_id": "ap-A",
                "event_version": 1,
                "timestamp": 1_700_000_043_000,
                "object_id": "ap-A",
                "object_type": "Approval",
                "content": "ap",
            },
            {
                "action": "kc.object.created",
                "stream_id": "pb-A",
                "event_version": 1,
                "timestamp": 1_700_000_044_000,
                "object_id": "pb-A",
                "object_type": "PublicationBatch",
                "content": "pb",
            },
        ],
    )

    for object_id, expected_type in [
        ("ku-A", "KnowledgeUnit"),
        ("ev-A", "Evidence"),
        ("sf-A", "StructuredFact"),
        ("ap-A", "Approval"),
        ("pb-A", "PublicationBatch"),
    ]:
        state = replay_object_from_events(object_id, 1, events_dir=events_dir)
        assert state["object_type"] == expected_type
        assert state["version"] == 1


def test_replay_object_from_events_uses_event_ordering_from_jsonl_file(tmp_path):
    """Out-of-order ``event_version`` values on disk (e.g. write races,
    recovery) still produce correct state because replay sorts by
    ``event_version`` — the contract OPEN-1's file lock makes cheap but
    the replay surface must remain correct without it."""
    from src.kc.integrity.replay import replay_object_from_events

    events_dir = tmp_path / "knowledge_graph"
    _write_replay_events(
        events_dir,
        [
            # Intentionally written with v3 first, then v1, then v2.
            {
                "action": "kc.object.updated",
                "stream_id": "ku-order",
                "event_version": 3,
                "timestamp": 1_700_000_050_000,
                "object_id": "ku-order",
                "object_type": "KnowledgeUnit",
                "content": "v3",
            },
            {
                "action": "kc.object.created",
                "stream_id": "ku-order",
                "event_version": 1,
                "timestamp": 1_700_000_051_000,
                "object_id": "ku-order",
                "object_type": "KnowledgeUnit",
                "content": "v1",
            },
            {
                "action": "kc.object.updated",
                "stream_id": "ku-order",
                "event_version": 2,
                "timestamp": 1_700_000_052_000,
                "object_id": "ku-order",
                "object_type": "KnowledgeUnit",
                "content": "v2",
            },
        ],
    )

    state_v2 = replay_object_from_events("ku-order", 2, events_dir=events_dir)
    assert state_v2["content"] == "v2"

    state_v3 = replay_object_from_events("ku-order", 3, events_dir=events_dir)
    assert state_v3["content"] == "v3"


def test_replay_object_from_events_skips_unrelated_streams(tmp_path):
    """Events for *other* objects in the same file must not leak into the
    replayed state for ``object_id``."""
    from src.kc.integrity.replay import replay_object_from_events

    events_dir = tmp_path / "knowledge_graph"
    _write_replay_events(
        events_dir,
        [
            {
                "action": "kc.object.created",
                "stream_id": "ku-X",
                "event_version": 1,
                "timestamp": 1_700_000_060_000,
                "object_id": "ku-X",
                "object_type": "KnowledgeUnit",
                "content": "X",
            },
            {
                "action": "kc.object.updated",
                "stream_id": "ku-Y",
                "event_version": 2,
                "timestamp": 1_700_000_061_000,
                "object_id": "ku-Y",
                "object_type": "KnowledgeUnit",
                "content": "Y",
            },
        ],
    )

    state_x = replay_object_from_events("ku-X", 1, events_dir=events_dir)
    assert state_x["content"] == "X"
    assert "version" in state_x and state_x["version"] == 1


def test_existing_event_replay_stub_placeholder_is_not_depended_on_by_new_surface(tmp_path):
    """The new ``replay_object_from_events`` is independent of the
    snapshot-based :meth:`KnowledgeKernel.replay_object` and the
    ``event_replay_stub`` reason code in
    :meth:`KnowledgeKernel.replay_core_from_events`. Both prior surfaces
    remain unchanged; this test freezes the new surface's independence
    so a future refactor doesn't silently couple them."""
    from src.kc.integrity.replay import replay_object_from_events

    events_dir = tmp_path / "knowledge_graph"
    _write_replay_events(
        events_dir,
        [
            {
                "action": "kc.object.created",
                "stream_id": "ku-indep",
                "event_version": 1,
                "timestamp": 1_700_000_070_000,
                "object_id": "ku-indep",
                "object_type": "KnowledgeUnit",
                "content": "independent",
            }
        ],
    )

    # The new surface resolves state purely from the JSONL file — no
    # VersionManager involvement, no event_replay_stub reason code.
    state = replay_object_from_events("ku-indep", 1, events_dir=events_dir)
    assert state is not None
    assert state["content"] == "independent"
    assert "event_replay_stub" not in state
