"""NDG gate — batch-level structural checks (P5–P7).

Consumes :mod:`src.wiki.features.lint` exported symbols so the gate and
``cli lint`` never diverge.  All checks are deterministic (zero LLM cost).

Scope
-----
The gate enforces only the **batch-level structural checks** that must run
before write (or on a batch of on-disk pages):

P4b UGC-CARRIER       a non-stub page derived from a UGC carrier raw must
                       carry BOTH 素材/ugc AND 可信度/ugc — missing either
                       is a blocker (D5 defensive line behind auto-tag)
P5  INPUT-SOURCE-PAIR  every raw input has a corresponding SOURCE page
                       (warning only — Fix D guarantees one per file)
P6  SLUG-CONFLICT      no two pages share the same slug with different types
P7  EXTRA-PAGES        extra_pages that would overwrite existing non-stub
                       pages → flag (unless ``--allow-overwrite``)

Per-page quality checks (P1 readability, P2 raw-paste, P3 missing-sources,
P4 ugc-cred) share their decision logic with ``cli lint`` (via
:mod:`src.wiki.features.lint`).  ``run_ndg_gate`` surfaces them as
**warnings** (``is_blocker=False``) so page quality is visible at write
time, but they never block the batch — ``cli lint`` remains the
authoritative quality gate.  The ``check_page`` helper is exported for
callers that want the P1–P4 predicates directly.

Usage (library)
---------------
>>> from src.wiki.features.ndg_gate import check_page, check_batch, GateReport
>>> issues_p14 = check_page(page)          # P1–P4 (lint-shared predicates)
>>> issues_p57 = check_batch(pages, raw_headers, paths)
>>> report = run_ndg_gate(pages, raw_headers=raw_headers, paths=paths)

Usage (CLI)
-----------
    python scripts/batch_gate_check.py <wiki_root> <page1.md> [page2.md ...]
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from ..core.types import PageType, WikiPage
from ..core.paths import WikiPaths
from .lint import (
    _has_fulltext_section,
    _long_raw_text_run,
    _readability_violation,
    _missing_sources,
    _missing_ugc_cred,
    _is_ugc_carrier,
    _DEFAULT_T_SOURCE,
    _DEFAULT_T_NON,
)

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class GateIssue:
    """A single NDG gate violation."""

    code: str            # "P1" … "P7"
    page_id: str | None  # None for batch-level issues without a single page
    message: str
    is_blocker: bool = True  # False → warning only, doesn't block commit


@dataclass
class GateReport:
    """Result of a full NDG gate run."""

    passed: bool
    issues: list[GateIssue] = field(default_factory=list)
    page_count: int = 0
    blocker_count: int = 0

    @property
    def warnings(self) -> list[GateIssue]:
        return [i for i in self.issues if not i.is_blocker]


def _build_report(issues: list[GateIssue], page_count: int) -> GateReport:
    blockers = [i for i in issues if i.is_blocker]
    return GateReport(
        passed=len(blockers) == 0,
        issues=issues,
        page_count=page_count,
        blocker_count=len(blockers),
    )


# ---------------------------------------------------------------------------
# Per-page checks (P1–P4)
# ---------------------------------------------------------------------------


def check_page(
    page: WikiPage,
    T_source: int | None = None,
    T_non: int | None = None,
) -> list[GateIssue]:
    """Run P1–P4 on a single page.

    Parameters
    ----------
    page:
        The WikiPage to check.
    T_source / T_non:
        RAW-PASTE thresholds.  When *None*, falls back to the module
        constants (:data:`_DEFAULT_T_SOURCE` / :data:`_DEFAULT_T_NON`).

    Returns
    -------
    list[GateIssue]
        Violations found (empty → pass).
    """
    issues: list[GateIssue] = []

    _check_p1_readability(page, issues)
    _check_p2_raw_paste(page, T_source, T_non, issues)
    _check_p3_missing_sources(page, issues)
    _check_p4_ugc_cred(page, issues)

    return issues


def _check_p1_readability(page: WikiPage, issues: list[GateIssue]) -> None:
    """P1: page must have non-empty id, title, and body."""
    violation = _readability_violation(page)
    if violation == "empty_id":
        issues.append(GateIssue("P1", None, "Page has empty id"))
    elif violation == "empty_title":
        issues.append(GateIssue("P1", page.id, "Page has empty title"))
    elif violation == "empty_body":
        issues.append(GateIssue("P1", page.id, "Page body is empty"))
    elif violation == "placeholder":
        issues.append(GateIssue("P1", page.id, "Page body is a placeholder"))


def _check_p2_raw_paste(
    page: WikiPage,
    T_source: int | None,
    T_non: int | None,
    issues: list[GateIssue],
) -> None:
    """P2: no full-text sections; raw run ≤ threshold."""
    ts = T_source if T_source is not None else _DEFAULT_T_SOURCE
    tn = T_non if T_non is not None else _DEFAULT_T_NON
    raw_run = _long_raw_text_run(page.body)

    if page.type == PageType.SOURCE:
        if _has_fulltext_section(page.body):
            issues.append(GateIssue(
                "P2", page.id,
                "Source page contains a full-text / transcript section "
                "heading (正文内容/转录内容/原文/全文/完整文本) — "
                "raw text belongs in raw/sources/, not the wiki.",
            ))
        elif raw_run > ts:
            issues.append(GateIssue(
                "P2", page.id,
                f"Source page body has {raw_run}-char raw run "
                f"(threshold {ts}) — expected a distilled summary, "
                f"not a verbatim echo of the source.",
            ))
    else:
        if raw_run > tn:
            issues.append(GateIssue(
                "P2", page.id,
                f"Page body has {raw_run}-char unstructured run "
                f"(threshold {tn}) — possible raw paste.",
            ))


def _check_p3_missing_sources(page: WikiPage, issues: list[GateIssue]) -> None:
    """P3: every page must reference its raw source(s)."""
    if _missing_sources(page):
        issues.append(GateIssue(
            "P3", page.id,
            "Page has no sources and no derived_from / supported_by relation.",
        ))


def _check_p4_ugc_cred(page: WikiPage, issues: list[GateIssue]) -> None:
    """P4: 素材/ugc must be paired with 可信度/ugc."""
    if _missing_ugc_cred(page):
        issues.append(GateIssue(
            "P4", page.id,
            "Page tagged 素材/ugc but missing 可信度/ugc credibility tag.",
        ))


# ---------------------------------------------------------------------------
# Batch-level checks (P5–P7)
# ---------------------------------------------------------------------------


def check_batch(
    pages: list[WikiPage],
    raw_headers: dict[str, str] | None = None,
    extra_pages: list[WikiPage] | None = None,
    paths: WikiPaths | None = None,
    allow_overwrite: bool = False,
) -> list[GateIssue]:
    """Run P5–P7 across the full batch.

    Parameters
    ----------
    pages:
        All pages produced by this batch's generate step.
    raw_headers:
        ``{raw_path: first_4000_chars}`` for every raw file in the batch.
        Used for P5 input→source pairing and P4b UGC-carrier detection.
    extra_pages:
        Pre-existing pages touched by reverse relations.  Checked by P7.
    paths:
        WikiPaths for the project (needed for P7 stub check).
    allow_overwrite:
        If True, P7 downgrades from blocker to warning.

    Returns
    -------
    list[GateIssue]
        Batch-level violations.
    """
    issues: list[GateIssue] = []

    raw_to_pages: dict[str, list[WikiPage]] = {}
    for page in pages:
        for src in (page.sources or []):
            raw_to_pages.setdefault(src, []).append(page)

    _check_p4b_ugc_carrier(pages, raw_headers, issues)
    _check_p5_input_source_pair(pages, raw_to_pages, raw_headers, issues)
    _check_p6_slug_conflict(pages, issues)
    _check_p7_extra_pages(extra_pages, paths, allow_overwrite, issues)

    return issues


def _check_p5_input_source_pair(
    pages: list[WikiPage],
    raw_to_pages: dict[str, list[WikiPage]],
    raw_headers: dict[str, str] | None,
    issues: list[GateIssue],
) -> None:
    """P5: every raw input should have exactly one SOURCE page.

    Warning only (is_blocker=False) — Fix D in generate_ingest always
    appends a source page, so this fires only when something unusual
    happens (LLM source-page suppression, path mismatch).
    """
    raw_paths = set(raw_headers or {})
    if not raw_paths:
        return

    source_per_raw: dict[str, list[str]] = {}
    for page in pages:
        if page.type != PageType.SOURCE:
            continue
        for src in (page.sources or []):
            if src in raw_paths:
                source_per_raw.setdefault(src, []).append(page.id)

    for rp in sorted(raw_paths):
        src_pages = source_per_raw.get(rp, [])
        if len(src_pages) == 0:
            issues.append(GateIssue(
                "P5", None,
                f"Raw input {rp!r} has no corresponding SOURCE page "
                f"in the batch.",
                is_blocker=False,
            ))
        elif len(src_pages) > 1:
            issues.append(GateIssue(
                "P5", None,
                f"Raw input {rp!r} maps to {len(src_pages)} SOURCE "
                f"pages: {src_pages} — expected exactly one.",
                is_blocker=False,
            ))


def _check_p6_slug_conflict(
    pages: list[WikiPage],
    issues: list[GateIssue],
) -> None:
    """P6: no two pages may share the same slug with different types.

    Same slug + same type → this is the normal overwrite (generator
    re-creating an existing page).  Same slug + DIFFERENT type → the
    batch has produced two conflicting pages (e.g. an ENTITY and a
    CONCEPT with the same id).
    """
    slug_types: dict[str, PageType] = {}
    for page in pages:
        if not page.id:
            continue
        existing = slug_types.get(page.id)
        if existing is not None and existing != page.type:
            issues.append(GateIssue(
                "P6", page.id,
                f"Slug {page.id!r} appears with type {page.type.value} "
                f"but also with type {existing.value} in the same batch "
                f"— cross-type slug conflict.",
            ))
        slug_types[page.id] = page.type


def _check_p7_extra_pages(
    extra_pages: list[WikiPage] | None,
    paths: WikiPaths | None,
    allow_overwrite: bool,
    issues: list[GateIssue],
) -> None:
    """P7: extra_pages that would destructively overwrite pages → flag.

    Content-preservation judgment: a hit on an existing non-stub page is
    allowed when the extra page's body is unchanged from the on-disk body
    — that is a reverse-relation back-edge update (B13), where only
    ``relations`` differ.  A body change is a destructive overwrite and
    requires ``--allow-overwrite``.  Overwriting a stub page is by design
    (stub→real upgrade).
    """
    if not extra_pages or paths is None:
        return

    from ..storage.page_writer import page_path_for

    for ep in extra_pages:
        ep_path = page_path_for(paths, ep.type, ep.id)
        if not ep_path.exists():
            continue
        if ep.processing_depth == "stub":
            continue
        try:
            from ..storage.page_writer import read_page
            existing = read_page(ep_path)
            if existing.processing_depth == "stub":
                continue
            if existing.body == ep.body:
                # Body unchanged → reverse-relation back-edge update
                # (B13), not a destructive overwrite.  Allow it.
                continue
        except Exception:
            pass

        msg = (
            f"Extra page {ep.id!r} ({ep.type.value}) would overwrite "
            f"an existing non-stub page."
        )
        if allow_overwrite:
            issues.append(GateIssue("P7", ep.id, msg, is_blocker=False))
        else:
            issues.append(GateIssue("P7", ep.id, msg, is_blocker=True))


def _check_p4b_ugc_carrier(
    pages: list[WikiPage],
    raw_headers: dict[str, str] | None,
    issues: list[GateIssue],
) -> None:
    """P4b: every non-stub page derived from a UGC carrier raw must carry
    BOTH ``素材/ugc`` and ``可信度/ugc``.

    A raw file is a UGC carrier when its header (first ~4000 chars) matches
    :func:`src.wiki.features.lint._is_ugc_carrier`.  A derived page is one
    whose ``sources`` contains such a raw.  Missing either tag is a blocker
    (the phase4 auto-tag step is the deterministic fixer; this check is the
    defensive line so a batch can never write an untagged UGC page).
    """
    if not raw_headers:
        return
    carrier_raws = {
        raw for raw, header in raw_headers.items()
        if _is_ugc_carrier(header)
    }
    if not carrier_raws:
        return

    for page in pages:
        if getattr(page, "processing_depth", "") == "stub":
            continue
        if not (set(page.sources or []) & carrier_raws):
            continue
        tags = set(page.tags or [])
        missing = [
            tag for tag in ("素材/ugc", "可信度/ugc") if tag not in tags
        ]
        if missing:
            issues.append(GateIssue(
                "P4b", page.id,
                f"Page derived from UGC carrier raw(s) is missing tag(s): "
                f"{', '.join(missing)}.",
                is_blocker=True,
            ))


# ---------------------------------------------------------------------------
# Convenience: run all checks
# ---------------------------------------------------------------------------


def run_ndg_gate(
    pages: list[WikiPage],
    raw_headers: dict[str, str] | None = None,
    extra_pages: list[WikiPage] | None = None,
    paths: WikiPaths | None = None,
    *,
    T_source: int | None = None,
    T_non: int | None = None,
    allow_overwrite: bool = False,
) -> GateReport:
    """Run the NDG gate on a batch.

    Batch-level structural checks (P5 input→source pairing, P6
    slug-conflict, P7 extra-page overwrite protection) keep their existing
    block semantics.  Per-page quality checks (P1 readability, P2
    raw-paste, P3 missing-sources, P4 ugc-cred) are additionally surfaced
    as **warnings** (``is_blocker=False``) so page quality is visible at
    write time — they never block the batch (``cli lint`` remains the
    authoritative quality gate).

    ``T_source`` / ``T_non`` tune the P2 RAW-PASTE threshold and fall back
    to the module defaults (:data:`_DEFAULT_T_SOURCE` / :data:`_DEFAULT_T_NON`).

    Returns a :class:`GateReport` whose ``passed`` attribute is ``True``
    only when zero blocker issues were found.
    """
    all_issues: list[GateIssue] = []

    all_issues.extend(
        check_batch(pages, raw_headers, extra_pages, paths,
                    allow_overwrite=allow_overwrite)
    )

    # R5-2 / F9: surface per-page P1–P4 as warnings — write-time
    # visibility into page quality without changing block semantics.
    for page in pages:
        for issue in check_page(page, T_source=T_source, T_non=T_non):
            all_issues.append(replace(issue, is_blocker=False))

    return _build_report(all_issues, len(pages))
