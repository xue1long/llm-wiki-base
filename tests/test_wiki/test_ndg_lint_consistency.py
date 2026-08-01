"""NDG Phase 6 (single source of truth): gate P1/P3/P4 must agree with lint.

These tests lock in the invariant that the NDG gate's per-page checks
(P1 readability, P3 missing-sources, P4 UGC-cred) and the ``cli lint``
checks (LINT-*-ID/TITLE/BODY, LINT-MISSING-SOURCES, LINT-UGC-CRED) share
the same *decision logic* — the gate must consume lint's exported
predicates, not a parallel re-implementation.

Each test builds a page, runs it through both the gate (check_page) and
the lint predicates, and asserts they agree.
"""
import pytest

from src.wiki.core.types import PageType, WikiPage
from src.wiki.features.relations import Relation
from src.wiki.features.ndg_gate import check_page
from src.wiki.features import lint


def _gate_has(page, code: str) -> bool:
    return any(i.code == code for i in check_page(page))


def _lint_has(page, codes: set[str]) -> bool:
    """Run the lint page predicates and return whether any of *codes* fired."""
    result = []
    if lint._readability_violation(page) is not None:
        result.append("READABILITY")
    if lint._missing_sources(page):
        result.append("MISSING-SOURCES")
    if lint._missing_ugc_cred(page):
        result.append("UGC-CRED")
    return bool(set(result) & codes)


# ---------------------------------------------------------------------------
# P1 READABILITY vs LINT id/title/body
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("page", [
    WikiPage(id="", title="T", type=PageType.ENTITY, body="x"),
    WikiPage(id="x", title="", type=PageType.ENTITY, body="x"),
    WikiPage(id="x", title="T", type=PageType.ENTITY, body=""),
    WikiPage(id="x", title="T", type=PageType.ENTITY, body="(empty)"),
    WikiPage(id="x", title="T", type=PageType.ENTITY, body="(placeholder)"),
    WikiPage(id="x", title="T", type=PageType.ENTITY, body="   "),
])
def test_p1_readability_agrees_with_lint(page):
    gate = _gate_has(page, "P1")
    lint_ = _lint_has(page, {"READABILITY"})
    assert gate == lint_, (
        f"gate P1={gate} but lint READABILITY={lint_} for {page.id!r}/{page.title!r}"
    )


def test_p1_clean_agrees_with_lint():
    page = WikiPage(id="x", title="T", type=PageType.ENTITY, body="content.")
    assert not _gate_has(page, "P1")
    assert not _lint_has(page, {"READABILITY"})


# ---------------------------------------------------------------------------
# P3 MISSING-SOURCES vs LINT-MISSING-SOURCES
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("page", [
    WikiPage(id="x", title="X", type=PageType.CONCEPT, body="content"),
    WikiPage(id="x", title="X", type=PageType.CONCEPT, body="c",
             sources=["raw/a.md"]),
    WikiPage(id="x", title="X", type=PageType.CONCEPT, body="c",
             relations=[Relation(target_id="src-a", type="derived_from")]),
    WikiPage(id="x", title="X", type=PageType.CONCEPT, body="c",
             relations=[Relation(target_id="b", type="supported_by")]),
    WikiPage(id="x", title="X", type=PageType.CONCEPT, body="c",
             relations=[Relation(target_id="b", type="related_to")]),
])
def test_p3_missing_sources_agrees_with_lint(page):
    gate = _gate_has(page, "P3")
    lint_ = _lint_has(page, {"MISSING-SOURCES"})
    assert gate == lint_, (
        f"gate P3={gate} but lint MISSING-SOURCES={lint_} for {page.id!r}"
    )


# ---------------------------------------------------------------------------
# P4 UGC-CRED vs LINT-UGC-CRED
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("page", [
    WikiPage(id="u", title="U", type=PageType.CONCEPT, body="c",
             tags=["素材/ugc"], sources=["a.md"]),
    WikiPage(id="u", title="U", type=PageType.CONCEPT, body="c",
             tags=["素材/ugc", "可信度/ugc"], sources=["a.md"]),
    WikiPage(id="u", title="U", type=PageType.CONCEPT, body="c",
             tags=["题材/玄幻"], sources=["a.md"]),
    WikiPage(id="u", title="U", type=PageType.CONCEPT, body="c",
             tags=[], sources=["a.md"]),
])
def test_p4_ugc_cred_agrees_with_lint(page):
    gate = _gate_has(page, "P4")
    lint_ = _lint_has(page, {"UGC-CRED"})
    assert gate == lint_, (
        f"gate P4={gate} but lint UGC-CRED={lint_} for {page.id!r}"
    )
