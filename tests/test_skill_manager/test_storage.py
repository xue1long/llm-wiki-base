from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from src.skill_manager.storage import SkillManagerStorage, StorageError, manager_lock
from src.skill_manager.types import Artifact, Deployment, SourceSpec


def _artifact(tmp_path: Path) -> Artifact:
    return Artifact(
        artifact_id="skill-a" * 8,
        name="demo",
        content_hash="b" * 64,
        files=(),
        total_bytes=0,
        source=SourceSpec(tmp_path / "source"),
    )


def test_storage_uses_user_config_dir_and_round_trips_artifact_and_deployment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    config = tmp_path / "config"
    monkeypatch.setattr("src.skill_manager.storage.config_dir", lambda: config)
    storage = SkillManagerStorage()
    artifact = _artifact(tmp_path)
    deployment = Deployment("deployment-1", artifact.artifact_id, "codex", "target", artifact.content_hash)

    storage.save_artifact(artifact)
    storage.save_deployment(deployment)
    storage.write_manifest({"artifact_ids": [artifact.artifact_id]})

    assert storage.root == config / "skill-manager"
    assert storage.load_artifact(artifact.artifact_id) == artifact
    assert storage.load_deployment(deployment.deployment_id) == deployment
    assert storage.read_manifest() == {"artifact_ids": [artifact.artifact_id]}
    assert (storage.root / "artifacts" / artifact.artifact_id / "artifact.json").is_file()
    assert (storage.root / "deployments" / "deployment-1.json").is_file()
    assert not list(storage.root.rglob("*.tmp"))


def test_corrupt_json_fails_closed(tmp_path: Path):
    storage = SkillManagerStorage(tmp_path / "skill-manager")
    storage.root.mkdir(parents=True)
    (storage.root / "manifest.json").write_text("{broken", encoding="utf-8")

    with pytest.raises(StorageError) as exc_info:
        storage.read_manifest()

    assert exc_info.value.code == "STATE_CORRUPT"


def test_inflight_operations_are_failed_after_restart(tmp_path: Path):
    storage = SkillManagerStorage(tmp_path / "skill-manager")
    storage.save_operation({"id": "op-1", "status": "installing"})
    storage.save_operation({"id": "op-2", "status": "succeeded"})

    recovered = storage.recover_inflight_operations()

    assert recovered == ["op-1"]
    assert storage.load_operation("op-1")["status"] == "failed"
    assert storage.load_operation("op-1")["error_code"] == "server_restarted"
    assert storage.load_operation("op-2")["status"] == "succeeded"


def test_manager_lock_serializes_threads(tmp_path: Path):
    lock_root = tmp_path / "skill-manager"
    active = 0
    maximum = 0
    guard = threading.Lock()

    def worker() -> None:
        nonlocal active, maximum
        with manager_lock(lock_root):
            with guard:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.01)
            with guard:
                active -= 1

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert maximum == 1
