"""Tests for Temporal Validity derivation (路线 v2.2 §A-2 / G4, spec §10 + §17 D-16/D-17).

5 TDD tests covering:

1. ``derive_status`` returns ``"current"`` when query_time falls inside the
   [valid_from, valid_to] window (spec §10 T-2 happy path).
2. ``derive_status`` returns ``"scheduled"`` when query_time is before
   valid_from — knowledge has not yet come into force (spec §10 T-9).
3. ``derive_status`` returns ``"historical"`` when query_time is on/after
   valid_to — knowledge is past its end-of-validity (spec §10 T-10).
4. ``derive_status`` returns ``"unknown"`` when BOTH valid_from and
   valid_to are ``None`` — boundary information is absent
   (spec §10 T-7 L-6 加固).
5. After applying the temporal filter (spec §12.1 R-2), only ``current``
   pages remain; ``historical`` / ``scheduled`` / ``unknown`` pages are
   dropped from the default retrieval result set (spec §17 D-16/D-17).

These tests are intentionally independent of the implementation file
(``src/kc.compiler.temporal``): until that module ships, every test
in this file must FAIL with ``ImportError`` or ``ModuleNotFoundError``.
After the module ships, all 5 must pass.
"""
from __future__ import annotations

import time


# NB: src.kc.compiler.temporal is the module under test — it does not exist
# yet at the time these tests are authored, so the import below is the red
# signal that kicks off TDD step 2.
from src.kc.compiler.temporal import (
    apply_temporal_filter,
    derive_status,
)

from src.knowledge.core.object import (
    KnowledgeObject,
    KnowledgeType,
    LifecycleState,
    Provenance,
)


# ── helpers ─────────────────────────────────────────────────────────────────


def _now_ms() -> int:
    """Return the current Unix time in milliseconds."""
    return int(time.time() * 1000)


def _make_ko(
    valid_from: int | None = None,
    valid_to: int | None = None,
    ko_id: str = "ko-001",
) -> KnowledgeObject:
    """Build a minimal KnowledgeObject for temporal tests.

    Only ``valid_from`` / ``valid_to`` matter for these tests; the other
    fields are filled with bare-minimum defaults that satisfy the
    dataclass required-args contract.
    """
    return KnowledgeObject(
        id=ko_id,
        type=KnowledgeType.CLAIM,
        title="Temporal test",
        content="x",
        lifecycle=LifecycleState.CREATED,
        confidence=0.5,
        provenance=Provenance(source_path="/t.md"),
        valid_from=valid_from,
        valid_to=valid_to,
    )


# ── test 1: query_time inside window → 'current' ────────────────────────────


def test_derive_status_current_when_query_time_inside_window() -> None:
    """derive_status returns 'current' for query_time ∈ [valid_from, valid_to).

    spec §10 T-2: knowledge whose validity window covers the query is
    current. ``valid_from <= query_time < valid_to`` is the canonical
    half-open interval (knowledge is in force at the start instant and
    stops being in force at the end instant).
    """
    obj = _make_ko(
        valid_from=1_600_000_000_000,
        valid_to=1_800_000_000_000,
    )
    assert derive_status(obj, query_time=1_700_000_000_000) == "current"


# ── test 2: query_time before valid_from → 'scheduled' ─────────────────────


def test_derive_status_scheduled_when_query_time_before_valid_from() -> None:
    """derive_status returns 'scheduled' when valid_from > query_time.

    spec §10 T-9: knowledge whose start-of-validity lies in the future
    is scheduled — it has not yet come into force but is known to be
    upcoming.
    """
    obj = _make_ko(
        valid_from=1_800_000_000_000,
        valid_to=2_000_000_000_000,
    )
    assert derive_status(obj, query_time=1_700_000_000_000) == "scheduled"


# ── test 3: query_time on/after valid_to → 'historical' ─────────────────────


def test_derive_status_historical_when_query_time_at_or_after_valid_to() -> None:
    """derive_status returns 'historical' when valid_to <= query_time.

    spec §10 T-10: knowledge whose end-of-validity has passed is
    historical — it was once current and may still be queryable for
    audit purposes, but it must not enter default current retrieval.
    """
    obj = _make_ko(
        valid_from=1_500_000_000_000,
        valid_to=1_600_000_000_000,
    )
    assert derive_status(obj, query_time=1_700_000_000_000) == "historical"


# ── test 4: both valid_from and valid_to are None → 'unknown' ──────────────


def test_derive_status_unknown_when_both_bounds_are_none() -> None:
    """derive_status returns 'unknown' when both valid_from and valid_to are None.

    spec §10 T-7 + L-6 加固: with no boundary information, the temporal
    status is unknown and the object must NOT enter default current
    retrieval (spec §17 D-17).
    """
    obj = _make_ko(valid_from=None, valid_to=None)
    assert derive_status(obj, query_time=1_700_000_000_000) == "unknown"


# ── test 5: temporal filter drops non-current pages from default retrieval ─


def test_apply_temporal_filter_drops_historical_from_default_retrieval() -> None:
    """apply_temporal_filter keeps 'current' pages, drops 'historical'.

    spec §12.1 R-2: default current-retrieval filter is
    ``temporal_status = current``. A page whose valid_to has passed
    (historical) must be filtered out of the default result set
    (spec §17 D-16).
    """
    current_ko = _make_ko(
        valid_from=1_600_000_000_000,
        valid_to=1_800_000_000_000,
        ko_id="ko-current",
    )
    historical_ko = _make_ko(
        valid_from=1_500_000_000_000,
        valid_to=1_600_000_000_000,
        ko_id="ko-historical",
    )

    kept = apply_temporal_filter(
        [current_ko, historical_ko],
        query_time=1_700_000_000_000,
    )
    kept_ids = [ko.id for ko in kept]
    assert kept_ids == ["ko-current"], (
        "Historical KO must be filtered out of default current retrieval "
        "(spec §12.1 R-2 + §17 D-16)"
    )


# ── bonus helper coverage ───────────────────────────────────────────────────


def test_derive_status_handles_partial_bounds() -> None:
    """derive_status handles valid_from=None + valid_to set (and mirror).

    Spec §10 boundary semantics: when only one boundary is present,
    derive_status returns the safe default that does not leak
    historical/unknown into default retrieval. The contract is
    implementation-defined as long as it is monotonic and documented.
    """
    # Only valid_to present, query_time well before valid_to → current
    obj_open_ended = _make_ko(
        valid_from=None,
        valid_to=2_000_000_000_000,
        ko_id="ko-open",
    )
    assert derive_status(obj_open_ended, query_time=1_700_000_000_000) == "current"

    # Only valid_to present, query_time on/after valid_to → historical
    obj_expired = _make_ko(
        valid_from=None,
        valid_to=1_600_000_000_000,
        ko_id="ko-expired",
    )
    assert derive_status(obj_expired, query_time=1_700_000_000_000) == "historical"


def test_apply_temporal_filter_includes_unknown_helper() -> None:
    """apply_temporal_filter surfaces a hook for unknown-temporality pages.

    When include_unknown_temporal=True is passed, pages whose temporal
    status is 'unknown' (both bounds missing) are also retained. This
    mirrors the spec §10 T-7 fail-closed-by-default + explicit-query
    opt-in pattern used by DefaultFilter.
    """
    current_ko = _make_ko(
        valid_from=1_600_000_000_000,
        valid_to=1_800_000_000_000,
        ko_id="ko-current",
    )
    unknown_ko = _make_ko(
        valid_from=None, valid_to=None, ko_id="ko-unknown"
    )

    # Default: unknown is dropped from current retrieval
    kept_default = apply_temporal_filter(
        [current_ko, unknown_ko],
        query_time=1_700_000_000_000,
    )
    assert [ko.id for ko in kept_default] == ["ko-current"]

    # Opt-in: unknown is included for explicit queries
    kept_explicit = apply_temporal_filter(
        [current_ko, unknown_ko],
        query_time=1_700_000_000_000,
        include_unknown_temporal=True,
    )
    assert sorted(ko.id for ko in kept_explicit) == ["ko-current", "ko-unknown"]
