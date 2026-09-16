"""Run a deterministic V7 extraction pilot in dry-run mode.

The pilot is deliberately a dry-run tool.  It reads raw sources, runs
the local Stage 1 / Stage 3 / Stage 4 / Stage 5 components, and writes
reports plus idempotent failure records; it never calls the Wiki writer
or mutates ``wiki/``.

v3 (plan 2026-09-15) changes:
- All Stage calls are now ``async def`` (Stage 1 / 3 / 4 / 5 are async
  per the new architecture). ``run_pilot`` / ``_extract_one`` are
  async; ``main`` enters via ``asyncio.run(main())``.
- ``classification.doc_type`` is now a plain string (was
  ``DocType.value`` in v2). Output JSON schema unchanged.
- CLI flags unchanged: ``--count``, ``--seed``, ``--root``,
  ``--json-out``, ``--markdown-out``, ``--provider``, ``--sources``.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable

# Make direct ``python scripts/extract_pilot.py`` execution behave like a
# module invocation from the repository root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.pipeline.v7_extract._page_id import _stable_page_id, validate_page_id
from src.pipeline.v7_extract.completeness_checker import check_completeness
from src.pipeline.v7_extract.doc_classifier import classify_doc
from src.pipeline.v7_extract.failures import (
    ExtractionResult,
    ExtractionStatus,
    enqueue_failure,
)
from src.pipeline.v7_extract.slot_filler import fill_slots
from src.pipeline.v7_extract.topic_clusterer import cluster_topics

log = logging.getLogger(__name__)


SUPPORTED_SUFFIXES = frozenset({".md", ".txt", ".html", ".htm"})
DEFAULT_ROOT = Path("knowledge/novel-wiki")
DEFAULT_JSON = Path("docs/superpowers/reports/2026-09-13-extract-pilot.json")
DEFAULT_MARKDOWN = Path("docs/superpowers/reports/2026-09-13-extract-pilot-report.md")

# T1 / H2 加固: cap the per-failure reason string so a noisy LLM trace
# doesn't dominate the pilot's report.
_EXC_REASON_LIMIT = 500


async def run_pilot(
    root: str | Path = DEFAULT_ROOT,
    *,
    count: int = 50,
    seed: int = 42,
    json_output: str | Path | None = None,
    markdown_output: str | Path | None = None,
    llm: Any = None,
    sources: Iterable[str | Path] | None = None,
) -> dict[str, Any]:
    """Run the pilot and optionally write JSON / Markdown reports.

    Selection is deterministic for a given ``seed``.  The returned report
    is fully JSON-serializable so callers can add human spot-check
    annotations.

    ``llm`` is the optional ``LLMClient`` injected for Stage 1 / 3 / 4 / 5.
    When ``llm`` is ``None`` the pipeline runs offline-heuristic only —
    but Stage 1 / 3 / 4 / 5 now REQUIRE an LLM, so this branch is
    effectively a no-op (every stage returns ``incomplete`` / empty
    topics). We keep the parameter for backward compatibility.

    ``sources`` is an explicit list of source paths to run. When provided
    it overrides the random selection — used by spot-check pilots that
    need to cover known-failure cases.
    """
    if count < 1:
        raise ValueError("count must be positive")
    root = Path(root)
    if sources is not None:
        selected = _resolve_sources(root, sources)
    else:
        candidates = _source_files(root)
        selected = _select_sources(candidates, count, seed)
    results: list[ExtractionResult] = []
    for path in selected:
        relative = path.relative_to(root).as_posix()
        results.append(await _extract_one(root, path, relative, llm=llm))

    # Serialize ExtractionResult → dict so the JSON / Markdown reports
    # keep the same shape callers (and the existing tests) rely on.
    serialized = [r.to_dict() for r in results]
    report = {
        "mode": "dry-run",
        "root": str(root),
        "seed": seed,
        "llm_enabled": llm is not None,
        "sources": [item["source"] for item in serialized],
        "summary": _summarize(serialized),
        "spot_check": {
            "status": "pending",
            "accuracy": None,
            "reviewed_sources": [],
        },
        "results": serialized,
    }
    if json_output is not None:
        _write_report(Path(json_output), _json_text(report))
    if markdown_output is not None:
        _write_report(Path(markdown_output), _markdown_text(report))
    return report


def _resolve_sources(root: Path, sources: Iterable[str | Path]) -> list[Path]:
    """Resolve the explicit source list to Path objects under ``root``.

    Sources that don't exist under ``root`` are silently dropped so the
    pilot still runs on the remaining files.
    """
    selected: list[Path] = []
    for raw in sources:
        path = Path(raw)
        if not path.is_absolute():
            path = root / path
        if path.is_file():
            selected.append(path)
    return selected


def _source_files(root: Path) -> list[Path]:
    source_root = root / "raw" / "sources"
    if not source_root.exists():
        return []
    return sorted(
        path
        for path in source_root.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )


def _select_sources(candidates: list[Path], count: int, seed: int) -> list[Path]:
    # A local import keeps the selection implementation obvious and avoids
    # touching global random state used by other scripts.
    import random

    rng = random.Random(seed)
    if len(candidates) <= count:
        return candidates
    return sorted(rng.sample(candidates, count))


async def _extract_one(
    root: Path,
    path: Path,
    relative: str,
    *,
    llm: Any = None,
    page_sink: Callable[[Any], None] | None = None,
) -> ExtractionResult:
    """v3 + Wave 1 + Task 2: 统一返回 ExtractionResult 五态对象.

    The canonical return type is now ``ExtractionResult`` (plan §2.2.1).
    The pre-refactor dict contract — ``source`` / ``doc_type`` /
    ``complete`` / ``topics`` / ``pages`` / ``error`` — round-trips
    through ``ExtractionResult.metadata`` so callers and the JSON
    report keep working unchanged. Stage failures roll up to
    ``ExtractionStatus.FAILED`` with a truncated reason and
    ``failure_stage="extract_one"``.
    """
    source_md5 = ""  # populated below; safe default for the FAILED branch
    try:
        # source_md5 lives in the try block so any IO failure (broken
        # symlink, permission denied on a directory) still falls through to
        # the ExtractionStatus.FAILED branch instead of crashing the
        # pipeline (P2: never raise).
        source_md5 = hashlib.md5(path.read_bytes()).hexdigest()
        content = path.read_text(encoding="utf-8", errors="replace")
        classification = await classify_doc(
            content, filename_hint=path.name, llm=llm,
            project_root=root,
        )
        # Plan 2026-09-17 / Task 2: short-circuit on Stage 1 technical
        # failure. Per Failure Contract, a Stage 1 LLM outage must NOT
        # silently become INCOMPLETE / WRITTEN — it returns FAILED and
        # records the failure to the reviews queue.
        if classification.failed:
            reason = f"stage1_llm_failed: {classification.error}"
            _record_failure(
                relative,
                "stage1",
                reason=reason,
                content_hash=source_md5,
                provider=_llm_provider_label(llm),
                queue_path=root / ".index" / "reviews_queue.json",
            )
            return ExtractionResult(
                status=ExtractionStatus.FAILED,
                source_id=relative,
                source_md5=source_md5,
                failure_stage="stage1",
                review_reasons=[reason],
                metadata={
                    "source": relative,
                    "characters": len(content),
                    "doc_type": classification.doc_type,
                    "confidence": classification.confidence,
                    "rationale": classification.rationale,
                    "complete": False,
                    "completeness_reason": "",
                    "topics": [],
                    "error": reason,
                },
            )
        # v3: Stage 3 is async + P5-decoupled (doc_type is soft hint).
        complete, completeness_reason = await check_completeness(
            content,
            doc_type_hint=classification.doc_type,
            llm=llm,
            project_root=root,
        )

        # Legacy dict fields carried through ``metadata`` so the JSON
        # contract stays identical to the pre-refactor shape.
        metadata: dict[str, Any] = {
            "source": relative,
            "characters": len(content),
            # v3: classification.doc_type is a plain string (was DocType.value in v2)
            "doc_type": classification.doc_type,
            "confidence": classification.confidence,
            "rationale": classification.rationale,
            "complete": complete,
            "completeness_reason": completeness_reason,
            "topics": [],
            "error": None,
        }
        result = ExtractionResult(
            status=ExtractionStatus.INCOMPLETE if not complete
            else ExtractionStatus.WRITTEN,
            source_id=relative,
            source_md5=source_md5,
            pages=[],
            metadata=metadata,
        )
        if not complete:
            return result

        items = _extract_items(content, relative)
        item_map = {item["id"]: item for item in items}
        # v3: cluster_topics is async; returns [] if LLM missing
        topics = await cluster_topics(
            items, llm=llm, project_root=root,
        )
        # Track topics + page summaries for the legacy JSON contract.
        topic_dicts: list[dict[str, Any]] = []
        page_dicts: list[dict[str, Any]] = []
        # Five-state counters — drive ``status`` below.
        failed_topic_ids: list[str] = []
        written_page_ids: list[str] = []
        blocked_page_ids: list[str] = []
        for topic in topics:
            topic_text = "\n\n".join(
                item_map[item_id]["text"]
                for item_id in topic.item_ids
                if item_id in item_map
            )
            # v3: fill_slots is async + D7 (returns None on failure)
            page = await fill_slots(
                topic, source_text=topic_text,
                llm=llm, item_texts=item_map, project_root=root,
            )
            if page is None:
                # D7: skip failed topic — record only that it failed
                topic_dicts.append({
                    "id": topic.id,
                    "title": topic.title,
                    "item_ids": topic.item_ids,
                    "failed": True,
                })
                failed_topic_ids.append(topic.id)
                _record_failure(
                    relative,
                    "stage5",
                    page_id=_stable_page_id(relative, topic.id),
                    topic_id=topic.id,
                    reason="stage5_llm_error",
                    content_hash=source_md5,
                    prompt_kind="fill_slots",
                    provider=_llm_provider_label(llm),
                    queue_path=root / ".index" / "reviews_queue.json",
                )
                continue
            # T1 / H2 加固: page ID is script-owned. Build a stable
            # page ID from the relative source path + topic slug; never
            # trust the LLM-supplied topic id as the page id (cross-document
            # collisions otherwise). The legacy __dict__ injection of
            # topic_id is replaced below via the dedicated ConceptPage
            # attribute, so failures.filter_failed_topics keeps working
            # without poking the dataclass.
            page_id = _stable_page_id(relative, topic.id)
            validate_page_id(page_id)
            page.topic_id = topic.id  # formal field (see ConceptPage)
            topic_dicts.append({
                "id": topic.id,
                "title": topic.title,
                "item_ids": topic.item_ids,
            })
            page_dicts.append({
                "id": page_id,
                "title": page.title,
                "type": page.type,
                "source_ids": list(page.sources),
                "filled_slots": list(page.slots),
                "needs_review_slots": list(page.needs_review_slots),
                "has_evidence": page.has_evidence,
            })
            # Wave 3 / Task 4 / §2.2.1: pages that the Writer will block
            # (needs_review / no_evidence / __other__ / content_filter)
            # MUST NOT count as written. They go into blocked_page_ids
            # so the source outcome reflects the actual terminal state.
            if page.needs_review_slots:
                blocked_page_ids.append(page_id)
                result.pages.append(page)
            elif not page.has_evidence:
                blocked_page_ids.append(page_id)
                result.pages.append(page)
            elif getattr(page, "topic_id", None) == "__other__":
                blocked_page_ids.append(page_id)
                result.pages.append(page)
            else:
                written_page_ids.append(page_id)
                result.pages.append(page)
            if page_sink is not None:
                page_sink(page)

        # Decide the five-state verdict. Topics that survived Stage 5
        # become WRITTEN; if every topic failed OR every page got
        # blocked (Gate B/C), escalate to BLOCKED (so the report
        # doesn't mistake silent Stage-5 failures for success).
        if failed_topic_ids and not written_page_ids:
            result.status = ExtractionStatus.BLOCKED
            result.review_reasons.append(
                f"all_topics_failed:{len(failed_topic_ids)}"
            )
        elif written_page_ids and not blocked_page_ids:
            # All pages written successfully.
            result.status = ExtractionStatus.WRITTEN
        elif written_page_ids and blocked_page_ids:
            # Mixed: some pages written, some blocked (Gate B/C).
            result.status = ExtractionStatus.WRITTEN
            result.review_reasons.append(
                f"pages_blocked:{len(blocked_page_ids)}"
            )
        elif blocked_page_ids and not written_page_ids:
            # Every page went through Stage 5 but the Writer gates
            # blocked them all — report as BLOCKED, not WRITTEN.
            result.status = ExtractionStatus.BLOCKED
            result.review_reasons.append(
                f"all_pages_blocked:{len(blocked_page_ids)}"
            )
        elif failed_topic_ids:
            # Mixed outcome: partial write + some blocked topics.
            result.status = ExtractionStatus.WRITTEN
            result.review_reasons.append(
                f"partial_blocked:{len(failed_topic_ids)}"
            )
        result.written_page_ids.extend(written_page_ids)
        result.blocked_page_ids.extend(blocked_page_ids)
        result.blocked_topic_ids.extend(failed_topic_ids)
        metadata["topics"] = topic_dicts
        metadata["pages"] = page_dicts
        return result
    except Exception as exc:
        # T1 / H2 加固: don't dump the full traceback to the operator's
        # console (P2). Record `failure_stage` + truncated reason in the
        # report so spot-check pilots can correlate failures without
        # drowning in stack noise.
        reason = f"{type(exc).__name__}: {exc}"[:_EXC_REASON_LIMIT]
        log.warning(
            "_extract_one failed for %r: %s", relative, reason,
        )
        _record_failure(
            relative,
            "extract_one",
            reason=reason,
            content_hash=source_md5,
            provider=_llm_provider_label(llm),
            queue_path=root / ".index" / "reviews_queue.json",
        )
        # source_md5 was assigned an empty string at function entry; if
        # the try block ran past ``read_bytes`` we already have the real
        # md5, otherwise it stays empty.
        return ExtractionResult(
            status=ExtractionStatus.FAILED,
            source_id=relative,
            source_md5=source_md5,
            failure_stage="extract_one",
            review_reasons=[reason],
            metadata={
                "source": relative,
                "characters": 0,
                "doc_type": None,
                "confidence": 0.0,
                "rationale": "",
                "complete": False,
                "completeness_reason": "",
                "topics": [],
                "error": reason,
            },
        )


def _extract_items(content: str, relative: str) -> list[dict[str, str]]:
    """Section / list-item based slicing — same algorithm as v2."""
    headings = list(re.finditer(r"(?m)^#{1,3}\s+(.+?)\s*$", content))
    if len(headings) >= 2:
        items = []
        for index, match in enumerate(headings):
            end = headings[index + 1].start() if index + 1 < len(headings) else len(content)
            text = content[match.start():end].strip()
            items.append({"id": f"{relative}#section-{index + 1}", "text": text})
        return items
    numbered = [line.strip() for line in content.splitlines() if re.match(r"^\d+[.、,，)]\s*\S", line)]
    if len(numbered) >= 3:
        return [
            {"id": f"{relative}#item-{index + 1}", "text": text}
            for index, text in enumerate(numbered)
        ]
    return [{"id": relative, "text": content.strip()}]


def _llm_provider_label(llm: Any) -> str:
    if llm is None:
        return "offline"
    return str(getattr(llm, "default_provider_name", "") or type(llm).__name__)


def _record_failure(*args: Any, **kwargs: Any) -> None:
    try:
        enqueue_failure(*args, **kwargs)
    except Exception as exc:  # queue I/O must not abort the source loop
        log.warning("failed to enqueue v7 review item: %s", exc)


def _summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    types = Counter(item["doc_type"] for item in results if item["doc_type"])
    statuses = Counter(item.get("status") for item in results)
    return {
        "selected": len(results),
        "processed": len(results),
        "skipped": statuses[ExtractionStatus.SKIPPED.value],
        "written": statuses[ExtractionStatus.WRITTEN.value],
        "blocked": statuses[ExtractionStatus.BLOCKED.value],
        "failed": statuses[ExtractionStatus.FAILED.value],
        "complete": sum(1 for item in results if item["complete"]),
        "incomplete": statuses[ExtractionStatus.INCOMPLETE.value],
        "errors": statuses[ExtractionStatus.FAILED.value],
        "topics": sum(len(item["topics"]) for item in results),
        "pages": sum(len(item["pages"]) for item in results),
        "generated_pages": sum(len(item["pages"]) for item in results),
        "batches": 1 if results else 0,
        "batches_skipped": 0,
        "results_reused": False,
        "doc_types": dict(sorted(types.items())),
    }


def _json_text(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2) + "\n"


def _markdown_text(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# V7 Extract Pilot Report",
        "",
        f"- mode: `{report['mode']}`",
        f"- seed: `{report['seed']}`",
        f"- selected: {summary['selected']}",
        f"- processed: {summary['processed']}",
        f"- written: {summary['written']}",
        f"- blocked: {summary['blocked']}",
        f"- failed: {summary['failed']}",
        f"- complete: {summary['complete']}",
        f"- incomplete: {summary['incomplete']}",
        f"- skipped: {summary['skipped']}",
        f"- generated_pages: {summary['generated_pages']}",
        f"- pages (dry-run): {summary['pages']}",
        "- spot-check: pending",
        "",
        "## Sources",
        "",
        "| Source | Type | Complete | Topics | Pages | Error |",
        "|---|---|---:|---:|---:|---|",
    ]
    for item in report["results"]:
        lines.append(
            f"| `{item['source']}` | `{item['doc_type']}` | "
            f"{item['complete']} | {len(item['topics'])} | "
            f"{len(item['pages'])} | {item['error'] or ''} |"
        )
    lines.append("")
    return "\n".join(lines)


def _write_report(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the V7 extraction pilot in dry-run mode.")
    parser.add_argument("--root", required=True, help="project root directory (required)")
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--json-out", default=str(DEFAULT_JSON))
    parser.add_argument("--markdown-out", default=str(DEFAULT_MARKDOWN))
    parser.add_argument(
        "--provider",
        default=None,
        help=(
            "Optional name of a configured LLM provider (from "
            "src.llm.registry.ProviderRegistry). When omitted, the pilot "
            "auto-resolves the registry default and falls back to "
            "offline-heuristic only when no provider is configured."
        ),
    )
    parser.add_argument(
        "--sources",
        default=None,
        help=(
            "Path to a JSON file holding an explicit list of source paths "
            "(relative to --root) to run. Overrides random selection."
        ),
    )
    args = parser.parse_args(argv)
    if not getattr(args, "root", None):
        parser.error("--root is required (use --root <project_root>)")
    llm = _build_llm(args.provider)
    sources = _load_sources(args.sources)
    report = asyncio.run(run_pilot(
        args.root,
        count=args.count,
        seed=args.seed,
        json_output=args.json_out,
        markdown_output=args.markdown_out,
        llm=llm,
        sources=sources,
    ))
    print(_json_text(report), end="")
    return 0 if report["summary"]["errors"] == 0 else 2


def _load_sources(path: str | None) -> list[str] | None:
    if not path:
        return None
    import json

    return json.loads(Path(path).read_text(encoding="utf-8"))


def _build_llm(provider_name: str | None):
    """Resolve an injected LLMClient. Returns None when no provider was
    requested — keeps the pilot offline-by-default."""
    target = provider_name
    if not target:
        try:
            from src.llm.registry import ProviderRegistry

            cfg = ProviderRegistry.get_default()
            target = cfg.name
        except Exception:
            return None
    try:
        # Lazy import keeps the offline path free of llm provider deps.
        from src.pipeline.v7_extract.llm_client import AnthropicLLMClient

        return AnthropicLLMClient(default_provider_name=target)
    except Exception:
        return None


if __name__ == "__main__":
    sys.exit(main())
