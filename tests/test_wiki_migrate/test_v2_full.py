import json

import pytest

from src.wiki.migrate import v2_full


def _fixture(tmp_path):
    source = tmp_path / "v2"
    target = tmp_path / "target"
    (source / "10_raw" / "01_B站视频转录").mkdir(parents=True)
    (source / "20_wiki").mkdir(parents=True)
    (source / "10_raw" / "01_B站视频转录" / "one.txt").write_text("raw", encoding="utf-8")
    (source / "20_wiki" / "card.md").write_text(
        "---\ntitle: Card\ntype: concept\n---\n\nbody\n", encoding="utf-8"
    )
    (target / ".llm-wiki").mkdir(parents=True)
    (target / ".llm-wiki" / "project.json").write_text(
        json.dumps({"id": "project-1"}), encoding="utf-8"
    )
    return source, target


def _ample_disk(monkeypatch):
    usage = type("Usage", (), {"free": 20 * 1024 * 1024 * 1024})()
    monkeypatch.setattr(v2_full.shutil, "disk_usage", lambda _: usage)


def test_apply_resume_skips_completed_staged_outputs(tmp_path, monkeypatch):
    source, target = _fixture(tmp_path)
    _ample_disk(monkeypatch)
    real_copy = v2_full.copy_raw_file
    calls = 0

    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("injected interruption")
        return real_copy(*args, **kwargs)

    monkeypatch.setattr(v2_full, "copy_raw_file", fail_once)
    with pytest.raises(RuntimeError, match="injected interruption"):
        v2_full.migrate_v2(target, source, run_id="resume-1", apply=True)

    result = v2_full.migrate_v2(
        target, source, run_id="resume-1", apply=True, resume=True
    )
    assert result["promoted"] is True
    assert (target / "raw" / "sources" / "01_B站视频转录" / "one.txt").exists()
    assert (target / ".index" / "migration" / "runs" / "resume-1" / "promoted_paths.json").exists()


def test_successful_run_can_be_rolled_back_by_run_id(tmp_path, monkeypatch):
    source, target = _fixture(tmp_path)
    _ample_disk(monkeypatch)
    result = v2_full.migrate_v2(target, source, run_id="rollback-1", apply=True)

    preview = v2_full.migrate_v2(
        target, source, run_id="rollback-1", rollback=True, apply=False
    )
    assert preview.applied is False
    assert preview.removed_paths

    applied = v2_full.migrate_v2(
        target, source, run_id="rollback-1", rollback=True, apply=True
    )
    assert applied.applied is True
    assert not (target / "raw" / "sources" / "01_B站视频转录" / "one.txt").exists()
    assert not (target / "wiki" / "concepts" / "card.md").exists()
    assert result["run_record_path"]


def test_collision_is_detected_before_any_promotion(tmp_path, monkeypatch):
    source, target = _fixture(tmp_path)
    _ample_disk(monkeypatch)
    existing = target / "raw" / "sources" / "01_B站视频转录" / "one.txt"
    existing.parent.mkdir(parents=True)
    existing.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError, match="target collision"):
        v2_full.migrate_v2(target, source, run_id="collision-1", apply=True)

    assert existing.read_text(encoding="utf-8") == "keep"
    assert not (target / "wiki" / "concepts" / "card.md").exists()


def test_dry_run_writes_auditable_reports_and_disk_result(tmp_path):
    source, target = _fixture(tmp_path)
    result = v2_full.migrate_v2(target, source, run_id="audit-1", apply=False)
    staging = target / ".index" / "staging" / "audit-1"

    assert result["dry_run"] is True
    assert "passed" in result["disk_preflight"]
    assert (staging / "migration-manifest.json").exists()
    assert (staging / "migration_report.csv").exists()
    assert (staging / "migration_warnings.csv").exists()
    assert (staging / "pending_decisions.csv").exists()
