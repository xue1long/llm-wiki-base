"""V7 end-to-end ingest bridge.

V7 Replace Plan Stage 0 Task 4.

The bridge chains V7's Stage 1 (classify) → Stage 3 (completeness) →
Stage 4 (cluster) → Stage 5 (fill_slots) → Stage 6 (relations), adapts
the resulting ``ConceptPage`` list to ``WikiPage`` objects via
``adapt_concept_page``, and appends a source stub via
``build_source_stub_page``. ``commit_ingest`` (unchanged) persists the
pages to disk and runs the lineage / vector pending / gbrain wikilink
rewrites that the rest of the wiki system expects.

Stage 5 path: this implementation uses ``fill_slots`` (v2 path, 1 LLM
call per topic). The v3 path ``fill_slots_v2`` (8+1 LLM calls per
topic) is a TODO for Stage 2 — it requires ``window_resolver`` to
produce ``spans_per_slot`` which adds significant Stage 5A plumbing.
The v2 path is sufficient for the Stage 0 smoke and matches
``scripts/extract_pilot.py`` production behavior.

The bridge itself does NOT write to disk — it returns a
``BridgeResult`` to the caller (the future ``generate_ingest``
replacement in ``src.pipeline.ingest``), which then passes the pages
to ``commit_ingest``. This keeps the write path uniform: one place
that does lineage, vector pending, gbrain compat, and the disk write.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import WikiPage

from .completeness_checker import CompletenessStatus, check_completeness
from .doc_classifier import classify_doc
from .failures import enqueue_failure
from .llm_bridge import ProviderAdapter
from .page_adapter import adapt_concept_page, build_source_stub_page
from .relation_extractor import extract_relations
from .segmentation import (
    build_structural_summary,
    extract_items_deterministic,
    wrap_items_as_segmentation_result,
)
from .slot_filler import fill_slots
from .topic_clusterer import (
    ClusterStatus,
    OTHER_TOPIC_ID,
    cluster_topics,
)


log = logging.getLogger(__name__)


# Default budget — overridden via env-var in Stage 2.
DEFAULT_MAX_USD: float = 0.5
DEFAULT_MAX_CALLS: int = 20
DEFAULT_STAGE_TIMEOUT_SEC: int = 120


@dataclass
class BridgeBudget:
    """Per-task cost + call budget. Read once at bridge entry; consumed
    monotonically by the bridge.
    """

    max_usd: float = DEFAULT_MAX_USD
    max_calls: int = DEFAULT_MAX_CALLS
    stage_timeout_sec: int = DEFAULT_STAGE_TIMEOUT_SEC

    @classmethod
    def from_env(cls) -> "BridgeBudget":
        """Load budget from environment variables.

        - ``RUFLO_V7_MAX_USD`` (default ``0.5``)
        - ``RUFLO_V7_MAX_CALLS`` (default ``20``)
        - ``RUFLO_V7_STAGE_TIMEOUT_SEC`` (default ``120``)
        """
        return cls(
            max_usd=float(os.environ.get("RUFLO_V7_MAX_USD", DEFAULT_MAX_USD)),
            max_calls=int(os.environ.get("RUFLO_V7_MAX_CALLS", DEFAULT_MAX_CALLS)),
            stage_timeout_sec=int(
                os.environ.get("RUFLO_V7_STAGE_TIMEOUT_SEC", DEFAULT_STAGE_TIMEOUT_SEC)
            ),
        )


@dataclass
class BridgeResult:
    """What the bridge returns to the caller (the future generate_ingest).

    ``pages`` is the list of WikiPages (concept + source stub) ready
    for ``commit_ingest``. ``meta`` carries stage-local state (Stage 5
    failures, etc.) that the caller may want to log. ``failure_stage``
    and ``failure_reason`` signal that the run did not produce usable
    pages — the caller should route the task to dead_letter.
    """

    pages: list[WikiPage] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    failure_stage: str | None = None
    failure_reason: str | None = None


def _write_v7_failure_markdown(
    paths: WikiPaths,
    task_id: str,
    stage: str,
    reason: str,
    *,
    source_path: Path | None = None,
    extra: dict | None = None,
) -> Path | None:
    """Write a small ``v7_failure.md`` marker to ``.index/quarantine/<task_id>/``
    so operators can triage V7 ingest failures (Stage 7 WikiWriter-style
    reviews_queue is the primary path; this is a backstop).

    Returns the path written, or None on filesystem error.
    """
    try:
        quarantine_dir = paths.index / "quarantine" / task_id
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        body_lines = [
            "---",
            f"stage: {stage}",
            f"reason: {reason}",
            f"task_id: {task_id}",
            f"written_at_ms: {int(time.time() * 1000)}",
            "---",
            "",
            f"# V7 ingest failure at stage {stage}",
            "",
            f"**Reason**: {reason}",
        ]
        if source_path is not None:
            body_lines.append(f"**Source**: `{source_path}`")
        if extra:
            body_lines.append("")
            body_lines.append("## Extra")
            body_lines.append("")
            body_lines.append("```json")
            body_lines.append(json.dumps(extra, ensure_ascii=False, indent=2, default=str))
            body_lines.append("```")
        body = "\n".join(body_lines) + "\n"
        target = quarantine_dir / "v7_failure.md"
        target.write_text(body, encoding="utf-8")
        return target
    except Exception as exc:  # pragma: no cover — disk failures shouldn't abort
        log.warning("[v7-bridge] failed to write v7_failure.md: %s", exc)
        return None


async def _bounded_complete(
    llm: Any,
    *,
    prompt_kind: str,
    user_prompt: str,
    system_prompt: str = "",
    max_tokens: int = 4096,
    temperature: float = 0.0,
    budget: BridgeBudget,
) -> str:
    """Single LLM call wrapped in (a) timeout and (b) call-counter check.

    Raises ``BridgeBudgetExceeded`` when ``adapter.calls_count`` would
    exceed ``budget.max_calls`` after this call. Raises ``asyncio.TimeoutError``
    when the underlying LLM call takes longer than ``budget.stage_timeout_sec``.
    Returns the LLM's text response (str).
    """
    if hasattr(llm, "calls_count"):
        # Pre-check: this call would push us over budget.
        if llm.calls_count + 1 > budget.max_calls:
            raise BridgeBudgetExceeded(
                f"calls {llm.calls_count + 1} > max {budget.max_calls}"
            )
    coro = llm.complete(
        prompt_kind=prompt_kind,
        user_prompt=user_prompt,
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return await asyncio.wait_for(coro, timeout=budget.stage_timeout_sec)


class BridgeBudgetExceeded(RuntimeError):
    """Raised when LLM call count would exceed BridgeBudget.max_calls.

    Reserved for future callers that want to enforce budget before each
    LLM call. The current Stage 0 bridge relies on V7 stages' own
    retry/parse loops and surfaces budget exhaustion via the
    ``calls_count`` property on ``ProviderAdapter`` instead.
    """


async def run_v7_ingest(
    *,
    paths: WikiPaths,
    source_path: Path,
    source_text: str,
    provider: Any,
    folder_context: str = "",
    task_id: str = "v7-bridge",
    schema_registry: Any = None,
    purpose_content: str = "",
    taxonomy_content: str = "",
    existing_wiki_index: str = "",
    use_fill_slots_v2: bool = False,
    budget: BridgeBudget | None = None,
    preprocessed: Any = None,
) -> BridgeResult:
    """V7 end-to-end ingest bridge.

    Returns a ``BridgeResult`` whose ``pages`` is ready for
    ``commit_ingest`` to persist. The bridge itself does not write to
    disk — see module docstring.

    Args:
        paths: WikiPaths of the project (used only for source-stub path
            metadata and quarantine writing).
        source_path: project-relative path to the raw source.
        source_text: full text of the source (used by Stage 5 truncate
            + Stage 2 deterministic splitter).
        provider: ``src.llm.LLMProvider`` instance — wrapped in
            ``ProviderAdapter`` automatically.
        task_id: queue task id, used in quarantine + ledger metadata.
        use_fill_slots_v2: when True, use Stage 5B ``fill_slots_v2`` path
            (TODO for Stage 2; not implemented in Stage 0).
        budget: cost / call / timeout budget. Defaults to
            ``BridgeBudget.from_env()`` when None.
        preprocessed: optional ``PreprocessResult`` from
            ``text_preprocessing.preprocess_source``. When None, the
            bridge re-runs the deterministic Stage 2 splitter inline.

    Returns:
        BridgeResult with pages (concept + source stub) and meta.
        ``failure_stage`` is non-None when the run did not produce
        usable pages.
    """
    result = BridgeResult()
    if budget is None:
        budget = BridgeBudget.from_env()
    source_key = str(source_path)

    # Wrap the provider in a V7 LLMClient. We always wrap — the
    # ProviderAdapter has zero overhead and exposes calls_count for
    # the budget check.
    llm: Any
    if isinstance(provider, ProviderAdapter):
        llm = provider
    else:
        llm = ProviderAdapter(provider)

    try:
        # ── Stage 2: deterministic splitter (no LLM) ──
        items = extract_items_deterministic(source_text, source_key)
        # Build a SegmentationResult so the rest of the pipeline has
        # the canonical types (Stage 4 consumes items directly; this
        # keeps the door open for Stage 3 / Stage 4 to consume
        # SegmentationResult if we want to).
        segmentation = wrap_items_as_segmentation_result(
            items, content=source_text, source_md5="", relative=source_key,
        )
        # Build the structural summary for completeness_checker (Stage
        # 3 uses Stage 2's signal dict to know item count, byline
        # count, etc.).
        structural_summary = build_structural_summary(segmentation, content=source_text)

        # ── Stage 1: classify ──
        # classify_doc handles prompt rendering + LLM call + JSON parsing
        # + Classification construction. Returns a Classification object
        # (never raises; failed=True signals technical failure).
        classification = await classify_doc(
            source_text,
            llm=llm,
            project_root=paths.root,
            filename_hint=source_key,
        )
        if classification.failed:
            result.failure_stage = "stage1"
            result.failure_reason = (
                classification.error or "classification failed"
            )
            result.meta["failure_detail"] = classification.rationale
            return result

        # ── Stage 3: completeness ──
        # check_completeness handles its own LLM call + retry + parse.
        # Returns CompletenessResult | None (None = technical failure).
        completeness = await check_completeness(
            source_text,
            doc_type_hint=classification.doc_type,
            llm=llm,
            project_root=paths.root,
            structural_summary=structural_summary,
        )
        if completeness is None or completeness.status is CompletenessStatus.TECHNICAL_FAILURE:
            result.failure_stage = "stage3_technical_failure"
            result.failure_reason = (
                completeness.technical_error if completeness else "check_completeness returned None"
            )
            return result
        if completeness.status is CompletenessStatus.INCOMPLETE:
            result.failure_stage = "stage3_incomplete"
            result.failure_reason = (
                "; ".join(completeness.reason_codes) or "incomplete content"
            )
            return result

        # ── Stage 4: cluster topics ──
        cluster_result = await cluster_topics(
            items,
            llm=llm,
            project_root=paths.root,
            classification_hint={"primary_type": classification.doc_type},
            source_id=source_key,
        )
        if cluster_result.status in (ClusterStatus.UNCERTAIN, ClusterStatus.EMPTY, ClusterStatus.FAILED):
            result.failure_stage = f"stage4_{cluster_result.status.value}"
            result.failure_reason = "; ".join(cluster_result.warnings) or cluster_result.status.value
            return result

        # ── Stage 5: fill_slots per topic (v2 path) ──
        # If use_fill_slots_v2=True, the v3 path requires window_resolver
        # to produce spans_per_slot — TODO for Stage 2.
        if use_fill_slots_v2:
            result.failure_stage = "stage5_v2_not_implemented"
            result.failure_reason = (
                "fill_slots_v2 requires window_resolver; deferred to Stage 2"
            )
            return result

        # Build the item_texts map from the splitter output so fill_slots
        # can index into the items by id.
        item_texts: dict[str, str] = {it["id"]: it["text"] for it in items}

        concept_pages: list[Any] = []
        failed_topics: list[str] = []
        for topic in cluster_result.topics:
            if topic.id == OTHER_TOPIC_ID:
                continue  # Stage 7 sentinel; never write
            topic_text = "\n\n".join(
                item_texts[item_id]
                for item_id in topic.item_ids
                if item_id in item_texts
            )
            try:
                concept_page = await fill_slots(
                    topic,
                    source_text=topic_text,
                    llm=llm,
                    item_texts=item_texts,
                    project_root=paths.root,
                )
            except Exception as exc:
                log.warning(
                    "[v7-bridge] fill_slots exception for topic %s: %s", topic.id, exc
                )
                concept_page = None
            if concept_page is None:
                failed_topics.append(topic.id)
                # record_failure to reviews_queue (V7 path)
                try:
                    enqueue_failure(
                        source_id=source_key,
                        stage="stage5",
                        topic_id=topic.id,
                        reason="stage5_llm_error",
                        provider=llm.provider_name if hasattr(llm, "provider_name") else "",
                        queue_path=paths.index / "reviews_queue.json",
                    )
                except Exception as exc:
                    log.warning("[v7-bridge] enqueue_failure failed: %s", exc)
                continue
            # T1 / H2 加固: page id must be script-owned (don't trust
            # LLM-supplied topic id). _stable_page_id is in _page_id.py.
            from src.pipeline.v7_extract._page_id import _stable_page_id, validate_page_id
            page_id = _stable_page_id(source_key, topic.id)
            try:
                validate_page_id(page_id)
            except Exception as exc:
                log.warning("[v7-bridge] page_id invalid for %s: %s", topic.id, exc)
                page_id = topic.id  # fall back to LLM id
            concept_page.id = page_id
            concept_page.topic_id = topic.id  # formal field for Stage 7
            concept_pages.append(concept_page)

        # ── Stage 6: relations (best-effort, never fatal) ──
        try:
            _ = extract_relations(
                concept_pages,
                llm=llm,
                project_root=paths.root,
            )
        except Exception as exc:
            log.warning("[v7-bridge] Stage 6 extract_relations failed: %s", exc)

        # ── Stage 7: adapt to WikiPage + build source stub ──
        wiki_concept_pages: list[WikiPage] = []
        for cp in concept_pages:
            try:
                wiki_concept_pages.append(adapt_concept_page(cp))
            except Exception as exc:
                log.warning(
                    "[v7-bridge] adapt_concept_page failed for %s: %s", cp.id, exc
                )
                failed_topics.append(cp.id)
        result.pages.extend(wiki_concept_pages)
        result.meta["concept_page_ids"] = [p.id for p in wiki_concept_pages]
        result.meta["failed_topics"] = failed_topics

        if not wiki_concept_pages and not failed_topics:
            # Empty extraction: source is too small or Stage 4/5
            # produced nothing. Mark the run as empty_extraction so the
            # caller can record this in the queue summary.
            result.meta["empty_extraction"] = True

        # Source stub — always written, even on partial / empty run.
        result.pages.append(build_source_stub_page(
            source_path=source_path,
            source_text=source_text,
            task_id=task_id,
            paths=paths,
            concept_page_ids=result.meta["concept_page_ids"],
        ))

        return result

    except BridgeBudgetExceeded as exc:
        result.failure_stage = "budget"
        result.failure_reason = str(exc)
        _write_v7_failure_markdown(
            paths, task_id, "budget", str(exc),
            source_path=source_path,
            extra={"calls_count": getattr(llm, "calls_count", -1), "max_calls": budget.max_calls},
        )
        return result
    except asyncio.TimeoutError as exc:
        result.failure_stage = "timeout"
        result.failure_reason = (
            f"LLM call exceeded {budget.stage_timeout_sec}s"
        )
        _write_v7_failure_markdown(
            paths, task_id, "timeout", result.failure_reason,
            source_path=source_path,
        )
        return result
    except Exception as exc:
        # Last-resort: catch any unhandled exception, write a triage
        # marker, return empty BridgeResult. The caller routes the
        # task to dead_letter.
        tb = traceback.format_exc()
        log.exception("[v7-bridge] unhandled exception")
        result.failure_stage = "unhandled"
        result.failure_reason = f"{type(exc).__name__}: {exc}"
        result.meta["traceback"] = tb
        _write_v7_failure_markdown(
            paths, task_id, "unhandled", result.failure_reason,
            source_path=source_path,
            extra={"traceback": tb},
        )
        return result


__all__ = [
    "BridgeBudget",
    "BridgeBudgetExceeded",
    "BridgeResult",
    "DEFAULT_MAX_CALLS",
    "DEFAULT_MAX_USD",
    "DEFAULT_STAGE_TIMEOUT_SEC",
    "run_v7_ingest",
]
