"""Tests for unified cache cleanup module."""
import json
import os
import time
from pathlib import Path

from src.maintenance.cache_cleanup import (
    cleanup_lint_cache,
    rotate_heat_log,
    cleanup_staging,
    cleanup_quarantine,
    cleanup_dedup_history,
    cleanup_backups,
    cleanup_all,
)
from src.wiki.core.paths import WikiPaths
from src.wiki.storage.ensure import ensure_knowledge_base


# ── helpers ───────────────────────────────────────────────────────────────

def _make_old(path: Path, days: int = 60) -> None:
    """Set mtime to *days* ago so the file appears stale."""
    old = time.time() - days * 86400
    os_stat = path.stat()
    os.utime(path, (os_stat.st_atime, old))


# ── lint_cache ────────────────────────────────────────────────────────────

def test_cleanup_lint_cache_empty_dir(tmp_path):
    paths = ensure_knowledge_base(tmp_path)
    assert cleanup_lint_cache(paths) == 0


def test_cleanup_lint_cache_missing_dir(tmp_path):
    paths = WikiPaths(tmp_path)
    assert cleanup_lint_cache(paths) == 0


def test_cleanup_lint_cache_only_fresh_entries(tmp_path):
    paths = ensure_knowledge_base(tmp_path)
    cache_dir = paths.index / "lint_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "fresh.json").write_text(json.dumps({"key": "fresh"}), encoding="utf-8")
    # File is brand new → not stale
    assert cleanup_lint_cache(paths) == 0


def test_cleanup_lint_cache_mixed_fresh_and_stale(tmp_path):
    paths = ensure_knowledge_base(tmp_path)
    cache_dir = paths.index / "lint_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    fresh = cache_dir / "fresh.json"
    stale = cache_dir / "stale.json"
    fresh.write_text(json.dumps({"key": "fresh"}), encoding="utf-8")
    stale.write_text(json.dumps({"key": "stale"}), encoding="utf-8")
    _make_old(stale, days=2)  # older than 24h
    assert cleanup_lint_cache(paths) == 1
    assert fresh.exists()
    assert not stale.exists()


# ── heat_log ──────────────────────────────────────────────────────────────

def test_rotate_heat_log_missing(tmp_path):
    paths = ensure_knowledge_base(tmp_path)
    assert rotate_heat_log(paths) == 0


def test_rotate_heat_log_small_file(tmp_path):
    paths = ensure_knowledge_base(tmp_path)
    log = paths.index / "heat_events.log"
    log.write_text("small", encoding="utf-8")
    assert rotate_heat_log(paths) == 0  # too small to rotate


def test_rotate_heat_log_large_file(tmp_path):
    paths = ensure_knowledge_base(tmp_path)
    log = paths.index / "heat_events.log"
    # Write 11 MB of data
    log.write_text("x" * (11 * 1024 * 1024), encoding="utf-8")
    assert rotate_heat_log(paths) == 1
    assert not log.exists()  # rotated away
    assert (paths.index / "heat_events.log.1").exists()


def test_rotate_heat_log_cascades_existing_backups(tmp_path):
    paths = ensure_knowledge_base(tmp_path)
    log = paths.index / "heat_events.log"
    log.write_text("x" * (11 * 1024 * 1024), encoding="utf-8")
    (paths.index / "heat_events.log.1").write_text("old1", encoding="utf-8")
    assert rotate_heat_log(paths) == 1
    assert (paths.index / "heat_events.log.1").exists()
    assert (paths.index / "heat_events.log.2").exists()


# ── staging ───────────────────────────────────────────────────────────────

def test_cleanup_staging_empty(tmp_path):
    paths = ensure_knowledge_base(tmp_path)
    assert cleanup_staging(paths) == 0


def test_cleanup_staging_missing_dir(tmp_path):
    paths = WikiPaths(tmp_path)
    assert cleanup_staging(paths) == 0


def test_cleanup_staging_mixed(tmp_path):
    paths = ensure_knowledge_base(tmp_path)
    staging = paths.index / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    fresh = staging / "fresh.md"
    stale = staging / "stale.md"
    fresh.write_text("# fresh", encoding="utf-8")
    stale.write_text("# stale", encoding="utf-8")
    _make_old(stale, days=60)
    assert cleanup_staging(paths) == 1
    assert fresh.exists()
    assert not stale.exists()


# ── quarantine ────────────────────────────────────────────────────────────

def test_cleanup_quarantine_empty(tmp_path):
    paths = ensure_knowledge_base(tmp_path)
    assert cleanup_quarantine(paths) == 0


def test_cleanup_quarantine_missing_dir(tmp_path):
    paths = WikiPaths(tmp_path)
    assert cleanup_quarantine(paths) == 0


def test_cleanup_quarantine_deletes_stale_and_empty_task_dirs(tmp_path):
    paths = ensure_knowledge_base(tmp_path)
    qdir = paths.index / "quarantine" / "task-1"
    qdir.mkdir(parents=True, exist_ok=True)
    stale_page = qdir / "page.md"
    stale_judge = qdir / "page.judgment.json"
    stale_page.write_text("# old", encoding="utf-8")
    stale_judge.write_text(json.dumps({"ok": False}), encoding="utf-8")
    _make_old(stale_page, days=120)
    _make_old(stale_judge, days=120)
    # Both files stale → task dir emptied
    result = cleanup_quarantine(paths)
    assert result >= 1  # at least the files
    # After files deleted, task dir should be removed (empty)
    assert not qdir.exists()


# ── dedup_history ─────────────────────────────────────────────────────────

def test_cleanup_dedup_history_empty(tmp_path):
    paths = ensure_knowledge_base(tmp_path)
    assert cleanup_dedup_history(paths) == 0


def test_cleanup_dedup_history_missing_dir(tmp_path):
    paths = WikiPaths(tmp_path)
    assert cleanup_dedup_history(paths) == 0


def test_cleanup_dedup_history_deletes_stale_records(tmp_path):
    paths = ensure_knowledge_base(tmp_path)
    history = paths.index / "dedup_history"
    record_dir = history / "rec-1"
    record_dir.mkdir(parents=True, exist_ok=True)
    (record_dir / "merged.md").write_text("# merged", encoding="utf-8")
    record_json = history / "rec-1.json"
    record_json.write_text(json.dumps({"id": "rec-1"}), encoding="utf-8")
    _make_old(record_dir / "merged.md", days=60)
    _make_old(record_json, days=60)
    deleted = cleanup_dedup_history(paths)
    assert deleted >= 1


# ── backups ───────────────────────────────────────────────────────────────

def test_cleanup_backups_empty(tmp_path):
    paths = ensure_knowledge_base(tmp_path)
    assert cleanup_backups(paths) == 0


def test_cleanup_backups_missing_dir(tmp_path):
    paths = WikiPaths(tmp_path)
    assert cleanup_backups(paths) == 0


def test_cleanup_backups_keeps_newest(tmp_path):
    paths = ensure_knowledge_base(tmp_path)
    backup_root = paths.llm_wiki / ".backup"
    backup_root.mkdir(parents=True, exist_ok=True)
    # Create 12 backups (keep 10)
    for i in range(12):
        d = backup_root / f"20260101-1200{i:02d}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "BACKUP_REASON.txt").write_text(f"backup {i}", encoding="utf-8")
        # Stagger ages so last 2 are oldest
        _make_old(d, days=12 - i)
    deleted = cleanup_backups(paths, max_count=10)
    assert deleted == 2
    remaining = [d for d in backup_root.iterdir() if d.is_dir() and d.name != "latest"]
    assert len(remaining) == 10


# ── cleanup_all ───────────────────────────────────────────────────────────

def test_cleanup_all_aggregates_results(tmp_path):
    paths = ensure_knowledge_base(tmp_path)
    # Create one stale lint cache entry
    cache_dir = paths.index / "lint_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    stale = cache_dir / "old.json"
    stale.write_text(json.dumps({"key": "old"}), encoding="utf-8")
    _make_old(stale, days=2)

    results = cleanup_all(paths)
    assert isinstance(results, dict)
    assert "lint_cache" in results
    assert results["lint_cache"] == 1
    # All other caches should report 0 (empty/missing)
    for k in ("staging", "quarantine", "dedup_history", "backups"):
        assert results[k] == 0
