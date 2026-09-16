"""Stage 4 of the V7 extract pipeline: cluster items into topics.

v3 (plan 2026-09-15): pure-LLM clustering with P4 hard constraint.

P4 says the v7 pipeline must not silently drop items: if the LLM
forgets to assign an item, we route it to a sentinel ``__other__``
topic that the WikiWriter will refuse to write. This guarantees 100%
item coverage at the cost of an extra reviewable topic.

Heuristic fallback ("综合主题" + first-heading bucketization) was
deleted (T2.3). Pure LLM only.

Task 9 (plan 2026-09-17): return ``ClusterResult`` carrying explicit
status + 9 metrics + quality gates. ``max_topics`` is now a hint, not
a semantic cap; 50 items → up to 50 topics is allowed.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from .llm_client import LLMClient
from .prompts.parser import PromptParseError
from .prompts.renderer import (
    LLMResponseError,
    parse_llm_response,
    render_prompt,
)
from .prompts.resolver import PromptNotFoundError, resolve
from .topic_candidate import TopicCandidate, derive_candidate_id

if TYPE_CHECKING:
    from .prompts.ast import PromptTemplate


log = logging.getLogger(__name__)


# P4: sentinel topic id for items the LLM forgot to assign. The
# WikiWriter (Stage 7) checks for this id and refuses to write the
# page — its content goes to review_queue instead.
OTHER_TOPIC_ID = "__other__"
OTHER_TOPIC_TITLE = "其他主题"


# Task 9: quality gate thresholds (master plan §4 Task 9 + F9 + FP3).
ARTICLE_PRESERVATION_UNCERTAIN = 0.85  # F9 — relaxed from 0.95
UMBRELLA_TOPIC_SHARE_DEGRADED = 0.5
UNRESOLVED_ARTICLE_RATIO_DEGRADED = 0.1  # FP3
SINGLETON_OVER_FRAGMENTATION = 0.7
OVER_FRAGMENTATION_MIN_ITEMS = 5


class ClusterStatus(str, Enum):
    """Stage 4 stage-local status enum (Failure Contract §1)."""

    CLUSTERED = "clustered"          # 正常聚类
    DEGRADED = "degraded"            # 有切分但 quality 低
    UNCERTAIN = "uncertain"          # 不可靠聚类（article 损失）
    FAILED = "failed"                # 技术失败 → ExtractionStatus.FAILED
    EMPTY = "empty"                  # items=[]


@dataclass
class ClusterMetrics:
    """9 metrics + 1 diagnostic. Plan 2026-09-17 §3.5 + F9 + FP3."""

    item_count: int
    topic_count: int
    items_per_topic: float
    unresolved_item_ratio: float
    unresolved_byte_ratio: float
    unresolved_article_ratio: float          # FP3
    singleton_topic_ratio: float
    largest_topic_share: float
    article_preservation_ratio: float
    article_preservation_diagnostic: str      # F9: none_lost / stage4_missed / actually_lost
    duplicate_assignment_ratio: float


@dataclass
class ClusterResult:
    """Stage 4 output contract (Task 9 / Plan §3.5)."""

    status: ClusterStatus
    topics: list["Topic"]
    unresolved: list[str]                   # unresolved candidate IDs
    metrics: ClusterMetrics
    warnings: list[str] = field(default_factory=list)
    clusterer_fingerprint: str = ""


@dataclass
class Topic:
    """One topic produced by Stage 4."""
    id: str
    title: str
    item_ids: list[str] = field(default_factory=list)


async def cluster_topics(
    items: list[dict],
    *,
    llm: LLMClient,
    project_root: Path | str | None = None,
    doc_type: str | None = None,
    min_topics: int = 1,
    max_topics: int = 20,
    max_retries: int = 3,
) -> ClusterResult:
    """Cluster ``items`` into topics with explicit status + metrics.

    Args:
        items: list of dicts with ``id`` and ``text`` keys (Stage 2 output).
            May include ``kind`` and ``is_article`` fields; articles feed
            ``unresolved_article_ratio`` (FP3) and ``article_preservation_ratio`` (F9).
        llm: any ``LLMClient``.
        project_root: passed through to ``prompts_resolver.resolve``.
        doc_type: Stage 1 doc_type hint (soft hint per Task 11; Task 9 keeps
            the kwarg but does not gate on it).
        min_topics: minimum number of topics to emit (hint, no longer enforced).
        max_topics: HINT only — Task 9 removed the semantic cap. Pre-Task 9
            behavior capped the LLM at 20 topics; now the LLM can emit up to
            ``len(items)`` topics. The value is still passed to the prompt
            for guidance but is not used to truncate or reject the response.
        max_retries: number of LLM retry attempts before falling to FAILED.

    Returns:
        ``ClusterResult`` with explicit ``status``, ``topics``, ``unresolved``,
        ``metrics``, ``warnings``, and ``clusterer_fingerprint``. Never raises
        (P2). On total LLM failure the status is ``FAILED`` (Failure Contract
        §1) — distinct from ``DEGRADED`` / ``UNCERTAIN``.
    """
    fingerprint = _compute_clusterer_fingerprint(
        _resolve_cluster_template(project_root)
    )

    if not items:
        return _empty_result(fingerprint)

    template = _resolve_cluster_template(project_root)
    item_ids = [str(item["id"]) for item in items]
    items_text = "\n".join(
        f"{index}: {str(item.get('text', ''))[:200]}"
        for index, item in enumerate(items)
    )
    # ponytail: prepending doc_type keeps the rule conditional — the
    # LLM only acts on collection-split when it sees "collection" in
    # the header. Empty string when caller did not pass doc_type so the
    # {{doc_type_header}} placeholder still renders.
    doc_type_header = f"\nDocument type: {doc_type}\n" if doc_type else ""
    system_prompt, user_prompt = render_prompt(template, {
        "min_topics": min_topics,
        "max_topics": max_topics,
        "items_text": items_text,
        "doc_type_header": doc_type_header,
    })

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            raw = await llm.complete(
                prompt_kind="cluster",
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                max_tokens=4096,
                temperature=0.0,
            )
            payload = parse_llm_response(raw, template.output_schema)
            topics = _payload_to_topics(payload, item_ids)
            topics = _enforce_full_coverage(topics, items)
            return _finalize_result(
                topics, items, fingerprint,
                technical_error=None,
            )
        except LLMResponseError as e:
            last_error = e
            log.info(
                "cluster_topics: response failed validation "
                "(attempt %d/%d): %s",
                attempt + 1, max_retries, e,
            )
            continue
        except Exception as e:
            last_error = e
            log.warning(
                "cluster_topics: LLM call failed (attempt %d/%d): %s",
                attempt + 1, max_retries, e,
            )
            continue

    log.error(
        "cluster_topics: all %d retries exhausted, returning FAILED. last_error=%r",
        max_retries, last_error,
    )
    # Failure Contract §1: technical failure is signalled by FAILED, not
    # by a fake CLUSTERED or DEGRADED. P4 still holds — items land in
    # __other__ so nothing is silently dropped.
    topics = _enforce_full_coverage([], items)
    return _finalize_result(
        topics, items, fingerprint,
        technical_error=str(last_error) if last_error else "llm_failed",
    )


def _empty_result(fingerprint: str) -> ClusterResult:
    return ClusterResult(
        status=ClusterStatus.EMPTY,
        topics=[],
        unresolved=[],
        metrics=_empty_metrics(),
        warnings=[],
        clusterer_fingerprint=fingerprint,
    )


def _empty_metrics() -> ClusterMetrics:
    return ClusterMetrics(
        item_count=0,
        topic_count=0,
        items_per_topic=0.0,
        unresolved_item_ratio=0.0,
        unresolved_byte_ratio=0.0,
        unresolved_article_ratio=0.0,
        singleton_topic_ratio=0.0,
        largest_topic_share=0.0,
        article_preservation_ratio=1.0,        # vacuous: nothing to preserve
        article_preservation_diagnostic="none_lost",
        duplicate_assignment_ratio=0.0,
    )


def _finalize_result(
    topics: list[Topic],
    items: list[dict],
    fingerprint: str,
    *,
    technical_error: str | None,
) -> ClusterResult:
    """Compute metrics + apply quality gates → ClusterResult.

    Technical failure path: caller passes ``technical_error`` set → status
    becomes FAILED (Failure Contract §1).
    """
    metrics = _compute_metrics(topics, items)
    if technical_error is not None:
        status = ClusterStatus.FAILED
        warnings = [f"cluster_topics: llm failed: {technical_error}"]
    else:
        status, warnings = _apply_quality_gate(metrics, items)
    unresolved_ids = _collect_unresolved(topics, items)
    return ClusterResult(
        status=status,
        topics=topics,
        unresolved=unresolved_ids,
        metrics=metrics,
        warnings=warnings,
        clusterer_fingerprint=fingerprint,
    )


def _compute_metrics(topics: list[Topic], items: list[dict]) -> ClusterMetrics:
    """Compute 9 metrics + diagnostic for the cluster output.

    ``unresolved_ids`` semantics: an item is "unresolved" when it lands
    in the ``__other__`` bucket (or is missing from any topic). Items
    assigned to a real (non-__other__) topic are "resolved".
    """
    item_count = len(items)
    topic_count = len(topics)
    assigned = [iid for t in topics for iid in t.item_ids]
    assigned_count = len(assigned)
    all_ids = [str(item["id"]) for item in items]
    all_id_set = set(all_ids)
    assigned_set = set(assigned)
    # IDs that ended up ONLY in __other__ (or missing) are "unresolved"
    other_ids: set[str] = set()
    for t in topics:
        if t.id == OTHER_TOPIC_ID:
            other_ids.update(t.item_ids)
    unresolved_ids = sorted(
        (all_id_set - assigned_set) | other_ids
    )

    # items_per_topic (excluding __other__ for ratio sanity)
    non_other_topics = [t for t in topics if t.id != OTHER_TOPIC_ID]
    items_per_topic = (
        sum(len(t.item_ids) for t in non_other_topics) / len(non_other_topics)
        if non_other_topics else 0.0
    )

    # unresolved_item_ratio (against ALL items)
    unresolved_item_ratio = (
        len(unresolved_ids) / item_count if item_count else 0.0
    )

    # unresolved_byte_ratio
    bytes_by_id = {
        str(item["id"]): int(item.get("byte_length") or len(str(item.get("text", ""))))
        for item in items
    }
    unresolved_bytes = sum(bytes_by_id.get(iid, 0) for iid in unresolved_ids)
    total_bytes = sum(bytes_by_id.values()) or 1
    unresolved_byte_ratio = unresolved_bytes / total_bytes if total_bytes else 0.0

    # FP3: unresolved_article_ratio — only counts items flagged as articles
    article_ids = {
        str(item["id"]) for item in items
        if item.get("is_article") or item.get("kind") == "article"
    }
    if article_ids:
        unresolved_article_count = sum(
            1 for iid in unresolved_ids if iid in article_ids
        )
        unresolved_article_ratio = unresolved_article_count / len(article_ids)
    else:
        unresolved_article_ratio = 0.0

    # singleton_topic_ratio (excluding __other__)
    if non_other_topics:
        singletons = sum(
            1 for t in non_other_topics if len(t.item_ids) == 1
        )
        singleton_topic_ratio = singletons / len(non_other_topics)
    else:
        singleton_topic_ratio = 0.0

    # largest_topic_share (across all topics including __other__)
    sizes = [len(t.item_ids) for t in topics]
    largest_topic_share = (max(sizes) / assigned_count) if assigned_count else 0.0

    # article_preservation_ratio (F9)
    # Articles are "preserved" if they appear in some non-__other__ topic.
    preserved_articles: set[str] = set()
    for t in topics:
        if t.id == OTHER_TOPIC_ID:
            continue
        preserved_articles.update(t.item_ids)
    if article_ids:
        preserved = sum(1 for aid in article_ids if aid in preserved_articles)
        article_preservation_ratio = preserved / len(article_ids)
        if preserved == len(article_ids):
            diagnostic = "none_lost"
        elif preserved == 0:
            diagnostic = "actually_lost"
        else:
            diagnostic = "stage4_missed"
    else:
        article_preservation_ratio = 1.0
        diagnostic = "none_lost"

    # duplicate_assignment_ratio
    seen: set[str] = set()
    duplicates = 0
    for t in topics:
        for iid in t.item_ids:
            if iid in seen:
                duplicates += 1
            else:
                seen.add(iid)
    duplicate_assignment_ratio = duplicates / assigned_count if assigned_count else 0.0

    return ClusterMetrics(
        item_count=item_count,
        topic_count=topic_count,
        items_per_topic=items_per_topic,
        unresolved_item_ratio=unresolved_item_ratio,
        unresolved_byte_ratio=unresolved_byte_ratio,
        unresolved_article_ratio=unresolved_article_ratio,
        singleton_topic_ratio=singleton_topic_ratio,
        largest_topic_share=largest_topic_share,
        article_preservation_ratio=article_preservation_ratio,
        article_preservation_diagnostic=diagnostic,
        duplicate_assignment_ratio=duplicate_assignment_ratio,
    )


def _apply_quality_gate(
    metrics: ClusterMetrics,
    items: list[dict],
) -> tuple[ClusterStatus, list[str]]:
    """Quality gate logic (master plan §4 Task 9 + F9 + FP3).

    Precedence (Failure Contract §1: technical failure is handled
    earlier — this function only sees post-success metrics):
      1. article_preservation_ratio < 0.85 (F9) → UNCERTAIN
      2. largest_topic_share > 0.5 (umbrella) → DEGRADED
      3. unresolved_article_ratio > 0.1 (FP3) → DEGRADED
      4. over-fragmentation (singleton > 0.7 with > 5 items) → DEGRADED
      5. otherwise → CLUSTERED
    """
    warnings: list[str] = []

    # Gate 2 (checked first for warnings regardless of outcome)
    if metrics.largest_topic_share > UMBRELLA_TOPIC_SHARE_DEGRADED:
        warnings.append(
            f"umbrella_topic: largest={metrics.largest_topic_share:.2f}"
        )

    # Gate 3 (FP3)
    if metrics.unresolved_article_ratio > UNRESOLVED_ARTICLE_RATIO_DEGRADED:
        warnings.append(
            f"unresolved_article_explosion: ratio={metrics.unresolved_article_ratio:.2f}"
        )

    # Gate 4 (over-fragmentation)
    if (
        metrics.singleton_topic_ratio > SINGLETON_OVER_FRAGMENTATION
        and metrics.item_count > OVER_FRAGMENTATION_MIN_ITEMS
    ):
        warnings.append(
            f"over_fragmentation: singleton={metrics.singleton_topic_ratio:.2f}"
        )

    # Gate 1 (F9): article preservation — strict UNCERTAIN (highest priority)
    if metrics.article_preservation_ratio < ARTICLE_PRESERVATION_UNCERTAIN:
        warnings.append(
            f"article_loss: preservation={metrics.article_preservation_ratio:.2f}, "
            f"diagnostic={metrics.article_preservation_diagnostic}"
        )
        return ClusterStatus.UNCERTAIN, warnings

    # Remaining gates → DEGRADED
    if any(
        w.startswith(prefix) for prefix in
        ("umbrella_topic", "unresolved_article_explosion", "over_fragmentation")
        for w in warnings
    ):
        return ClusterStatus.DEGRADED, warnings

    return ClusterStatus.CLUSTERED, warnings


def _collect_unresolved(topics: list[Topic], items: list[dict]) -> list[str]:
    """List of candidate IDs the LLM did not assign to any non-__other__ topic."""
    assigned: set[str] = {iid for t in topics for iid in t.item_ids}
    return sorted({item["id"] for item in items} - assigned)


def _payload_to_topics(
    payload: dict,
    item_ids: list[str],
    item_fingerprints: list[str] | None = None,
) -> list[Topic]:
    """Convert validated LLM JSON payload into Topic list.

    Task 10: accept BOTH the new ``candidates`` shape (per-item, multi-
    candidate via ``local_index``) and the legacy ``topics`` shape.
    Canonical item IDs stay script-owned; ``candidate_id`` is derived
    from the span fingerprint (not the LLM-supplied label).

    In the legacy ``topics`` shape each ``item_index`` may appear in at
    most one topic (the old single-topic-per-item hard constraint). In
    the new ``candidates`` shape the same ``item_index`` may appear
    multiple times with distinct ``local_index`` values, lifting that
    constraint at the candidate level.
    """
    if "candidates" in payload:
        fingerprints = item_fingerprints or [str(iid) for iid in item_ids]
        candidates = _payload_to_candidates(
            payload, item_ids, fingerprints,
        )
        return _candidates_to_topics(candidates, item_ids)
    return _payload_to_topics_legacy(payload, item_ids)


def _payload_to_candidates(
    payload: dict,
    item_ids: list[str],
    item_fingerprints: list[str],
) -> list[TopicCandidate]:
    """Parse the new ``candidates`` shape into ``TopicCandidate`` objects.

    Lifts the old single-topic-per-item hard constraint: the same
    ``item_index`` may appear multiple times as long as ``local_index``
    differs. ``candidate_id`` is script-generated via
    :func:`derive_candidate_id` so identity never depends on the LLM
    label.
    """
    raw = payload.get("candidates", [])
    if not isinstance(raw, list):
        return []
    candidates: list[TopicCandidate] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            item_index = int(entry["item_index"])
            local_index = int(entry.get("local_index", 0))
        except (TypeError, ValueError, KeyError):
            continue
        if (
            isinstance(item_index, bool)
            or not 0 <= item_index < len(item_ids)
        ):
            raise LLMResponseError(
                f"candidates contains invalid item_index: {item_index!r}"
            )
        span_hint = str(entry.get("span_hint", ""))
        label = str(entry.get("semantic_label", ""))
        try:
            confidence = float(entry.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        cid = derive_candidate_id(
            item_index, local_index,
            span_hint=span_hint,
            item_fingerprint=item_fingerprints[item_index],
        )
        candidates.append(TopicCandidate(
            candidate_id=cid,
            item_index=item_index,
            local_index=local_index,
            semantic_label=label,
            evidence_span_hint=span_hint,
            confidence=confidence,
        ))
    return candidates


def _candidates_to_topics(
    candidates: list[TopicCandidate],
    item_ids: list[str],
) -> list[Topic]:
    """Group ``TopicCandidate`` list into ``Topic`` list (Task 10 baseline).

    Task 11 will replace this with a real discovery → grouping two-stage
    LLM. For Task 10 we use the trivial grouping: one Topic per item
    that produced at least one candidate.
    """
    by_item: dict[int, list[TopicCandidate]] = {}
    for c in candidates:
        by_item.setdefault(c.item_index, []).append(c)
    topics: list[Topic] = []
    for item_index in sorted(by_item):
        # Use the first candidate's label as the topic title (best hint
        # we have without a grouping LLM call).
        first = by_item[item_index][0]
        title = first.semantic_label or f"item-{item_index}"
        topics.append(Topic(
            id=f"item-{item_index}",
            title=title,
            item_ids=[item_ids[item_index]],
        ))
    return topics


def _payload_to_topics_legacy(payload: dict, item_ids: list[str]) -> list[Topic]:
    """Convert validated LLM JSON payload into Topic list (legacy shape).

    The LLM returns positions; canonical item IDs stay script-owned.
    Legacy ``topics`` shape retains the single-topic-per-item hard
    constraint (each ``item_index`` may appear in at most one topic).
    """
    raw = payload.get("topics", [])
    if not isinstance(raw, list):
        return []
    topics: list[Topic] = []
    seen: set[str] = set()  # avoid duplicate topic ids
    seen_indexes: set[int] = set()
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            continue
        tid = str(entry.get("id") or f"topic-{idx + 1}")
        # If the LLM produces a duplicate id, suffix it
        original_tid = tid
        suffix = 1
        while tid in seen:
            tid = f"{original_tid}-{suffix}"
            suffix += 1
        seen.add(tid)
        title = str(entry.get("title") or tid)
        indexes = entry.get("item_indexes", [])
        if not isinstance(indexes, list):
            raise LLMResponseError("item_indexes must be a list")
        mapped_ids: list[str] = []
        for item_index in indexes:
            if (
                isinstance(item_index, bool)
                or not isinstance(item_index, int)
                or not 0 <= item_index < len(item_ids)
            ):
                raise LLMResponseError(
                    f"item_indexes contains invalid index: {item_index!r}"
                )
            if item_index in seen_indexes:
                raise LLMResponseError(
                    f"item_indexes contains duplicate assignment: {item_index}"
                )
            seen_indexes.add(item_index)
            mapped_ids.append(item_ids[item_index])
        topics.append(Topic(id=tid, title=title, item_ids=mapped_ids))
    return topics


def _enforce_full_coverage(topics: list[Topic], items: list[dict]) -> list[Topic]:
    """P4: every item in ``items`` must appear in some topic.

    Items the LLM forgot to assign are bundled into a sentinel
    ``__other__`` topic. The WikiWriter (Stage 7) refuses to write this
    bucket's pages — they go to review_queue instead.
    """
    assigned: set[str] = {iid for t in topics for iid in t.item_ids}
    all_ids: set[str] = {item["id"] for item in items}
    leftover = sorted(all_ids - assigned)
    if not leftover:
        return topics
    # If a __other__ bucket already exists, merge into it
    for t in topics:
        if t.id == OTHER_TOPIC_ID:
            t.item_ids = sorted(set(t.item_ids) | set(leftover))
            return topics
    topics.append(Topic(
        id=OTHER_TOPIC_ID,
        title=OTHER_TOPIC_TITLE,
        item_ids=leftover,
    ))
    return topics


def _compute_clusterer_fingerprint(template: "PromptTemplate") -> str:
    """Stable hash of the cluster prompt + a static version tag.

    ponytail: hash the prompt kind + template version + a short body
    sample. The hash changes when the prompt template body changes, so
    source-skip can detect prompt upgrades.
    """
    version = getattr(template, "version", "") or ""
    body = getattr(template, "user_template", "") or getattr(template, "raw_body", "") or ""
    identity = f"cluster|{version}|{body[:200]}"
    return "clu-" + hashlib.sha1(identity.encode("utf-8")).hexdigest()[:16]


def _resolve_cluster_template(project_root: Path | str | None) -> "PromptTemplate":
    try:
        return resolve("cluster", project_root=project_root)
    except (PromptNotFoundError, PromptParseError) as e:
        raise RuntimeError(
            f"V7 cluster prompt is not available: {e}. "
            f"Check that prompts/builtin/cluster.toml is installed."
        ) from e
