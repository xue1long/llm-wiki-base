"""Batch V7 extraction dry-run with resumable checkpoints.

This is the safe Phase 2 preparation step.  Applying pages is deliberately
fail-closed until the Task 7 human spot-check has been approved.
"""
from __future__ import annotations

import argparse
import json
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


DEFAULT_ROOT = Path("knowledge/novel-wiki")
DEFAULT_CHECKPOINT = ".index/v7_full_checkpoint.json"
DEFAULT_JSON = Path("docs/superpowers/reports/2026-09-14-extract-full.json")
DEFAULT_MARKDOWN = Path("docs/superpowers/reports/2026-09-14-extract-full-report.md")


def run_full(
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
    """Process every supported raw source in resumable dry-run batches."""
    if not dry_run:
        raise RuntimeError(
            "full apply is blocked until Task 7 spot-check accuracy is approved"
        )
    if batch_size < 1 or max_retries < 1:
        raise ValueError("batch_size and max_retries must be positive")
    root = Path(root)
    checkpoint = Path(checkpoint_path) if checkpoint_path else root / DEFAULT_CHECKPOINT
    source_files = _source_files(root)
    batches = [
        source_files[start : start + batch_size]
        for start in range(0, len(source_files), batch_size)
    ]
    completed = _read_checkpoint(checkpoint)
    results: list[dict[str, Any]] = []
    batches_skipped = 0
    for batch_number, batch in enumerate(batches, 1):
        if batch_number in completed:
            batches_skipped += 1
            continue
        batch_results = [_with_retries(root, path, max_retries, llm=llm) for path in batch]
        results.extend(batch_results)
        if not any(item["error"] for item in batch_results):
            completed.add(batch_number)
            _write_checkpoint(checkpoint, completed)

    previous_results = _previous_results(json_output) if not results else []
    report_results = results or previous_results

    summary = {
        "selected": len(source_files),
        "processed": len(results),
        "batches": len(batches),
        "batches_skipped": batches_skipped,
        "errors": sum(1 for item in report_results if item["error"]),
        "pages": sum(len(item["pages"]) for item in report_results),
        "results_reused": bool(previous_results),
    }
    report = {
        "mode": "dry-run",
        "root": str(root),
        "batch_size": batch_size,
        "max_retries": max_retries,
        "checkpoint": str(checkpoint),
        "llm_enabled": llm is not None,
        "summary": summary,
        "results": report_results,
    }
    if json_output is not None:
        _write_report(Path(json_output), _json_text(report))
    if markdown_output is not None:
        _write_report(Path(markdown_output), _markdown_text(report))
    return report


def _with_retries(
    root: Path, path: Path, max_retries: int, *, llm: Any = None
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for attempt in range(1, max_retries + 1):
        result = _extract_one(root, path, path.relative_to(root).as_posix(), llm=llm)
        result["attempts"] = attempt
        if not result["error"]:
            return result
    return result


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
            {"version": 1, "completed_batches": sorted(completed)},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )


def _previous_results(path: str | Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        results = payload.get("results", [])
        return results if isinstance(results, list) else []
    except (OSError, ValueError, AttributeError):
        return []


def _markdown_text(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# V7 Extract Full Dry-Run Report",
        "",
        f"- mode: `{report['mode']}`",
        f"- batch size: {report['batch_size']}",
        f"- selected: {summary['selected']}",
        f"- processed this run: {summary['processed']}",
        f"- batches: {summary['batches']} (skipped: {summary['batches_skipped']})",
        f"- errors: {summary['errors']}",
        f"- pages (dry-run): {summary['pages']}",
        "",
        "No Wiki pages were written. Full apply remains blocked until pilot spot-check approval.",
        "",
        "## Sources",
        "",
        "| Source | Type | Complete | Pages | Attempts | Error |",
        "|---|---|---:|---:|---:|---|",
    ]
    for item in report["results"]:
        lines.append(
            f"| `{item['source']}` | `{item['doc_type']}` | {item['complete']} | "
            f"{len(item['pages'])} | {item.get('attempts', 1)} | {item['error'] or ''} |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the V7 full extraction dry-run.")
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--checkpoint", default=None)
    parser.add_argument("--json-out", default=str(DEFAULT_JSON))
    parser.add_argument("--markdown-out", default=str(DEFAULT_MARKDOWN))
    parser.add_argument(
        "--provider",
        default=None,
        help=(
            "Optional name of a configured LLM provider (from "
            "src.llm.registry.ProviderRegistry). When omitted, the run is "
            "offline-heuristic only and never hits the network."
        ),
    )
    parser.add_argument("--apply", action="store_true", help="blocked until pilot approval")
    args = parser.parse_args(argv)
    llm = _build_llm(args.provider)
    try:
        report = run_full(
            args.root,
            batch_size=args.batch_size,
            max_retries=args.max_retries,
            checkpoint_path=args.checkpoint,
            dry_run=not args.apply,
            json_output=args.json_out,
            markdown_output=args.markdown_out,
            llm=llm,
        )
    except (RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    print(_json_text(report), end="")
    return 0 if report["summary"]["errors"] == 0 else 2


def _build_llm(provider_name: str | None):
    if not provider_name:
        return None
    from src.pipeline.v7_extract.llm_client import AnthropicLLMClient

    return AnthropicLLMClient(default_provider_name=provider_name)


if __name__ == "__main__":
    sys.exit(main())
