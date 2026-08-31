"""Build a provider-free, read-only content readiness inventory."""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from scripts.kc_novel_wiki_preflight import build_preflight
from src.pipeline.extraction_types import collect_artifact
from src.pipeline.text_preprocessing import assess_artifact


def inventory(
    project: Path,
    *,
    output: Path,
    policy_version: str,
    protected_root: Path | None = None,
) -> dict:
    project = Path(project).resolve()
    output = Path(output).resolve()
    preflight = build_preflight(project, protected_root=protected_root, output=output)
    if preflight["hard_failures"]:
        raise ValueError("inventory preflight failed: " + "; ".join(preflight["hard_failures"]))
    records = []
    for item in preflight["sources"]:
        path = project / item["path"]
        artifact = collect_artifact(path, source_id=item["source_id"])
        assessment = assess_artifact(artifact, policy_version=policy_version)
        record = {
            "source_id": artifact.source_id,
            "path": item["path"],
            "source_bytes_sha256": artifact.source_bytes_sha256,
            "input_text_sha256": artifact.input_text_sha256,
            "format": artifact.format,
            "extraction_method": artifact.extraction_method,
            "content_kind": assessment.content_kind.value,
            "decision": assessment.decision.value,
            "reason_codes": list(assessment.reason_codes),
            "evidence_capacity": {
                "blocks": assessment.evidence_capacity.blocks,
                "chars": assessment.evidence_capacity.chars,
                "units": assessment.evidence_capacity.units,
                "min_span_chars": assessment.evidence_capacity.min_span_chars,
                "max_span_chars": assessment.evidence_capacity.max_span_chars,
            },
            "stratum": f"{assessment.decision.value}:{assessment.content_kind.value}",
        }
        records.append(record)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(project),
        "policy_version": policy_version,
        "selected": len(records),
        "unique_sources": len({record["source_id"] for record in records}),
        "decisions": dict(sorted(Counter(record["decision"] for record in records).items())),
        "records": records,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def select_stratified_sources(inventory: dict, *, limit: int = 15, seed: int = 20260830) -> list[str]:
    if limit < 0:
        raise ValueError("limit must be non-negative")
    buckets: dict[str, list[dict]] = {}
    for record in inventory.get("records", []):
        buckets.setdefault(record.get("stratum", "unknown"), []).append(record)
    rng = random.Random(seed)
    for bucket in buckets.values():
        bucket.sort(key=lambda record: record["source_id"])
        rng.shuffle(bucket)
    selected: list[str] = []
    keys = sorted(buckets)
    while len(selected) < limit and any(buckets.values()):
        for key in keys:
            if buckets[key] and len(selected) < limit:
                selected.append(buckets[key].pop()["source_id"])
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--policy-version", default="content-policy-v1")
    parser.add_argument("--protected-root", type=Path)
    args = parser.parse_args()
    report = inventory(
        args.project_root,
        output=args.output,
        policy_version=args.policy_version,
        protected_root=args.protected_root,
    )
    print(json.dumps({key: value for key, value in report.items() if key != "records"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
