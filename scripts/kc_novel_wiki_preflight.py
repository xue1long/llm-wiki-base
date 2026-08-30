"""Read-only preflight and source manifest for a novel-wiki staging project."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_preflight(project: Path) -> dict:
    project = project.resolve()
    raw_root = project / "raw" / "sources"
    source_files = sorted(p for p in raw_root.rglob("*") if p.is_file()) if raw_root.exists() else []
    schema = project / "schema.md"
    purpose = project / "purpose.md"
    sources = [
        {
            "source_id": hashlib.sha256(str(path.relative_to(project)).encode()).hexdigest()[:24],
            "path": path.relative_to(project).as_posix(),
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
            "suffix": path.suffix.lower(),
        }
        for path in source_files
    ]
    seen: dict[str, str] = {}
    duplicates = []
    for item in sources:
        previous = seen.get(item["sha256"])
        if previous:
            duplicates.append({"sha256": item["sha256"], "first": previous, "duplicate": item["path"]})
        else:
            seen[item["sha256"]] = item["path"]
    usage = shutil.disk_usage(project)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(project),
        "schema_sha256": _sha256(schema) if schema.exists() else None,
        "purpose_sha256": _sha256(purpose) if purpose.exists() else None,
        "raw_source_count": len(sources),
        "canonical_source_count": len(seen),
        "duplicate_source_count": len(duplicates),
        "duplicates": duplicates,
        "sources": sources,
        "disk_free_bytes": usage.free,
        "hard_failures": [
            item for item in (
                "raw/sources missing" if not raw_root.exists() else None,
                "schema.md missing" if not schema.exists() else None,
                "purpose.md missing" if not purpose.exists() else None,
            ) if item
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_preflight(args.project_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"sources", "duplicates"}}, ensure_ascii=False, indent=2))
    return 1 if report["hard_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
