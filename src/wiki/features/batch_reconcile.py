"""Batch-level reconcile (NDG Phase 4.2) — deterministic, zero LLM cost.

Runs between ``generate_ingest`` and the NDG gate to resolve intra-batch
conflicts that arise from concurrent generation (V13/V15/V17):

1. **Stub suppression** — ``processing_depth=stub`` pages whose slug matches
   a non-stub page in the same batch are discarded (the real page supersedes
   the placeholder).

2. **Same-slug same-type merge (V15)** — when two raw files extract the same
   entity/concept (same slug + same type), keep the higher-grade page and
   merge the loser's relations / backward edges into the winner.  Record
   every merge in the returned report.

3. **Same-slug cross-type conflict** — detected and returned as a conflict
   list.  The caller (NDG gate P6) decides whether to reject the batch.

All operations are in-memory; nothing is written to disk.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.wiki.core.types import WikiPage


@dataclass
class MergeEntry:
    """Record of a single entity merge during batch reconcile."""
    kept: str       # slug of the page that survived
    dropped: str    # slug of the page that was merged into *kept*
    reason: str     # e.g. "higher grade (A > B)", "same grade, kept first"


@dataclass
class ConflictEntry:
    """A cross-type slug conflict that must be resolved before commit."""
    slug: str
    types: tuple[str, str]  # the two conflicting PageType values


@dataclass
class ReconcileResult:
    """Output of :func:`reconcile_batch`.

    *pages* is the authoritative page list for subsequent gate + commit.
    """
    pages: list[WikiPage]
    merged: list[MergeEntry] = field(default_factory=list)
    conflicts: list[ConflictEntry] = field(default_factory=list)
    stubs_suppressed: int = 0


def reconcile_batch(
    pages: list[WikiPage],
    extra_pages: list[WikiPage] | None = None,
) -> ReconcileResult:
    """Reconcile a batch of generated pages before gate + commit.

    Parameters
    ----------
    pages:
        All pages produced by this batch's ``generate_ingest`` calls.
    extra_pages:
        Pre-existing pages touched by reverse relations (will be
        included in the output but not subject to merge logic).

    Returns
    -------
    ReconcileResult
        Reconciled page list + merge log + cross-type conflicts.
    """
    all_pages = list(pages)
    if extra_pages:
        all_pages.extend(extra_pages)

    # ── Step 1: stub suppression ──────────────────────────────────
    # Build a lookup of non-stub slugs in this batch.
    non_stub_slugs: set[str] = {
        p.id for p in all_pages
        if p.id and getattr(p, "processing_depth", None) != "stub"
    }

    stubs_suppressed = 0
    kept: list[WikiPage] = []
    for p in all_pages:
        if getattr(p, "processing_depth", None) == "stub" and p.id in non_stub_slugs:
            stubs_suppressed += 1
            continue  # real page supersedes stub
        kept.append(p)

    # ── Step 2: same-slug same-type merge (V15) ───────────────────
    merged: list[MergeEntry] = []
    conflicts: list[ConflictEntry] = []

    # Index by (slug, type)
    by_slug_type: dict[tuple[str, str], list[WikiPage]] = {}
    for p in kept:
        if not p.id:
            continue
        key = (p.id, p.type.value if hasattr(p.type, "value") else str(p.type))
        by_slug_type.setdefault(key, []).append(p)

    # Cross-type conflicts
    slug_types: dict[str, str] = {}
    for p in kept:
        if not p.id:
            continue
        pt = p.type.value if hasattr(p.type, "value") else str(p.type)
        existing = slug_types.get(p.id)
        if existing is not None and existing != pt:
            conflicts.append(ConflictEntry(slug=p.id, types=(existing, pt)))
        slug_types[p.id] = pt

    # Merge within same (slug, type) groups
    deduped: list[WikiPage] = []
    for (slug, _pt), group in by_slug_type.items():
        if len(group) == 1:
            deduped.append(group[0])
            continue

        # Sort by grade: A > B > C, then by position in original list
        _grade_order = {"A": 0, "B": 1, "C": 2}
        group.sort(key=lambda p: (
            _grade_order.get(getattr(p, "grade", "B"), 1),
        ))

        winner = group[0]
        for loser in group[1:]:
            # Merge loser's relations into winner
            if loser.relations:
                winner_rels = list(winner.relations or [])
                existing_targets = {(r.target_id, r.type) for r in winner_rels}
                for rel in loser.relations:
                    if (rel.target_id, rel.type) not in existing_targets:
                        winner_rels.append(rel)
                        existing_targets.add((rel.target_id, rel.type))
                winner.relations = winner_rels

            merged.append(MergeEntry(
                kept=winner.id,
                dropped=loser.id,
                reason=(
                    f"higher grade ({getattr(winner, 'grade', 'B')}"
                    f" > {getattr(loser, 'grade', 'B')})"
                ),
            ))

        deduped.append(winner)

    return ReconcileResult(
        pages=deduped,
        merged=merged,
        conflicts=conflicts,
        stubs_suppressed=stubs_suppressed,
    )
