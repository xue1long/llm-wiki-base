"""Task 31 — Reconciliation Phase 1 main entry point.

Public API:

  * :py:func:`reconcile_pages`
        — iterate over pages, run the per-page pipeline
          (retrieve_candidates → resolve_identity → apply_decisions),
          aggregate metrics. Per-page failures are isolated; one bad
          page never aborts the batch (Failure Contract §1).

  * :py:func:`reconcile_stale_signals`
        — F4 整改: at job startup (and on pipeline upgrade), scan the
          registry and mark every ACTIVE concept whose
          ``resolver_fingerprint`` no longer matches the current one
          as ``STALE``. Returns the list of canonical ids that
          transitioned to ``STALE``.

Phase 1 contract
----------------
The Phase 1 pipeline is intentionally minimal:

    1. Build a :py:class:`CanonicalIndex` from the registry's current
       canonical concepts.
    2. For each page (in input order):
         a. retrieve_candidates (using body + title + optional
            query embedding).
         b. resolve_identity (LLM call). Empty candidates → no LLM
            call, no records (not even UNRESOLVED fallback) — the
            resolver is short-circuited.
         c. apply_decisions (writes canonical_concepts.json + appends
            to decision_log.jsonl).

The full Phase 2 (claim-level reconciliation, semantic reviewer,
structural scanner, etc.) lands in subsequent tasks. Phase 1 ships the
minimum closed loop: ingest → decide → store.

Failure Contract §1
-------------------
* Per-page errors are counted but never abort the batch.
* LLM technical failures are already handled inside
  :py:func:`identity_resolver.resolve_identity` (every candidate
  receives ``UNRESOLVED``; the function never raises). A bug in our
  pipeline (e.g. an attribute typo on the page object) is logged and
  counted as ``errors``, and the loop continues.
* :py:func:`reconcile_stale_signals` swallows every exception: the
  fingerprint-drift scan is best-effort and must not block startup.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .canonical_models import ReconciliationDecision
from .canonical_registry import CanonicalRegistry
from .candidate_retrieval import CanonicalIndex, retrieve_candidates
from .identity_resolver import resolve_identity


_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ReconcileResult:
    """Aggregate metrics from one :py:func:`reconcile_pages` run.

    Attributes
    ----------
    processed:
        Number of pages visited by the pipeline (including those that
        errored out — a page is "processed" once we attempted the
        retrieve/resolve/apply chain on it).
    created_new:
        Number of DISTINCT decisions emitted. Each DISTINCT decision
        creates a new :py:class:`CanonicalConcept` via
        :py:meth:`CanonicalRegistry.apply_decisions`.
    joined_existing:
        Number of SAME / ALIAS / BROADER / NARROWER / OVERLAP /
        CONFLICT decisions emitted that successfully joined a known
        canonical. UNRESOLVED is *not* counted here.
    unresolved:
        Number of UNRESOLVED decisions emitted (one per candidate
        the resolver could not decide on).
    errors:
        Number of pages whose pipeline raised before completion
        (i.e. technical failures distinct from "resolver couldn't
        decide" — those are counted as ``unresolved``).
    touched_canonical_ids:
        Canonical ids touched during this run, in input order. Used
        by callers (and tests) to assert which concepts moved.
    """

    processed: int = 0
    created_new: int = 0
    joined_existing: int = 0
    unresolved: int = 0
    errors: int = 0
    touched_canonical_ids: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def reconcile_pages(
    pages: list[Any],
    *,
    project_root: Path | str,
    llm: Any,
    template: Any | None = None,
    body_by_page: dict[str, str] | None = None,
    query_embeddings: dict[str, list[float]] | None = None,
    embedding_model_id: str = "",
    language: str = "",
    resolver_fingerprint: str = "",
    max_candidates: int = 20,
    slug_registry: Any | None = None,
) -> ReconcileResult:
    """Reconciliation Phase 1 main entry.

    Steps:
      1. Build ``CanonicalIndex`` from the current registry.
      2. For each page (in input order):
           a. ``retrieve_candidates(page)``
           b. ``resolve_identity(page, candidates)``
           c. ``registry.apply_decisions(page_id, decisions)``
      3. Aggregate metrics into :py:class:`ReconcileResult`.

    Failure Contract §1: per-page errors are isolated. A page whose
    pipeline raises is counted as ``errors`` and the batch continues.
    LLM technical failures are already swallowed inside
    :py:func:`resolve_identity` (every candidate → UNRESOLVED); they
    do *not* count as ``errors`` here.

    Parameters
    ----------
    pages:
        Iterable of wiki-page objects. Each must expose ``.id`` and
        ``.title``; ``.body`` and ``.slots`` are read by the resolver
        but are optional (the test fixture pages use ``.slots`` but
        not all pages do).
    project_root:
        Path to the project root. Used by :py:class:`CanonicalRegistry`
        and by the prompt-template loader.
    llm:
        Async LLM client exposing ``complete(*, prompt_kind,
        user_prompt, system_prompt, max_tokens, temperature) -> str``.
    template:
        Optional pre-loaded identity-resolve TOML payload. When ``None``,
        :py:func:`resolve_identity` loads it from disk (best-effort).
    body_by_page:
        Optional ``page_id -> body text`` map. Used both for the index
        and by the resolver's evidence pack.
    query_embeddings:
        Optional ``page_id -> embedding`` map. When present and
        non-empty, ``retrieve_candidates`` runs the
        ``vector_neighbor`` strategy.
    embedding_model_id:
        The model id corresponding to ``query_embeddings`` entries.
    language:
        ISO 639-1 language code forwarded to ``apply_decisions``.
    resolver_fingerprint:
        F4 fingerprint wired into every decision record.
    max_candidates:
        Cap on the per-page candidate short-list (default 20).
    slug_registry:
        Optional :py:class:`SlugAliasRegistry` instance forwarded to
        the registry's :py:class:`SlugAliasRegistryAdapter`. When
        ``None``, aliases are not propagated to the slug layer.

    Returns
    -------
    ReconcileResult
        Aggregate metrics + touched canonical id list.
    """
    registry = CanonicalRegistry(
        project_root,
        slug_registry=slug_registry,
        resolver_fingerprint=resolver_fingerprint,
    )
    concepts = list(registry.load_concepts().values())
    index = CanonicalIndex.build(concepts, body_by_page=body_by_page)

    embeddings = query_embeddings or {}
    body_lookup = body_by_page or {}

    result = ReconcileResult()

    for page in pages:
        page_id = getattr(page, "id", "") or ""
        page_title = getattr(page, "title", "") or ""
        page_body = getattr(page, "body", "") or ""
        if not page_id:
            # A page with no id cannot be reconciled — count it as an
            # error and continue.
            result.errors += 1
            continue

        result.processed += 1

        try:
            candidates = retrieve_candidates(
                new_page_id=page_id,
                new_page_body=page_body or body_lookup.get(page_id, "") or "",
                new_page_title=page_title,
                index=index,
                max_candidates=max_candidates,
                query_embedding=embeddings.get(page_id),
                embedding_model_id=embedding_model_id,
            )
            decisions = await resolve_identity(
                new_page_id=page_id,
                new_page_title=page_title,
                new_page=page,
                candidates=candidates,
                index=index,
                llm=llm,
                template=template,
                project_root=project_root,
                body_by_page=body_lookup,
                resolver_fingerprint=resolver_fingerprint,
            )
        except Exception as exc:
            # Per-page pipeline failure (caller bug, I/O error, ...).
            # resolve_identity itself never raises (see Failure
            # Contract §1 there); this branch is for *our* bugs.
            _LOG.warning(
                "reconcile_pages: pipeline failed for page=%s: %s",
                page_id, exc,
            )
            result.errors += 1
            continue

        # Empty candidates → resolve_identity returned [] (no UNRESOLVED
        # fallback). apply_decisions on [] is a no-op; skip it so we
        # don't pollute the decision log with empty entries.
        if not decisions:
            continue

        # Tally per-decision verdict before applying.
        for d in decisions:
            if d.decision is ReconciliationDecision.DISTINCT:
                result.created_new += 1
            elif d.decision is ReconciliationDecision.UNRESOLVED:
                result.unresolved += 1
            else:
                result.joined_existing += 1

        try:
            touched = registry.apply_decisions(
                page_id,
                decisions,
                language=language,
                resolver_fingerprint=resolver_fingerprint,
            )
        except Exception as exc:
            _LOG.warning(
                "reconcile_pages: apply_decisions failed for page=%s: %s",
                page_id, exc,
            )
            result.errors += 1
            continue

        for cc in touched:
            if cc.canonical_id not in result.touched_canonical_ids:
                result.touched_canonical_ids.append(cc.canonical_id)

    return result


# ---------------------------------------------------------------------------
# F4 stale signal entry
# ---------------------------------------------------------------------------


async def reconcile_stale_signals(
    project_root: Path | str,
    *,
    current_fingerprint: str,
    slug_registry: Any | None = None,
) -> list[str]:
    """F4 整改: scan registry, mark concepts STALE on fingerprint drift.

    Called at job startup (and on pipeline upgrade). Returns the list
    of ``canonical_id`` values newly transitioned to ``STALE``.

    The function swallows every exception (best-effort): the
    fingerprint-drift scan must not block startup, and a missing or
    corrupted ``canonical_concepts.json`` simply yields an empty
    list.
    """
    try:
        registry = CanonicalRegistry(
            project_root,
            slug_registry=slug_registry,
            resolver_fingerprint=current_fingerprint,
        )
        return registry.mark_stale_concepts(current_fingerprint)
    except Exception as exc:  # pragma: no cover - defensive guard
        _LOG.warning(
            "reconcile_stale_signals: scan failed for root=%s: %s",
            project_root, exc,
        )
        return []


__all__ = [
    "ReconcileResult",
    "reconcile_pages",
    "reconcile_stale_signals",
]