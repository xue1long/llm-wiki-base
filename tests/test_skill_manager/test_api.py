from __future__ import annotations

from pathlib import Path

from src.skill_manager.api import get_operation, list_artifacts, list_targets
from src.skill_manager.storage import SkillManagerStorage
from src.skill_manager.types import Artifact, SourceSpec


def test_public_api_lists_artifacts_targets_and_operations(tmp_path: Path, monkeypatch):
    storage = SkillManagerStorage(tmp_path / "library")
    artifact = Artifact("skill-a", "demo", "h" * 64, (), 0, SourceSpec(tmp_path / "source"))
    storage.save_artifact(artifact)
    storage.save_operation({"id": "op-1", "status": "succeeded", "artifact_id": artifact.artifact_id})
    monkeypatch.setattr("src.skill_manager.api.discover_targets", lambda: ())

    assert list_artifacts(storage=storage) == (artifact,)
    assert list_targets() == ()
    assert get_operation("op-1", storage=storage)["status"] == "succeeded"
