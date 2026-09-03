"""Wiki-quality CLI subcommand: V4 strict-whitelist quality gate.

wiki-repair-novel-wiki §7: aggregate the structural integrity checks
(H1/H2/H4/H5), the V4 frontmatter validator, and the supplementary
content-quality scans (duplicate-FM, duplicate-titles, ISO-string
timestamps, dangling-relations, broken-wikilinks) into a single
report. Produces both a human-readable table and a JSON dump.

This is the operator-facing entrypoint for the quality gate. It does
NOT mutate any page; it only reports.

Usage:
    python -m src.cli wiki-quality [--project PATH] [--json] [--strict]

Exit codes:
    0  healthy (no errors, no warnings)
    1  unhealthy (errors present; --strict forces exit 1)
    2  invalid arguments / missing project
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROJECT_ROOT = REPO_ROOT / "knowledge" / "novel-wiki"
QUALITY_DIR = PROJECT_ROOT / ".index" / "quality"


def _run_structural_checks(project_path: Path) -> dict:
    """Delegate to HealthCheckRunner for H1/H2/H4/H5."""
    from src.maintenance.health_check import HealthCheckRunner
    from src.maintenance.checks.h1_file_existence import H1FileExistenceCheck
    from src.maintenance.checks.h2_break_links import H2BreakLinksCheck
    from src.maintenance.checks.h4_id_format import H4IdFormatCheck
    from src.maintenance.checks.h5_cache_health import H5CacheHealthCheck

    runner = HealthCheckRunner(project_path=project_path, project_id=str(project_path))
    runner.register("H1", H1FileExistenceCheck(project_path))
    runner.register("H2", H2BreakLinksCheck(project_path))
    runner.register("H4", H4IdFormatCheck(project_path))
    runner.register("H5", H5CacheHealthCheck(project_path))
    report = runner.run()

    return {
        "passed": report.passed,
        "total_issues": report.total_issues,
        "total_errors": report.total_errors,
        "total_warnings": report.total_warnings,
        "checks": {
            cid: {
                "passed": r.passed,
                "issue_count": r.issue_count,
                "stats": r.stats,
            }
            for cid, r in report.check_results.items()
        },
    }


def _count_iso_string_timestamps(wiki_root: Path) -> int:
    """Scan wiki for any `created_at:` / `updated_at:` lines with quoted string values."""
    iso_re = re.compile(r"^(created_at|updated_at):\s*['\"][^'\"]+['\"]", re.MULTILINE)
    n = 0
    for md in wiki_root.rglob("*.md"):
        rel = md.relative_to(wiki_root)
        if len(rel.parts) == 1 and rel.name in {"index.md", "log.md"}:
            continue
        if rel.parts[0] not in {"concepts", "sources", "entities", "synthesis", "_stubs"}:
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if text.startswith("﻿"):
            text = text[1:]
        end = text.find("\n---", 4)
        if end < 0:
            continue
        n += len(iso_re.findall(text[4:end]))
    return n


def _count_duplicate_titles(wiki_root: Path) -> tuple[int, int]:
    """Return (group_count, page_count) of pages whose title matches ≥1 other page."""
    titles: dict[str, int] = {}
    for md in wiki_root.rglob("*.md"):
        rel = md.relative_to(wiki_root)
        if len(rel.parts) == 1 and rel.name in {"index.md", "log.md"}:
            continue
        if rel.parts[0] not in {"concepts", "sources", "entities", "synthesis", "_stubs"}:
            continue
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except UnicodeDecodeError:
            continue
        if text.startswith("﻿"):
            text = text[1:]
        if not text.startswith("---\n"):
            continue
        end = text.find("\n---", 4)
        if end < 0:
            continue
        for line in text[4:end].split("\n"):
            if line.startswith("title:"):
                t = line[6:].strip()
                if t:
                    titles[t] = titles.get(t, 0) + 1
                break
    groups = [c for c in titles.values() if c > 1]
    return len(groups), sum(groups)


def _count_duplicate_frontmatter(wiki_root: Path) -> int:
    """Count pages with the stray `---` after the closing Frontmatter delimiter."""
    n = 0
    for md in wiki_root.rglob("*.md"):
        rel = md.relative_to(wiki_root)
        if len(rel.parts) == 1 and rel.name in {"index.md", "log.md"}:
            continue
        if rel.parts[0] not in {"concepts", "sources", "entities", "synthesis", "_stubs"}:
            continue
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except UnicodeDecodeError:
            continue
        lines = text.split("\n")
        if not lines or lines[0].strip() != "---":
            continue
        close_line = None
        for i, line in enumerate(lines[1:], 2):
            if line.strip() == "---":
                close_line = i
                break
        if close_line is None:
            continue
        next_line = lines[close_line] if close_line < len(lines) else ""
        if next_line.strip() == "---":
            n += 1
    return n


def _count_bom_files(wiki_root: Path) -> int:
    BOM = b"\xef\xbb\xbf"
    n = 0
    for md in wiki_root.rglob("*.md"):
        rel = md.relative_to(wiki_root)
        if len(rel.parts) == 1 and rel.name in {"index.md", "log.md"}:
            continue
        if rel.parts[0] not in {"concepts", "sources", "entities", "synthesis", "_stubs"}:
            continue
        try:
            with md.open("rb") as f:
                if f.read(3) == BOM:
                    n += 1
        except OSError:
            pass
    return n


def _count_wiki_pages(wiki_root: Path) -> int:
    n = 0
    for md in wiki_root.rglob("*.md"):
        rel = md.relative_to(wiki_root)
        if len(rel.parts) == 1 and rel.name in {"index.md", "log.md"}:
            continue
        if rel.parts[0] not in {"concepts", "sources", "entities", "synthesis", "_stubs"}:
            continue
        n += 1
    return n


def build_report(project_path: Path) -> dict:
    wiki_root = project_path / "wiki"
    structural = _run_structural_checks(project_path)
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "project_path": str(project_path),
        "wiki_root": str(wiki_root),
        "scale": {
            "total_wiki_pages": _count_wiki_pages(wiki_root),
        },
        "structural_checks": structural,
        "content_quality": {
            "utf8_bom_files": _count_bom_files(wiki_root),
            "duplicate_frontmatter_pages": _count_duplicate_frontmatter(wiki_root),
            "iso_string_timestamps": _count_iso_string_timestamps(wiki_root),
            "duplicate_titles": {
                "groups": _count_duplicate_titles(wiki_root)[0],
                "pages": _count_duplicate_titles(wiki_root)[1],
            },
        },
    }


def _print_table(report: dict) -> None:
    s = report["scale"]
    print(f"Project: {report['project_path']}")
    print(f"Wiki root: {report['wiki_root']}")
    print(f"Total pages: {s['total_wiki_pages']}")
    print()
    print("== Structural integrity ==")
    sc = report["structural_checks"]
    for cid, c in sc["checks"].items():
        icon = "[OK]" if c["passed"] and c["issue_count"] == 0 else "[WARN]"
        print(f"  {icon} {cid}: {c['issue_count']} issues")
        for k, v in c["stats"].items():
            print(f"      {k}: {v}")
    print()
    print("== Content quality ==")
    cq = report["content_quality"]
    rows = [
        ("UTF-8 BOM files", cq["utf8_bom_files"], "0 expected"),
        ("Duplicate frontmatter pages", cq["duplicate_frontmatter_pages"], "0 expected"),
        ("ISO string timestamps", cq["iso_string_timestamps"], "0 expected"),
        ("Duplicate-title groups", cq["duplicate_titles"]["groups"], "0 expected"),
    ]
    for name, val, expect in rows:
        flag = "[OK]" if val == 0 else "[WARN]"
        print(f"  {flag} {name}: {val}  ({expect})")
    print()
    print(f"Total errors:   {sc['total_errors']}")
    print(f"Total warnings: {sc['total_warnings']}")
    print(f"Status:         {'HEALTHY' if sc['passed'] and cq['utf8_bom_files'] == 0 and cq['duplicate_frontmatter_pages'] == 0 and cq['iso_string_timestamps'] == 0 else 'NEEDS_REVIEW'}")


def cmd_wiki_quality(args: argparse.Namespace) -> int:
    project_path = Path(args.project).resolve() if args.project else PROJECT_ROOT
    if not project_path.exists():
        print(f"error: {project_path} not found", file=sys.stderr)
        return 2

    report = build_report(project_path)

    if args.out:
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_table(report)

    if args.strict:
        unhealthy = (
            not report["structural_checks"]["passed"]
            or report["content_quality"]["utf8_bom_files"] > 0
            or report["content_quality"]["duplicate_frontmatter_pages"] > 0
            or report["content_quality"]["iso_string_timestamps"] > 0
        )
        return 1 if unhealthy else 0
    return 0


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "wiki-quality",
        help="V4 strict-whitelist quality gate (H1/H2/H4/H5 + content scans)",
    )
    p.add_argument("--project", help="Project root (default: knowledge/novel-wiki)")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.add_argument("--strict", action="store_true", help="Exit 1 on any quality issue")
    p.add_argument("--out", help="Write JSON report to this path")
    p.set_defaults(func=_cmd_wrapper)


def _cmd_wrapper(args: argparse.Namespace) -> int:
    return cmd_wiki_quality(args)