import hashlib
import json
import time

import pytest

from src.pipeline.task_contract import (
    InvalidTaskTransition,
    StageManifest,
    TaskContext,
    TaskLock,
    TaskState,
    claim_task,
    recover_task,
    transition,
)


def test_task_key_contains_source_template_and_contract(tmp_path):
    ctx = TaskContext.create(
        "task-1", tmp_path / "a.md", "正文",
        template_version="tpl-1", contract_version="v2",
    )
    assert ctx.idempotency_key == "v2:tpl-1:" + ctx.source_hash


def test_source_hash_is_utf8_sha256(tmp_path):
    ctx = TaskContext.create("task-1", tmp_path / "a.md", "中文", template_version="t", contract_version="v1")
    assert ctx.source_hash == hashlib.sha256("中文".encode("utf-8")).hexdigest()


def test_invalid_transition_is_rejected():
    with pytest.raises(InvalidTaskTransition):
        transition(TaskState.CREATED, TaskState.COMMITTED)


def test_lock_is_exclusive_and_owner_bound(tmp_path):
    lock = TaskLock(tmp_path)
    assert lock.acquire("key", "owner-a", stale_after_seconds=60)
    assert not lock.acquire("key", "owner-b", stale_after_seconds=60)
    lock.release("key", "owner-b")
    assert lock._path("key").exists()
    lock.release("key", "owner-a")
    assert not lock._path("key").exists()


def test_expired_lock_is_reclaimed(tmp_path):
    lock = TaskLock(tmp_path)
    assert lock.acquire("key", "owner-a", stale_after_seconds=60)
    path = lock._path("key")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["created_at"] = time.time() - 120
    path.write_text(json.dumps(data), encoding="utf-8")
    assert lock.acquire("key", "owner-b", stale_after_seconds=60)


def test_manifest_and_recovery(tmp_path):
    manifest = StageManifest(tmp_path)
    manifest.save("task-1", "analyzed", "in", "out", {"version": "v1"})
    decision = recover_task("task-1", tmp_path)
    assert decision.reusable_stages == ("analyzed",)
    assert decision.quarantined is False


def test_claim_task_is_idempotent_within_root(tmp_path, monkeypatch):
    monkeypatch.setenv("RUFLO_TASK_STATE_DIR", str(tmp_path))
    assert claim_task("same")
    assert not claim_task("same")
