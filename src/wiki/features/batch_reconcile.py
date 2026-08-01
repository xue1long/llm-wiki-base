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
        Pre-existing pages touched by reverse relations.  These are
        appended to the output as-is — they are **not** subject to
        merge logic (merging could throw away richer existing content).

    Returns
    -------
    ReconcileResult
        Reconciled page list + merge log + cross-type conflicts.
    """
    # ── Step 1: stub suppression (batch pages only) ───────────────
    non_stub_slugs: set[str] = {
        p.id for p in pages
        if p.id and getattr(p, "processing_depth", None) != "stub"
    }

    stubs_suppressed = 0
    kept: list[WikiPage] = []
    for p in pages:
        if getattr(p, "processing_depth", None) == "stub" and p.id in non_stub_slugs:
            stubs_suppressed += 1
            continue
        kept.append(p)

    # ── Step 2: same-slug same-type merge (V15, batch pages only) ──
    merged: list[MergeEntry] = []
    conflicts: list[ConflictEntry] = []

    # Index batch pages by (slug, type)
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
    for (_slug, _pt), group in by_slug_type.items():
        if len(group) == 1:
            deduped.append(group[0])
            continue

        # Sort by grade: A > B > C, then by position in original list
        _grade_order = {"A": 0, "B": 1, "C": 2}
        group.sort(key=lambda p: (
            _grade_order.get(getattr(p, "grade", "B"), 1),
        ))

        winner = group[0]
        w_grade = getattr(winner, "grade", "B")
        for loser in group[1:]:
            l_grade = getattr(loser, "grade", "B")

            # Merge loser's sources
            if loser.sources:
                winner_srcs = set(winner.sources or [])
                for s in loser.sources:
                    if s not in winner_srcs:
                        winner.sources = list(winner.sources or []) + [s]
                        winner_srcs.add(s)

            # Merge relations: keep higher-weight relation on ties
            if loser.relations:
                winner_rels = list(winner.relations or [])
                # Index winner relations by (target_id, type)
                w_idx: dict[tuple[str, str], int] = {}
                for i, r in enumerate(winner_rels):
                    w_idx[(r.target_id, r.type)] = i
                for rel in loser.relations:
                    key_r = (rel.target_id, rel.type)
                    if key_r not in w_idx:
                        winner_rels.append(rel)
                        w_idx[key_r] = len(winner_rels) - 1
                    else:
                        # Keep the one with higher weight
                        existing_w = getattr(winner_rels[w_idx[key_r]], "weight", 1.0) or 1.0
                        loser_w = getattr(rel, "weight", 1.0) or 1.0
                        if loser_w > existing_w:
                            winner_rels[w_idx[key_r]] = rel
                winner.relations = winner_rels

            reason = (
                f"higher grade ({w_grade} > {l_grade})"
                if w_grade != l_grade
                else "same grade, kept first"
            )
            merged.append(MergeEntry(
                kept=winner.id,
                dropped=loser.id,
                reason=reason,
            ))

        deduped.append(winner)

    # ── Step 3: append extra_pages (unmerged) ─────────────────────
    if extra_pages:
        deduped.extend(extra_pages)

    return ReconcileResult(
        pages=deduped,
        merged=merged,
        conflicts=conflicts,
        stubs_suppressed=stubs_suppressed,
)
