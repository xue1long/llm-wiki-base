"""CLI command for the read-only content health aggregate."""
import argparse
import json
from pathlib import Path

from ..maintenance.content_health import build_content_health
from ..wiki.core.paths import WikiPaths


def cmd_content_health(args: argparse.Namespace) -> None:
    report = build_content_health(WikiPaths(Path(args.project) if args.project else Path.cwd()))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    print(f"Pages: {report['page_count']}")
    print(f"Grades: {report['grades']}")
    print(f"Processing depths: {report['processing_depths']}")
    print(f"Triage non-process: {report['triage_non_process_count']}")
