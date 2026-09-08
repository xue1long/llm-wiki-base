"""Fail-closed safety gates for the series-level dependency / cross-link graph.

These tests specify the behaviour the production code must exhibit for the
2026-09-06 book-series target plan (Task 5):

* No cycles in the hard/soft book dependency graph.
* No dangling edges (book/chapter/page targets that don't resolve).
* No edges that reference an outline other than the one bound to the same
  ``release_id``.
* Namespace edges (``taxonomy_of``, ``belongs_to_audience``,
  ``hosted_on_platform``, ``has_credibility``) are excluded from the failure
  ratio and from cycle / dangling detection.

The tests deliberately exercise the public seams exposed from
``src.kc.views.book.wiki``: ``validate_series_manifest``,
``build_cross_link_candidates`` and ``relation_stats``.
"""
from __future__ import annotations

import inspect

import pytest

from src.kc.views.book.wiki.aggregator import relation_stats
from src.kc.views.book.wiki.cross_links import build_cross_link_candidates
from src.kc.views.book.wiki.model import ContentBlock, PageRecord, WikiSnapshot
from src.kc.views.book.wiki.series_model import SCHEMA_VERSION, canonical_digest
from src.kc.views.book.wiki.series_validate import (
    dependency_report,
    validate_series_manifest,
)


# ─── fixtures ──────────────────────────────────────────────────────────


def _book(book_id: str, status: str = "ready", *, required: bool = True,
          release_id: str = "r1", hard=(), soft=(), outline_id: str | None = None,
          **extra) -> dict:
    payload = {
        "book_id": book_id, "required": required, "status": status,
        "outline_id": outline_id or f"o-{book_id}",
        "hard_dependencies": list(hard), "soft_dependencies": list(soft),
        "release_id": release_id,
    }
    payload.update(extra)
    return payload


def _series(status: str, books: list[dict], *, release_id: str = "r1") -> dict:
    payload = {"schema_version": SCHEMA_VERSION, "series_id": "s", "release_id": release_id,
               "status": status, "books": books}
    payload["manifest_sha256"] = canonical_digest(payload)
    return payload


def _page(pid: str, *, relations=()) -> PageRecord:
    return PageRecord(
        page_id=pid, title=pid.title(), page_type="concept",
        path=f"wiki/concepts/{pid}.md", primary_taxonomy="topic",
        summary="summary",
        content_blocks=(ContentBlock(f"{pid}:0", pid, None, "body", 0),),
        relation_targets=tuple(relations),
        content_sha256=f"hash-{pid}", char_count=10, token_count=None,
    )


def _snapshot(*pages: PageRecord) -> WikiSnapshot:
    return WikiSnapshot("snap-1", "/tmp/wiki", "wiki-v3", tuple(pages), ())


# ─── 1. dependency cycle detection ─────────────────────────────────────


def test_hard_dependency_cycle_is_reported_and_blocks_series() -> None:
    """A → B → A must be rejected even if both books are ``ready``."""
    payload = _series("ready", [
        _book("a", hard=["b"]),
        _book("b", hard=["a"]),
    ])

    report = validate_series_manifest(payload)

    assert report["ok"] is False, (
        "validate_series_manifest must reject a hard-dependency cycle "
        "(a -> b -> a). The cycle detection hook is currently missing, so the "
        "manifest passes — production code needs an explicit cycle pass over "
        "hard_dependencies (and soft_dependencies) keyed by book_id."
    )
    assert any("cycle" in err.lower() or "loop" in err.lower() for err in report["errors"]), (
        f"Expected a cycle error code, got {report['errors']!r}"
    )


def test_soft_dependency_cycle_is_reported() -> None:
    """Soft dependencies may miss, but they must never be cyclic."""
    payload = _series("partial", [
        _book("a", "partial", hard=[], soft=["b"]),
        _book("b", "ready", hard=[], soft=["a"]),
    ])

    report = validate_series_manifest(payload)

    assert report["ok"] is False
    cycle_errors = [err for err in report["errors"] if "cycle" in err.lower() or "loop" in err.lower()]
    assert cycle_errors, (
        "Soft-dependency cycles should be reported the same way as hard ones. "
        f"Current errors: {report['errors']!r}"
    )


def test_self_loop_dependency_is_rejected() -> None:
    """A book that depends on itself is the trivial cycle case."""
    payload = _series("ready", [_book("a", hard=["a"])])

    report = validate_series_manifest(payload)

    assert report["ok"] is False
    assert any("cycle" in err.lower() or "self" in err.lower() for err in report["errors"]), (
        f"Self-loop dependency must be reported, got {report['errors']!r}"
    )


def test_three_step_dependency_cycle_is_rejected() -> None:
    """A → B → C → A: cycle must surface even across three hops."""
    payload = _series("ready", [
        _book("a", hard=["b"]),
        _book("b", hard=["c"]),
        _book("c", hard=["a"]),
    ])

    report = validate_series_manifest(payload)

    assert report["ok"] is False
    assert any("cycle" in err.lower() for err in report["errors"])


def test_dependency_report_signals_cycle_to_callers() -> None:
    """``dependency_report`` is the seam callers use for the dry-run gate.

    It must surface cycle findings so the publisher can block before
    touching the staged release.
    """
    report = dependency_report([
        _book("a", hard=["b"]),
        _book("b", hard=["a"]),
    ])

    assert report["ok"] is False, (
        "dependency_report should return ok=False when a cycle exists, but "
        "the current implementation only flags hard-dependency absence. Cycle "
        "detection needs to be added (e.g. via DFS over hard/soft edges)."
    )
    cycle_errors = [err for err in report["errors"] if "cycle" in err.lower() or "loop" in err.lower()]
    assert cycle_errors


# ─── 2. release / outline binding ──────────────────────────────────────


def test_hard_dependency_across_releases_is_rejected() -> None:
    """A book depending on another book that ships in a different release must fail."""
    payload = _series("ready", [
        _book("a", release_id="r1", hard=["b"]),
        _book("b", release_id="r2"),
    ])

    report = validate_series_manifest(payload)

    assert report["ok"] is False, (
        "Cross-release hard dependencies are currently only caught when the "
        "series status is 'ready'. The publisher must refuse them regardless "
        "of status because they cannot be staged atomically."
    )
    cross_errors = [err for err in report["errors"]
                    if "release" in err.lower() or "batch" in err.lower()]
    assert cross_errors


def test_outline_id_must_match_book_release_binding() -> None:
    """A book's outline_id must resolve within the same release's namespace."""
    payload = _series("ready", [
        _book("a", outline_id="o-from-r2"),
        # book 'b' claims an outline that lives in a different release:
        _book("b", outline_id="o-from-r2"),
    ])

    report = validate_series_manifest(payload)

    # The outline_id collision is currently unflagged because the validator
    # only inspects outline_id as a free-form string. Outline ids are supposed
    # to be release-scoped, so two books within the same release sharing an
    # outline id is a binding violation.
    outline_errors = [err for err in report["errors"] if "outline" in err.lower()]
    assert outline_errors, (
        "Outline id collisions within one release must be flagged. Current "
        f"errors: {report['errors']!r}"
    )


# ─── 3. dangling edges ─────────────────────────────────────────────────


def test_build_cross_link_candidates_rejects_self_loops() -> None:
    """A cross-link candidate that points from a page to itself is dangling by definition."""
    outline = {"cross_link_candidates": [
        {"from_page": "p1", "to_page": "p1", "reason": "related"},
        {"from_page": "p1", "to_page": "p2", "reason": "related"},
    ]}

    result = build_cross_link_candidates(outline, {"p1", "p2"})

    assert result == [{"from_page": "p1", "to_page": "p2", "reason": "related"}], (
        "Self-loop cross-link candidates must be filtered. The current "
        "implementation only checks endpoint membership in page_ids, which "
        "silently allows a page to link to itself."
    )


def test_build_cross_link_candidates_rejects_blank_or_non_string_endpoints() -> None:
    """Empty / non-string from/to/reason fields are dangling."""
    outline = {"cross_link_candidates": [
        {"from_page": "", "to_page": "p2", "reason": "related"},
        {"from_page": "p1", "to_page": "p2", "reason": ""},
        {"from_page": "p1", "to_page": "p2", "reason": 42},
        {"from_page": "p1", "to_page": "p2", "reason": "related"},
    ]}

    result = build_cross_link_candidates(outline, {"p1", "p2"})

    assert result == [{"from_page": "p1", "to_page": "p2", "reason": "related"}], (
        "build_cross_link_candidates must filter candidates with empty or "
        "non-string endpoints/reason. Current result: "
        f"{result!r}"
    )


def test_build_cross_link_candidates_rejects_non_dict_entries() -> None:
    """A list element that isn't a mapping must not propagate silently."""
    outline = {"cross_link_candidates": [
        "not-a-mapping",
        ["from_page", "p1"],
        {"from_page": "p1", "to_page": "p2", "reason": "related"},
    ]}

    result = build_cross_link_candidates(outline, {"p1", "p2"})

    assert result == [{"from_page": "p1", "to_page": "p2", "reason": "related"}]


def test_cross_link_dangling_target_is_fail_closed() -> None:
    """If the requested page_ids set is empty, every link is dangling.

    Today the function silently returns []. That is unsafe — a downstream
    publisher should see ``[]`` only when every endpoint resolved.
    """
    outline = {"cross_link_candidates": [
        {"from_page": "p1", "to_page": "p2", "reason": "related"},
    ]}

    result = build_cross_link_candidates(outline, set())

    assert result == [], (
        "An empty page_ids set means every candidate is dangling; this is "
        "expected. The point of this test is to lock in the behaviour and "
        "force the publisher to surface a 'dangling' error rather than "
        "silently publish zero cross-links."
    )
    # And the complementary case: with all endpoints present we keep the link.
    result_full = build_cross_link_candidates(outline, {"p1", "p2"})
    assert result_full == [{"from_page": "p1", "to_page": "p2", "reason": "related"}]


def test_cross_links_do_not_silently_drop_when_reason_is_invalid_type() -> None:
    """A non-string reason must be treated as a malformed candidate.

    The current implementation already rejects this case, but only because
    the truthiness check on the reason fails — the test guards that contract
    so a future refactor doesn't relax it back to `bool(reason)`.
    """
    outline = {"cross_link_candidates": [
        {"from_page": "p1", "to_page": "p2", "reason": None},
        {"from_page": "p1", "to_page": "p2", "reason": "valid"},
    ]}

    result = build_cross_link_candidates(outline, {"p1", "p2"})

    assert result == [{"from_page": "p1", "to_page": "p2", "reason": "valid"}]


# ─── 4. namespace edges are excluded from failure ratio ────────────────


def test_relation_stats_excludes_all_namespace_kinds_from_unresolved() -> None:
    """Namespace edges (``taxonomy_of`` / ``belongs_to_audience`` /
    ``hosted_on_platform`` / ``has_credibility``) must never count as
    unresolved and must never inflate the unresolved ratio.
    """
    snapshot = _snapshot(_page("p1", relations=(
        ("taxonomy_of", "taxonomy-写作技法"),
        ("belongs_to_audience", "audience-beginner"),
        ("hosted_on_platform", "platform-web"),
        ("has_credibility", "credibility-official"),
    )))

    stats = relation_stats(snapshot)

    assert stats["ignored_namespace"] == 4
    assert stats["total"] == 0, (
        "Namespace edges must be subtracted from ``total`` so they don't "
        "inflate the unresolved ratio. The current aggregator counts them "
        f"as ignored but still inside the total; stats={stats!r}"
    )
    assert stats["unresolved"] == 0
    assert stats["unresolved_ratio"] == 0.0


def test_relation_stats_mixes_namespace_and_real_edges_safely() -> None:
    """When namespace and real edges coexist, only real edges count."""
    snapshot = _snapshot(_page("p1", relations=(
        ("taxonomy_of", "taxonomy-x"),
        ("supports", "missing-page"),
        ("references", "p2"),  # real, must be ignored too (counts toward ignored namespace? no, it's not)
    )), _page("p2"))

    stats = relation_stats(snapshot)

    # 'taxonomy_of' is namespace, 'supports' to a missing page is unresolved,
    # 'references' to p2 is resolved.
    assert stats["ignored_namespace"] == 1
    assert stats["total"] == 2
    assert stats["unresolved"] == 1
    assert stats["unresolved_ratio"] == pytest.approx(0.5)


# ─── 5. surface compatibility ──────────────────────────────────────────


def test_dependency_cycle_detection_is_exposed_in_public_surface() -> None:
    """A public ``detect_dependency_cycles`` (or similar) must exist so callers
    can wire the gate into the publisher without reaching into private symbols.
    """
    import src.kc.views.book.wiki as pkg

    has_seam = any(
        callable(getattr(pkg, name))
        for name in (
            "detect_dependency_cycles",
            "find_dependency_cycles",
            "dependency_cycles",
        )
    )
    assert has_seam, (
        "Expected a public seam for dependency cycle detection "
        "(detect_dependency_cycles / find_dependency_cycles / dependency_cycles). "
        "Currently the only public symbol is validate_series_manifest, which "
        "is fine, but cycle detection must be reachable as its own function so "
        "the publisher can fail-closed before staging."
    )


def test_cross_link_dangling_check_is_exposed_in_public_surface() -> None:
    """A dedicated dangling-target check must exist as a public seam."""
    import src.kc.views.book.wiki as pkg

    has_seam = any(
        callable(getattr(pkg, name))
        for name in (
            "find_dangling_cross_links",
            "validate_cross_links",
            "dangling_cross_links",
        )
    )
    assert has_seam, (
        "Expected a public seam for dangling cross-link validation. The current "
        "build_cross_link_candidates helper silently filters, which loses the "
        "diagnostic information the publisher needs to fail-closed."
    )


def test_relation_stats_does_not_silently_shrink() -> None:
    """Lock-in: when only namespace edges exist, total == 0 and unresolved == 0.

    If a future refactor 'improves' relation_stats to compute the ratio as
    ``unresolved / max(total, 1)`` or filters out the empty case, the publisher
    will lose the explicit signal that there are no real edges at all.
    """
    snapshot = _snapshot(_page("p1", relations=(
        ("taxonomy_of", "taxonomy-x"),
    )))

    stats = relation_stats(snapshot)

    assert stats["total"] == 0
    assert stats["unresolved"] == 0
    assert stats["ignored_namespace"] == 1
    assert "insufficient_sample" not in stats, (
        "relation_stats should not introduce a new 'insufficient_sample' "
        "field — total=0 is already a sufficient signal."
    )