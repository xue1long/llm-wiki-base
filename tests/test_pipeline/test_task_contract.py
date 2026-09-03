import hashlib
import json
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor

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
    assert not lock.acquire("key", "owner-b", stale_after_seconds=60)
    assert lock.reclaim("key", "recovery", stale_after_seconds=60)
    assert lock.acquire("key", "owner-b", stale_after_seconds=60)
    lock.release("key", "owner-a")
    assert lock._path("key").exists()


def test_manifest_and_recovery(tmp_path):
    manifest = StageManifest(tmp_path)
    manifest.save("task-1", "analyzed", "in", "out", {"version": "v1"})
    decision = recover_task("task-1", tmp_path)
    assert decision.reusable_stages == ("analyzed",)
    assert decision.quarantined is False


def test_recovery_mismatched_context_quarantines(tmp_path):
    manifest = StageManifest(tmp_path)
    manifest.save("task/unsafe", "generated", "in", "out", {
        "task_context": {"source_hash": "old", "template_version": "tpl", "contract_version": "v1"},
    })
    expected = TaskContext.create("task/unsafe", "a.md", "new", template_version="tpl", contract_version="v1")
    decision = recover_task("task/unsafe", tmp_path, expected_context=expected)
    assert decision.quarantined
    assert not (tmp_path / "staging" / "task" / "unsafe").exists()
    assert decision.quarantine_path.name != "unsafe"


def test_committed_manifest_is_reported_as_completed(tmp_path):
    manifest = StageManifest(tmp_path)
    ctx = TaskContext.create("done", tmp_path / "source.md", "正文", template_version="tpl", contract_version="v1")
    metadata = {"task_context": ctx.to_dict()}
    manifest.save("done", "committed", ctx.source_hash, ctx.source_hash, metadata)
    decision = recover_task("done", tmp_path, expected_context=ctx)
    assert decision.completed is True


def test_manifest_updates_are_serialized(tmp_path):
    manifest = StageManifest(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda stage: manifest.save("task", stage, "i", stage, {}), ("a", "b")))
    data = json.loads((tmp_path / "staging" / "task" / "manifest.json").read_text(encoding="utf-8"))
    assert set(data["stages"]) == {"a", "b"}


def test_claim_task_is_idempotent_within_root(tmp_path, monkeypatch):
    monkeypatch.setenv("RUFLO_TASK_STATE_DIR", str(tmp_path))
    assert claim_task("same")
    assert not claim_task("same")


def test_run_ingest_claims_locks_and_stages(monkeypatch, tmp_path):
    import src.pipeline.ingest as ingest
    from src.wiki.core.paths import WikiPaths

    async def fake_generate(**kwargs):
        return [], [], {"rejected": False}

    async def fake_commit(**kwargs):
        return None

    monkeypatch.setattr(ingest, "generate_ingest", fake_generate)
    monkeypatch.setattr(ingest, "commit_ingest", fake_commit)
    asyncio.run(ingest.run_ingest(WikiPaths(tmp_path), tmp_path / "a.md", "正文", object(), task_id="task/unsafe"))
    manifest = next((tmp_path / ".index" / "staging").glob("*/manifest.json"))
    assert {"created", "analyzed", "reviewed", "generated", "validated", "committed"} <= set(
        json.loads(manifest.read_text(encoding="utf-8"))["stages"]
    )
    assert not list((tmp_path / ".index" / "task_locks").glob("*"))
