from pathlib import Path
import json

from scripts.kc_lineage_migrate import migrate


def test_migration_defaults_to_dry_run(tmp_path: Path) -> None:
    raw = tmp_path / "raw" / "sources"
    raw.mkdir(parents=True)
    (raw / "a.md").write_text("a", encoding="utf-8")

    report = migrate(tmp_path)

    assert report["dry_run"] is True
    assert report["scan_complete"] is True
    assert "backup" not in report


def test_migration_apply_backups_lineage_db(tmp_path: Path) -> None:
    raw = tmp_path / "raw" / "sources"
    raw.mkdir(parents=True)
    (raw / "a.md").write_text("a", encoding="utf-8")
    migrate(tmp_path)

    report = migrate(tmp_path, apply=True)

    assert report["dry_run"] is False
    assert Path(report["backup"]).exists()


def test_migration_marks_legacy_state_unverified(tmp_path: Path) -> None:
    (tmp_path / ".index").mkdir()
    (tmp_path / ".index" / "batch_build_state.json").write_text("{}", encoding="utf-8")

    report = migrate(tmp_path)

    assert "batch_build_state_present" in report["legacy_unverified"]


def test_migration_maps_deterministic_legacy_raw_status(tmp_path: Path) -> None:
    raw = tmp_path / "raw" / "sources"
    raw.mkdir(parents=True)
    (raw / "a.md").write_text("a", encoding="utf-8")
    index = tmp_path / ".index"
    index.mkdir()
    (index / "batch_build_state.json").write_text(json.dumps({
        "batch_0": {"raw_states": {"raw/sources/a.md": {"status": "done"}}}
    }), encoding="utf-8")

    report = migrate(tmp_path)

    assert report["legacy_migrated"] == 1
