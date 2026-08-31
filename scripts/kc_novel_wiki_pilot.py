"""Run a bounded pilot through the default candidate ingest pipeline."""
from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import json
from datetime import datetime, timezone
from pathlib import Path

from src.llm.provider_factory import create_llm_provider
from src.pipeline import _get_provider, commit_ingest, generate_ingest
from src.pipeline.text_preprocessing import preprocess_source
from src.utils.path import canonical_raw_key
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


async def run_pilot(project: Path, limit: int = 3, provider_name: str | None = None, concurrency: int = 3) -> dict:
    project = project.resolve()
    sources = select_sources(project, limit)
    if not sources:
        raise ValueError("no markdown sources found")
    paths = WikiPaths(project)
    provider = create_llm_provider(provider_name) if provider_name else _get_provider()
    semaphore = asyncio.Semaphore(concurrency)

    async def process(source: Path) -> dict:
        async with semaphore:
            source_text = source.read_text(encoding="utf-8", errors="replace")
            audit_fields: dict = {}
            try:
                prepared = preprocess_source(
                    source_text,
                    source_id=canonical_raw_key(str(source), project),
                    source_bytes_sha256=sha256(source.read_bytes()).hexdigest(),
                )
                audit_fields = {
                    "preprocessing_version": prepared.report.version,
                    "source_bytes_sha256": prepared.report.source_bytes_sha256,
                    "input_text_sha256": prepared.report.input_text_sha256,
                    "canonical_text_sha256": prepared.report.canonical_text_sha256,
                    "prompt_text_sha256": prepared.report.prompt_text_sha256,
                    "noise_warnings": list(prepared.report.warnings),
                    "applied_rules": [
                        {
                            "rule_id": rule.rule_id,
                            "removed_line_count": rule.removed_line_count,
                            "removed_char_count": rule.removed_char_count,
                        }
                        for rule in prepared.report.applied_rules
                    ],
                }
                pages, extra_pages, meta = await generate_ingest(
                    paths=paths,
                    source_path=source,
                    source_text=source_text,
                    provider=provider,
                    task_id=f"novel-wiki-pilot-{source.stem[:24]}",
                )
                await commit_ingest(
                    paths=paths,
                    source_path=source,
                    pages=pages,
                    extra_pages=extra_pages,
                    task_id=f"novel-wiki-pilot-{source.stem[:24]}",
                    triage_result=meta.get("triage"),
                    missing_slugs=meta.get("missing_slugs"),
                    kc_bundle_key=meta.get("kc_bundle_key"),
                )
                result = {
                    "source": source.relative_to(project).as_posix(),
                    "status": "success",
                    "pages": len(pages),
                    **audit_fields,
                }
                audit = meta.get("pilot_audit")
                if isinstance(audit, dict):
                    for key in (
                        "source_id", "block_id", "quote_hash", "binding_mode",
                        "evidence_refs", "preprocessing_version",
                        "source_bytes_sha256", "input_text_sha256",
                        "canonical_text_sha256", "prompt_text_sha256",
                        "noise_warnings", "applied_rules",
                    ):
                        if key in audit:
                            result[key] = audit[key]
                    if "exact_quote" in audit:
                        result["exact_quote"] = audit["exact_quote"]
                    elif "quote" in audit:
                        result["exact_quote"] = audit["quote"]
                return result
            except Exception as exc:  # keep the pilot report source-scoped
                return {
                    "source": source.relative_to(project).as_posix(),
                    "status": "failed",
                    **audit_fields,
                    "error": _error_summary(exc),
                }

    results = await asyncio.gather(*(process(source) for source in sources))
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
    parser.add_argument("--provider", default=None, help="explicit registry provider name")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(run_pilot(args.project_root, args.limit, args.provider, args.concurrency))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
