from __future__ import annotations

import json

import pytest

from src.wiki.migrate.v2_manifest import CheckpointItem
from src.wiki.migrate.v2_run_state import (
    RunState,
    RunStateError,
    load_run_state,
    run_state_path,
    save_run_state,
    write_checkpoint,
    load_checkpoint,
    rollback_run,
)


def _project(root, project_uuid="project-uuid"):
    (root / ".llm-wiki").mkdir(parents=True)
    (root / ".llm-wiki" / "project.json").write_text(
        json.dumps({"id": project_uuid, "name": "test"}), encoding="utf-8"
    )


def test_run_state_round_trips_atomically_and_has_required_fields(tmp_path):
    _project(tmp_path)
    state = RunState(
        run_id="run-001",
        project_uuid="project-uuid",
        source_root="D:/v2",
        manifest_hash="a" * 64,
        phase="raw",
        checkpoint={"raw": "10_raw/a.txt"},
        counts={"done": 1},
    )

    path = save_run_state(tmp_path, state)
    assert path == run_state_path(tmp_path, "run-001")
    restored = load_run_state(tmp_path, "run-001", manifest_hash="a" * 64)
    assert restored.to_dict() == state.to_dict()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert set(
        [
            "run_id",
            "project_uuid",
            "source_root",
            "manifest_hash",
            "phase",
            "checkpoint",
            "counts",
            "failure_reason",
        ]
    ) <= payload.keys()


def test_checkpoint_is_idempotent_filtered_by_run_and_rejects_escape(tmp_path):
    checkpoint_path = tmp_path / "run" / "migration_progress.jsonl"
    item = CheckpointItem(
        run_id="run-001", source_path="10_raw/a.txt", phase="raw", status="done"
    )
    write_checkpoint(checkpoint_path, item)
    write_checkpoint(checkpoint_path, item)
    write_checkpoint(
        checkpoint_path,
        CheckpointItem(
            run_id="run-002", source_path="10_raw/other.txt", phase="raw", status="done"
        ),
    )

    assert load_checkpoint(checkpoint_path, "run-001") == {"10_raw/a.txt"}
    assert len(checkpoint_path.read_text(encoding="utf-8").splitlines()) == 2

    with pytest.raises(RunStateError, match="checkpoint path"):
        write_checkpoint(tmp_path / "outside.jsonl", item)


def test_run_state_rejects_manifest_change_and_project_mismatch(tmp_path):
    _project(tmp_path)
    state = RunState(
        run_id="run-001",
        project_uuid="project-uuid",
        source_root="D:/v2",
        manifest_hash="a" * 64,
    )
    save_run_state(tmp_path, state)

    with pytest.raises(RunStateError, match="manifest hash"):
        load_run_state(tmp_path, "run-001", manifest_hash="b" * 64)
    with pytest.raises(RunStateError, match="project UUID"):
        save_run_state(tmp_path, RunState(
            run_id="run-002",
            project_uuid="other",
            source_root="D:/v2",
            manifest_hash="a" * 64,
        ))


def test_phase_completion_pause_and_failure_are_persistable(tmp_path):
    _project(tmp_path)
    state = RunState(
        run_id="run-001",
        project_uuid="project-uuid",
        source_root="D:/v2",
        manifest_hash="a" * 64,
    )
    state.complete_phase("raw", checkpoint={"last": "a"}, counts={"done": 1})
    assert state.phase == "raw"
    assert state.status == "phase-complete"
    state.pause("operator stopped")
    assert state.status == "paused"
    assert state.failure_reason == "operator stopped"
    state.fail("source changed")
    assert state.status == "failed"
    assert state.failure_reason == "source changed"
    save_run_state(tmp_path, state)


def test_rollback_dry_run_and_apply_are_scoped_to_authenticated_run(tmp_path):
    _project(tmp_path)
    state = RunState(
        run_id="run-001",
        project_uuid="project-uuid",
        source_root="D:/v2",
        manifest_hash="a" * 64,
        phase="promotion",
    )
    staging = tmp_path / ".index" / "staging" / "run-001"
    staging.mkdir(parents=True)
    (staging / "created.txt").write_text("created", encoding="utf-8")
    save_run_state(tmp_path, state)
    unrelated = tmp_path / ".index" / "staging" / "other-run" / "keep.txt"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("keep", encoding="utf-8")

    preview = rollback_run(tmp_path, "run-001", dry_run=True)
    assert preview.run_id == "run-001"
    assert preview.removed_paths
    assert staging.exists()
    assert unrelated.exists()

    result = rollback_run(tmp_path, "run-001", dry_run=False)
    assert result.applied is True
    assert not staging.exists()
    assert unrelated.exists()
