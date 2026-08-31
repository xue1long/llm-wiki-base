"""Read-only readiness audit inventory and comparison commands."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from ..pipeline.readiness_audit import compare_readiness_records, read_readiness_record


def cmd_readiness_inventory(args: argparse.Namespace) -> None:
    root = Path(args.project) if args.project else Path.cwd()
    records = []
    for path in sorted((root / ".index" / "quarantine" / "readiness").glob("*/*.json")):
        records.append(read_readiness_record(path))
    report = {
        "count": len(records),
        "decisions": dict(sorted(Counter(record["decision"] for record in records).items())),
        "records": records,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    print(f"Records: {report['count']}")
    print(f"Decisions: {report['decisions']}")


def cmd_readiness_compare(args: argparse.Namespace) -> None:
    old = read_readiness_record(Path(args.old))
    new = read_readiness_record(Path(args.new))
    report = compare_readiness_records(old, new)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    for key, value in report.items():
        print(f"{key}: {value['old']} -> {value['new']}")
