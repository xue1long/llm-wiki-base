"""Default Retrieval Filter (路线 v2.2 §C-2 / G2, spec §11.3 + §12.1).

Implements the *status subset* of the default-published-closure
(spec §11.3 closed-loop condition #1) plus the disputed/quarantined
gates (spec §11.4 error-injection counter-measures).

Scope of this module:

- **status gate**: only ``workflow_state == "verified"`` passes.
  ``draft`` / ``ready`` / ``outdated`` are all out of the default
  retrieval result set by virtue of their workflow state. The spec
  §11.4 candidate / rejected / disputed / quarantined categories are
  surfaced through the parallel KO ``_ko_extra.lifecycle`` channel —
  when set, they dominate the workflow_state gate.

- **temporal gate**: stubbed here (spec §10 T-7 unknown defaults to
  ``current`` for backward compat). WikiPage has no native
  ``valid_from`` / ``valid_to`` fields yet (A-2 task); the temporal
  check is a single ``return True`` line for now so the seam is in
  place for the future upgrade without an API change.

The full 8-condition default-published-closure (B-3 task) builds on
top of this filter; the B-3 task is the right place to wire the
remaining conditions (evidence integrity, heat, is_immutable, etc.).
This module is intentionally narrow so it can be exercised in isolation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


#: Workflow states that pass the default retrieval status gate.
#: spec §11.3 default-published-closure condition #1 + §12.1 default
#: current-retrieval filter. ``verified`` is the only state that
#: survives; ``draft`` / ``ready`` are pre-verification, ``outdated``
#: is post-deprecation.
_DEFAULT_VERIFIED_STATES: frozenset[str] = frozenset({"verified"})

#: KO lifecycle categories that default retrieval must drop
#: (spec §11.3 closed-loop + §11.4 error-injection counter-measures).
#: These ride on ``_ko_extra.lifecycle`` because WikiPage does not have
#: a native lifecycle field — see C-0 Commit 2 (decision_record) and
#: Commit 4 (evidence_refs) for the same pattern.
_BLOCKED_LIFECYCLE_STATES: frozenset[str] = frozenset({
    "CANDIDATE",   # spec §11.4 #1 — Unsupported Fact counter
    "QUARANTINED", # spec §11.4 #2 — Critical Evidence Missing counter
    "REJECTED",    # spec §11.3 closed-loop — terminal KO state
})


@dataclass
class DefaultFilter:
    """Default retrieval filter for Knowledge Core published closure.

    ON-by-default (Route B H-3): every page passes through this filter
    before it surfaces in any default retrieval call. The opt-in flags
    below are the only ways to relax the gates — they exist to support
    explicit queries (spec §11.4 "unless explicitly queried" semantics).

    Attributes:
        include_disputed: When True, DISPUTED pages pass the gate.
            Default False (spec §11.4 closed-loop).
        include_quarantined: When True, QUARANTINED pages pass the gate.
            Default False (spec §11.4 #2).
        include_candidate: When True, CANDIDATE pages pass the gate.
            Default False (spec §11.4 #1). Off by default so that
            pre-publication pages never leak.
        include_rejected: When True, REJECTED pages pass the gate.
            Default False. REJECTED is a terminal KO state; opt-in is
            reserved for audit tooling.
    """

    include_disputed: bool = False
    include_quarantined: bool = False
    include_candidate: bool = False
    include_rejected: bool = False

    def passes(self, page: Any, query_time: int | None = None) -> bool:
        """Check whether *page* should appear in default retrieval results.

        Args:
            page: WikiPage instance (or anything exposing the same
                ``workflow_state`` / ``_ko_extra`` attribute surface).
            query_time: Unix-millisecond timestamp of the query. ``None``
                is treated as "current time"; the temporal check is a
                pass-through stub here (A-2 task will tighten it).

        Returns:
            ``True`` only when the page clears every gate below.
        """
        # 1. status gate (spec §11.3 condition #1, §12.1 default).
        #    WikiPage.workflow_state is the canonical status field
        #    (C-0 Commit 1 migration); any non-verified value fails.
        if getattr(page, "workflow_state", "draft") not in _DEFAULT_VERIFIED_STATES:
            return False

        # 2. KO lifecycle gate (spec §11.3 closed-loop + §11.4).
        #    WikiPage has no native lifecycle field; the value rides
        #    on _ko_extra. We tolerate _ko_extra being absent or
        #    non-dict (legacy pages may have it as None).
        ko_extra = getattr(page, "_ko_extra", None)
        lifecycle = ""
        if isinstance(ko_extra, dict):
            lifecycle = str(ko_extra.get("lifecycle", "") or "")

        if lifecycle == "DISPUTED" and not self.include_disputed:
            return False
        if lifecycle == "QUARANTINED" and not self.include_quarantined:
            return False
        if lifecycle == "CANDIDATE" and not self.include_candidate:
            return False
        if lifecycle == "REJECTED" and not self.include_rejected:
            return False

        # 3. temporal gate (spec §12.1 valid_from / valid_to).
        #    WikiPage does not currently carry valid_from/valid_to;
        #    A-2 task will introduce them. Until then the gate is a
        #    pass-through (unknown defaults to current, spec §10 T-7).
        #    We deliberately accept query_time without consuming it
        #    so the API stays stable for A-2.
        _ = query_time

        return True


def apply_default_filter(
    pages: list[Any],
    query_time: int | None = None,
    include_disputed: bool = False,
    include_quarantined: bool = False,
    include_candidate: bool = False,
    include_rejected: bool = False,
) -> list[Any]:
    """Convenience wrapper: apply ``DefaultFilter`` to a list of pages.

    Returns a new list containing only the pages that pass the filter;
    input order is preserved.
    """
    f = DefaultFilter(
        include_disputed=include_disputed,
        include_quarantined=include_quarantined,
        include_candidate=include_candidate,
        include_rejected=include_rejected,
    )
    return [p for p in pages if f.passes(p, query_time=query_time)]
