"""Backup manager — timestamped backups + latest/ symlink for migrations."""
import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path


_logger = logging.getLogger(__name__)


@dataclass
class BackupInfo:
    name: str                       # timestamp dir name
    path: Path
    reason: str
    created_at: float              # unix seconds


class BackupManager:
    BACKUP_ROOT = ".llm-wiki/.backup"
    LATEST_SYMLINK = "latest"

    @classmethod
    def create_backup(cls, project_path: Path, reason: str) -> Path:
        """Copy wiki/ + .llm-wiki/ to timestamped backup dir; update latest/ symlink.

        Returns the backup dir path.
        """
        project_path = Path(project_path)
        backup_root = project_path / cls.BACKUP_ROOT
        # Snapshot existing subdirs BEFORE creating backup_root (which would
        # otherwise create .llm-wiki/ and cause recursive copy on next loop).
        existing_subs = {
            sub: (project_path / sub)
            for sub in ("wiki", ".llm-wiki")
            if (project_path / sub).exists()
        }
        backup_root.mkdir(parents=True, exist_ok=True)

        timestamp = time.strftime("%Y%m%d-%H%M%S")
        # Ensure unique timestamp (append millis if collision)
        backup_dir = backup_root / timestamp
        if backup_dir.exists():
            millis = int((time.time() % 1) * 1000)
            backup_dir = backup_root / f"{timestamp}-{millis:03d}"
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Copy wiki/ and .llm-wiki/ subdirs. Ignore .backup/ inside .llm-wiki/ to
        # prevent recursing into prior backups on subsequent calls.
        def _ignore_backup(dirname, names):
            if Path(dirname).name == ".llm-wiki":
                return [n for n in names if n == ".backup"]
            return []

        for sub, src in existing_subs.items():
            dst = backup_dir / sub
            shutil.copytree(src, dst, dirs_exist_ok=True, ignore=_ignore_backup)

        # Write reason
        (backup_dir / "BACKUP_REASON.txt").write_text(reason, encoding="utf-8")

        # Update latest symlink
        latest = backup_root / cls.LATEST_SYMLINK
        if latest.is_symlink() or latest.exists():
            try:
                latest.unlink()
            except OSError:
                pass
        try:
            latest.symlink_to(backup_dir.name)
        except OSError:
            shutil.copy2(backup_dir / "BACKUP_REASON.txt", latest / "BACKUP_REASON.txt") if False else None
            # On Windows, symlinks may need admin; skip if it fails

        _logger.info(f"[backup] created {backup_dir}")
        return backup_dir

    @classmethod
    def list_backups(cls, project_path: Path) -> list[BackupInfo]:
        """List all backup dirs, sorted by timestamp descending (most recent first)."""
        backup_root = project_path / cls.BACKUP_ROOT
        if not backup_root.exists():
            return []
        backups = []
        for entry in backup_root.iterdir():
            if not entry.is_dir() or entry.name == cls.LATEST_SYMLINK:
                continue
            reason_file = entry / "BACKUP_REASON.txt"
            reason = reason_file.read_text(encoding="utf-8") if reason_file.exists() else ""
            stat = entry.stat()
            backups.append(BackupInfo(name=entry.name, path=entry, reason=reason, created_at=stat.st_mtime))
        backups.sort(key=lambda b: -b.created_at)
        return backups

    @classmethod
    def restore(cls, project_path: Path, backup_name: str) -> None:
        """Restore files from named backup, overwriting current state."""
        project_path = Path(project_path)
        backup_dir = project_path / cls.BACKUP_ROOT / backup_name
        if not backup_dir.exists():
            raise FileNotFoundError(f"Backup not found: {backup_dir}")

        for sub in ("wiki", ".llm-wiki"):
            src = backup_dir / sub
            dst = project_path / sub
            if src.exists():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
        _logger.info(f"[backup] restored from {backup_dir}")
