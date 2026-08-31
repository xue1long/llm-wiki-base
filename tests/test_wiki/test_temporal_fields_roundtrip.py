"""Task 6 tests: WikiPage valid_from/valid_to (P1).

Plan 2026-08-29-kc-integrity-idempotency-layered.md §Task 6 — Wiki 增加
可选 valid_from/valid_to；旧 frontmatter 无字段时兼容；区间半开
[valid_from, valid_to)；unknown / scheduled / historical / current /
invalid 状态可观察.

V4 (ADR-002, 2026-08-31) update:
- valid_from/valid_to are NO LONGER serialized to disk (V4 8-key whitelist)
- They remain on the in-memory WikiPage for code that needs them
- from_dict() restores them from legacy frontmatter for backward compat
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
    does not introduce the fields."""
    legacy_fm = {
        "id": "legacy",
        "title": "Legacy",
        "type": "concept",
        "workflow_state": "verified",
    }
    page = WikiPage.from_dict(legacy_fm, body="")

    assert page.valid_from is None
    assert page.valid_to is None

    # V4: valid_from/valid_to are in-memory only — never serialized.
    emitted = page.to_frontmatter_dict()
    assert "valid_from" not in emitted
    assert "valid_to" not in emitted


# ---------------------------------------------------------------------------
# 2. Both bounds → kept in memory (not serialized)
# ---------------------------------------------------------------------------


def test_page_with_both_bounds_in_memory() -> None:
    page = _page(valid_from=100, valid_to=200)

    # In-memory state is preserved.
    assert page.valid_from == 100
    assert page.valid_to == 200

    # V4: NOT in frontmatter.
    emitted = page.to_frontmatter_dict()
    assert "valid_from" not in emitted
    assert "valid_to" not in emitted


# ---------------------------------------------------------------------------
# 3. Only valid_from → kept in memory
# ---------------------------------------------------------------------------


def test_page_with_only_valid_from_in_memory() -> None:
    page = _page(valid_from=100)
    assert page.valid_from == 100
    assert page.valid_to is None


# ---------------------------------------------------------------------------
# 4. Round-trip is byte-stable for the V4 whitelist
# ---------------------------------------------------------------------------


def test_round_trip_is_byte_stable() -> None:
    """Legacy page with temporal fields is read back; serializing
    produces only the V4 8-key whitelist."""
    fm = {
        "id": "p",
        "title": "P",
        "type": "concept",
        "valid_from": 1000,
        "valid_to": 2000,
    }
    p1 = WikiPage.from_dict(fm, body="")
    fm2 = p1.to_frontmatter_dict()
    # V4: emitted is the 8-key whitelist (no temporal fields).
    assert "valid_from" not in fm2
    assert "valid_to" not in fm2
    p2 = WikiPage.from_dict(fm2, body="")
    # V4: re-serialization is idempotent.
    assert p2.to_frontmatter_dict() == fm2


# ---------------------------------------------------------------------------
# 5. Half-open interval [valid_from, valid_to) — pure logic, unchanged
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
# 6. Unknown (both None) preserved across round-trip (memory only)
# ---------------------------------------------------------------------------


def test_unknown_state_preserved_in_memory() -> None:
    page = _page(valid_from=None, valid_to=None)
    assert page.valid_from is None
    assert page.valid_to is None


# ---------------------------------------------------------------------------
# 7. Invalid (valid_from > valid_to) is preserved in memory
# ---------------------------------------------------------------------------


def test_invalid_interval_preserved_in_memory() -> None:
    page = _page(valid_from=300, valid_to=100)
    assert page.valid_from == 300
    assert page.valid_to == 100