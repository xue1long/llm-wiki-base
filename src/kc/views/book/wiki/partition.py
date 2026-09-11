"""Deterministic page partitioning and bounded, whole-page chapter chunks."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json

from .model import WikiSnapshot


@dataclass(frozen=True)
class ReaderProfile:
    profile_id: str
    task_types: tuple[str, ...]
    min_pages_per_book: int = 20
    min_source_coverage: float = 0.80
    min_reader_tasks: int = 6
    candidate_taxonomies: tuple[str, ...] = ("book-a", "book-b", "book-c")
    chapter_exit_evidence: tuple[str, ...] = ()
    # v0.3 plan-audit S1: profile-driven relax flags. Default keeps the
    # original strict behavior so existing tests stay green.
    closure_strict_types: tuple[str, ...] = (
        "concept|foundation|orientation",
        "entity|method|explanation",
        "synthesis|application|example",
    )
    allowed_learning_edge_types: tuple[str, ...] = ("supports", "required_by")
    require_target_task_match: bool = True

    def __post_init__(self) -> None:
        # Reject malformed closures up front so the gate never silently
        # evaluates an empty/garbled frozenset.
        if not self.closure_strict_types:
            raise ValueError("closure_strict_types must be a non-empty tuple")
        for group in self.closure_strict_types:
            parts = [p.strip() for p in group.split("|") if p.strip()]
            if not parts:
                raise ValueError(f"closure_strict_types group {group!r} is empty")
            for name in parts:
                if name not in _TASK_TYPES and name not in {
                    "concept", "entity", "synthesis", "foundation",
                    "orientation", "method", "explanation",
                    "application", "example", "source",
                }:
                    raise ValueError(f"closure_strict_types unknown page_type: {name!r}")
        if not self.allowed_learning_edge_types:
            raise ValueError("allowed_learning_edge_types must be a non-empty tuple")


@dataclass(frozen=True)
class GovernanceConfig:
    external_authorized: bool | None = None
    budget_cap: int | None = None
    approver: str | None = None
    hard_reference_dependencies: tuple[str, ...] = ()
    soft_reference_dependencies: tuple[str, ...] = ()
    closure_evidence: tuple[str, ...] = ()
    closure_status_reason: str = ""


@dataclass(frozen=True)
class GateMetrics:
    page_type_counts: tuple[tuple[str, int], ...]
    total_pages: int
    duplicate_pages: int
    duplicate_rate: float
    pages_with_sources: int
    source_coverage: float
    relation_count: int
    relation_parse_rate: float | None
    estimated_chars: int
    reader_task_candidates: int
    relation_unresolved_count: int = 0
    duplicate_denominator: int = 0


@dataclass(frozen=True)
class CandidateDecision:
    candidate_id: str
    eligible_page_ids: tuple[str, ...]
    eligible_page_count: int
    chapter_density: float
    source_coverage: float
    duplicate_rate: float
    estimated_chars: int
    reader_task_count: int
    closure_status: str
    decision: str
    reason_codes: tuple[str, ...]
    hard_reference_dependencies: tuple[str, ...] = ()
    soft_reference_dependencies: tuple[str, ...] = ()
    closure_evidence: tuple[str, ...] = ()
    closure_status_reason: str = ""
    duplicate_denominator: int = 0


@dataclass(frozen=True)
class SeriesGateResult:
    snapshot_fingerprint: str
    metrics: GateMetrics
    candidates: tuple[CandidateDecision, ...]
    status: str
    generation_mode: str
    block_reasons: tuple[str, ...] = ()
    hard_reference_dependencies: tuple[str, ...] = ()
    soft_reference_dependencies: tuple[str, ...] = ()


_TASK_TYPES = {
    "concept": "learn_concept", "entity": "reference", "synthesis": "apply",
    "foundation": "learn_concept", "orientation": "learn_concept",
    "method": "apply", "explanation": "apply", "application": "apply", "example": "apply",
}
_SOURCE_TASKS = {"learn_concept", "reference", "foundation", "orientation"}
_TARGET_TASKS = {"apply", "example", "application", "explanation", "method"}


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _candidate_pages(snapshot: WikiSnapshot, profile: ReaderProfile) -> dict[str, tuple]:
    grouped: dict[str, list] = defaultdict(list)
    for page in snapshot.pages:
        grouped[(page.primary_taxonomy or "unassigned").strip()].append(page)
    # Only return keys the caller asked about (``profile.candidate_taxonomies``)
    # plus the implicit ``unassigned`` bucket. Real taxonomies that the
    # profile never referenced are excluded so callers do not silently
    # include unrelated candidates. Each requested taxonomy always appears
    # (with an empty tuple when the snapshot has no pages for it) so the
    # resulting CandidateDecision is auditable per the plan contract.
    requested = set(profile.candidate_taxonomies) | {"unassigned"}
    return {key: tuple(sorted(grouped.get(key, ()), key=lambda page: page.page_id))
            for key in sorted(requested)}


def _duplicate_rate(pages: tuple) -> tuple[int, float, int]:
    hashes: dict[str, int] = defaultdict(int)
    for page in pages:
        if page.content_sha256:
            hashes[page.content_sha256] += 1
    duplicate_pages = sum(count - 1 for count in hashes.values() if count > 1)
    denominator = sum(bool(page.content_sha256) for page in pages)
    return duplicate_pages, _rate(duplicate_pages, denominator), denominator


def evaluate_series_gate(
    snapshot: WikiSnapshot,
    *,
    reader_profile: ReaderProfile,
    governance: GovernanceConfig | None = None,
) -> SeriesGateResult:
    """Build a deterministic, rule-only book-series baseline.

    This function intentionally has no provider/callback argument: a result
    can only authorize later LLM work after all local governance fields exist.
    """
    pages = tuple(sorted(snapshot.pages, key=lambda page: page.page_id))
    type_counts: dict[str, int] = defaultdict(int)
    for page in pages:
        type_counts[page.page_type] += 1
    duplicate_pages, duplicate_rate, duplicate_denominator = _duplicate_rate(pages)
    pages_with_sources = sum(bool(page.sources) for page in pages)
    page_ids = {page.page_id for page in pages}
    relation_count = sum(len(page.relation_targets) for page in pages)
    relation_unresolved = sum(
        1 for page in pages for _, target in page.relation_targets
        if target not in page_ids and not (target.startswith("taxonomy/") or target.startswith("taxonomy-"))
    )
    relation_parse_rate = _rate(relation_count - relation_unresolved, relation_count) if relation_count else None
    min_reader_tasks = max(6, reader_profile.min_reader_tasks)
    task_candidates = sum(_TASK_TYPES.get(page.page_type, "reference") in reader_profile.task_types for page in pages)
    metrics = GateMetrics(
        tuple(sorted(type_counts.items())), len(pages), duplicate_pages, duplicate_rate,
        pages_with_sources, _rate(pages_with_sources, len(pages)), relation_count,
        relation_parse_rate,
        sum(max(0, page.char_count) for page in pages), task_candidates, relation_unresolved,
        sum(bool(page.content_sha256) for page in pages),
    )
    candidates: list[CandidateDecision] = []
    for candidate_id, candidate_pages in _candidate_pages(snapshot, reader_profile).items():
        ids = tuple(page.page_id for page in candidate_pages)
        count = len(candidate_pages)
        _, candidate_duplicate_rate, candidate_duplicate_denominator = _duplicate_rate(candidate_pages)
        coverage = _rate(sum(bool(page.sources) for page in candidate_pages), count)
        types = {page.page_type.lower() for page in candidate_pages}
        def task_for(page):
            return (page.task_type or _TASK_TYPES.get(page.page_type, "reference")).lower()
        # v0.3 plan-audit S1: closure_parts is now driven by
        # ``reader_profile.closure_strict_types`` (pipe-separated OR groups).
        # Default keeps the original 3-slot semantics so existing strict tests
        # remain green.
        closure_required_sets = tuple(
            frozenset(p.strip() for p in group.split("|") if p.strip())
            for group in reader_profile.closure_strict_types
        )
        closure_parts = tuple(bool(types & req) for req in closure_required_sets)
        candidate_ids = set(ids)
        allowed_edge_types = set(reader_profile.allowed_learning_edge_types)
        valid_edges = tuple(
            (page.page_id, relation_type, target)
            for page in candidate_pages for relation_type, target in page.relation_targets
            if relation_type in allowed_edge_types
            and page.page_id != target and target in candidate_ids
            and task_for(page) in _SOURCE_TASKS
            and (
                not reader_profile.require_target_task_match
                or task_for(next((item for item in candidate_pages if item.page_id == target), page)) in _TARGET_TASKS
            )
        )
        has_learning_edge = bool(valid_edges)
        candidate_tasks = sum(
            task_for(page) in reader_profile.task_types
            for page in candidate_pages
        )
        exit_ids = set(reader_profile.chapter_exit_evidence)
        chapter_known = bool(exit_ids) and exit_ids <= candidate_ids and all(
            task_for(page) in _TARGET_TASKS for page in candidate_pages if page.page_id in exit_ids
        )
        closure_ok = all(closure_parts) and has_learning_edge and candidate_tasks >= min_reader_tasks and chapter_known
        closure_status = "closed" if closure_ok else "unknown" if not chapter_known else "incomplete" if any(closure_parts) else "none"
        reasons: list[str] = []
        if coverage < reader_profile.min_source_coverage:
            reasons.append("LOW_SOURCE_COVERAGE")
        if count < reader_profile.min_pages_per_book:
            reasons.append("INSUFFICIENT_PAGES")
        if closure_status != "closed":
            reasons.append("NO_LEARNING_CLOSURE")
        if not chapter_known:
            reasons.append("CHAPTER_EXIT_UNKNOWN")
        if candidate_tasks < min_reader_tasks:
            reasons.append("INSUFFICIENT_READER_TASKS")
        cross_candidate = any(
            target not in candidate_ids and target in page_ids
            for page in candidate_pages for _, target in page.relation_targets
        )
        decision = "proceed" if not reasons else "merge" if cross_candidate else "reference" if candidate_pages else "cancel"
        candidates.append(CandidateDecision(
            candidate_id, ids, count, _rate(count, len({page.page_type for page in candidate_pages})),
            coverage, candidate_duplicate_rate, sum(max(0, page.char_count) for page in candidate_pages),
            candidate_tasks, closure_status, decision, tuple(reasons),
            (), (),
            tuple(f"edge:{source}:{kind}->{target}" for source, kind, target in valid_edges),
            ";".join(reasons),
            candidate_duplicate_denominator,
        ))
    governance = governance or GovernanceConfig()
    block_reasons = tuple(name for name, value in (
        ("external_authorized", governance.external_authorized),
        ("budget_cap", governance.budget_cap),
        ("approver", governance.approver),
    ) if value is None or value is False or value == "")
    candidate_ids = {candidate_id for candidate_id, candidate_pages in _candidate_pages(snapshot, reader_profile).items() if candidate_pages}
    missing_hard = tuple(sorted(set(governance.hard_reference_dependencies) - candidate_ids))
    if missing_hard:
        block_reasons += ("hard_reference_dependencies",)
    soft_missing = tuple(sorted(set(governance.soft_reference_dependencies) - candidate_ids))
    fingerprint_payload = {
        "snapshot": snapshot.snapshot_id,
        "profile": reader_profile.__dict__,
        "governance": governance.__dict__,
    }
    fingerprint = hashlib.sha256(json.dumps(fingerprint_payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    blocked = bool(block_reasons) or not candidates or not any(candidate.decision == "proceed" for candidate in candidates)
    if not candidates or not any(candidate.decision == "proceed" for candidate in candidates):
        block_reasons += ("no_retained_candidate",)
    candidates = [CandidateDecision(
        **{**candidate.__dict__,
           "hard_reference_dependencies": missing_hard,
           "soft_reference_dependencies": soft_missing}
    ) for candidate in candidates]
    return SeriesGateResult(
        fingerprint, metrics, tuple(candidates), "blocked" if blocked else "ready",
        "rule_only" if blocked else "llm_allowed", block_reasons,
        tuple(governance.hard_reference_dependencies), tuple(governance.soft_reference_dependencies),
    )


def partition_pages(snapshot: WikiSnapshot) -> dict[str, tuple[str, ...]]:
    """Group classified pages by type/taxonomy; keep unclassified pages in fallback."""
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    fallback: list[str] = []
    pages = {page.page_id: page for page in snapshot.pages}
    for page in snapshot.pages:
        taxonomy = (page.primary_taxonomy or "").strip()
        if taxonomy:
            groups[(page.page_type, taxonomy)].append(page.page_id)
        else:
            fallback.append(page.page_id)
    result = {
        f"{page_type}-{taxonomy}": tuple(sorted(ids))
        for (page_type, taxonomy), ids in sorted(groups.items())
    }
    if fallback:
        result["fallback"] = tuple(sorted(fallback))
    # Detect malformed caller snapshots early, before any LLM call.
    if sorted(i for ids in result.values() for i in ids) != sorted(pages):
        raise ValueError("partition does not cover snapshot page IDs exactly")
    return result


def build_chapter_chunks(
    snapshot: WikiSnapshot,
    partitions: dict[str, tuple[str, ...]],
    *,
    context_window: int,
    output_reserve: int,
) -> dict[str, tuple[str, ...]]:
    """Pack complete pages in stable order, never splitting a page or content block.

    ``token_count`` is preferred; otherwise ``char_count`` is used as a
    deliberately conservative estimate so a missing tokenizer cannot cause
    an over-limit request.
    """
    if context_window <= 0 or output_reserve < 0 or output_reserve >= context_window:
        raise ValueError("context_window must exceed non-negative output_reserve")
    page_map = {page.page_id: page for page in snapshot.pages}
    expected = sorted(page_map)
    actual = sorted(i for ids in partitions.values() for i in ids)
    if actual != expected or len(actual) != len(set(actual)):
        raise ValueError("partitions must cover each snapshot page ID exactly once")
    limit = context_window - output_reserve
    result: dict[str, tuple[str, ...]] = {}
    for volume_id in sorted(partitions):
        current: list[str] = []
        used = 0
        ordinal = 0
        for page_id in sorted(partitions[volume_id]):
            page = page_map[page_id]
            cost = max(1, page.token_count if page.token_count is not None else page.char_count)
            if current and used + cost > limit:
                result[f"{volume_id}:{ordinal}"] = tuple(current)
                ordinal += 1
                current, used = [], 0
            current.append(page_id)
            used += cost
            # An over-limit page is deliberately isolated and rule-only downstream.
            if used > limit:
                result[f"{volume_id}:{ordinal}"] = tuple(current)
                ordinal += 1
                current, used = [], 0
        if current:
            result[f"{volume_id}:{ordinal}"] = tuple(current)
    return result


def build_series_assignment(
    snapshot: WikiSnapshot,
    *,
    candidate_taxonomies: tuple[str, ...] = ("book-a", "book-b", "book-c"),
) -> dict:
    """Create a deterministic, rule-only page ownership ledger."""
    allowed = {str(value).strip() for value in candidate_taxonomies if str(value).strip()}
    pages = tuple(sorted(snapshot.pages, key=lambda page: (page.page_id, page.path)))
    counts: dict[str, int] = defaultdict(int)
    for page in pages:
        counts[page.page_id] += 1
    page_map = {page.page_id: page for page in pages}
    conflicting_ids = {page_id for page_id, count in counts.items() if count > 1}
    conflict_pages: set[str] = set()
    isolated_pages: set[str] = set()
    for page in pages:
        taxonomy = (page.primary_taxonomy or "").strip()
        for _, target in page.relation_targets:
            target_page = page_map.get(target)
            if not target_page:
                isolated_pages.add(page.page_id)
            elif taxonomy and (target_page.primary_taxonomy or "").strip() != taxonomy:
                conflict_pages.update((page.page_id, target))

    seen_hashes: set[str] = set()
    rows: list[dict] = []
    for page in pages:
        taxonomy = (page.primary_taxonomy or "").strip()
        reason = None
        if page.page_id in conflicting_ids:
            reason = "duplicate_page_id"
        elif page.page_id in conflict_pages:
            reason = "cross_book_conflict"
        elif page.page_id in isolated_pages:
            reason = "isolated_relation"
        elif taxonomy not in allowed:
            reason = "unknown_taxonomy"
        elif not page.sources:
            reason = "missing_source"
        elif not page.content_sha256:
            reason = "missing_canonical_hash"
        elif page.content_sha256 in seen_hashes:
            reason = "duplicate_canonical"
        if reason is None:
            seen_hashes.add(page.content_sha256)
        rows.append({
            "page_id": page.page_id,
            "page_type": page.page_type,
            "primary_taxonomy": taxonomy or None,
            "source_status": "present" if page.sources else "missing",
            "content_fingerprint": page.content_sha256,
            "primary_book_id": None if reason else taxonomy,
            "chapter_id": None if reason else f"chapter-{taxonomy}-{page.page_id}",
            "secondary_topics": [],
            "ledger_reason": reason,
        })

    payload = {
        "snapshot_id": snapshot.snapshot_id,
        "schema_version": snapshot.schema_version,
        "candidate_taxonomies": sorted(allowed),
        "pages": [
            {key: value for key, value in row.items() if key not in {"primary_book_id", "chapter_id", "ledger_reason"}}
            for row in rows
        ],
    }
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    reason_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        if row["ledger_reason"]:
            reason_counts[row["ledger_reason"]] += 1
    return {
        "schema_version": "series-assignment-v1",
        "snapshot_fingerprint": fingerprint,
        "fingerprint": fingerprint,
        "assignments": rows,
        "metrics": {
            "total_pages": len(rows),
            "assigned_pages": sum(row["primary_book_id"] is not None for row in rows),
            "ledger_pages": sum(row["ledger_reason"] is not None for row in rows),
            "duplicate_pages": reason_counts["duplicate_canonical"],
            "duplicate_page_ids": sum(count - 1 for count in counts.values() if count > 1),
            "missing_sources": reason_counts["missing_source"],
            "unknown_taxonomies": reason_counts["unknown_taxonomy"],
            "conflict_pages": len(conflict_pages) + len(conflicting_ids),
            "isolated_relations": sum(
                1 for page in pages for _, target in page.relation_targets if target not in page_map
            ),
            "ledger_reasons": dict(sorted(reason_counts.items())),
        },
    }



# ──────────────────────────────────────────────────────────────────
# Task 4 (plan 2026-09-10-novel-wiki-fullbook-readability):
# consolidate the 68 writing-technique-related chapters into 8 named
# chapters (人物塑造 / 情节节奏 / 开篇签约 / 套路爽点 / 描写文笔 /
# 题材世界观 / 心态职业 / 平台读者) without losing any page_id or
# disturbing other chapter buckets.
# ──────────────────────────────────────────────────────────────────

import re as _re_partition

# Default regroup rules: new chapter_id -> regex over (title + summary).
# Each page is matched against rules in order; first match wins. Pages
# that match none of the writing-technique rules fall back to the
# passthrough bucket (so the snapshot invariant still holds).
DEFAULT_WRITING_TECHNIQUE_REGROUP: dict[str, "_re_partition.Pattern[str]"] = {
    "concept-写作技法-人物塑造与设定": _re_partition.compile(
        r"人物|主角|配角|性格|女主|反派|身世"
    ),
    "concept-写作技法-情节与节奏": _re_partition.compile(
        r"情节|主线|支线|冲突|转折|伏笔|节奏"
    ),
    "concept-写作技法-开篇与签约": _re_partition.compile(
        r"开篇|书名|简介|上架|A签|VIP|签约"
    ),
    "concept-写作技法-套路与爽点": _re_partition.compile(
        r"套路|YY|扮猪|装B|金手指|打脸|碾压"
    ),
    "concept-写作技法-描写与文笔": _re_partition.compile(
        r"描写|五感|对话|动作|环境|意象|文笔"
    ),
    "concept-写作技法-题材与世界观": _re_partition.compile(
        r"题材|世界观|玄幻|仙侠|都市|历史|科幻"
    ),
    "concept-写作技法-心态与职业": _re_partition.compile(
        r"心态|职业|坚持|完本|全职"
    ),
    "concept-写作技法-平台与读者": _re_partition.compile(
        r"平台|读者|书评|签约"
    ),
}


def _writing_technique_pages(snapshot) -> set[str]:
    """Return the page_ids currently allocated to any
    `concept-写作技法__...` chapter, plus `synthesis-写作技法__...`
    pages. The 8 new chapters consume exactly this set; everything
    else passes through unchanged.
    """
    return {
        p.page_id
        for p in snapshot.pages
        if p.primary_taxonomy == "写作技法" or p.page_id.startswith("concept-写作技法")
    }


def partition_writing_technique_merged(
    snapshot,
    *,
    regroup_rules=None,
    passthrough_prefixes=("fallback", "entity-", "synthesis-"),
):
    """Consolidate writing-technique pages into 8 named chapters.

    Returns a `chapter_id -> tuple[page_id, ...]` mapping whose
    union is exactly `sorted(snapshot.pages)`, satisfying the
    same coverage invariant `partition_pages` enforces.

    - `regroup_rules` defaults to `DEFAULT_WRITING_TECHNIQUE_REGROUP`
      (8 named chapters). Each rule's regex matches against the
      page title (PageRecord.title); first match wins.
    - Pages not currently in any writing-technique chapter
      are passed through under their existing chapter_id (derived
      from `primary_taxonomy` + first page title segment).
    - Pages in writing-technique chapters that match none of the
      rules fall into the first regroup rule ("人物塑造与设定")
      as a deterministic catch-all so no page is lost.

    The caller is expected to feed this into the existing
    `build_chapter_chunks` pipeline (with appropriate
    `context_window`) — see `partition.build_chapter_chunks`.
    """
    if regroup_rules is not None and not regroup_rules:
        # Caller asked for custom rules but gave an empty mapping.
        # That is a programming error, not a "use defaults" signal
        # (use None for the default path).
        raise ValueError("regroup_rules must contain at least one entry")
    rules = regroup_rules if regroup_rules is not None else DEFAULT_WRITING_TECHNIQUE_REGROUP

    page_map = {p.page_id: p for p in snapshot.pages}
    expected = sorted(page_map)

    writing_pages = _writing_technique_pages(snapshot)
    rule_order = list(rules.keys())
    new_chapters: dict[str, list[str]] = {cid: [] for cid in rule_order}
    passthrough: dict[str, list[str]] = defaultdict(list)
    catchall = rule_order[0]

    for page in snapshot.pages:
        if page.page_id in writing_pages:
            matched = False
            title = page.title or ""
            for cid, pattern in rules.items():
                if pattern.search(title):
                    new_chapters[cid].append(page.page_id)
                    matched = True
                    break
            if not matched:
                new_chapters[catchall].append(page.page_id)
            continue

        # Passthrough: bucket by taxonomy unless its prefix is in
        # `passthrough_prefixes` (handled separately), otherwise use
        # the first page_id segment + its taxonomy label as bucket.
        taxonomy = (page.primary_taxonomy or "").strip() or "passthrough"
        bucket = f"{page.page_type}-{taxonomy}"
        for prefix in passthrough_prefixes:
            if taxonomy.startswith(prefix) or bucket.startswith(prefix):
                bucket = prefix.rstrip("-")
                break
        passthrough[bucket].append(page.page_id)

    # Merge new chapters and passthrough into one result dict.
    result: dict[str, list[str]] = {}
    for cid in rule_order:
        if new_chapters[cid]:
            result[cid] = new_chapters[cid]
    for bucket, ids in sorted(passthrough.items()):
        result[bucket] = ids

    # Enforce coverage invariant: union must equal snapshot.pages.
    actual = sorted(p for ids in result.values() for p in ids)
    if actual != expected:
        raise ValueError(
            "partition_writing_technique_merged does not cover the "
            f"snapshot: missing {sorted(set(expected) - set(actual))}, "
            f"extra {sorted(set(actual) - set(expected))}"
        )

    # Convert each bucket to a stable tuple. Sort within a bucket so
    # the chapter composition is deterministic across runs.
    return {cid: tuple(sorted(ids)) for cid, ids in result.items()}
__all__ = [
    "partition_pages", "build_chapter_chunks", "ReaderProfile", "GovernanceConfig",
    "GateMetrics", "CandidateDecision", "SeriesGateResult", "evaluate_series_gate",
    "build_series_assignment",
    "partition_writing_technique_merged", "DEFAULT_WRITING_TECHNIQUE_REGROUP",
]
