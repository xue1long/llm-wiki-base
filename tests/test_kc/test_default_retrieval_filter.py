"""Tests for Default Retrieval Filter (路线 v2.2 §C-2 / G2).

5 TDD tests covering:

1. ``DefaultFilter`` passes on a verified + current WikiPage (spec §12.1 happy path).
2. ``DefaultFilter`` rejects a candidate page (spec §11.4 #1 错误注入 — Unsupported Fact
   countermeasure: candidates must not enter default retrieval).
3. ``DefaultFilter`` rejects a quarantined page (spec §11.4 #2 错误注入 — Critical
   Evidence Missing countermeasure: quarantined pages must not surface).
4. ``DefaultFilter`` rejects a rejected page (spec §11.3 closed-loop — REJECTED is a
   terminal KO lifecycle and must never enter default retrieval).
5. ``DefaultFilter`` rejects a disputed page by default; an explicit
   ``include_disputed=True`` opt-in surfaces it (spec §11.4 closed-loop semantics).

These tests are intentionally independent of the implementation file
(``src/kc.retrieval.filter``): until that module ships, every test in this file
must FAIL with ``ImportError`` or ``ModuleNotFoundError``. After the module
ships, all 5 must pass.
"""
from __future__ import annotations

import time

import pytest

from src.wiki.core.types import PageType, WikiPage

# NB: src.kc.retrieval.filter is the module under test — it does not exist yet
# at the time these tests are authored, so the import below is the red signal
# that kicks off TDD step 2.
from src.kc.retrieval.filter import DefaultFilter, apply_default_filter


# ── helpers ─────────────────────────────────────────────────────────────────


def _now_ms() -> int:
    """Return the current Unix time in milliseconds."""
    return int(time.time() * 1000)


def make_wiki_page(
    workflow_state: str = "draft",
    custom_lifecycle: str | None = None,
    evidence_refs: list[str] | None = None,
    closure_passed: bool | None = True,
    **kwargs,
) -> WikiPage:
    """Build a test WikiPage with the given workflow_state.

    ``custom_lifecycle`` is injected via ``_ko_extra`` (the WikiPage-side
    legacy KO bag), e.g. ``CANDIDATE`` / ``QUARANTINED`` / ``REJECTED`` /
    ``DISPUTED``. These are spec §11.4 categories, not WikiPage native
    fields — they're carried by the parallel KO model and surface on the
    page through the ``_ko_extra`` channel.
    """
    page = WikiPage(
        id=kwargs.get("id", "test_001"),
        title=kwargs.get("title", "test"),
        type=PageType(kwargs.get("type", "concept")),
        evidence_refs=list(
            ["doc_001:block_001"] if evidence_refs is None else evidence_refs
        ),
    )
    page.workflow_state = workflow_state
    if custom_lifecycle is not None or closure_passed is not None:
        # WikiPage has no native lifecycle field; spec §11.4 error-injection
        # categories ride on the KO ``_ko_extra`` bag (mirrors C-0 Commit 2
        # migration of decision_record and C-0 Commit 4 of evidence_refs).
        # The attribute is normally only set by WikiPage.from_dict(); we
        # use setattr so the helper works on fresh WikiPage instances.
        existing = getattr(page, "_ko_extra", None) or {}
        page._ko_extra = dict(existing)
        if custom_lifecycle is not None:
            page._ko_extra["lifecycle"] = custom_lifecycle
        if closure_passed is not None:
            page._ko_extra["closure_report"] = {"passed": closure_passed}
    return page


# ── test 1: verified + current → True ──────────────────────────────────────


def test_default_filter_passes_verified_current_page() -> None:
    """DefaultFilter passes a verified + current WikiPage (spec §12.1)."""
    page = make_wiki_page(workflow_state="verified")
    f = DefaultFilter()
    assert f.passes(page, query_time=_now_ms()) is True


# ── test 2: candidate → False (error injection: Unsupported Fact counter) ──


def test_default_filter_rejects_candidate_page() -> None:
    """DefaultFilter rejects a candidate page (spec §11.4 #1 错误注入).

    A page in CANDIDATE state must never surface in default retrieval, even
    if its workflow_state would otherwise be a candidate — this is the
    primary defence against the Unsupported Fact error class.
    """
    page = make_wiki_page(
        workflow_state="draft",
        custom_lifecycle="CANDIDATE",
    )
    f = DefaultFilter()
    assert f.passes(page, query_time=_now_ms()) is False


# ── test 3: quarantined → False (error injection: Critical Evidence Missing) ─


def test_default_filter_rejects_quarantined_page() -> None:
    """DefaultFilter rejects a quarantined page (spec §11.4 #2 错误注入).

    Quarantined pages are the primary defence against Critical Evidence
    Missing: they hold content whose evidence is missing, so the filter
    must keep them out of the default result set.
    """
    page = make_wiki_page(
        workflow_state="verified",
        custom_lifecycle="QUARANTINED",
    )
    f = DefaultFilter()
    assert f.passes(page, query_time=_now_ms()) is False


# ── test 4: rejected → False ───────────────────────────────────────────────


def test_default_filter_rejects_rejected_page() -> None:
    """DefaultFilter rejects a REJECTED page (spec §11.3 closed-loop).

    REJECTED is a terminal KO lifecycle state; even when its
    workflow_state says verified (a malformed legacy combination), the
    REJECTED flag must dominate and keep the page out of default
    retrieval.
    """
    page = make_wiki_page(
        workflow_state="verified",
        custom_lifecycle="REJECTED",
    )
    f = DefaultFilter()
    assert f.passes(page, query_time=_now_ms()) is False


# ── test 5: disputed default → False; include_disputed=True → True ──────────


def test_default_filter_rejects_disputed_page_by_default() -> None:
    """DefaultFilter hides disputed pages by default; explicit opt-in surfaces them.

    spec §11.3 default-published-closure does not include DISPUTED in the
    status subset, so the default behaviour is to exclude. An explicit
    ``include_disputed=True`` flips the gate, matching the spec §11.4
    "explicit query" semantics.
    """
    page = make_wiki_page(
        workflow_state="verified",
        custom_lifecycle="DISPUTED",
    )

    f_default = DefaultFilter()
    assert f_default.passes(page, query_time=_now_ms()) is False

    f_explicit = DefaultFilter(include_disputed=True)
    assert f_explicit.passes(page, query_time=_now_ms()) is True


# ── bonus: helper-level filter over a list of pages ─────────────────────────


def test_apply_default_filter_drops_candidate_and_quarantined() -> None:
    """``apply_default_filter`` helper drops candidate + quarantined, keeps verified.

    This is the integration seam test for the helper that ``hybrid_search``
    will eventually call in step-3 follow-up; it is included here so the
    list-level contract is locked in independently of the keyword-path
    integration.
    """
    pages = [
        make_wiki_page(id="p1", workflow_state="verified"),
        make_wiki_page(id="p2", workflow_state="draft", custom_lifecycle="CANDIDATE"),
        make_wiki_page(id="p3", workflow_state="verified", custom_lifecycle="QUARANTINED"),
        make_wiki_page(id="p4", workflow_state="verified", custom_lifecycle="DISPUTED"),
        make_wiki_page(id="p5", workflow_state="ready"),  # not verified → drop
    ]
    kept = apply_default_filter(pages, query_time=_now_ms())
    kept_ids = [p.id for p in kept]
    assert kept_ids == ["p1"]


def test_default_filter_rejects_verified_page_without_evidence_refs() -> None:
    """Verified page with no evidence refs must not surface by default."""
    page = make_wiki_page(
        workflow_state="verified",
        evidence_refs=[],
    )

    f = DefaultFilter()
    assert f.passes(page, query_time=_now_ms()) is False


def test_default_filter_rejects_verified_page_without_passing_closure_report() -> None:
    """Verified page without a passing closure report must not surface by default."""
    page = make_wiki_page(
        workflow_state="verified",
        closure_passed=False,
    )

    f = DefaultFilter()
    assert f.passes(page, query_time=_now_ms()) is False


def test_default_filter_rejects_truthy_non_boolean_closure_state() -> None:
    page = make_wiki_page(workflow_state="verified")
    page._ko_extra["closure_report"] = {"passed": "false"}

    assert DefaultFilter().passes(page, query_time=_now_ms()) is False
