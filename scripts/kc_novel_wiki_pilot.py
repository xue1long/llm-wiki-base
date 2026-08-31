"""Run a bounded pilot through the default candidate ingest pipeline."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import json
from datetime import datetime, timezone
from pathlib import Path

from src.llm.provider_factory import create_llm_provider
from src.pipeline import _get_provider, commit_ingest, generate_ingest
from src.pipeline.extraction_types import collect_artifact
from src.pipeline.text_preprocessing import preprocess_source
from src.pipeline.readiness_replay import serialize_audit
from scripts.kc_novel_wiki_inventory import select_stratified_sources
from src.utils.path import canonical_raw_key
from src.wiki.core.paths import WikiPaths


def select_sources(project: Path, limit: int) -> list[Path]:
    """Select deterministic, small, markdown inputs for the first live run."""
    root = project / "raw" / "sources"
    return sorted(root.rglob("*.md"), key=lambda p: (p.stat().st_size, p.as_posix()))[:limit]


def select_sources_from_inventory(project: Path, inventory_path: Path, limit: int) -> list[Path]:
    report = json.loads(inventory_path.read_text(encoding="utf-8"))
    return [project / source_id for source_id in select_stratified_sources(report, limit=limit)]


def _error_summary(exc: BaseException) -> str:
    """Keep the deepest provider error visible in the pilot report."""
    parts = [f"{type(exc).__name__}: {exc}"]
    cause = exc.__cause__
    while cause is not None:
        parts.append(f"{type(cause).__name__}: {cause}")
        cause = cause.__cause__
    return " <- ".join(parts)


async def run_pilot(
    project: Path,
    limit: int = 3,
    provider_name: str | None = None,
    concurrency: int = 3,
    inventory_path: Path | None = None,
    commit: bool = True,
) -> dict:
    project = project.resolve()
    sources = (
        select_sources_from_inventory(project, inventory_path, limit)
        if inventory_path is not None
        else select_sources(project, limit)
    )
    if not sources:
        raise ValueError("no markdown sources found")
    paths = WikiPaths(project)
    provider = create_llm_provider(provider_name) if provider_name else _get_provider()
    semaphore = asyncio.Semaphore(concurrency)

    async def process(source: Path) -> dict:
        async with semaphore:
            source_id = canonical_raw_key(str(source), project)
            artifact = collect_artifact(source, source_id=source_id)
            source_text = artifact.input_text
            audit_fields: dict = {}
            try:
                prepared = preprocess_source(
                    source_text,
                    source_id=artifact.source_id,
                    source_bytes_sha256=artifact.source_bytes_sha256,
                    format=artifact.format,
                    extraction_method=artifact.extraction_method,
                )
                audit_fields = serialize_audit(
                    prepared.content_assessment,
                    prepared.report,
                    analyzer_called=False,
                    failure_reason=None,
                )
                audit_fields.update({
                    "noise_warnings": list(prepared.report.warnings),
                    "applied_rules": [
                        {
                            "rule_id": rule.rule_id,
                            "removed_line_count": rule.removed_line_count,
                            "removed_char_count": rule.removed_char_count,
                        }
                        for rule in prepared.report.applied_rules
                    ],
                })
                pages, extra_pages, meta = await generate_ingest(
                    paths=paths,
                    source_path=source,
                    source_text=source_text,
                    provider=provider,
                    task_id=f"novel-wiki-pilot-{source.stem[:24]}",
                )
                if commit:
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
                        "assessment_version", "policy_version", "source_id", "format",
                        "extraction_method", "content_kind", "decision", "reason_codes",
                        "analyzer_called", "evidence_capacity", "failure_reason",
                        "binding_mode", "evidence_refs", "evidence", "preprocessing_version",
                        "source_bytes_sha256", "input_text_sha256",
                        "canonical_text_sha256", "prompt_text_sha256",
                        "noise_warnings", "applied_rules",
                    ):
                        if key in audit:
                            result[key] = audit[key]
                    if "block_id" in audit:
                        result["block_id"] = audit["block_id"]
                    if "exact_quote" in audit:
                        result["exact_quote"] = audit["exact_quote"]
                    elif "quote" in audit:
                        result["exact_quote"] = audit["quote"]
                    if "quote_hash" in audit:
                        result["quote_hash"] = audit["quote_hash"]
                result["category"] = "accepted" if result["pages"] else _decision_category(result)
                return result
            except Exception as exc:  # keep the pilot report source-scoped
                audit_fields["failure_reason"] = _error_summary(exc)
                return {
                    "source": source.relative_to(project).as_posix(),
                    "status": "failed",
                    "category": _error_category(exc),
                    **audit_fields,
                    "error": _error_summary(exc),
                }

    results = await asyncio.gather(*(process(source) for source in sources))
    categories = Counter(item.get("category", "rejected") for item in results)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(project),
        "selected": len(sources),
        "succeeded": sum(item["status"] == "success" for item in results),
        "failed": sum(item["status"] == "failed" for item in results),
        "categories": {key: categories.get(key, 0) for key in (
            "accepted", "skipped", "rejected", "needs_human_review", "provider_error"
        )},
        "accepted": categories.get("accepted", 0),
        "skipped": categories.get("skipped", 0),
        "rejected": categories.get("rejected", 0),
        "needs_human_review": categories.get("needs_human_review", 0),
        "provider_error": categories.get("provider_error", 0),
        "results": results,
    }


def _decision_category(result: dict) -> str:
    decision = result.get("decision")
    if decision == "skip_no_content":
        return "skipped"
    if decision in {"quarantine_degraded", "unsupported"}:
        return "rejected"
    return "needs_human_review"


def _error_category(exc: BaseException) -> str:
    text = _error_summary(exc).lower()
    if any(marker in text for marker in (
        "provider", "429", "quota", "timeout", "connection", "httpx",
        "truncatedresponseerror", "max_tokens", "finish_reason",
    )):
        return "provider_error"
    return "rejected"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--provider", default=None, help="explicit registry provider name")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--inventory", type=Path, default=None)
    parser.add_argument("--no-commit", action="store_true", help="generate only; do not write staging wiki/audit")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(run_pilot(args.project_root, args.limit, args.provider, args.concurrency, args.inventory, not args.no_commit))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
