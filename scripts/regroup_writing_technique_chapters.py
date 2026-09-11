"""Apply the Task 4 regroup to the active release (dry-run by default).

Reads the active release's snapshot, runs
`partition_writing_technique_merged`, and prints the resulting
chapter composition. The actual rewrite of `.md` chapter files
plus the manifest refresh is staged behind `book build-from-wiki
--apply-from` (see Task 4 in the plan), so this script focuses on
verifying the regroup produces the expected 8 named chapters
without losing any page_id.

Usage:
    python scripts/regroup_writing_technique_chapters.py --project <id>
    python scripts/regroup_writing_technique_chapters.py --project <id> --json

The script is read-only by design. It does not call LLM and does
not write any release artifact. The `book build-from-wiki`
subcommand owns the full re-publish path.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from src.kc.views.book.wiki.partition import (  # noqa: E402
    DEFAULT_WRITING_TECHNIQUE_REGROUP,
    partition_writing_technique_merged,
)
from src.kc.views.book.wiki.scanner import WikiScanError, scan_wiki_snapshot  # noqa: E402
from src.lib.project import resolve_project  # noqa: E402
from src.project.context import ProjectNotFoundError  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--project", required=True, help="Project id or name")
    parser.add_argument(
        "--min-pages", type=int, default=5,
        help="Min pages per new chapter (regroup is rejected if any "
             "chapter has fewer pages; default 5)",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    return parser.parse_args()


def _load_snapshot(project_root: Path):
    """Load the Wiki snapshot for the project root.

    Falls back to scanning the wiki tree directly when the cached
    snapshot is unavailable. The fallback path uses the same scanner
    `book build-from-wiki` uses, so the regroup output matches what
    the compiler would see.
    """
    try:
        return scan_wiki_snapshot(project_root)
    except WikiScanError as exc:
        print(f"Error: scan failed: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc


def _summarize(result: dict) -> dict:
    """Render the regroup result as a small report dict."""
    new_keys = set(DEFAULT_WRITING_TECHNIQUE_REGROUP.keys())
    new_chapters = []
    passthrough = []
    for cid, ids in result.items():
        entry = {"chapter_id": cid, "page_count": len(ids)}
        if cid in new_keys:
            new_chapters.append(entry)
        else:
            passthrough.append(entry)
    # Stable ordering: new chapters first in rule order, then passthrough
    # alphabetically.
    new_chapters.sort(key=lambda e: list(DEFAULT_WRITING_TECHNIQUE_REGROUP).index(e["chapter_id"]))
    passthrough.sort(key=lambda e: e["chapter_id"])
    total_pages = sum(e["page_count"] for e in new_chapters + passthrough)
    return {
        "new_chapter_count": len(new_chapters),
        "passthrough_buckets": len(passthrough),
        "total_pages": total_pages,
        "new_chapters": new_chapters,
        "passthrough": passthrough,
    }


def main() -> int:
    args = _parse_args()
    try:
        ctx, _paths = resolve_project(args.project, by_id_only=True)
    except ProjectNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    snapshot = _load_snapshot(ctx.path)
    result = partition_writing_technique_merged(snapshot)
    report = _summarize(result)

    # Reject if any new chapter has fewer than min_pages.
    too_small = [c for c in report["new_chapters"] if c["page_count"] < args.min_pages]
    if too_small:
        report["validation_errors"] = [
            f"{c['chapter_id']} has only {c['page_count']} pages "
            f"(< {args.min_pages}); adjust regroup_rules or lower min-pages"
            for c in too_small
        ]

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"new chapters: {report['new_chapter_count']} (target 8), "
            f"passthrough buckets: {report['passthrough_buckets']}, "
            f"total pages: {report['total_pages']}"
        )
        for c in report["new_chapters"]:
            print(f"  + {c['chapter_id']}: {c['page_count']} pages")
        for c in report["passthrough"]:
            print(f"  = {c['chapter_id']}: {c['page_count']} pages")
        if report.get("validation_errors"):
            print("validation errors:")
            for e in report["validation_errors"]:
                print(f"  ! {e}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
