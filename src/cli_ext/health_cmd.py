"""Health check CLI subcommand."""
import argparse
import json
import sys
from pathlib import Path

from ..maintenance.health_check import HealthCheckRunner
from ..maintenance.checks.h1_file_existence import H1FileExistenceCheck
from ..maintenance.checks.h2_break_links import H2BreakLinksCheck
from ..maintenance.checks.h4_id_format import H4IdFormatCheck


CHECKS_AVAILABLE = {"H1", "H2", "H4"}  # MVP scope


def cmd_health(args: argparse.Namespace) -> None:
    """Run wiki structural integrity checks."""
    project_path = Path(args.project) if args.project else Path.cwd()
    if not project_path.exists():
        print(f"Project path not found: {project_path}", file=sys.stderr)
        sys.exit(2)

    selected = args.only if args.only else None
    skipped = args.skip if args.skip else None

    runner = HealthCheckRunner(project_path=project_path, project_id=str(project_path))
    runner.register("H1", H1FileExistenceCheck(project_path))
    runner.register("H2", H2BreakLinksCheck(project_path))
    runner.register("H4", H4IdFormatCheck(project_path))

    report = runner.run(selected=selected, skipped=skipped)

    if args.json:
        print(json.dumps(_report_to_dict(report), indent=2, ensure_ascii=False))
    else:
        _print_text_report(report)

    if args.strict and not report.passed:
        sys.exit(1)


def _print_text_report(report) -> None:
    for check_id, result in report.check_results.items():
        if result.passed and result.issue_count == 0:
            icon = "[OK]"
        elif result.passed:
            icon = "[WARN]"
        else:
            icon = "[FAIL]"
        print(
            f"{icon} {check_id}: {result.description}  "
            f"({result.issue_count} issues, {result.duration_ms:.1f}ms)"
        )
        for stat, val in result.stats.items():
            print(f"    {stat}: {val}")
        for issue in result.issues:
            print(f"    [{issue.severity.value}] {issue.code}: {issue.message}")
    print()
    total_status = "HEALTHY" if report.passed else "UNHEALTHY"
    print(
        f"Total: {report.total_issues} issues "
        f"({report.total_errors} errors, {report.total_warnings} warnings)"
    )
    print(f"Status: {total_status}")


def _report_to_dict(report) -> dict:
    return {
        "project_id": report.project_id,
        "started_at": report.started_at,
        "finished_at": report.finished_at,
        "passed": report.passed,
        "total_issues": report.total_issues,
        "total_errors": report.total_errors,
        "total_warnings": report.total_warnings,
        "check_results": {
            cid: {
                "name": r.name,
                "description": r.description,
                "passed": r.passed,
                "issue_count": r.issue_count,
                "issues": [
                    {
                        "severity": i.severity.value,
                        "code": i.code,
                        "message": i.message,
                        "page_id": i.page_id,
                        "file_path": i.file_path,
                        "target": i.target,
                    }
                    for i in r.issues
                ],
                "stats": r.stats,
                "duration_ms": r.duration_ms,
            }
            for cid, r in report.check_results.items()
        },
    }
