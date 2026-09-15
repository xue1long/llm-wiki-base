"""Batch V7 extraction with resumable checkpoints.

Dry-run is the default. Apply remains fail-closed unless explicitly unlocked.

v3 (plan 2026-09-15): run_full / _with_retries are now async (Stage
1/3/4/5 are async). The CLI entry point calls ``asyncio.run(main())``.
CLI flags are unchanged.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.extract_pilot import (  # noqa: E402
    _extract_one,
    _json_text,
    _source_files,
    _write_report,
)
from src.pipeline.v7_extract.failures import ExtractionResult, ExtractionStatus  # noqa: E402
from src.pipeline.v7_extract.wiki_writer import WikiWriter  # noqa: E402


DEFAULT_ROOT = Path("knowledge/novel-wiki")
DEFAULT_CHECKPOINT = ".index/v7_full_checkpoint.json"
DEFAULT_JSON = Path("docs/superpowers/reports/2026-09-14-extract-full.json")
DEFAULT_MARKDOWN = Path("docs/superpowers/reports/2026-09-14-extract-full-report.md")


async def run_full(
    root: str | Path = DEFAULT_ROOT,
    *,
    batch_size: int = 500,
    checkpoint_path: str | Path | None = None,
    max_retries: int = 3,
    dry_run: bool = True,
    json_output: str | Path | None = None,
    markdown_output: str | Path | None = None,
    llm: Any = None,
) -> dict[str, Any]:
    """Process every supported raw source in resumable batches.

    Async version (v3): awaits ``_extract_one`` for each source. The
    CLI stays sync (main() wraps ``asyncio.run(run_full(...))``).

    Plan 2026-09-15 Plan 2: --apply is gated by the V7_ALLOW_APPLY env
    var instead of an 80% spot-check threshold. LLM mis-categorizations
    land in review_queue (D4) for human triage. Default behaviour is
    still dry-run only; the env var is an explicit acknowledgement that
    the operator has reviewed the spot-check report.
    """
    if not dry_run:
        if not os.environ.get("V7_ALLOW_APPLY"):
            raise RuntimeError(
                "full apply is blocked by default. Either run --dry-run first, "
                "or set V7_ALLOW_APPLY=1 to acknowledge that LLM errors may "
                "occur and any low-confidence page will be flagged for "
                "human review via .index/reviews_queue.json."
            )
    if batch_size < 1 or max_retries < 1:
        raise ValueError("batch_size and max_retries must be positive")
    root = Path(root)
    checkpoint = Path(checkpoint_path) if checkpoint_path else root / DEFAULT_CHECKPOINT
    writer = WikiWriter(root) if not dry_run else None
    source_files = _source_files(root)
    batches = [
        source_files[start : start + batch_size]
        for start in range(0, len(source_files), batch_size)
    ]
    completed = _read_checkpoint(checkpoint)
    results: list[ExtractionResult] = []
    batches_skipped = 0
    for batch_number, batch in enumerate(batches, 1):
        if batch_number in completed:
            batches_skipped += 1
            continue
        # v3: each source is processed via async _extract_one
        batch_results: list[ExtractionResult] = []
        batch_pages: list[Any] = []
        for path in batch:
            result = await _with_retries(
                root, path, max_retries, llm=llm, page_sink=batch_pages.append
            )
            batch_results.append(result)
        if writer is not None and not any(
            r.status == ExtractionStatus.FAILED for r in batch_results
        ):
            writer.commit_and_index(batch_pages)
        results.extend(batch_results)
        if not any(r.status == ExtractionStatus.FAILED for r in batch_results):
            completed.add(batch_number)
            _write_checkpoint(checkpoint, completed)

    # Wave 2 / Task 2: a "previous_results" cache hit returns the prior
    # JSON report's results as raw dicts (legacy shape). Convert them to
    # ExtractionResult so the summary counters use the same code path.
    raw_previous = _previous_results(json_output) if not results else []
    reused_results = _to_results(raw_previous) if raw_previous else []
    effective_results = results or reused_results
    raw_dicts = (
        [r.to_dict() for r in results]
        if results
        else [r.to_dict() for r in reused_results]
    )

    summary = _summarize_results(
        effective_results,
        selected=len(source_files),
        processed=len(results),
        batches=len(batches),
        batches_skipped=batches_skipped,
        results_reused=bool(raw_previous),
    )
    report = {
        "mode": "apply" if not dry_run else "dry-run",
        "root": str(root),
        "batch_size": batch_size,
        "max_retries": max_retries,
        "checkpoint": str(checkpoint),
        "llm_enabled": llm is not None,
        "summary": summary,
        "results": raw_dicts,
    }
    if json_output is not None:
        _write_report(Path(json_output), _json_text(report))
    if markdown_output is not None:
        _write_report(Path(markdown_output), _markdown_text(report))
    return report


async def _with_retries(
    root: Path,
    path: Path,
    max_retries: int,
    *,
    llm: Any = None,
    page_sink: Any = None,
) -> ExtractionResult:
    """v3 + Wave 2: awaits _extract_one (async) and updates the
    five-state ``ExtractionResult`` returned by it.

    The retry loop tracks attempts on the dataclass attribute
    (``attempts``) instead of the legacy ``result["attempts"]`` dict
    key. A retry that still returns ``FAILED`` will eventually surface
    after ``max_retries`` is exhausted.
    """
    result: ExtractionResult | None = None
    for attempt in range(1, max_retries + 1):
        pages: list[Any] = []
        result = await _extract_one(
            root,
            path,
            path.relative_to(root).as_posix(),
            llm=llm,
            page_sink=pages.append,
        )
        result.attempts = attempt
        if result.status != ExtractionStatus.FAILED:
            if page_sink is not None:
                for page in pages:
                    page_sink(page)
            return result
    return result  # type: ignore[return-value]


def _read_checkpoint(path: Path) -> set[int]:
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        values = payload.get("completed_batches", [])
        return {int(value) for value in values}
    except (OSError, ValueError, AttributeError, TypeError):
        return set()


def _write_checkpoint(path: Path, completed: set[int]) -> None:
    _write_report(
        path,
        json.dumps(
            {"completed_batches": sorted(completed)},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )


def _previous_results(json_output: str | Path | None) -> list[dict[str, Any]]:
    """Reuse the prior JSON report's results when this run is empty."""
    if json_output is None:
        return []
    path = Path(json_output)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    results = payload.get("results", [])
    return [dict(item) for item in results if isinstance(item, dict)]


def _to_results(raw_dicts: list[dict[str, Any]]) -> list[ExtractionResult]:
    """Rehydrate ``ExtractionResult`` instances from JSON-loaded dicts.

    The prior JSON report's ``results`` field is a list of dicts (the
    legacy shape). When the current run is empty we want to compute the
    same five-state summary as a fresh run — rebuild dataclasses so
    ``summarize_results`` has a uniform input.

    Missing fields fall back to safe defaults so an older report
    (pre-Wave 2) still round-trips.
    """
    out: list[ExtractionResult] = []
    for raw in raw_dicts:
        source_id = str(raw.get("source_id") or raw.get("source") or "")
        legacy_value = raw.get("legacy_status") or raw.get("status") or "ok"
        try:
            legacy = ExtractionStatus(legacy_value)
        except ValueError:
            legacy = ExtractionStatus.OK
        pages_field = raw.get("pages") or []
        pages = [
            {"id": page.get("id"), "title": page.get("title")}
            if isinstance(page, dict) else page
            for page in pages_field
        ]
        out.append(ExtractionResult.from_v3_status(
            legacy,
            source_id,
            pages=pages,
            source_md5=raw.get("source_md5", ""),
            written_page_ids=list(raw.get("written_page_ids", [])),
            blocked_page_ids=list(raw.get("blocked_page_ids", [])),
            failed_page_ids=list(raw.get("failed_page_ids", [])),
            review_reasons=list(raw.get("review_reasons", [])),
            blocked_topic_ids=list(raw.get("blocked_topic_ids", [])),
            failure_stage=raw.get("failure_stage"),
            attempts=int(raw.get("attempts", 1)),
            metadata=raw,
        ))
    return out


def _summarize_results(
    results: list[ExtractionResult],
    *,
    selected: int,
    processed: int,
    batches: int,
    batches_skipped: int,
    results_reused: bool,
) -> dict[str, Any]:
    """Build the five-state summary for ``run_full`` (plan §4 Task 5).

    Five-state + legacy_status counters live here, alongside the legacy
    ``errors`` / ``pages`` aggregates. ``errors`` is strictly the count
    of FAILED results (pre-refactor conflated BLOCKED + FAILED into the
    same counter; plan §4 Task 5 splits them).
    """
    by_status: dict[str, int] = {
        ExtractionStatus.WRITTEN.value: 0,
        ExtractionStatus.BLOCKED.value: 0,
        ExtractionStatus.FAILED.value: 0,
        ExtractionStatus.INCOMPLETE.value: 0,
        ExtractionStatus.SKIPPED.value: 0,
    }
    by_legacy_status: dict[str, int] = {
        ExtractionStatus.OK.value: 0,
        ExtractionStatus.NEEDS_REVIEW.value: 0,
        ExtractionStatus.INCOMPLETE.value: 0,
    }
    for result in results:
        status_value = result.status.value
        if status_value in by_status:
            by_status[status_value] += 1
        legacy = (result.legacy_status or result._legacy_from_status()).value
        if legacy in by_legacy_status:
            by_legacy_status[legacy] += 1
    return {
        "selected": selected,
        "processed": processed,
        "batches": batches,
        "batches_skipped": batches_skipped,
        "results_reused": results_reused,
        "by_status": by_status,
        "by_legacy_status": by_legacy_status,
        "errors": by_status[ExtractionStatus.FAILED.value],
        "pages": sum(len(r.written_page_ids) for r in results),
    }


def _markdown_text(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# V7 Extract Full Batch Report",
        "",
        f"- mode: `{report['mode']}`",
        f"- root: `{report['root']}`",
        f"- batch_size: {report['batch_size']}",
        f"- max_retries: {report['max_retries']}",
        f"- selected: {summary['selected']}",
        f"- processed: {summary['processed']}",
        f"- batches: {summary['batches']}",
        f"- batches_skipped: {summary['batches_skipped']}",
        f"- errors: {summary['errors']}",
        f"- pages: {summary['pages']}",
        "",
        "## Results",
        "",
        "| Source | Type | Complete | Topics | Pages | Attempts | Error |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for item in report["results"]:
        lines.append(
            f"| `{item['source']}` | `{item['doc_type']}` | "
            f"{item['complete']} | {len(item['topics'])} | "
            f"{len(item['pages'])} | {item.get('attempts', 1)} | {item['error'] or ''} |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the V7 extraction full batch.")
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--checkpoint", default=DEFAULT_CHECKPOINT)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--json-out", default=str(DEFAULT_JSON))
    parser.add_argument("--markdown-out", default=str(DEFAULT_MARKDOWN))
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write accepted concept pages (requires V7_ALLOW_APPLY=1)",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="Optional LLM provider name (auto-resolves to registry default)",
    )
    args = parser.parse_args(argv)
    llm = _build_llm(args.provider)
    report = asyncio.run(run_full(
        args.root,
        batch_size=args.batch_size,
        checkpoint_path=args.checkpoint,
        max_retries=args.max_retries,
        dry_run=not args.apply,
        json_output=args.json_out,
        markdown_output=args.markdown_out,
        llm=llm,
    ))
    print(_json_text(report), end="")
    return 0 if report["summary"]["errors"] == 0 else 2


def _build_llm(provider_name: str | None):
    target = provider_name
    if not target:
        try:
            from src.llm.registry import ProviderRegistry

            cfg = ProviderRegistry.get_default()
            target = cfg.name
        except Exception:
            return None
    try:
        from src.pipeline.v7_extract.llm_client import AnthropicLLMClient

        return AnthropicLLMClient(default_provider_name=target)
    except Exception:
        return None


if __name__ == "__main__":
    sys.exit(main())
