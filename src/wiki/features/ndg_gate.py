"""NDG gate — per-page + batch-level quality checks (P1–P7 + P4b).

Consumes :mod:`src.wiki.features.lint` exported symbols so the gate and
``cli lint`` never diverge.  All checks are deterministic (zero LLM cost).

Checks
------
**Per-page (P1–P4):** run on every page in the batch.

P1  READABILITY       body is non-empty and the page can be parsed
P2  RAW-PASTE         no full-text section heading; raw run ≤ threshold
P3  MISSING-SOURCES   ``sources`` is non-empty OR has derivation relation
P4  UGC-CRED          ``素材/ugc`` → must also carry ``可信度/ugc``

**Batch-level (P4b, P5–P7):** run once across the whole batch.

P4b UGC-SOURCE-TAG    raw file is UGC → every derived page MUST carry
                       ``素材/ugc`` + ``可信度/ugc``
P5  INPUT-SOURCE-PAIR  every raw input has a corresponding SOURCE page
P6  SLUG-CONFLICT      no two pages share the same slug with different types
P7  EXTRA-PAGES        extra_pages that would overwrite existing non-stub
                       pages → flag (unless ``--allow-overwrite``)

Usage (library)
---------------
>>> from src.wiki.features.ndg_gate import check_page, check_batch, GateReport
>>> issues_p14 = check_page(page, is_ugc_source=False)
>>> issues_p4bp7 = check_batch(pages, raw_headers, paths)
>>> report = GateReport(issues_p14 + issues_p4bp7)

Usage (CLI)
-----------
    python scripts/batch_gate_check.py <wiki_root> <page1.md> [page2.md ...]
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..core.types import PageType, WikiPage
from ..core.paths import WikiPaths
from .lint import (
    _has_fulltext_section,
    _long_raw_text_run,
    _load_raw_paste_thresholds,
    _DEFAULT_T_SOURCE,
    _DEFAULT_T_NON,
)

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# UGC source markers (D1 — deterministic, no LLM)
# ---------------------------------------------------------------------------
# When the first 4000 chars of a raw file contain one of these markers the
# file is classified as UGC and every page derived from it MUST carry both
# ``素材/ugc`` and ``可信度/ugc`` tags.
_UGC_MARKERS = (
    "feishu.cn",
    "mp.weixin.qq.com",
    "飞书云文档",
    "公众号",
    "论坛",
    "知乎",
    "豆瓣",
    "简书",
    "QQ群",
)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class GateIssue:
    """A single NDG gate violation."""

    code: str            # "P1" … "P7", "P4b"
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
# UGC source detection (P4b helper)
# ---------------------------------------------------------------------------


def is_ugc_source(raw_header: str) -> bool:
    """True if *raw_header* contains a known UGC carrier marker.

    *raw_header* should be the first ~4000 characters of the raw file.
    """
    return any(marker in raw_header for marker in _UGC_MARKERS)


# ---------------------------------------------------------------------------
# Per-page checks (P1–P4)
# ---------------------------------------------------------------------------


def check_page(
    page: WikiPage,
    is_ugc_source: bool = False,
    T_source: int | None = None,
    T_non: int | None = None,
) -> list[GateIssue]:
    """Run P1–P4 on a single page.

    Parameters
    ----------
    page:
        The WikiPage to check.
    is_ugc_source:
        True when the raw file this page derives from is a known UGC
        carrier (P4b context — the batch runner sets this flag).
    T_source / T_non:
        RAW-PASTE thresholds.  When *None*, loaded from the project
        quality-settings file via :func:`_load_raw_paste_thresholds`
        (which falls back to internal constants).

    Returns
    -------
    list[GateIssue]
        Violations found (empty → pass).
    """
    issues: list[GateIssue] = []

    # ── P1: READABILITY ──────────────────────────────────────────
    _check_p1_readability(page, issues)

    # ── P2: RAW-PASTE ────────────────────────────────────────────
    _check_p2_raw_paste(page, T_source, T_non, issues)

    # ── P3: MISSING-SOURCES ──────────────────────────────────────
    _check_p3_missing_sources(page, issues)

    # ── P4: UGC-CRED (per-page tag consistency) ──────────────────
    _check_p4_ugc_cred(page, issues)

    # ── P4b: UGC-SOURCE-TAG (raw-level enforcement) ──────────────
    _check_p4b_ugc_source_tag(page, is_ugc_source, issues)

    return issues


def _check_p1_readability(page: WikiPage, issues: list[GateIssue]) -> None:
    """P1: page must have non-empty id, title, and body."""
    if not page.id or not page.id.strip():
        issues.append(GateIssue("P1", None, "Page has empty id"))
    elif not page.title or not page.title.strip():
        issues.append(GateIssue("P1", page.id, "Page has empty title"))
    elif not page.body or not page.body.strip():
        issues.append(GateIssue("P1", page.id, "Page body is empty"))
    elif page.body.strip() in (
        "(empty)", "(无内容)", "(占位)", "(placeholder)",
    ):
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
        # Check 1: fulltext-section heading (unconditional flag).
        if _has_fulltext_section(page.body):
            issues.append(GateIssue(
                "P2", page.id,
                "Source page contains a full-text / transcript section "
                "heading (正文内容/转录内容/原文/全文/完整文本) — "
                "raw text belongs in raw/sources/, not the wiki.",
            ))
        # Check 2: long raw run past source threshold.
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
    rel_types = {
        r.type if isinstance(r.type, str) else r.type.value
        for r in (page.relations or [])
    }
    if not page.sources and not (rel_types & {"derived_from", "supported_by"}):
        issues.append(GateIssue(
            "P3", page.id,
            "Page has no sources and no derived_from / supported_by relation.",
        ))


def _check_p4_ugc_cred(page: WikiPage, issues: list[GateIssue]) -> None:
    """P4: 素材/ugc must be paired with 可信度/ugc."""
    if "素材/ugc" in page.tags and "可信度/ugc" not in page.tags:
        issues.append(GateIssue(
            "P4", page.id,
            "Page tagged 素材/ugc but missing 可信度/ugc credibility tag.",
        ))


def _check_p4b_ugc_source_tag(
    page: WikiPage,
    is_ugc_source: bool,
    issues: list[GateIssue],
) -> None:
    """P4b: if the raw source is UGC, the page MUST carry both tags.

    .. note::

        *Known residual* — raw files that are genuinely UGC but whose
        headers do NOT contain any ``_UGC_MARKERS`` substring will not
        set ``is_ugc_source`` and this check will be skipped.  These
        are documented as a known gap; do not pretend coverage.
    """
    if not is_ugc_source:
        return
    missing = []
    if "素材/ugc" not in page.tags:
        missing.append("素材/ugc")
    if "可信度/ugc" not in page.tags:
        missing.append("可信度/ugc")
    if missing:
        issues.append(GateIssue(
            "P4b", page.id,
            f"Raw source is UGC but page is missing required tag(s): "
            f"{', '.join(missing)}.",
        ))


# ---------------------------------------------------------------------------
# Batch-level checks (P4b context, P5–P7)
# ---------------------------------------------------------------------------


def check_batch(
    pages: list[WikiPage],
    raw_headers: dict[str, str] | None = None,
    extra_pages: list[WikiPage] | None = None,
    paths: WikiPaths | None = None,
    allow_overwrite: bool = False,
) -> list[GateIssue]:
    """Run P5–P7 (and UGC context) across the full batch.

    Parameters
    ----------
    pages:
        All pages produced by this batch's generate step.
    raw_headers:
        ``{raw_path: first_4000_chars}`` for every raw file in the batch.
        Used for P4b UGC-source detection.
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

    # Build a raw→pages index so we can answer "which pages derive
    # from this raw file?" for P4b and P5.
    raw_to_pages: dict[str, list[WikiPage]] = {}
    for page in pages:
        for src in (page.sources or []):
            raw_to_pages.setdefault(src, []).append(page)

    # ── P4b: UGC-source tag enforcement (batch context) ──────────
    if raw_headers:
        for raw_path, header in raw_headers.items():
            if is_ugc_source(header):
                derived = raw_to_pages.get(raw_path, [])
                for page in derived:
                    _check_p4b_ugc_source_tag(page, True, issues)

    # ── P5: INPUT-SOURCE-PAIR ────────────────────────────────────
    _check_p5_input_source_pair(pages, raw_to_pages, raw_headers, issues)

    # ── P6: SLUG-CONFLICT ────────────────────────────────────────
    _check_p6_slug_conflict(pages, issues)

    # ── P7: EXTRA-PAGES ──────────────────────────────────────────
    _check_p7_extra_pages(extra_pages, paths, allow_overwrite, issues)

    return issues


def _check_p5_input_source_pair(
    pages: list[WikiPage],
    raw_to_pages: dict[str, list[WikiPage]],
    raw_headers: dict[str, str] | None,
    issues: list[GateIssue],
) -> None:
    """P5: every raw input must have exactly one SOURCE page."""
    raw_paths = set(raw_headers or {})
    if not raw_paths:
        return

    # Count source pages that reference each raw path
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
            ))
        elif len(src_pages) > 1:
            issues.append(GateIssue(
                "P5", None,
                f"Raw input {rp!r} maps to {len(src_pages)} SOURCE "
                f"pages: {src_pages} — expected exactly one.",
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
    """P7: extra_pages that would overwrite non-stub pages → flag.

    Overwriting a stub page is by design (stub→real upgrade).
    Overwriting a non-stub page requires ``--allow-overwrite``.
    """
    if not extra_pages or paths is None:
        return

    from ..storage.page_writer import page_path_for

    for ep in extra_pages:
        ep_path = page_path_for(paths, ep.type, ep.id)
        if not ep_path.exists():
            continue
        # Stub overwrite is always OK.
        if ep.processing_depth == "stub":
            continue
        # Check if the on-disk page is a stub.
        try:
            from ..storage.page_writer import read_page
            existing = read_page(ep_path)
            if existing.processing_depth == "stub":
                continue  # stub → real upgrade
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
    """Run the full NDG gate (P1–P7 + P4b) on a batch.

    Returns a :class:`GateReport` whose ``passed`` attribute is ``True``
    only when zero blocker issues were found.
    """
    all_issues: list[GateIssue] = []

    # Per-page checks (P1–P4 + P4b).  P4b needs per-raw UGC context:
    # precompute a {raw_path: is_ugc} lookup from the headers.
    ugc_raw: set[str] = set()
    if raw_headers:
        for rp, hdr in raw_headers.items():
            if is_ugc_source(hdr):
                ugc_raw.add(rp)

    for page in pages:
        _is_ugc = any(src in ugc_raw for src in (page.sources or []))
        all_issues.extend(check_page(page, is_ugc_source=_is_ugc,
                                     T_source=T_source, T_non=T_non))

    # Batch-level checks (P5–P7).
    all_issues.extend(
        check_batch(pages, raw_headers, extra_pages, paths,
                    allow_overwrite=allow_overwrite)
    )

    return _build_report(all_issues, len(pages))
