"""Task 6 tests: WikiPage valid_from/valid_to round-trip (P1).

Plan 2026-08-29-kc-integrity-idempotency-layered.md §Task 6 — Wiki 增加
可选 valid_from/valid_to；旧 frontmatter 无字段时兼容；区间半开
[valid_from, valid_to)；unknown / scheduled / historical / current /
invalid 状态可观察.

Coverage:
1. Old page without temporal fields → from_dict defaults both to None
   ("unknown"); to_frontmatter_dict omits the keys (no null clutter).
2. Page with both bounds → V4 keeps both in memory but omits them from
   to_frontmatter_dict.
3. Page with only valid_from → V4 omits the temporal keys.
4. Round-trip is idempotent: write → read → write → identical bytes.
5. Half-open interval semantics: valid_from=100, valid_to=200 →
   query_time=100 is current, 199 is current, 200 is historical.
6. Unknown (both None) is preserved across round-trip.
7. Invalid (valid_from > valid_to) is not emitted by the V4 serializer.
"""
from __future__ import annotations

import pytest

from src.kc.compiler.temporal import derive_status
from src.wiki.core.types import PageType, WikiPage


def _page(pid: str = "p1", *, valid_from=None, valid_to=None) -> WikiPage:
    return WikiPage(
        id=pid,
        title=pid,
        type=PageType.CONCEPT,
        body="",
        valid_from=valid_from,
        valid_to=valid_to,
    )


# ---------------------------------------------------------------------------
# 1. Old page → unknown (both None), frontmatter omits the keys
# ---------------------------------------------------------------------------


def test_old_page_round_trips_as_unknown() -> None:
    """Legacy frontmatter (no valid_from/valid_to) → both None; re-emit
    does not introduce null fields."""
    legacy_fm = {
        "id": "legacy",
        "title": "Legacy",
        "type": "concept",
        "workflow_state": "verified",
    }
    page = WikiPage.from_dict(legacy_fm, body="")

    assert page.valid_from is None
    assert page.valid_to is None

    emitted = page.to_frontmatter_dict()
    assert "valid_from" not in emitted
    assert "valid_to" not in emitted


# ---------------------------------------------------------------------------
# 2. Both bounds remain in memory but are omitted by V4
# ---------------------------------------------------------------------------


def test_page_with_both_bounds_are_v4_in_memory_only() -> None:
    page = _page(valid_from=100, valid_to=200)
    emitted = page.to_frontmatter_dict()

    assert "valid_from" not in emitted
    assert "valid_to" not in emitted

    restored = WikiPage.from_dict(emitted, body="")
    assert restored.valid_from is None
    assert restored.valid_to is None


# ---------------------------------------------------------------------------
# 3. Only valid_from is also V4 in-memory only
# ---------------------------------------------------------------------------


def test_page_with_only_valid_from_is_v4_in_memory_only() -> None:
    """valid_from set + valid_to=None → omit both V4 frontmatter keys."""
    page = _page(valid_from=100)
    emitted = page.to_frontmatter_dict()

    assert "valid_from" not in emitted
    assert "valid_to" not in emitted


# ---------------------------------------------------------------------------
# 4. Round-trip is byte-stable
# ---------------------------------------------------------------------------


def test_round_trip_is_byte_stable() -> None:
    fm = {
        "id": "p",
        "title": "P",
        "type": "concept",
        "valid_from": 1000,
        "valid_to": 2000,
    }
    p1 = WikiPage.from_dict(fm, body="")
    fm2 = p1.to_frontmatter_dict()
    p2 = WikiPage.from_dict(fm2, body="")
    assert p2.to_frontmatter_dict() == fm2


# ---------------------------------------------------------------------------
# 5. Half-open interval [valid_from, valid_to)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "valid_from,valid_to,query_time,expected",
    [
        (100, 200, 100, "current"),   # left edge inclusive
        (100, 200, 199, "current"),   # last in-window
        (100, 200, 200, "historical"),  # right edge exclusive
        (None, 200, 150, "current"),
        (100, None, 150, "current"),
        (None, None, 150, "unknown"),
    ],
)
def test_derive_status_half_open(
    valid_from, valid_to, query_time, expected,
) -> None:
    page = _page(valid_from=valid_from, valid_to=valid_to)
    # derive_status reads .valid_from / .valid_to from the page.
    from src.knowledge.core.object import KnowledgeObject, LifecycleState, Provenance
    ko = KnowledgeObject(
        id="ko",
        type=__import__("src.knowledge.core.object", fromlist=["KnowledgeType"]).KnowledgeType.CONCEPT,
        title="ko",
        content="",
        lifecycle=LifecycleState.ACTIVE,
        confidence=0.9,
        provenance=Provenance(source_path="/x"),
        valid_from=valid_from,
        valid_to=valid_to,
    )
    assert derive_status(ko, query_time) == expected


# ---------------------------------------------------------------------------
# 6. Unknown (both None) preserved across round-trip
# ---------------------------------------------------------------------------


def test_unknown_state_preserved_across_round_trip() -> None:
    page = _page(valid_from=None, valid_to=None)
    fm = page.to_frontmatter_dict()
    assert "valid_from" not in fm and "valid_to" not in fm
    restored = WikiPage.from_dict(fm, body="")
    assert restored.valid_from is None
    assert restored.valid_to is None


# ---------------------------------------------------------------------------
# 7. Invalid bounds are also omitted by the V4 serializer
# ---------------------------------------------------------------------------


def test_invalid_interval_is_v4_in_memory_only() -> None:
    page = _page(valid_from=300, valid_to=100)
    fm = page.to_frontmatter_dict()
    restored = WikiPage.from_dict(fm, body="")
    assert restored.valid_from is None
    assert restored.valid_to is None
