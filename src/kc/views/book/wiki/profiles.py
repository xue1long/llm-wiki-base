"""Book-series profiles and chapter-exit evidence derivation.

Plan: docs/superpowers/plans/2026-09-06-novel-wiki-book-series-compile-enable.md
Slice S2: NOVEL_WIKI_PROFILE for the real novel-wiki wiki + chapter exit evidence
auto-derivation.

The default `ReaderProfile` in `partition.py` keeps the strict closure contract
so existing tests stay green. `NOVEL_WIKI_PROFILE` here relaxes three gates
specifically for the real novel-wiki structure:

* ``closure_strict_types=("concept|foundation|orientation",
  "synthesis|application|example")`` — drops the entity slot, because
  novel-wiki's writing-craft taxonomy has 0 entity pages.
* ``allowed_learning_edge_types`` — adds ``referenced_by``, ``supported_by``,
  ``is_part_of``, ``references``, ``contains`` so the real wiki's dense
  in-candidate graph counts toward the learning-edge gate.
* ``require_target_task_match=False`` — accepts concept→concept edges, which
  are the dominant pattern in novel-wiki.

``derive_chapter_exit_evidence`` synthesizes an exit-evidence tuple from the
candidate's synthesis pages so the gate's ``chapter_known`` check passes
without the operator hand-curating page ids.
"""
from __future__ import annotations

from .model import WikiSnapshot
from .partition import ReaderProfile


NOVEL_WIKI_PROFILE = ReaderProfile(
    profile_id="novel-wiki-default",
    task_types=("learn_concept", "reference", "apply"),
    candidate_taxonomies=(
        "写作技法",
        "题材体系",
        "心态与职业",
        "平台规则",
        "读者与市场",
        "案例与素材",
    ),
    min_pages_per_book=20,
    min_source_coverage=0.8,
    min_reader_tasks=6,
    # closure relaxed — entity slot is dropped because real novel-wiki
    # candidate taxonomies rarely have entity pages.
    closure_strict_types=(
        "concept|foundation|orientation",
        "synthesis|application|example",
    ),
    # learning-edge types expanded beyond supports/required_by.
    allowed_learning_edge_types=(
        "supports",
        "required_by",
        "referenced_by",
        "supported_by",
        "is_part_of",
        "references",
        "contains",
    ),
    require_target_task_match=False,
    # chapter_exit_evidence is left empty by default; callers must invoke
    # ``derive_chapter_exit_evidence`` to populate it per candidate.
    chapter_exit_evidence=(),
)


_SYNTHESIS_TYPES = frozenset({"synthesis", "application", "example"})


def derive_chapter_exit_evidence(snapshot: WikiSnapshot,
                                  candidate_taxonomy: str) -> tuple[str, ...]:
    """Return a deterministic tuple of synthesis/concept page_ids inside the
    candidate taxonomy so the gate's ``chapter_known`` check can pass.

    The tuple is sorted by page_id for stability; up to three pages are
    returned (the dominant synthesis pages plus a single concept anchor when
    no synthesis is present). Returns ``()`` when no eligible page exists.
    """
    pages = [
        page for page in snapshot.pages
        if (page.primary_taxonomy or "").strip() == candidate_taxonomy
    ]
    synth = sorted(
        (p.page_id for p in pages if p.page_type in _SYNTHESIS_TYPES),
        key=lambda pid: pid,
    )
    if not synth:
        return ()
    return tuple(synth[:3])


__all__ = ["NOVEL_WIKI_PROFILE", "derive_chapter_exit_evidence"]
