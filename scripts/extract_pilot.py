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

Task 6 (plan 2026-09-17 Stage 3 remediation): ``check_completeness``
returns ``CompletenessResult | None`` — ``None`` means technical
failure (LLM timeout / parse / schema invalid). Per Failure Contract
(2026-09-17-remediation-contract-freeze §1), technical failure MUST
NOT be routed as INCOMPLETE — it becomes ``ExtractionStatus.FAILED``
with ``failure_stage="stage3"``.
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
from src.pipeline.v7_extract.completeness_checker import (
    CompletenessStatus,
    check_completeness,
)
from src.pipeline.v7_extract.doc_classifier import classify_doc
from src.pipeline.v7_extract.failures import (
    ExtractionResult,
    ExtractionStatus,
    enqueue_failure,
)
from src.pipeline.v7_extract.invariants import validate_segmentation_invariants
from src.pipeline.v7_extract.segmentation import (
    AUTHOR_BYLINE_RE_BROAD,
    AUTHOR_BYLINE_RE_STRICT,
    CanonicalItem,
    CoverageReport,
    ItemKind,
    SegmentationResult,
    SegmentationStatus,
)
from src.pipeline.v7_extract.slot_filler import fill_slots
from src.pipeline.v7_extract.topic_clusterer import (
    ClusterStatus,
    cluster_topics,
)

log = logging.getLogger(__name__)


SUPPORTED_SUFFIXES = frozenset({".md", ".txt", ".html", ".htm"})
DEFAULT_ROOT = Path("knowledge/novel-wiki")
DEFAULT_JSON = Path("docs/superpowers/reports/2026-09-13-extract-pilot.json")
DEFAULT_MARKDOWN = Path("docs/superpowers/reports/2026-09-13-extract-pilot-report.md")

# T1 / H2 加固: cap the per-failure reason string so a noisy LLM trace
# doesn't dominate the pilot's report.
_EXC_REASON_LIMIT = 500

# Task 13 (Plan 2026-09-17): when Stage 4's unresolved_item_ratio
# exceeds this threshold, emit a ``stage4_unresolved`` entry in
# ``result.review_reasons`` so operators can monitor knowledge loss.
# The ``__other__`` Topic in ``cluster_result.topics`` is preserved
# regardless (Stage 7 Guard A reads it as a sentinel and blocks the
# page) — this signal is purely advisory for the JSON report.
UNRESOLVED_REVIEW_THRESHOLD = 0.3


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
        # v3 + Task 7: Stage 2 runs BEFORE Stage 3 so the latter can
        # consume Stage 2's ``SegmentationResult`` as a bounded
        # structural summary (Bounded Evidence Contract §3.2). Stage 2
        # is a deterministic structural split — no LLM — so running
        # it on a stub source costs only a regex sweep.
        items = _extract_items(content, relative)
        # Task 3: wrap into the canonical SegmentationResult contract.
        # Downstream Stage 4 still consumes ``items`` (legacy dicts);
        # the result is informational here — recorded for callers and
        # future Stage 5 byte-span migration (Task 5).
        segmentation_result = _wrap_items_as_segmentation_result(
            items, content=content, source_md5=source_md5, relative=relative,
        )
        structural_summary = _build_structural_summary(
            segmentation_result, content=content,
        )

        # v3: Stage 3 is async + P5-decoupled (doc_type is soft hint).
        # Task 6: returns CompletenessResult | None. None = technical
        # failure (LLM timeout / parse / schema invalid) — per Failure
        # Contract (§1), this MUST NOT be routed as INCOMPLETE.
        # Task 7: pass structural_summary so Stage 3 sees bounded
        # Stage 2 signals (HEAD/TAIL + 3 mid samples) instead of the
        # raw full content.
        completeness = await check_completeness(
            content,
            doc_type_hint=classification.doc_type,
            llm=llm,
            project_root=root,
            structural_summary=structural_summary,
        )

        # Legacy dict fields carried through ``metadata`` so the JSON
        # contract stays identical to the pre-refactor shape.
        # Task 6: technical failure -> FAILED (not INCOMPLETE). The
        # legacy ``complete`` boolean still serializes as False so old
        # JSON consumers do not crash.
        metadata: dict[str, Any] = {
            "source": relative,
            "characters": len(content),
            # v3: classification.doc_type is a plain string (was DocType.value in v2)
            "doc_type": classification.doc_type,
            "confidence": classification.confidence,
            "rationale": classification.rationale,
            "topics": [],
            "error": None,
        }

        # Task 6: CompletenessResult | None -> ExtractionStatus mapping.
        #   None                -> FAILED (failure_stage="stage3")  [tech fail]
        #   TECHNICAL_FAILURE   -> FAILED (defense in depth — should
        #                                       not happen if None works)
        #   INCOMPLETE          -> INCOMPLETE
        #   UNCERTAIN           -> BLOCKED (review; ambiguous)
        #   COMPLETE            -> WRITTEN
        if completeness is None:
            reason = "stage3_llm_failed_after_retries"
            metadata["complete"] = False
            metadata["completeness_reason"] = reason
            return ExtractionResult(
                status=ExtractionStatus.FAILED,
                source_id=relative,
                source_md5=source_md5,
                failure_stage="stage3",
                review_reasons=[reason],
                metadata=metadata,
            )

        metadata["complete"] = (
            completeness.status is CompletenessStatus.COMPLETE
        )
        metadata["completeness_reason"] = (
            completeness.reason_codes[0] if completeness.reason_codes else ""
        )

        if completeness.status is CompletenessStatus.TECHNICAL_FAILURE:
            # Defense in depth — None path is the primary signal. If a
            # TECHNICAL_FAILURE enum slips through, route the same way.
            reason = (
                "stage3_technical_failure: "
                f"{completeness.technical_error or 'unspecified'}"
            )
            return ExtractionResult(
                status=ExtractionStatus.FAILED,
                source_id=relative,
                source_md5=source_md5,
                failure_stage="stage3",
                review_reasons=[reason],
                metadata=metadata,
            )

        if completeness.status is CompletenessStatus.UNCERTAIN:
            result = ExtractionResult(
                status=ExtractionStatus.BLOCKED,
                source_id=relative,
                source_md5=source_md5,
                review_reasons=list(completeness.reason_codes),
                blocked_topic_ids=[relative],
                metadata=metadata,
            )
            return result

        if completeness.status is CompletenessStatus.INCOMPLETE:
            result = ExtractionResult(
                status=ExtractionStatus.INCOMPLETE,
                source_id=relative,
                source_md5=source_md5,
                review_reasons=list(completeness.reason_codes),
                metadata=metadata,
            )
            return result

        # COMPLETE — continue to Stage 4 / 5.
        result = ExtractionResult(
            status=ExtractionStatus.WRITTEN,
            source_id=relative,
            source_md5=source_md5,
            metadata=metadata,
        )

        # Stage 2 ran above (Task 7: moved before Stage 3). Stage 3 just
        # consumed its structural_summary — now record the same fields
        # on the legacy metadata block so existing JSON consumers keep
        # seeing them.
        metadata["segmentation_status"] = segmentation_result.status.value
        metadata["segmentation_coverage"] = segmentation_result.coverage.byte_accounting
        metadata["segmentation_invariants_pass"] = segmentation_result.invariants.all_pass
        metadata["segmentation_item_count"] = len(segmentation_result.items)
        item_map = {item["id"]: item for item in items}
        # Task 9: cluster_topics returns ClusterResult carrying explicit
        # status + 9 metrics + quality gates. Map stage-local ClusterStatus
        # to global ExtractionStatus (Failure Contract §1):
        #   FAILED    → ExtractionStatus.FAILED  (retry)
        #   UNCERTAIN → ExtractionStatus.BLOCKED (review)
        #   EMPTY     → ExtractionStatus.BLOCKED (no topics → no useful work)
        #   DEGRADED  → continue (warnings emitted)
        #   CLUSTERED → continue
        cluster_result = await cluster_topics(
            items,
            llm=llm,
            project_root=root,
            segmentation_result=segmentation_result,
        )
        # Stage 4 quality metrics get surfaced in metadata so the JSON
        # report carries them without callers re-running Stage 4.
        metadata["cluster_status"] = cluster_result.status.value
        metadata["cluster_metrics"] = {
            "item_count": cluster_result.metrics.item_count,
            "topic_count": cluster_result.metrics.topic_count,
            "items_per_topic": cluster_result.metrics.items_per_topic,
            "unresolved_item_ratio": cluster_result.metrics.unresolved_item_ratio,
            "unresolved_byte_ratio": cluster_result.metrics.unresolved_byte_ratio,
            "unresolved_article_ratio": cluster_result.metrics.unresolved_article_ratio,
            "singleton_topic_ratio": cluster_result.metrics.singleton_topic_ratio,
            "largest_topic_share": cluster_result.metrics.largest_topic_share,
            "article_preservation_ratio": cluster_result.metrics.article_preservation_ratio,
            "article_preservation_diagnostic": cluster_result.metrics.article_preservation_diagnostic,
            "duplicate_assignment_ratio": cluster_result.metrics.duplicate_assignment_ratio,
        }
        metadata["cluster_warnings"] = list(cluster_result.warnings)
        metadata["clusterer_fingerprint"] = cluster_result.clusterer_fingerprint

        # Task 13: surface knowledge-loss signal in review_reasons.
        # The ``__other__`` Topic in ``cluster_result.topics`` is kept
        # (Stage 7 Guard A reads it as a block sentinel — backward compat);
        # this is purely an operator-facing metric that fires when the LLM
        # forgot more than UNRESOLVED_REVIEW_THRESHOLD of the items.
        unresolved_ratio = cluster_result.metrics.unresolved_item_ratio
        if unresolved_ratio > UNRESOLVED_REVIEW_THRESHOLD:
            result.review_reasons.append(
                f"stage4_unresolved: ratio={unresolved_ratio:.2f}"
            )

        # Failure Contract §1: ClusterStatus.FAILED → ExtractionStatus.FAILED.
        # Technical failure (LLM timeout / parse / schema invalid) MUST NOT
        # be routed as BLOCKED or WRITTEN.
        if cluster_result.status is ClusterStatus.FAILED:
            reason = (
                "stage4_technical_failure: "
                f"{cluster_result.warnings[0] if cluster_result.warnings else 'unspecified'}"
            )
            _record_failure(
                relative,
                "stage4",
                reason=reason,
                content_hash=source_md5,
                provider=_llm_provider_label(llm),
                queue_path=root / ".index" / "reviews_queue.json",
            )
            return ExtractionResult(
                status=ExtractionStatus.FAILED,
                source_id=relative,
                source_md5=source_md5,
                failure_stage="stage4",
                review_reasons=[reason],
                metadata=metadata,
            )

        # UNCERTAIN / EMPTY → ExtractionStatus.BLOCKED.
        # UNCERTAIN = article loss (F9). EMPTY = no items to work on.
        if cluster_result.status in {
            ClusterStatus.UNCERTAIN, ClusterStatus.EMPTY,
        }:
            result = ExtractionResult(
                status=ExtractionStatus.BLOCKED,
                source_id=relative,
                source_md5=source_md5,
                review_reasons=list(cluster_result.warnings),
                metadata=metadata,
            )
            return result

        # DEGRADED / CLUSTERED → continue. Quality warnings become
        # review_reasons so the JSON report carries the audit trail.
        topics = cluster_result.topics
        # Track topics + page summaries for the legacy JSON contract.
        topic_dicts: list[dict[str, Any]] = []
        page_dicts: list[dict[str, Any]] = []
        # Five-state counters — drive ``status`` below.
        failed_topic_ids: list[str] = []
        written_page_ids: list[str] = []
        blocked_page_ids: list[str] = []
        if cluster_result.warnings:
            for w in cluster_result.warnings:
                result.review_reasons.append(f"stage4:{w}")
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


def _build_structural_summary(
    segmentation_result: SegmentationResult,
    *,
    content: str,
) -> dict:
    """Re-export the public implementation for backward compatibility.

    The canonical implementation now lives in
    ``src.pipeline.v7_extract.segmentation.build_structural_summary``
    (V7 replace Plan Stage 0 Task 1). This wrapper keeps existing
    callers in scripts/extract_pilot.py working unchanged.
    """
    from src.pipeline.v7_extract.segmentation import (
        build_structural_summary as _impl,
    )
    return _impl(segmentation_result, content=content)


def _wrap_items_as_segmentation_result(
    items: list[dict[str, str]],
    *,
    content: str,
    source_md5: str,
    relative: str,
) -> SegmentationResult:
    """Re-export the public implementation for backward compatibility.

    Canonical implementation: ``src.pipeline.v7_extract.segmentation.wrap_items_as_segmentation_result``.
    """
    from src.pipeline.v7_extract.segmentation import (
        wrap_items_as_segmentation_result as _impl,
    )
    return _impl(items, content=content, source_md5=source_md5, relative=relative)


def _extract_items(content: str, relative: str) -> list[dict[str, str]]:
    """Re-export the public implementation for backward compatibility.

    Canonical implementation: ``src.pipeline.v7_extract.segmentation.extract_items_deterministic``.
    """
    from src.pipeline.v7_extract.segmentation import (
        extract_items_deterministic as _impl,
    )
    return _impl(content, relative)


# byline patterns — re-exported for callers that used to import
# these constants from this module.
_AUTHOR_BYLINE_RE_STRICT = AUTHOR_BYLINE_RE_STRICT
_AUTHOR_BYLINE_RE_BROAD = AUTHOR_BYLINE_RE_BROAD


def _extract_items_by_author_byline(
    content: str, relative: str,
) -> list[dict[str, str]]:
    """Split a source on ``作者 XXX`` byline lines.

    Helper kept here for backward compatibility — callers should
    prefer ``extract_items_deterministic`` from
    ``src.pipeline.v7_extract.segmentation`` which encapsulates the
    full deterministic splitter chain (byline → headings →
    numbered list → single-item fallback).

    Accepts both the strict ``作者 : XXX`` form (doc_classifier
    evidence_summary signal) and the heading-wrapped
    ``## 作者 314 — Title`` form found in actual fixtures.
    """
    from src.pipeline.v7_extract.segmentation import (
        _extract_items_by_author_byline as _impl,
    )
    return _impl(content, relative)


def _looks_like_collection(content: str) -> bool:
    """Soft structural hint that ``content`` reads like a multi-author
    collection. Pure function — derived from regex sweep only, never
    consults Stage 1 ``doc_type``.

    Returns True when BOTH signals fire:
      - ≥ 2 author byline lines (strict or heading form, multi-author)
      - ≥ 1 markdown ``#`` / ``##`` header (curated editorial wrapper)
    """
    strict_count = len(_AUTHOR_BYLINE_RE_STRICT.findall(content))
    broad_count = len(_AUTHOR_BYLINE_RE_BROAD.findall(content))
    byline_count = max(strict_count, broad_count)
    header_count = len(re.findall(r"(?m)^#+\s+", content))
    return byline_count >= 2 and header_count >= 1


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
