"""Rule-only chapter aggregation with block identity preservation."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .model import ContentBlock, PageRecord
from .section_buckets import bucket_for_heading


@dataclass(frozen=True)
class ChapterDraft:
    chapter_id: str
    page_ids: tuple[str, ...]
    blocks: tuple[ContentBlock, ...]
    block_ids: tuple[str, ...]
    bucket_index: dict[str, tuple[str, ...]]
    transition_in: str | None = None
    transition_out: str | None = None
    intra_chapter_order: tuple[str, ...] = ()


_TYPE_ORDER = {"synthesis": 0, "concept": 1, "entity": 2, "source": 3}
_GRADE_ORDER = {"A": 0, "B": 1, "C": 2}


def order_pages_within_chapter(
    chapter: dict, pages: dict[str, PageRecord], *, mode: Literal["rule_only", "llm_enhanced"] = "rule_only"
) -> tuple[str, ...]:
    del mode  # LLM ordering is an optional later stage; rule output remains safe and complete.
    ids = tuple(item if isinstance(item, str) else item["page_id"] for item in chapter.get("page_ids", ()))
    if any(pid not in pages for pid in ids):
        missing = sorted(set(ids) - pages.keys())
        raise ValueError(f"unknown page id(s): {missing!r}")
    return tuple(sorted(ids, key=lambda pid: (_TYPE_ORDER.get(pages[pid].page_type, 99), _GRADE_ORDER.get(getattr(pages[pid], "grade", "B"), 99), pid)))


def aggregate_chapter(chapter: dict, pages: dict[str, PageRecord]) -> ChapterDraft:
    ordered = order_pages_within_chapter(chapter, pages)
    blocks: list[ContentBlock] = []
    buckets: dict[str, list[str]] = {}
    for pid in ordered:
        for block in pages[pid].content_blocks:
            blocks.append(block)
            buckets.setdefault(bucket_for_heading(block.heading), []).append(block.block_id)
    block_ids = tuple(block.block_id for block in blocks)
    if len(Counter(block_ids)) != len(block_ids):
        raise ValueError("duplicate block_id in chapter")
    return ChapterDraft(str(chapter.get("chapter_id", "")), ordered, tuple(blocks), block_ids,
                        {name: tuple(ids) for name, ids in buckets.items()},
                        intra_chapter_order=ordered)


def relation_stats(snapshot) -> dict[str, object]:
    known = {p.page_id for p in snapshot.pages}
    known.update(snapshot.excluded_sources)
    # Legacy generators emitted equivalent IDs with punctuation/number
    # separators in different positions. Resolve only unambiguous aliases;
    # ambiguous compactions remain blocking unresolved edges.
    from src.wiki.features.slug_utils import normalize_reconcile_slug
    normalized = {}
    compact = {}
    for page_id in known:
        normalized.setdefault(normalize_reconcile_slug(page_id), set()).add(page_id)
        compact.setdefault(page_id.replace("-", ""), set()).add(page_id)
    alias_registry = None
    try:
        from src.wiki.features.slug_aliases import SlugAliasRegistry
        alias_registry = SlugAliasRegistry(Path(snapshot.wiki_root).parent)
    except Exception:
        pass
    namespace_types = {"taxonomy_of", "belongs_to_audience", "hosted_on_platform", "has_credibility"}
    total = unresolved = 0
    ignored_namespace = 0
    resolved_normalized = resolved_compact = resolved_alias = 0
    unresolved_ids: list[str] = []
    for page in snapshot.pages:
        for _kind, target in page.relation_targets:
            if _kind in namespace_types:
                ignored_namespace += 1
                continue
            total += 1
            if target not in known:
                if len(normalized.get(normalize_reconcile_slug(target), ())) == 1:
                    resolved_normalized += 1
                elif len(compact.get(target.replace("-", ""), ())) == 1:
                    resolved_compact += 1
                elif alias_registry and alias_registry.get_canonical(target) in known:
                    resolved_alias += 1
                else:
                    unresolved += 1
                    unresolved_ids.append(target)
    return {"total": total, "unresolved": unresolved, "ignored_namespace": ignored_namespace,
            "resolved_normalized": resolved_normalized, "resolved_compact": resolved_compact,
            "resolved_alias": resolved_alias,
            "unresolved_ratio": unresolved / total if total else 0.0,
            "unresolved_targets": tuple(sorted(unresolved_ids))}


__all__ = ["ChapterDraft", "aggregate_chapter", "order_pages_within_chapter", "relation_stats"]
