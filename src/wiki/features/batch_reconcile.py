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

4. **Extra-page management (R1-2)** — pre-existing pages touched by reverse
   relations are deduped by id; a collision with a batch page is adjudicated
   by grade (batch wins → extra folded; extra wins → batch dropped) and the
   survivors are returned separately in ``ReconcileResult.extras``, never
   mixed into ``pages``.

All operations are in-memory; nothing is written to disk.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.wiki.core.types import WikiPage

# Grade precedence for reconcile adjudication: A > B > C.
_GRADE_ORDER = {"A": 0, "B": 1, "C": 2}


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

    *pages* is the authoritative batch-page list for subsequent gate + commit.
    *extras* are the pre-existing pages that survive reconcile — either
    non-colliding extras passed in, or extras that beat a same-(id, type)
    batch page on grade.  They are kept separate from the batch's own pages.
    """
    pages: list[WikiPage]
    extras: list[WikiPage] = field(default_factory=list)
    merged: list[MergeEntry] = field(default_factory=list)
    conflicts: list[ConflictEntry] = field(default_factory=list)
    stubs_suppressed: int = 0


def _fold_relations(winner: WikiPage, loser: WikiPage) -> None:
    """Merge *loser*'s relations into *winner*, deduped by (target_id, type);
    on a tie the higher-weight relation wins.  Mutates *winner* in place."""
    if not loser.relations:
        return
    winner_rels = list(winner.relations or [])
    w_idx: dict[tuple[str, str], int] = {}
    for i, r in enumerate(winner_rels):
        w_idx[(r.target_id, r.type)] = i
    for rel in loser.relations:
        key_r = (rel.target_id, rel.type)
        if key_r not in w_idx:
            winner_rels.append(rel)
            w_idx[key_r] = len(winner_rels) - 1
        else:
            existing_w = getattr(winner_rels[w_idx[key_r]], "weight", 1.0) or 1.0
            loser_w = getattr(rel, "weight", 1.0) or 1.0
            if loser_w > existing_w:
                winner_rels[w_idx[key_r]] = rel
    winner.relations = winner_rels


def _fold_extras(group: list[WikiPage]) -> WikiPage:
    """Fold a group of same-(id, type) extras into a single representative.

    Duplicate extras arise when several batch pages reference the same
    existing page; their bodies are identical by construction, so only
    relations are unioned.  The highest-grade page becomes the rep."""
    group = sorted(group, key=lambda e: _GRADE_ORDER.get(getattr(e, "grade", "B"), 1))
    rep = group[0]
    for other in group[1:]:
        _fold_relations(rep, other)
    return rep


def reconcile_batch(
    pages: list[WikiPage],
    extra_pages: list[WikiPage] | None = None,
    paths: "WikiPaths | None" = None,
) -> ReconcileResult:
    """Reconcile a batch of generated pages before gate + commit.

    Parameters
    ----------
    pages:
        All pages produced by this batch's ``generate_ingest`` calls.
    extra_pages:
        Pre-existing pages touched by reverse relations.  Same-id extras are
        folded (relations unioned) into a single representative; a collision
        with a batch page (same id + type) is adjudicated by grade — the
        higher-grade page wins and the loser's relations fold into it.  The
        survivors are returned in ``ReconcileResult.extras``, kept separate
        from the batch's own pages.
    paths:
        When provided, the batch's cross-type slug conflicts are resolved
        against the existing wiki: the on-disk type for a slug wins, and
        batch pages of the *other* type are dropped.  A cross-type
        conflict is only reported when the wiki has no entry for the slug
        (nothing to defer to).  When ``None`` (legacy callers / pure batch
        tests), every cross-type slug collision is reported as a conflict.

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

    # When paths is provided, load the existing wiki's slug→type map so
    # cross-type collisions can defer to the on-disk type (Phase 6 fix).
    wiki_slug_types: dict[str, str] = {}
    if paths is not None:
        try:
            from .indexer import read_index
            for slug, ptype, _title in read_index(paths):
                wiki_slug_types[slug] = ptype.value if hasattr(ptype, "value") else str(ptype)
        except Exception:
            wiki_slug_types = {}

    # Cross-type conflicts.  Two-pass detection so the resolution is
    # deterministic regardless of page order:
    #   1st pass — collect every type a slug appears with in the batch.
    #   2nd pass — for slugs with >1 type: if the wiki knows the slug,
    #              drop the pages whose type differs from the wiki type
    #              (the wiki is the source of truth); otherwise report a
    #              ConflictEntry (nothing to defer to).
    batch_types: dict[str, set[str]] = {}
    for p in kept:
        if not p.id:
            continue
        pt = p.type.value if hasattr(p.type, "value") else str(p.type)
        batch_types.setdefault(p.id, set()).add(pt)

    cross_type_slugs = {
        slug for slug, types in batch_types.items()
        if len(types) > 1
    }

    drop_slugs: set[str] = set()   # slugs resolved by the wiki (drop non-matching)
    for slug in cross_type_slugs:
        wiki_type = wiki_slug_types.get(slug)
        if wiki_type is not None:
            # Wiki knows the slug → its type wins; the batch pages of the
            # other type(s) are dropped, not flagged.
            drop_slugs.add(slug)
        else:
            # Wiki has no entry → genuine cross-type collision.
            conflicts.append(ConflictEntry(
                slug=slug, types=tuple(sorted(batch_types[slug])),
            ))

    if drop_slugs:
        # Wiki-known slug with a cross-type batch collision: keep only the
        # pages whose type matches the wiki's type, and fold the dropped
        # pages' sources + relations into the surviving page(s) so no
        # information is lost by the type resolution.
        _survivors: list[WikiPage] = []
        _dropped: list[WikiPage] = []
        for p in kept:
            if not p.id or p.id not in drop_slugs:
                _survivors.append(p)
                continue
            pt = p.type.value if hasattr(p.type, "value") else str(p.type)
            if pt == wiki_slug_types[p.id]:
                _survivors.append(p)
            else:
                _dropped.append(p)
        # Fold dropped pages' sources + relations into survivors of the
        # same slug (best-effort; multiple survivors share the folded info).
        if _dropped:
            for d in _dropped:
                targets = [q for q in _survivors if q.id == d.id]
                if not targets:
                    continue
                t = targets[0]
                if d.sources:
                    _srcs = set(t.sources or [])
                    for s in d.sources:
                        if s not in _srcs:
                            t.sources = list(t.sources or []) + [s]
                            _srcs.add(s)
                if d.relations:
                    _rels = list(t.relations or [])
                    _ridx = {(r.target_id, r.type) for r in _rels}
                    for rel in d.relations:
                        if (rel.target_id, rel.type) not in _ridx:
                            _rels.append(rel)
                            _ridx.add((rel.target_id, rel.type))
                    t.relations = _rels
        kept = _survivors

    # Index batch pages by (slug, type) — after cross-type resolution so
    # dropped pages never reach the merge step.
    by_slug_type: dict[tuple[str, str], list[WikiPage]] = {}
    for p in kept:
        if not p.id:
            continue
        key = (p.id, p.type.value if hasattr(p.type, "value") else str(p.type))
        by_slug_type.setdefault(key, []).append(p)

    # Merge within same (slug, type) groups
    deduped: list[WikiPage] = []
    for (_slug, _pt), group in by_slug_type.items():
        if len(group) == 1:
            deduped.append(group[0])
            continue

        # Sort by grade: A > B > C, then by position in original list
        group.sort(key=lambda p: (
            _GRADE_ORDER.get(getattr(p, "grade", "B"), 1),
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
            _fold_relations(winner, loser)

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

    # ── Step 3: extra_pages — fold by id, adjudicate collisions by grade ──
    # Extras are pre-existing pages touched by reverse relations.  When an
    # extra collides with a batch page (same id + type), the higher-grade page
    # survives: batch wins (equal-or-higher) → extra's relations fold into the
    # batch page; extra wins (strictly higher) → the batch page drops and the
    # extra is kept in result.extras.  Non-colliding extras are deduped by id
    # and kept in result.extras — result.pages holds only the batch's pages.
    batch_by_id: dict[tuple[str, str], WikiPage] = {}
    for p in deduped:
        if not p.id:
            continue
        key = (p.id, p.type.value if hasattr(p.type, "value") else str(p.type))
        batch_by_id[key] = p

    extra_by_id: dict[tuple[str, str], list[WikiPage]] = {}
    for ep in (extra_pages or []):
        if not ep.id:
            continue
        key = (ep.id, ep.type.value if hasattr(ep.type, "value") else str(ep.type))
        extra_by_id.setdefault(key, []).append(ep)

    extras_out: list[WikiPage] = []
    for key, extra_group in extra_by_id.items():
        rep = _fold_extras(extra_group)
        batch_page = batch_by_id.get(key)
        if batch_page is None:
            extras_out.append(rep)
            continue
        b_order = _GRADE_ORDER.get(getattr(batch_page, "grade", "B"), 1)
        e_order = _GRADE_ORDER.get(getattr(rep, "grade", "B"), 1)
        if b_order <= e_order:
            # Batch page is equal-or-higher grade → fold the extra into it.
            _fold_relations(batch_page, rep)
            merged.append(MergeEntry(
                kept=batch_page.id,
                dropped=rep.id,
                reason=f"extra folded (grade {getattr(rep, 'grade', 'B')})",
            ))
        else:
            # Extra has strictly higher grade → it survives; batch page drops
            # (its outbound relations drop with it — quality over connectivity).
            deduped = [p for p in deduped if p is not batch_page]
            extras_out.append(rep)
            merged.append(MergeEntry(
                kept=rep.id,
                dropped=batch_page.id,
                reason="existing higher grade",
            ))

    return ReconcileResult(
        pages=deduped,
        extras=extras_out,
        merged=merged,
        conflicts=conflicts,
        stubs_suppressed=stubs_suppressed,
)
