from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.skill_manager import manager
from src.skill_manager.agents import AgentTarget, MANAGER_MARKER_NAME
from src.skill_manager.manager import (
    apply_deployment,
    import_artifact,
    inspect_source,
    plan_deployment,
)
from src.skill_manager.storage import SkillManagerStorage
from src.skill_manager.types import SourceSpec


def _source(tmp_path: Path, text: str = "# Demo\n") -> Path:
    source = tmp_path / "demo"
    source.mkdir()
    (source / "SKILL.md").write_text(text, encoding="utf-8")
    return source


def _targets(monkeypatch: pytest.MonkeyPatch, *roots: Path) -> None:
    monkeypatch.setattr(
        manager,
        "discover_targets",
        lambda: tuple(
            AgentTarget(f"agent-{index}", root, exists=True)
            for index, root in enumerate(roots, 1)
        ),
    )


def test_import_writes_library_snapshot_but_not_agent(tmp_path: Path):
    source = _source(tmp_path)
    storage = SkillManagerStorage(tmp_path / "library")
    inspection = inspect_source(SourceSpec(source))

    artifact = import_artifact(
        SourceSpec(source),
        plan_hash=inspection.content_hash,
        confirmation="confirm",
        storage=storage,
    )

    assert artifact.artifact_id == inspection.artifact_id
    assert not (tmp_path / "agent").exists()
    assert (storage.root / "artifacts" / artifact.artifact_id / "content" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == "# Demo\n"


def test_import_plan_hash_detects_changed_source(tmp_path: Path):
    source = _source(tmp_path)
    spec = SourceSpec(source)
    before = inspect_source(spec)
    (source / "SKILL.md").write_text("# Changed\n", encoding="utf-8")

    with pytest.raises(ValueError, match="plan hash"):
        import_artifact(spec, plan_hash=before.content_hash, confirmation="confirm", storage=SkillManagerStorage(tmp_path / "library"))


def test_default_library_snapshot_can_be_revalidated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = _source(tmp_path)
    config = tmp_path / "config"
    monkeypatch.setattr("src.skill_manager.manager.config_dir", lambda: config)
    monkeypatch.setattr("src.skill_manager.storage.config_dir", lambda: config)
    inspection = inspect_source(SourceSpec(source))

    artifact = import_artifact(SourceSpec(source), plan_hash=inspection.content_hash,
                               confirmation="confirm")

    assert artifact.artifact_id.startswith("skill-")
    assert plan_deployment(artifact.artifact_id, [], storage=SkillManagerStorage()).targets == ()


def test_tampered_artifact_name_is_rejected_before_target_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = _source(tmp_path)
    storage = SkillManagerStorage(tmp_path / "library")
    inspection = inspect_source(SourceSpec(source))
    artifact = import_artifact(SourceSpec(source), plan_hash=inspection.content_hash,
                               confirmation="confirm", storage=storage)
    storage.save_artifact(replace(artifact, name="..\\escape"))
    target_root = tmp_path / "codex-skills"
    target_root.mkdir()
    _targets(monkeypatch, target_root)

    with pytest.raises(ValueError, match="Artifact name"):
        plan_deployment(artifact.artifact_id, ["agent-1"], storage=storage)


def test_deploy_is_separate_and_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = _source(tmp_path)
    storage = SkillManagerStorage(tmp_path / "library")
    inspection = inspect_source(SourceSpec(source))
    artifact = import_artifact(
        SourceSpec(source), plan_hash=inspection.content_hash, confirmation="confirm", storage=storage
    )
    target_root = tmp_path / "codex-skills"
    target_root.mkdir()
    _targets(monkeypatch, target_root)

    plan = plan_deployment(artifact.artifact_id, ["agent-1"], storage=storage)
    assert plan.targets[0].status == "ready"
    result = apply_deployment(plan, plan_hash=plan.plan_hash, confirmation="confirm", storage=storage)
    assert result.status == "succeeded"
    installed = target_root / artifact.name
    assert (installed / "SKILL.md").is_file()
    assert json.loads((installed / MANAGER_MARKER_NAME).read_text(encoding="utf-8"))["artifact_id"] == artifact.artifact_id

    repeat = apply_deployment(
        plan_deployment(artifact.artifact_id, ["agent-1"], storage=storage),
        plan_hash=plan_deployment(artifact.artifact_id, ["agent-1"], storage=storage).plan_hash,
        confirmation="confirm",
        storage=storage,
    )
    assert repeat.status == "succeeded"
    assert repeat.results[0]["action"] == "no_op"


def test_conflicts_are_reported_before_any_target_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = _source(tmp_path)
    storage = SkillManagerStorage(tmp_path / "library")
    inspection = inspect_source(SourceSpec(source))
    artifact = import_artifact(
        SourceSpec(source), plan_hash=inspection.content_hash, confirmation="confirm", storage=storage
    )
    target_root = tmp_path / "codex-skills"
    target_root.mkdir()
    conflict = target_root / artifact.name
    conflict.mkdir()
    (conflict / "SKILL.md").write_text("unmanaged", encoding="utf-8")
    _targets(monkeypatch, target_root)

    plan = plan_deployment(artifact.artifact_id, ["agent-1"], storage=storage)
    assert plan.targets[0].status == "conflict"
    result = apply_deployment(plan, plan_hash=plan.plan_hash, confirmation="confirm", storage=storage)
    assert result.status == "conflict"
    assert (conflict / "SKILL.md").read_text(encoding="utf-8") == "unmanaged"


def test_managed_content_conflict_is_not_overwritten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = _source(tmp_path)
    storage = SkillManagerStorage(tmp_path / "library")
    inspection = inspect_source(SourceSpec(source))
    artifact = import_artifact(
        SourceSpec(source), plan_hash=inspection.content_hash, confirmation="confirm", storage=storage
    )
    target_root = tmp_path / "codex-skills"
    target_root.mkdir()
    _targets(monkeypatch, target_root)
    first_plan = plan_deployment(artifact.artifact_id, ["agent-1"], storage=storage)
    apply_deployment(first_plan, plan_hash=first_plan.plan_hash, confirmation="confirm", storage=storage)
    installed = target_root / artifact.name
    (installed / "SKILL.md").write_text("changed", encoding="utf-8")

    plan = plan_deployment(artifact.artifact_id, ["agent-1"], storage=storage)
    assert plan.targets[0].status == "conflict"
    result = apply_deployment(plan, plan_hash=plan.plan_hash, confirmation="confirm", storage=storage)
    assert result.status == "conflict"
    assert (installed / "SKILL.md").read_text(encoding="utf-8") == "changed"


def test_staging_content_is_verified_before_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = _source(tmp_path)
    storage = SkillManagerStorage(tmp_path / "library")
    inspection = inspect_source(SourceSpec(source))
    artifact = import_artifact(SourceSpec(source), plan_hash=inspection.content_hash,
                               confirmation="confirm", storage=storage)
    target_root = tmp_path / "codex-skills"
    target_root.mkdir()
    _targets(monkeypatch, target_root)
    plan = plan_deployment(artifact.artifact_id, ["agent-1"], storage=storage)
    original = manager.copy_local_skill

    def tamper_after_copy(src, destination, files):
        original(src, destination, files)
        (destination / "SKILL.md").write_text("tampered", encoding="utf-8")

    monkeypatch.setattr(manager, "copy_local_skill", tamper_after_copy)
    result = apply_deployment(plan, plan_hash=plan.plan_hash, confirmation="confirm", storage=storage)

    assert result.status == "failed"
    assert not (target_root / artifact.name).exists()


def test_rollback_keeps_a_target_changed_after_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = _source(tmp_path)
    storage = SkillManagerStorage(tmp_path / "library")
    inspection = inspect_source(SourceSpec(source))
    artifact = import_artifact(SourceSpec(source), plan_hash=inspection.content_hash,
                               confirmation="confirm", storage=storage)
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir(); second.mkdir()
    _targets(monkeypatch, first, second)
    plan = plan_deployment(artifact.artifact_id, ["agent-1", "agent-2"], storage=storage)
    original = manager._install_one

    def fail_after_first(*args, **kwargs):
        if kwargs["target"].id == "agent-2":
            raise OSError("simulated install failure")
        original(*args, **kwargs)
        (first / artifact.name / "SKILL.md").write_text("user change", encoding="utf-8")

    monkeypatch.setattr(manager, "_install_one", fail_after_first)
    result = apply_deployment(plan, plan_hash=plan.plan_hash, confirmation="confirm", storage=storage)

    assert result.status == "partial_failure"
    assert (first / artifact.name / "SKILL.md").read_text(encoding="utf-8") == "user change"


def test_partial_failure_reports_compensation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = _source(tmp_path)
    storage = SkillManagerStorage(tmp_path / "library")
    inspection = inspect_source(SourceSpec(source))
    artifact = import_artifact(
        SourceSpec(source), plan_hash=inspection.content_hash, confirmation="confirm", storage=storage
    )
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    _targets(monkeypatch, first, second)
    plan = plan_deployment(artifact.artifact_id, ["agent-1", "agent-2"], storage=storage)

    original = manager._install_one

    def fail_second(*args, **kwargs):
        if kwargs["target"].id == "agent-2":
            raise OSError("simulated install failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(manager, "_install_one", fail_second)
    result = apply_deployment(plan, plan_hash=plan.plan_hash, confirmation="confirm", storage=storage)

    assert result.status == "partial_failure"
    assert not (first / artifact.name).exists()
    assert not list(tmp_path.rglob(".skill-manager-staging-*"))
