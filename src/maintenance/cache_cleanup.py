"""Unified cache cleanup for ruflo-kb project-level caches.

Each function returns the count of deleted/rotated items and is idempotent
(safe to call on missing directories/files). Use ``cleanup_all()`` as the
single entry point for batch cleanup.

TTL defaults follow the constants already defined in each feature module.
"""
import logging
import shutil
import time
from pathlib import Path

from ..wiki.core.paths import WikiPaths

_logger = logging.getLogger(__name__)

# ── defaults (mirrors the constants in each feature module) ──────────────
DEFAULT_LINT_CACHE_MAX_AGE_HOURS = 24
DEFAULT_HEAT_LOG_MAX_SIZE_MB = 10
DEFAULT_HEAT_LOG_KEEP = 3
DEFAULT_STAGING_MAX_AGE_DAYS = 30
DEFAULT_QUARANTINE_MAX_AGE_DAYS = 90
DEFAULT_DEDUP_HISTORY_MAX_AGE_DAYS = 30
DEFAULT_BACKUP_MAX_COUNT = 10

# C-0.5a: Knowledge Core snapshot retention (Z-1, spec §1 M-7).
# Distinct from DEFAULT_BACKUP_MAX_COUNT which targets the schema-migration
# ``.llm-wiki/.backup/`` directory. KC snapshots live under
# ``.llm-wiki/backups/<snap_<ts>>/`` and are kept (max_count=10) before
# rotation kicks in.
DEFAULT_KC_BACKUP_MAX_COUNT = 10


# ── helpers ───────────────────────────────────────────────────────────────

def _now_ms() -> int:
    return int(time.time() * 1000)


def _older_than_ms(path: Path, max_age_ms: int) -> bool:
    """True if *path*'s mtime is older than *max_age_ms* milliseconds."""
    try:
        stat = path.stat()
    except FileNotFoundError:
        return False
    return (_now_ms() - int(stat.st_mtime * 1000)) > max_age_ms


# ── per-cache cleaners ────────────────────────────────────────────────────

def cleanup_lint_cache(
    paths: WikiPaths,
    max_age_hours: int = DEFAULT_LINT_CACHE_MAX_AGE_HOURS,
) -> int:
    """Delete lint cache entries older than *max_age_hours*.

    Stale entries are detected lazily by the ``get()`` function (TTL check on
    read), but the JSON files themselves are never deleted until this function
    runs.  This sweeper removes those orphaned files.
    """
    cache_dir = paths.index / "lint_cache"
    if not cache_dir.exists():
        return 0
    max_age_ms = max_age_hours * 3600 * 1000
    deleted = 0
    for f in cache_dir.glob("*.json"):
        if _older_than_ms(f, max_age_ms):
            try:
                f.unlink()
            except OSError:
                pass
            else:
                deleted += 1
    if deleted:
        _logger.info("[cleanup] lint_cache: %d stale entries deleted", deleted)
    return deleted


def rotate_heat_log(
    paths: WikiPaths,
    max_size_mb: int = DEFAULT_HEAT_LOG_MAX_SIZE_MB,
    keep: int = DEFAULT_HEAT_LOG_KEEP,
) -> int:
    """Rotate ``heat_events.log`` when it exceeds *max_size_mb*.

    Keeps *keep* old copies named ``heat_events.log.1``, ``.2``, etc.
    Returns 1 if rotation occurred, 0 otherwise.
    """
    log_path = paths.index / "heat_events.log"
    if not log_path.exists():
        return 0
    size_mb = log_path.stat().st_size / (1024 * 1024)
    if size_mb < max_size_mb:
        return 0

    # Shift existing backups: .2 → .3, .1 → .2
    for i in range(keep - 1, 0, -1):
        older = paths.index / f"heat_events.log.{i}"
        newer = paths.index / f"heat_events.log.{i + 1}"
        if older.exists():
            shutil.move(str(older), str(newer))
    # Rotate current log → .1
    shutil.move(str(log_path), str(paths.index / "heat_events.log.1"))
    _logger.info("[cleanup] heat_events.log rotated (was %.1f MB)", size_mb)
    return 1


def cleanup_staging(
    paths: WikiPaths,
    max_age_days: int = DEFAULT_STAGING_MAX_AGE_DAYS,
) -> int:
    """Delete zombie staging drafts older than *max_age_days*."""
    staging_dir = paths.index / "staging"
    if not staging_dir.exists():
        return 0
    max_age_ms = max_age_days * 86400 * 1000
    deleted = 0
    for f in staging_dir.glob("*.md"):
        if _older_than_ms(f, max_age_ms):
            try:
                f.unlink()
            except OSError:
                pass
            else:
                deleted += 1
    if deleted:
        _logger.info("[cleanup] staging: %d zombie drafts deleted", deleted)
    return deleted


def cleanup_quarantine(
    paths: WikiPaths,
    max_age_days: int = DEFAULT_QUARANTINE_MAX_AGE_DAYS,
) -> int:
    """Delete quarantined pages + judgments older than *max_age_days*."""
    quarantine_root = paths.index / "quarantine"
    if not quarantine_root.exists():
        return 0
    max_age_ms = max_age_days * 86400 * 1000
    deleted = 0
    for task_dir in quarantine_root.iterdir():
        if not task_dir.is_dir():
            continue
        for f in task_dir.glob("*"):
            if _older_than_ms(f, max_age_ms):
                try:
                    f.unlink()
                except OSError:
                    pass
                else:
                    deleted += 1
        # Remove empty task directories
        if not any(task_dir.iterdir()):
            try:
                task_dir.rmdir()
            except OSError:
                pass
    if deleted:
        _logger.info("[cleanup] quarantine: %d items deleted", deleted)
    return deleted


def cleanup_dedup_history(
    paths: WikiPaths,
    max_age_days: int = DEFAULT_DEDUP_HISTORY_MAX_AGE_DAYS,
) -> int:
    """Delete dedup merge records older than *max_age_days*.

    This enforces the ``RETENTION_DAYS = 30`` constant in
    ``src/wiki/features/dedup_auto.py``, which was previously declared but
    never enforced.
    """
    history_root = paths.index / "dedup_history"
    if not history_root.exists():
        return 0
    max_age_ms = max_age_days * 86400 * 1000
    deleted = 0
    for entry in history_root.iterdir():
        if entry.is_dir():
            # Record directory — delete entirely if all files are stale
            all_stale = True
            for f in entry.rglob("*"):
                if f.is_file() and not _older_than_ms(f, max_age_ms):
                    all_stale = False
                    break
            if all_stale:
                try:
                    shutil.rmtree(entry)
                except OSError:
                    pass
                else:
                    deleted += 1
        elif entry.suffix == ".json":
            if _older_than_ms(entry, max_age_ms):
                try:
                    entry.unlink()
                except OSError:
                    pass
                else:
                    deleted += 1
    if deleted:
        _logger.info("[cleanup] dedup_history: %d records deleted", deleted)
    return deleted


def cleanup_backups(
    paths: WikiPaths,
    max_count: int = DEFAULT_BACKUP_MAX_COUNT,
) -> int:
    """Keep only the *max_count* most recent schema backups."""
    backup_root = paths.llm_wiki / ".backup"
    if not backup_root.exists():
        return 0
    dirs = sorted(
        (d for d in backup_root.iterdir() if d.is_dir() and d.name != "latest"),
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    deleted = 0
    for d in dirs[max_count:]:
        try:
            shutil.rmtree(d)
        except OSError:
            pass
        else:
            deleted += 1
    if deleted:
        _logger.info("[cleanup] backups: %d old backups deleted", deleted)
    return deleted


def cleanup_kc_backups(
    paths: WikiPaths,
    max_count: int = DEFAULT_KC_BACKUP_MAX_COUNT,
) -> int:
    """Keep only the *max_count* most recent Knowledge Core snapshots.

    Targets ``.llm-wiki/backups/<snap_<ts>>/`` (路线 v2.2 §C-0.5a / Z-1).
    Does NOT touch ``.llm-wiki/.backup/`` (handled by cleanup_backups above).
    Snapshots are named ``snap_<13-digit-ms-timestamp>`` so lexical sort
    matches chronological order.
    """
    backup_root = paths.llm_wiki / "backups"
    if not backup_root.exists():
        return 0
    dirs = sorted(
        (d for d in backup_root.iterdir() if d.is_dir() and d.name.startswith("snap_")),
        key=lambda d: d.name,
        reverse=True,
    )
    deleted = 0
    for d in dirs[max_count:]:
        try:
            shutil.rmtree(d)
        except OSError:
            pass
        else:
            deleted += 1
    if deleted:
        _logger.info("[cleanup] kc_backups: %d old KC snapshots deleted", deleted)
    return deleted


# ── batch entry point ─────────────────────────────────────────────────────

def cleanup_kc_evidence(paths: WikiPaths) -> int:
    """K-7 whitelist: `.index/evidence/` 是生产数据，不清理.

    No-op but explicitly registered so the whitelist is auditable
    (路线 v2.2 §B-4 commit 2 / K-7).
    """
    return 0


def cleanup_kc_diffs(paths: WikiPaths) -> int:
    """K-7 whitelist: `.index/diffs/` 是审计数据，不清理.

    No-op but explicitly registered so the whitelist is auditable
    (路线 v2.2 §B-4 commit 2 / K-7).
    """
    return 0


def cleanup_all(paths: WikiPaths) -> dict[str, int]:
    """Run all cleanup functions; return ``{cache_name: items_deleted}``."""
    results: dict[str, int] = {}
    cleaners = [
        ("lint_cache", cleanup_lint_cache),
        ("heat_log_rotation", rotate_heat_log),
        ("staging", cleanup_staging),
        ("quarantine", cleanup_quarantine),
        ("dedup_history", cleanup_dedup_history),
        ("backups", cleanup_backups),
        ("kc_backups", cleanup_kc_backups),
        ("kc_evidence_whitelist", cleanup_kc_evidence),  # K-7: 白名单 no-op
        ("kc_diffs_whitelist", cleanup_kc_diffs),        # K-7: 白名单 no-op
    ]
    for name, fn in cleaners:
        try:
            results[name] = fn(paths)
        except Exception:
            _logger.exception("[cleanup] %s failed", name)
            results[name] = -1
    total = sum(v for v in results.values() if v > 0)
    if total > 0:
        _logger.info("[cleanup] done — %d total items cleaned", total)
    return results
