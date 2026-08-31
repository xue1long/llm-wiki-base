"""Read-only preflight and source manifest for a novel-wiki staging project."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import unicodedata
from datetime import datetime, timezone
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _overlaps(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def build_preflight(
    project: Path,
    *,
    protected_root: Path | None = None,
    output: Path | None = None,
) -> dict:
    project = project.resolve()
    protected_root = protected_root.resolve() if protected_root is not None else None
    output = output.resolve() if output is not None else None
    project_exists = project.exists()
    project_overlaps_protected = bool(protected_root and _overlaps(project, protected_root))
    output_overlaps_project = bool(output and _overlaps(output, project))
    output_overlaps_protected = bool(output and protected_root and _overlaps(output, protected_root))
    hard_failures = [
        item
        for item in (
            "project root missing" if not project_exists else None,
            "project overlaps protected root" if project_overlaps_protected else None,
            "output overlaps project root" if output_overlaps_project else None,
            "output overlaps protected root" if output_overlaps_protected else None,
        )
        if item
    ]
    raw_root = project / "raw" / "sources"
    source_files = (
        sorted(p for p in raw_root.rglob("*") if p.is_file())
        if project_exists and raw_root.exists() and not project_overlaps_protected
        else []
    )
    schema = project / "schema.md"
    purpose = project / "purpose.md"
    sources = [
        {
            "source_id": unicodedata.normalize("NFC", path.relative_to(project).as_posix()),
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
    usage = shutil.disk_usage(project if project_exists else project.parent)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(project),
        "protected_root": str(protected_root) if protected_root is not None else None,
        "output": str(output) if output is not None else None,
        "schema_sha256": _sha256(schema) if schema.exists() else None,
        "purpose_sha256": _sha256(purpose) if purpose.exists() else None,
        "raw_source_count": len(sources),
        "canonical_source_count": len(seen),
        "duplicate_source_count": len(duplicates),
        "duplicates": duplicates,
        "sources": sources,
        "disk_free_bytes": usage.free,
        "hard_failures": hard_failures + [
            item
            for item in (
                "raw/sources missing" if project_exists and not raw_root.exists() and not project_overlaps_protected else None,
                "schema.md missing" if project_exists and not schema.exists() and not project_overlaps_protected else None,
                "purpose.md missing" if project_exists and not purpose.exists() and not project_overlaps_protected else None,
            )
            if item
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--protected-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_preflight(
        args.project_root,
        protected_root=args.protected_root,
        output=args.output,
    )
    if any(
        item in {"output overlaps project root", "output overlaps protected root"}
        for item in report["hard_failures"]
    ):
        print(json.dumps({k: v for k, v in report.items() if k not in {"sources", "duplicates"}}, ensure_ascii=False, indent=2))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"sources", "duplicates"}}, ensure_ascii=False, indent=2))
    return 1 if report["hard_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
