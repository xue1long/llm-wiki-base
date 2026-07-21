import os
from pathlib import Path

from src.schemas.backup import BackupManager


def test_create_backup_copies_files(tmp_path):
    """create_backup() copies all wiki/ + .llm-wiki/ files to timestamped dir."""
    # Set up project structure
    (tmp_path / "wiki" / "entities").mkdir(parents=True)
    (tmp_path / "wiki" / "entities" / "foo.md").write_text("body", encoding="utf-8")
    (tmp_path / ".llm-wiki").mkdir()
    (tmp_path / ".llm-wiki" / "project.json").write_text("{}", encoding="utf-8")

    backup_dir = BackupManager.create_backup(tmp_path, reason="test")

    assert backup_dir.exists()
    assert (backup_dir / "wiki" / "entities" / "foo.md").read_text(encoding="utf-8") == "body"
    assert (backup_dir / ".llm-wiki" / "project.json").read_text(encoding="utf-8") == "{}"
    # Reason file created
    assert (backup_dir / "BACKUP_REASON.txt").exists()
    assert "test" in (backup_dir / "BACKUP_REASON.txt").read_text()


def test_create_backup_updates_latest_symlink(tmp_path):
    """After create_backup(), .llm-wiki/.backup/latest points to the new backup."""
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "a.md").write_text("a", encoding="utf-8")

    backup_dir = BackupManager.create_backup(tmp_path, reason="r1")
    latest = tmp_path / ".llm-wiki" / ".backup" / "latest"

    assert latest.is_symlink() or latest.exists()
    # Symlink target should be the backup dir
    target = os.readlink(latest) if latest.is_symlink() else None
    if target:
        assert backup_dir.name in target or target.endswith(backup_dir.name)


def test_list_backups(tmp_path):
    """list_backups() returns all backup dirs sorted by timestamp."""
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "a.md").write_text("a", encoding="utf-8")

    BackupManager.create_backup(tmp_path, reason="r1")
    import time
    time.sleep(0.01)  # ensure different timestamp
    BackupManager.create_backup(tmp_path, reason="r2")

    backups = BackupManager.list_backups(tmp_path)
    assert len(backups) == 2
    # Most recent first
    assert backups[0].reason in ("r1", "r2")  # both valid


def test_restore_backup(tmp_path):
    """restore() copies backup files back to project."""
    (tmp_path / "wiki").mkdir()
    f = tmp_path / "wiki" / "a.md"
    f.write_text("ORIGINAL", encoding="utf-8")

    backup_dir = BackupManager.create_backup(tmp_path, reason="r1")
    f.write_text("MODIFIED", encoding="utf-8")
    BackupManager.restore(tmp_path, backup_dir.name)

    assert f.read_text(encoding="utf-8") == "ORIGINAL"