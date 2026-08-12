"""Cache management CLI — status + cleanup."""
import argparse
import sys

from ..maintenance.cache_cleanup import cleanup_all
from ..maintenance.checks.h5_cache_health import H5CacheHealthCheck
from .project_resolve import resolve_cli_project


def _resolve_ctx(project_arg):
    return resolve_cli_project(project_arg)


def cmd_cache_status(args: argparse.Namespace) -> None:
    """Show cache health stats (read-only, uses H5 check)."""
    ctx, paths = _resolve_ctx(args.project)
    check = H5CacheHealthCheck(ctx.path)
    result = check.run()

    print(f"Cache Health for {ctx.name}")
    print(f"  lint_cache entries:  {result.stats.get('lint_cache_entries', 0)}")
    if "lint_cache_oldest_age_h" in result.stats:
        print(f"    oldest:             {result.stats['lint_cache_oldest_age_h']}h")
    print(f"  heat_events.log:      {result.stats.get('heat_log_size_mb', 0)} MB")
    print(f"  staging drafts:       {result.stats.get('staging_drafts', 0)}")
    if "staging_oldest_age_d" in result.stats:
        print(f"    oldest:             {result.stats['staging_oldest_age_d']}d")
    print(f"  quarantine items:     {result.stats.get('quarantine_items', 0)}")
    print(f"  dedup_history:        {result.stats.get('dedup_history_records', 0)} records")
    print(f"  backups:              {result.stats.get('backup_count', 0)}")
    print(f"  issues:               {result.issue_count}")

    if result.issues:
        print("Issues:")
        for issue in result.issues:
            print(f"  [{issue.severity.value}] {issue.code}: {issue.message}")


def cmd_cache_cleanup(args: argparse.Namespace) -> None:
    """Run all cache cleanup operations."""
    ctx, paths = _resolve_ctx(args.project)

    if args.dry_run:
        # Run H5 first to show what would be cleaned
        check = H5CacheHealthCheck(ctx.path)
        result = check.run()
        print("(dry run) Would clean up to:")
        print(f"  lint_cache entries:  {result.stats.get('lint_cache_entries', 0)}")
        print(f"  staging drafts:      {result.stats.get('staging_drafts', 0)}")
        print(f"  quarantine items:    {result.stats.get('quarantine_items', 0)}")
        print(f"  dedup_history:       {result.stats.get('dedup_history_records', 0)} records")
        print(f"  backups:             {result.stats.get('backup_count', 0)}")
        return

    results = cleanup_all(paths)
    total = sum(v for v in results.values() if v > 0)
    errors = sum(1 for v in results.values() if v < 0)

    print("Cache cleanup complete:")
    for name, count in results.items():
        if count > 0:
            print(f"  {name}: {count}")
        elif count < 0:
            print(f"  {name}: ERROR (see log)")
    print(f"Total: {total} items cleaned" + (f" ({errors} errors)" if errors else ""))
