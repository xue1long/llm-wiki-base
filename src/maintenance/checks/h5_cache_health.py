"""H5: Cache health — sizes, staleness, and disk usage of all project caches.

Read-only by convention: health checks never mutate state.  Use
``src.maintenance.cache_cleanup.cleanup_all()`` to actually free space.
"""
import time
from pathlib import Path

from ..health_check import Check, CheckIssue, CheckResult, CheckSeverity
from ...wiki.core.paths import WikiPaths


class H5CacheHealthCheck(Check):
    name = "H5"
    description = "Cache health — staleness and disk usage of all project caches"

    # Thresholds (WARNING when exceeded)
    LINT_CACHE_MAX_ENTRIES = 1000
    HEAT_LOG_MAX_SIZE_MB = 10
    STAGING_MAX_DRAFTS = 50
    QUARANTINE_MAX_ITEMS = 200
    DEDUP_HISTORY_MAX_RECORDS = 100
    BACKUP_MAX_COUNT = 10

    def run(self) -> CheckResult:
        issues: list[CheckIssue] = []
        stats: dict[str, int] = {}
        paths = WikiPaths(self.project_path)

        # ── lint_cache ──────────────────────────────────────────────
        lint_dir = paths.index / "lint_cache"
        if lint_dir.exists():
            entries = list(lint_dir.glob("*.json"))
            stats["lint_cache_entries"] = len(entries)
            if len(entries) > self.LINT_CACHE_MAX_ENTRIES:
                issues.append(CheckIssue(
                    severity=CheckSeverity.WARNING,
                    code="H5-LINT-CACHE-COUNT",
                    message=f"lint_cache has {len(entries)} entries "
                            f"(threshold: {self.LINT_CACHE_MAX_ENTRIES})",
                ))
            if entries:
                oldest_age_h = self._oldest_age_hours(entries)
                stats["lint_cache_oldest_age_h"] = oldest_age_h
                if oldest_age_h > 24:
                    issues.append(CheckIssue(
                        severity=CheckSeverity.WARNING,
                        code="H5-LINT-CACHE-STALE",
                        message=f"lint_cache oldest entry is {oldest_age_h}h old",
                    ))
        else:
            stats["lint_cache_entries"] = 0

        # ── heat_events.log ─────────────────────────────────────────
        heat_log = paths.index / "heat_events.log"
        if heat_log.exists():
            size_mb = round(heat_log.stat().st_size / (1024 * 1024), 1)
            stats["heat_log_size_mb"] = int(size_mb)
            if size_mb > self.HEAT_LOG_MAX_SIZE_MB:
                issues.append(CheckIssue(
                    severity=CheckSeverity.WARNING,
                    code="H5-HEAT-LOG-SIZE",
                    message=f"heat_events.log is {size_mb} MB "
                            f"(threshold: {self.HEAT_LOG_MAX_SIZE_MB} MB)",
                ))
        else:
            stats["heat_log_size_mb"] = 0

        # ── staging ─────────────────────────────────────────────────
        staging_dir = paths.index / "staging"
        if staging_dir.exists():
            drafts = list(staging_dir.glob("*.md"))
            stats["staging_drafts"] = len(drafts)
            if len(drafts) > self.STAGING_MAX_DRAFTS:
                issues.append(CheckIssue(
                    severity=CheckSeverity.WARNING,
                    code="H5-STAGING-COUNT",
                    message=f"staging has {len(drafts)} zombie drafts "
                            f"(threshold: {self.STAGING_MAX_DRAFTS})",
                ))
            if drafts:
                oldest_age_d = self._oldest_age_days(drafts)
                stats["staging_oldest_age_d"] = oldest_age_d
                if oldest_age_d > 30:
                    issues.append(CheckIssue(
                        severity=CheckSeverity.WARNING,
                        code="H5-STAGING-STALE",
                        message=f"staging oldest draft is {oldest_age_d}d old",
                    ))
        else:
            stats["staging_drafts"] = 0

        # ── quarantine ──────────────────────────────────────────────
        quarantine_root = paths.index / "quarantine"
        if quarantine_root.exists():
            items = list(quarantine_root.rglob("*"))
            file_items = [f for f in items if f.is_file()]
            stats["quarantine_items"] = len(file_items)
            if len(file_items) > self.QUARANTINE_MAX_ITEMS:
                issues.append(CheckIssue(
                    severity=CheckSeverity.WARNING,
                    code="H5-QUARANTINE-COUNT",
                    message=f"quarantine has {len(file_items)} items "
                            f"(threshold: {self.QUARANTINE_MAX_ITEMS})",
                ))
        else:
            stats["quarantine_items"] = 0

        # ── dedup_history ───────────────────────────────────────────
        dedup_dir = paths.index / "dedup_history"
        if dedup_dir.exists():
            records = [e for e in dedup_dir.iterdir() if e.is_dir()]
            stats["dedup_history_records"] = len(records)
            if len(records) > self.DEDUP_HISTORY_MAX_RECORDS:
                issues.append(CheckIssue(
                    severity=CheckSeverity.WARNING,
                    code="H5-DEDUP-HISTORY-COUNT",
                    message=f"dedup_history has {len(records)} records "
                            f"(threshold: {self.DEDUP_HISTORY_MAX_RECORDS})",
                ))
        else:
            stats["dedup_history_records"] = 0

        # ── backups ─────────────────────────────────────────────────
        backup_root = paths.llm_wiki / ".backup"
        if backup_root.exists():
            backup_dirs = [
                d for d in backup_root.iterdir()
                if d.is_dir() and d.name != "latest"
            ]
            stats["backup_count"] = len(backup_dirs)
            if len(backup_dirs) > self.BACKUP_MAX_COUNT:
                issues.append(CheckIssue(
                    severity=CheckSeverity.WARNING,
                    code="H5-BACKUP-COUNT",
                    message=f"backups has {len(backup_dirs)} entries "
                            f"(threshold: {self.BACKUP_MAX_COUNT})",
                ))
        else:
            stats["backup_count"] = 0

        return CheckResult(
            name=self.name,
            description=self.description,
            passed=len(issues) == 0,
            issue_count=len(issues),
            issues=issues,
            stats=stats,
        )

    # ── helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _oldest_age_hours(paths: list[Path]) -> int:
        now = time.time()
        try:
            oldest = min(p.stat().st_mtime for p in paths)
        except (ValueError, FileNotFoundError):
            return 0
        return int((now - oldest) / 3600)

    @staticmethod
    def _oldest_age_days(paths: list[Path]) -> int:
        now = time.time()
        try:
            oldest = min(p.stat().st_mtime for p in paths)
        except (ValueError, FileNotFoundError):
            return 0
        return int((now - oldest) / 86400)
