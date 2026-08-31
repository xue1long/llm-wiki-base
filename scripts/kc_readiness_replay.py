"""Replay a readiness audit record against its source artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.pipeline.extraction_types import collect_artifact
from src.pipeline.readiness_replay import replay_evidence


def replay_record(record_path: Path, source_path: Path) -> dict:
    record = json.loads(record_path.read_text(encoding="utf-8"))
    source_id = record.get("source_id")
    if not isinstance(source_id, str) or not source_id:
        raise ValueError("audit record source_id is required")
    artifact = collect_artifact(source_path, source_id=source_id)
    result = replay_evidence(record, artifact)
    return {
        "accepted": result.accepted,
        "reason_codes": list(result.reason_codes),
        "failure_reason": result.failure_reason,
        "record": str(record_path),
        "source": str(source_path),
    }


def replay_pilot_report(project: Path, report_path: Path) -> dict:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    checked = 0
    failures = []
    for record in report.get("results", []):
        if record.get("category") != "accepted":
            continue
        checked += 1
        artifact = collect_artifact(
            Path(project) / record["source"], source_id=record["source_id"]
        )
        result = replay_evidence(record, artifact)
        if not result.accepted:
            failures.append({"source": record["source"], "failure_reason": result.failure_reason})
    return {
        "report": str(report_path),
        "accepted_checked": checked,
        "replay_failures": len(failures),
        "false_accepts": len(failures),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--pilot-report", type=Path)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.pilot_report is not None:
        if args.project_root is None:
            parser.error("--project-root is required with --pilot-report")
        result = replay_pilot_report(args.project_root, args.pilot_report)
    elif args.record is not None and args.source is not None:
        result = replay_record(args.record, args.source)
    else:
        parser.error("provide --record and --source, or --pilot-report and --project-root")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if result.get("accepted", result.get("replay_failures", 1) == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
