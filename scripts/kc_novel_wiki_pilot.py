"""Run a bounded pilot through the default candidate ingest pipeline."""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from src.pipeline import _get_provider, run_ingest
from src.wiki.core.paths import WikiPaths


def select_sources(project: Path, limit: int) -> list[Path]:
    """Select deterministic, small, markdown inputs for the first live run."""
    root = project / "raw" / "sources"
    return sorted(root.rglob("*.md"), key=lambda p: (p.stat().st_size, p.as_posix()))[:limit]


def _error_summary(exc: BaseException) -> str:
    """Keep the deepest provider error visible in the pilot report."""
    parts = [f"{type(exc).__name__}: {exc}"]
    cause = exc.__cause__
    while cause is not None:
        parts.append(f"{type(cause).__name__}: {cause}")
        cause = cause.__cause__
    return " <- ".join(parts)


async def run_pilot(project: Path, limit: int = 3) -> dict:
    project = project.resolve()
    sources = select_sources(project, limit)
    if not sources:
        raise ValueError("no markdown sources found")
    paths = WikiPaths(project)
    provider = _get_provider()
    results = []
    for source in sources:
        try:
            pages = await run_ingest(
                paths=paths,
                source_path=source,
                source_text=source.read_text(encoding="utf-8", errors="replace"),
                provider=provider,
                task_id=f"novel-wiki-pilot-{source.stem[:24]}",
            )
            results.append({"source": source.relative_to(project).as_posix(), "status": "success", "pages": len(pages)})
        except Exception as exc:  # keep the pilot report source-scoped
            results.append({"source": source.relative_to(project).as_posix(), "status": "failed", "error": _error_summary(exc)})
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(project),
        "selected": len(sources),
        "succeeded": sum(item["status"] == "success" for item in results),
        "failed": sum(item["status"] == "failed" for item in results),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(run_pilot(args.project_root, args.limit))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
