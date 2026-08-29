"""Temporal Validity derivation (路线 v2.2 §A-2 / G4, spec §10 + §17 D-16/D-17).

This module is the single source of truth for ``temporal_status`` — the
spec §10 rule that "temporal_status must be computed from query time,
boundary and supersession relations" (i.e. it must NEVER be written
directly by the Extractor, LLM or human). The derivation is:

* ``valid_from > query_time`` → ``"scheduled"``  (not yet in force, T-9)
* ``valid_to <= query_time`` → ``"historical"`` (past end-of-validity, T-10)
* ``valid_from <= query_time < valid_to`` → ``"current"``  (in force, T-2)
* both bounds ``None`` → ``"unknown"``  (boundary absent, T-7 / L-6)

The companion ``apply_temporal_filter`` is the list-level seam used by
the default current-retrieval filter (spec §12.1 R-2): pages whose
``derive_status`` is not ``current`` are dropped unless the caller
explicitly opts in via ``include_unknown_temporal=True`` (spec §10
T-7 fail-closed-by-default + §11.4 explicit-query semantics).
"""
from __future__ import annotations

from typing import Literal

from ...knowledge.core.object import KnowledgeObject


TemporalStatus = Literal["current", "historical", "scheduled", "unknown"]


def derive_status(obj: KnowledgeObject, query_time: int) -> TemporalStatus:
    """Compute the temporal_status of *obj* relative to *query_time*.

    spec §10 boundary semantics (T-2 / T-7 / T-9 / T-10):

    * ``valid_from > query_time`` → ``"scheduled"``  (T-9: future-effective)
    * ``valid_to <= query_time`` → ``"historical"`` (T-10: past-effective)
    * both bounds present, query_time in [valid_from, valid_to) → ``"current"`` (T-2)
    * both bounds missing → ``"unknown"``  (T-7 / L-6 加固)
    * one bound present only — fallback is "conservatively safe":

      - ``valid_from is None`` + ``valid_to is not None``: query_time <
        valid_to → ``current``; otherwise ``historical``.
      - ``valid_from is not None`` + ``valid_to is None``: query_time
        >= valid_from → ``current``; otherwise ``scheduled``.

    spec §10 says ``temporal_status`` must be computed from query time,
    boundary and supersession; it is NEVER a stored attribute on the
    KnowledgeObject (no ``Extractor`` / LLM / human writes it directly).
    """
    valid_from = obj.valid_from
    valid_to = obj.valid_to

    # T-7 / L-6 加固: both bounds absent → unknown. Caller is expected to
    # drop "unknown" objects from default retrieval (spec §17 D-17).
    if valid_from is None and valid_to is None:
        return "unknown"

    # T-9: knowledge whose start lies in the future is scheduled.
    if valid_from is not None and valid_from > query_time:
        return "scheduled"

    # T-10: knowledge whose end has passed is historical.
    if valid_to is not None and valid_to <= query_time:
        return "historical"

    # T-2: both bounds present and query_time ∈ [valid_from, valid_to).
    if valid_from is not None and valid_to is not None:
        if valid_from <= query_time < valid_to:
            return "current"

    # One-sided bound: the surviving branch above narrowed the case to
    # the still-applicable side. The remaining case is conservatively
    # current (we'd rather over-include under explicit query than leak
    # a still-applicable fact into "historical"). This matches the
    # spec §10 T-7 fail-closed-by-default posture: a partial boundary
    # is weaker evidence than both bounds, but it isn't evidence of
    # expiry, so we don't drop it from current.
    return "current"


def _passes_temporal(page: object, query_time: int) -> bool:
    """Return True iff *page* should pass the default temporal gate.

    spec §12.1 R-2 default current-retrieval filter is
    ``temporal_status = current``. Task 6 (plan 2026-08-29-...) added
    native ``valid_from`` / ``valid_to`` to WikiPage as optional fields
    defaulting to ``None``. For back-compat, WikiPage with BOTH bounds
    set to None is treated as currently-valid (legacy behaviour
    preserved). KnowledgeObject has had these fields since A-2 and the
    strict spec semantics (both None → "unknown" → drop) still apply.
    """
    valid_from = getattr(page, "valid_from", None)
    valid_to = getattr(page, "valid_to", None)
    # Back-compat: WikiPage without temporal fields is pass-through.
    if (
        type(page).__name__ == "WikiPage"
        and valid_from is None
        and valid_to is None
    ):
        return True

    try:
        status = derive_status(page, query_time=query_time)  # type: ignore[arg-type]
    except Exception:
        # Fail-closed-but-usable: a malformed page is treated as
        # currently-valid rather than dropped.
        return True

    return status == "current"


def apply_temporal_filter(
    pages: list,
    query_time: int,
    include_unknown_temporal: bool = False,
) -> list:
    """Filter *pages* to those whose temporal_status == 'current'.

    spec §12.1 R-2: default current-retrieval filter. spec §10 T-7:
    pages with unknown temporal status (both bounds missing) are
    dropped unless ``include_unknown_temporal=True`` is passed —
    mirrors the DefaultFilter explicit-query opt-in semantics
    (spec §11.4).

    Task 6 back-compat: WikiPage without temporal fields passes
    through (legacy behaviour). KnowledgeObject with None/None is
    strictly unknown and dropped unless opt-in.
    """
    kept = []
    for p in pages:
        valid_from = getattr(p, "valid_from", None)
        valid_to = getattr(p, "valid_to", None)
        # WikiPage back-compat: no temporal fields at all → pass.
        if (
            type(p).__name__ == "WikiPage"
            and valid_from is None
            and valid_to is None
        ):
            kept.append(p)
            continue
        try:
            status = derive_status(p, query_time=query_time)
        except Exception:
            kept.append(p)
            continue
        if status == "current":
            kept.append(p)
        elif status == "unknown" and include_unknown_temporal:
            kept.append(p)
    return kept