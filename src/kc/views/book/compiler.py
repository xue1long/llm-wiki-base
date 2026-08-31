"""compile_chapter + IntegrityGate + StrengthPolicy integration (B-T3b).

Roadmap §12.5 (Book Contract) + §14 A8 step 1244 — 单章节 Compiler.

This module stitches three earlier layers together:

    * the **KnowledgeCoreView** Protocol (B-T3a) — read-only access to the
      Knowledge Core
    * the **bind_evidence** helper (B-T3a) — pure-function resolver from
      ``KnowledgeBlock.evidence_refs`` to ``EvidenceRef`` snapshots
    * the **IntegrityGate** orchestrator (§11.2) — 11 Gate pipeline that
      decides whether a KU is publish-quality
    * the **StrengthPolicy** (§6) — derives Evidence strength from
      evidence_type + provenance fields

The compile_chapter() entry point is the B-T3b task deliverable. It does
NOT render Markdown (B-T3c), build outline proposals (B-T4), or create a
PublicationBatch (downstream).

Block construction strategy (B-T3b + B-T3.5 fix):

    The B-T1 ``Chapter`` schema exposes ``source_knowledge_unit_ids`` and
    ``knowledge_block_ids`` but does NOT carry a per-KU → evidence id
    mapping. B-T3b introduced a ``block_evidence_refs=...`` kwarg as a
    transition mechanism; B-T3.5 moves that wiring onto the
    ``KnowledgeCoreView`` Protocol itself (see ``KnowledgeCoreView
    .ku_evidence_ids`` in ``core_view.py``). Each block's
    ``evidence_refs`` is now seeded via ``core_view.ku_evidence_ids(
    ku.ku_id)`` BEFORE ``bind_evidence`` is called.

    A KU missing from the mapping yields an empty tuple — the block
    becomes ``unsupported_fact=True`` (Gate A8 "Unsupported Fact = 0"
    surfaced explicitly via the ``unsupported_fact_count`` field). This
    keeps compile_chapter a pure function (no I/O, no mutation of the
    chapter) and removes the foot-gun where callers could forget to wire
    evidence.

StrengthPolicy wiring (the B-T3b contribution vs. B-T3a):

    B-T3a's ``bind_evidence`` defaults every ``EvidenceRef.strength`` to
    ``"medium"`` (placeholder; see binder.py TODO(B-T3b) marker). B-T3b
    replaces each ref's strength AFTER ``bind_evidence`` by calling
    ``strength_policy.compute_strength(backing_evidence)`` and rebuilding
    a new frozen ``EvidenceRef`` with the real strength. The binder itself
    is NOT modified (B-T3a regression — see tests/test_kc/test_book_binder.py).

IntegrityGate integration:

    For each KU, ``integrity_gate.check(ku, context={...})`` runs the
    11 Gate pipeline. Any ``verdict.blocked == True`` is a compile failure
    (``category="integrity_block"``). Warnings are collected into the
    per-block ``reason_codes`` tuple but never block the compile on their
    own.

    The ``context`` dict is intentionally minimal — gates look up evidence
    and temporal data via attributes on the KU itself; the optional
    ``query_time`` field is the only contextual field the gates consume
    (see src/kc/integrity/gates.py).

    The function does NOT call ``integrity_gate.check_default_closure()``
    — that is a publish-time check (B-T3 / A8 spec) that runs on a
    KnowledgeObject AFTER the entire batch is committed, NOT during single
    chapter compilation.

``IntegrityReport`` placement in ``ChapterRender``:

    Semantics: the chapter compiles one KU at a time; for the whole
    chapter we store the FIRST KU's ``IntegrityReport`` as
    ``ChapterRender.integrity_report``. This is intentional (see B-T3b
    docstring) — chapter-level aggregation is the job of
    ``KnowledgeHealthReport`` (B-T5 / A5). For empty chapters the field
    is ``None`` (no check was run).

Category priority resolution:

    When multiple CompileError categories could fire, return the HIGHEST
    priority category:

        1. ``ku_resolution``        (chapter itself is broken; nothing
                                     else can succeed)
        2. ``integrity_block``      (KU semantic / provenance failure)
        3. ``evidence_unsupported`` (bind_evidence missing)
        4. ``compile_exception``    (lowest — unexpected exceptions)

Compile_exception handling:

    The entire compile_chapter body is wrapped in a try/except. Any
    unexpected exception is converted to a ``CompileError`` with category
    ``"compile_exception"`` and ``reason_codes`` prefixed by
    ``"compile_exception:<ExceptionType>"``. Normal failure paths
    (``ValueError`` from bind_evidence / core_view) are caught by the
    structured error machinery, not by this blanket handler.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal

from src.kc.contracts.strength_policy import StrengthPolicy
from src.kc.integrity.orchestrator import (
    IntegrityGate,
    IntegrityReport,
)
from src.kc.views.book.binder import (
    EvidenceRef,
    EvidenceRefStrength,
    bind_evidence,
)
from src.kc.views.book.contract import (
    Chapter,
    KnowledgeBlock,
    KnowledgeBlockType,
)
from src.kc.views.book.core_view import KnowledgeCoreView
from src.kc.views.book.id_policy import generate_stable_knowledge_block_id


# ─── Decision table: KU unit_type → KnowledgeBlockType ───────────────────
#
# See spec §12.5 KnowledgeBlock (6 values) vs. spec §5.4 KU unit_type
# (8 values). Documented in module docstring above as the canonical
# resolution; preserved here for one-glance review.

_UNIT_TYPE_TO_BLOCK_TYPE: dict[str, KnowledgeBlockType] = {
    "definition": KnowledgeBlockType.DEFINITION,
    "principle": KnowledgeBlockType.PRINCIPLE,
    "mechanism": KnowledgeBlockType.METHOD,    # mechanism = implementation of a method
    "method": KnowledgeBlockType.METHOD,
    "process": KnowledgeBlockType.METHOD,      # process = temporal aspect of a method
    "pattern": KnowledgeBlockType.EXAMPLE,     # pattern is shown via examples
    "case": KnowledgeBlockType.EXAMPLE,        # case = a concrete example
    "event": KnowledgeBlockType.PERSPECTIVE,   # event carries a specific perspective
}


def map_unit_type_to_block_type(unit_type: str) -> KnowledgeBlockType:
    """Map a KU ``unit_type`` (8-value vocabulary, spec §5.4) to a
    ``KnowledgeBlockType`` (6-value vocabulary, spec §12.5).

    Decision table (documented in module docstring):

        definition  → definition
        principle   → principle
        mechanism   → method   (mechanism = implementation detail of a method)
        method      → method
        process     → method   (process = temporal aspect of a method)
        pattern     → example  (pattern is shown via examples)
        case        → example  (case = a concrete example)
        event       → perspective (event carries a specific perspective;
                     B-T3c Renderer may reclassify as conflict if KU has
                     Conflict elements)

    Unknown unit_type → ``KnowledgeBlockType.PRINCIPLE`` (safe default;
    documented as a known compromise).

    Pure function. Same input → same output.
    """
    return _UNIT_TYPE_TO_BLOCK_TYPE.get(unit_type, KnowledgeBlockType.PRINCIPLE)


# ─── Result dataclasses ─────────────────────────────────────────────────


@dataclass(frozen=True)
class CompiledBlock:
    """B-T3b compile 产物的最小单元.

    对应 spec §12.5 KnowledgeBlock + bind_evidence 产物.  故意不带
    IntegrityReport — 整章报告聚合到 ``ChapterRender.integrity_report``.

    Fields:
        knowledge_block    The synthesized ``KnowledgeBlock`` (one per KU).
        evidence_refs      Tuple of bound ``EvidenceRef`` snapshots; empty
                           when the KU has no evidence wiring.
        unsupported_fact   ``True`` when the bind_evidence phase could not
                           resolve evidence ids the block referenced
                           (informational; integrity_block-level errors
                           are separate and prevent the whole compile).
        reason_codes       Tuple of block-level warn/block reason codes
                           surfaced from the 11 Gate pipeline (collected
                           but non-fatal at block level).
    """

    knowledge_block: KnowledgeBlock
    evidence_refs: tuple[EvidenceRef, ...]
    unsupported_fact: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class ChapterRender:
    """compile_chapter 成功时的最终产物.

    Fields:
        chapter                 The source ``Chapter`` (verbatim reference).
        blocks                   ``tuple[CompiledBlock, ...]`` — one per KU,
                                in ``chapter.source_knowledge_unit_ids`` order.
                                Empty tuple when the chapter had no source KUs.
        publication_version      From ``core_view.current_publication_version()``
                                (spec §17 D-21 — Book views MUST consume
                                PublicationGate's value, not invent their own).
        rendered_at              Unix ms timestamp at the moment compile
                                produced this render.
        integrity_report         The FIRST KU's ``IntegrityReport``
                                (representative — chapter-level aggregation is
                                KnowledgeHealthReport's job, B-T5 / A5).
                                ``None`` only when the chapter had zero KUs
                                (no check was run).
        reason_codes             Tuple of chapter-level reason codes (union
                                across all blocks, deduped, order preserved).
        unsupported_fact_count   Sum of block-level ``unsupported_fact`` flags
                                (normally 0; Gate A8 "Unsupported Fact = 0").
    """

    chapter: Chapter
    blocks: tuple[CompiledBlock, ...]
    publication_version: int
    rendered_at: int
    integrity_report: IntegrityReport | None
    reason_codes: tuple[str, ...]
    unsupported_fact_count: int
    conflicts: tuple[Any, ...] | None = None


@dataclass(frozen=True)
class CompileError:
    """compile_chapter 失败时的结构化错误.

    Category priority (highest first):
        1. ``ku_resolution``        chapter is broken; no KU can be resolved
        2. ``integrity_block``      any KU's 11 Gate pipeline returned
                                   ``IntegrityReport.blocked=True``
        3. ``evidence_unsupported`` bind_evidence could not resolve
                                   every block's evidence ids (atomic)
        4. ``compile_exception``    unexpected exception (lowest priority)

    When multiple categories could fire, the highest-priority category
    wins. The chosen category's reason codes populate
    ``CompileError.reason_codes``; ``failed_ku_ids`` is the union of all
    KU ids contributing to the chosen category.
    """

    chapter_id: str
    category: Literal[
        "ku_resolution",
        "integrity_block",
        "evidence_unsupported",
        "compile_exception",
    ]
    reason_codes: tuple[str, ...]
    failed_ku_ids: tuple[str, ...]
    failed_block_ids: tuple[str, ...]
    integrity_report: IntegrityReport | None


# ─── Internal helpers ───────────────────────────────────────────────────


def _ordered_unique(seq: tuple[str, ...]) -> tuple[str, ...]:
    """Return ``seq`` deduplicated (first occurrence wins), order preserved."""
    seen: set[str] = set()
    out: list[str] = []
    for item in seq:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return tuple(out)


def _union_reason_codes(*tuples: tuple[str, ...]) -> tuple[str, ...]:
    """Concatenate reason-code tuples into a single deduped tuple (order preserved)."""
    combined: list[str] = []
    for tup in tuples:
        for item in tup:
            if item not in combined:
                combined.append(item)
    return tuple(combined)


def _build_block_for_ku(
    ku: Any,  # KnowledgeUnit — typed as Any to avoid a circular import
    chapter_id: str,
    *,
    evidence_refs: tuple[str, ...] = (),
) -> KnowledgeBlock:
    """Construct the placeholder ``KnowledgeBlock`` for a single KU.

    Per spec §14 A8 step 1244 (B-T3b):
        b. 构造临时 KnowledgeBlock (占位, 含 ku_id + knowledge_mode)

    The block id is derived from the chapter/KU identity so repeated
    compilation of the same snapshot is stable.
    """
    return KnowledgeBlock(
        id=generate_stable_knowledge_block_id(chapter_id, ku.ku_id),
        chapter_id=chapter_id,
        block_type=map_unit_type_to_block_type(ku.unit_type),
        knowledge_unit_ids=[ku.ku_id],
        statement_refs=[],
        evidence_refs=list(evidence_refs),
        knowledge_mode=str(ku.knowledge_mode),
    )


def _rebuild_evidence_refs_with_strength(
    raw_refs: tuple[EvidenceRef, ...],
    core_view: KnowledgeCoreView,
    strength_policy: StrengthPolicy,
) -> tuple[EvidenceRef, ...]:
    """Replace each ``EvidenceRef.strength`` with StrengthPolicy's verdict.

    The B-T3a binder defaults every strength to ``"medium"``. B-T3b
    supersedes this at compile time by looking up the backing ``Evidence``
    via ``core_view.get_evidence`` and calling
    ``strength_policy.compute_strength``.

    Implementation note:
        We trust bind_evidence has already confirmed every id resolves
        (atomic). If for any reason a ref's evidence id is missing here,
        we fall back to the binder's placeholder "medium" (defensive
        belt-and-braces — this should never happen in production).
    """
    rebuilt: list[EvidenceRef] = []
    for ref in raw_refs:
        backing = core_view.get_evidence(ref.evidence_id)
        if backing is None:
            # Defensive: shouldn't happen — bind_evidence already raised
            # if any id was missing. Preserve the binder default.
            rebuilt.append(ref)
            continue
        strength = strength_policy.compute_strength(backing)
        rebuilt.append(
            EvidenceRef(
                evidence_id=ref.evidence_id,
                strength=strength,
                evidence_type=ref.evidence_type,
                quote=ref.quote,
                quote_hash=ref.quote_hash,
                document_id=ref.document_id,
                block_id=ref.block_id,
            )
        )
    return tuple(rebuilt)


# ─── Main entry point ───────────────────────────────────────────────────


def compile_chapter(
    chapter: Chapter,
    core_view: KnowledgeCoreView,
    integrity_gate: IntegrityGate,
    *,
    strength_policy: StrengthPolicy | None = None,
) -> ChapterRender | CompileError:
    """Compile a ``Chapter`` into a ``ChapterRender`` (or a structured
    ``CompileError`` on failure).

    Step-by-step (spec §14 A8 step 1244):

        1.  Resolve KUs (``core_view.kus_for_chapter(chapter)``).
            * Failure → ``CompileError(category='ku_resolution')``.
            * Empty → return a ``ChapterRender`` with zero blocks and
              ``integrity_report=None`` (placeholder chapter is valid).
        2.  For each KU, in ``chapter.source_knowledge_unit_ids`` order:
            a.  ``integrity_gate.check(ku, context={...})`` →
                ``IntegrityReport``.  ``blocked=True`` is recorded per KU
                but compile continues to aggregate the full failure.
            b.  Build a placeholder ``KnowledgeBlock`` whose
                ``evidence_refs`` are seeded from
                ``core_view.ku_evidence_ids(ku.ku_id)`` (B-T3.5 — moved
                off the B-T3b ``block_evidence_refs`` kwarg).
            c.  ``bind_evidence(block, core_view)`` →
                ``tuple[EvidenceRef, ...]``.  Failure (missing evidence
                id) → ``CompileError(category='evidence_unsupported')``.
            d.  StrengthPolicy recomputation (replaces B-T3a's
                ``"medium"`` placeholder).
        3.  Decide the final outcome by priority:
                ku_resolution > integrity_block > evidence_unsupported.
            ``compile_exception`` is the catch-all for the wrap-around
            try/except (lowest priority).
        4.  All-clear → return ``ChapterRender`` with:
                - ``blocks`` in source order
                - ``publication_version`` from
                  ``core_view.current_publication_version()``
                - ``integrity_report`` from the first KU
                - ``reason_codes`` = union of block-level codes
                - ``unsupported_fact_count`` = sum of block flags

    Args:
        chapter            Source ``Chapter`` (read-only).
        core_view          Read-only view of the Knowledge Core. The
                           per-KU evidence wiring is sourced from
                           ``core_view.ku_evidence_ids(ku.ku_id)`` —
                           B-T3.5 surface on the Protocol.
        integrity_gate     The 11 Gate orchestrator.  Treated as a black
                           box — only ``IntegrityReport.blocked``,
                           ``get_blocking_reasons()``, and ``warnings``
                           are consumed (per B-T3b hard rules).
        strength_policy    Optional StrengthPolicy; defaults to a fresh
                           ``StrengthPolicy()`` (stateless, no caching).

    Returns:
        ``ChapterRender`` on success, ``CompileError`` on failure.
        The function NEVER raises for normal failure paths.
    """
    # Default StrengthPolicy here (stateless) so call sites don't have to
    # construct one.  Caching is intentionally NOT done — the policy is
    # pure and re-running it on every compile is cheap.
    if strength_policy is None:
        strength_policy = StrengthPolicy()

    try:
        return _compile_chapter_inner(
            chapter,
            core_view,
            integrity_gate,
            strength_policy,
        )
    except Exception as exc:
        # Catch-all for any unexpected exception escaping the inner pipeline.
        # Normal failure paths (ValueError from bind_evidence / core_view)
        # are converted to CompileError INSIDE _compile_chapter_inner and
        # never reach this except clause.
        return CompileError(
            chapter_id=chapter.id,
            category="compile_exception",
            reason_codes=(f"compile_exception:{type(exc).__name__}",),
            failed_ku_ids=(),
            failed_block_ids=(),
            integrity_report=None,
        )


def _compile_chapter_inner(
    chapter: Chapter,
    core_view: KnowledgeCoreView,
    integrity_gate: IntegrityGate,
    strength_policy: StrengthPolicy,
) -> ChapterRender | CompileError:
    """Inner pipeline wrapped by ``compile_chapter`` for the catch-all.

    The real priority-resolution logic lives here so that normal
    ``ValueError``-based failure paths return structured ``CompileError``
    records WITHOUT being misinterpreted as ``compile_exception``.
    """
    rendered_at = int(time.time() * 1000)
    publication_version = core_view.current_publication_version()

    # ── Step 1: resolve KUs ────────────────────────────────────────────────
    try:
        kus = core_view.kus_for_chapter(chapter)
    except ValueError as exc:
        # kus_for_chapter raises ValueError when any ku_id is missing
        # (B-T3a strict). Convert to a structured CompileError.
        return CompileError(
            chapter_id=chapter.id,
            category="ku_resolution",
            reason_codes=("ku_resolution:missing_kus",),
            failed_ku_ids=tuple(chapter.source_knowledge_unit_ids),
            failed_block_ids=(),
            integrity_report=None,
        )

    if not kus:
        # Empty chapter — valid placeholder per B-T3a core_view contract.
        return ChapterRender(
            chapter=chapter,
            blocks=(),
            publication_version=publication_version,
            rendered_at=rendered_at,
            integrity_report=None,
            reason_codes=(),
            unsupported_fact_count=0,
        )

    # ── Step 2: per-KU pipeline ───────────────────────────────────────────
    compiled: list[CompiledBlock] = []
    integrity_blocked_ku_ids: list[str] = []
    integrity_blocked_reasons: list[str] = []
    first_integrity_report: IntegrityReport | None = None
    first_block_failed: tuple[str, ...] | None = None
    evidence_unsupported_reasons: list[str] = []

    for ku in kus:
        # 2a: integrity gate
        integrity_report: IntegrityReport = integrity_gate.check(ku)
        if first_integrity_report is None:
            first_integrity_report = integrity_report
        if integrity_report.blocked:
            integrity_blocked_ku_ids.append(ku.ku_id)
            integrity_blocked_reasons.extend(integrity_report.get_blocking_reasons())
            # Don't short-circuit — continue to surface the full failure set,
            # but skip the block-building/binding work for blocked KUs
            # (the whole chapter has already failed; no point building
            # CompiledBlock entries for KUs that won't ship).
            continue

        # 2b: placeholder block
        evidence_ids_for_ku = core_view.ku_evidence_ids(ku.ku_id)
        block = _build_block_for_ku(
            ku,
            chapter.id,
            evidence_refs=tuple(evidence_ids_for_ku),
        )

        # 2c: bind evidence (may fail atomically with ValueError)
        try:
            raw_refs = bind_evidence(block, core_view)
        except ValueError as exc:
            evidence_unsupported_reasons.append(
                f"evidence_unsupported:block={block.id}"
            )
            if first_block_failed is None:
                first_block_failed = (block.id,)
            else:
                first_block_failed = first_block_failed + (block.id,)
            # Continue the loop to collect all failing blocks (so the
            # final CompileError can list every affected block), but
            # we still need to honor priority if ku_resolution /
            # integrity_block also failed elsewhere — that priority
            # check happens AFTER the loop.
            continue

        # 2d: strength recomputation
        rebuilt_refs = _rebuild_evidence_refs_with_strength(
            raw_refs, core_view, strength_policy,
        )

        # Collect block-level reason codes (warn + integration blockers if any)
        block_reason_codes = integrity_report.warnings

        compiled.append(
            CompiledBlock(
                knowledge_block=block,
                evidence_refs=rebuilt_refs,
                unsupported_fact=(len(rebuilt_refs) == 0),
                reason_codes=block_reason_codes,
            )
        )

    # ── Step 3: priority resolution ───────────────────────────────────────
    # ku_resolution wins only if it fired BEFORE the per-KU loop above; the
    # inner loop catches its own ValueError, so by construction a chapter
    # with a missing KU id exits at the Step 1 check above. We still
    # expose the priority order to make the resolution explicit.

    # integrity_block priority
    if integrity_blocked_ku_ids:
        return CompileError(
            chapter_id=chapter.id,
            category="integrity_block",
            reason_codes=tuple(integrity_blocked_reasons),
            failed_ku_ids=tuple(integrity_blocked_ku_ids),
            failed_block_ids=(),
            integrity_report=first_integrity_report,
        )

    # evidence_unsupported priority (lower than integrity_block but
    # higher than compile_exception)
    if evidence_unsupported_reasons:
        return CompileError(
            chapter_id=chapter.id,
            category="evidence_unsupported",
            reason_codes=tuple(evidence_unsupported_reasons),
            failed_ku_ids=(),
            failed_block_ids=first_block_failed or (),
            integrity_report=first_integrity_report,
        )

    # ── Step 4: all-clear → ChapterRender ─────────────────────────────────
    return ChapterRender(
        chapter=chapter,
        blocks=tuple(compiled),
        publication_version=publication_version,
        rendered_at=rendered_at,
        integrity_report=first_integrity_report,
        reason_codes=_union_reason_codes(
            *(cb.reason_codes for cb in compiled)
        ),
        unsupported_fact_count=sum(1 for cb in compiled if cb.unsupported_fact),
    )


__all__ = [
    "ChapterRender",
    "CompileError",
    "CompiledBlock",
    "compile_chapter",
    "map_unit_type_to_block_type",
]
