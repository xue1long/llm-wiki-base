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

- **evidence gate (Task 2)**: verified pages without ``evidence_refs``
  cannot enter the default retrieval result set. Per plan
  2026-08-29-kc-integrity-idempotency-layered.md Task 2, the retrieval
  boundary must reject verified pages whose evidence_refs is missing
  (no fabrication). Surfaced as ``missing_evidence_refs`` in audits.

- **closure gate (Task 2)**: verified pages whose ``closure_report``
  is not strictly passed (passed is True) are rejected. Per plan Task 2,
  truthy non-boolean ``closure_report["passed"]`` is rejected (strict
  ``is True`` check) so legacy fixtures that recorded "false" / "true"
  strings do not silently pass. Surfaced as ``closure_not_passed``.

- **temporal gate (Task 6 wiring)**: default current-retrieval only
  keeps pages whose ``temporal_status`` is ``current`` (spec §12.1 R-2,
  derived by ``src.kc.compiler.temporal``). Task 6 added native
  ``valid_from`` / ``valid_to`` to WikiPage as optional fields defaulting
  to ``None``: a WikiPage with BOTH bounds ``None`` is a back-compat
  pass-through (legacy pages stay visible), while a KnowledgeObject with
  both bounds ``None`` is strictly ``unknown`` and dropped (spec §10
  T-7). Historical / scheduled / unknown pages fail the default gate
  unless explicitly queried (spec §11.4).

The full 8-condition default-published-closure (B-3 task) builds on
top of this filter; the B-3 task is the right place to wire the
remaining conditions (heat, is_immutable, etc.). This module is
intentionally narrow so it can be exercised in isolation.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ..compiler.temporal import _passes_temporal


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


def _get_ko_extra(page: Any) -> dict:
    """Return ``page._ko_extra`` if it is a dict, else empty dict.

    Tolerates legacy pages that may have ``_ko_extra`` set to ``None``
    or another type — the typed attribute is a v2.x addition.
    """
    ko_extra = getattr(page, "_ko_extra", None)
    if isinstance(ko_extra, dict):
        return ko_extra
    return {}


def _get_closure_report(page: Any) -> Any:
    """Read the closure report from a page, preferring the typed field.

    Lookup order:
        1. ``page.closure_report`` (typed attribute, set by integrity pipeline)
        2. ``page._ko_extra["closure_report"]`` (legacy frontmatter key)

    Returns the raw report (or dict), or ``None`` if absent.
    """
    report = getattr(page, "closure_report", None)
    if report is not None:
        return report
    return _get_ko_extra(page).get("closure_report")


def _closure_passed(report: Any) -> bool:
    """Return True iff *report* explicitly passes the closure check.

    Strict boolean ``passed is True`` — truthy non-boolean values
    (legacy fixtures that wrote "false" / "true" strings) are rejected
    so missing evidence / fake-passes cannot leak into default
    retrieval. See plan Task 2 (Spec §12.1 + 2026-08-29-... Task 2).
    """
    if report is None:
        return False
    if isinstance(report, dict):
        return report.get("passed") is True
    return getattr(report, "passed", None) is True


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
                is treated as "current time". The temporal gate (Task 6)
                keeps only ``current`` pages; WikiPage with both bounds
                None is a back-compat pass-through, KnowledgeObject with
                both None is a strict unknown-drop (spec §10 T-7).

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
        ko_extra = _get_ko_extra(page)
        lifecycle = str(ko_extra.get("lifecycle", "") or "")

        if lifecycle == "DISPUTED" and not self.include_disputed:
            return False
        if lifecycle == "QUARANTINED" and not self.include_quarantined:
            return False
        if lifecycle == "CANDIDATE" and not self.include_candidate:
            return False
        if lifecycle == "REJECTED" and not self.include_rejected:
            return False

        # 3. evidence gate (Task 2: 强制证据链).
        #    verified pages without evidence_refs do not pass.
        #    We refuse to fabricate refs — missing info means missing.
        if not getattr(page, "evidence_refs", None):
            return False

        # 4. closure gate (Task 2: 默认检索边界).
        #    verified pages whose closure_report is not strictly
        #    passed (passed is True) do not pass.
        if not _closure_passed(_get_closure_report(page)):
            return False

        # 5. temporal gate (spec §12.1 R-2 + §10 T-7, Task 6 wiring).
        #    WikiPage now carries valid_from/valid_to (additive None
        #    defaults): WikiPage with both None is a back-compat
        #    pass-through; KnowledgeObject with both None is a strict
        #    unknown-drop. Non-current statuses (historical / scheduled /
        #    unknown KO) fail the default gate unless explicitly queried
        #    (spec §11.4). query_time None = "current time".
        if query_time is None:
            query_time = int(time.time() * 1000)
        if not _passes_temporal(page, query_time=query_time):
            return False

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
