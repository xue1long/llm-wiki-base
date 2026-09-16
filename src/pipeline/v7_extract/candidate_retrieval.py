"""Stage 6R — candidate retrieval + LLM-controlled predicate ontology (Task 25).

This module replaces the O(N²) pairwise candidate scan from
``relation_extractor.extract_relations`` v1 with a bounded, index-driven
retrieval pipeline. Two concerns:

1. **Candidate retrieval** — given one source page, find up to
   ``MAX_CANDIDATES_PER_PAGE`` candidate target pages via six independent
   strategies (explicit wikilink, entity Jaccard, lexical token overlap,
   acronym match, alias dictionary, optional vector neighbor). Each
   strategy is independently wrapped in try/except so one buggy heuristic
   can't poison the rest of the pipeline.

2. **LLM-controlled ontology** — the LLM never sees the full relation
   predicate enum. ``ALLOWED_PREDICATES_FOR_LLM`` whitelists exactly the
   12 substantive predicates (UNRESOLVED is excluded — the LLM cannot
   produce UNRESOLVED; ``parse_llm_edges`` coerces garbage into
   ``RelationPredicate.UNRESOLVED`` and stamps
   ``RelationSupportStatus.UNRESOLVED`` on the assertion so the review
   queue keeps the evidence trail).

Identity contract
-----------------
Each strategy returns a ``RetrievalCandidate`` with its own ``score`` and
``kind`` (``EXPLICIT`` for wikilinks, ``INFERRED`` for the entity /
lexical / acronym / alias strategies, ``HEURISTIC`` for the optional
vector neighbor). ``retrieve_candidates`` dedupes by target page id
(keeping the highest score) and caps the result at
``MAX_CANDIDATES_PER_PAGE`` rows. Sort order is score-desc, then
target_page_id asc — both for determinism and so the explicit wikilinks
float to the top of the LLM prompt.

Failure contract
----------------
- Unknown predicate strings from the LLM are *expected*: ``coerce`` maps
  them to ``UNRESOLVED`` and ``parse_llm_edges`` marks the assertion as
  ``RelationSupportStatus.UNRESOLVED``. No exception is raised.
- Unknown target page ids (the LLM invents a target outside the
  candidate list) → ``RelationSupportStatus.REJECTED``.
- Self-loops → ``RelationSupportStatus.REJECTED``.
- Each retrieval strategy is wrapped in ``_safe_strategy``; exceptions
  are swallowed and logged, never propagated.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from .relation_models import (
    RelationAssertion,
    RelationKey,
    RelationSupportKind,
    RelationSupportStatus,
)
from .relation_ontology import RelationPredicate, coerce

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_CANDIDATES_PER_PAGE = 30


# Substantive predicates the LLM is allowed to emit. UNRESOLVED is
# explicitly excluded — the LLM must never produce it directly; the
# downstream parser coerces garbage into UNRESOLVED + UNRESOLVED status.
ALLOWED_PREDICATES_FOR_LLM: tuple[str, ...] = (
    "refines",
    "supported_by",
    "causes",
    "requires",
    "contradicts",
    "extends",
    "depends_on",
    "instance_of",
    "related_to",
    "similar_to",
    "co_occurs_with",
    "paired_with",
)


# ---------------------------------------------------------------------------
# PageIndex — pre-built per-page index for O(1) retrieval
# ---------------------------------------------------------------------------


_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


@dataclass
class PageIndexEntry:
    """Pre-indexed representation of one wiki page for retrieval.

    Attributes
    ----------
    page_id:
        Stable page identifier (matches the wiki's ``id`` field).
    title:
        Human-readable title — used for acronym first-letter matching
        and alias lookups.
    body:
        The page body with frontmatter stripped. Wikilinks are scanned
        from this string; entity tokens are derived from this string.
    wikilinks:
        Set of target ids extracted from ``[[...]]`` bodies. The match
        text is normalized to a page id (lowercased, whitespace squashed)
        so callers can look it up directly against ``PageIndex.pages``.
    entity_tokens:
        Lowercased alphanumeric tokens from ``body``. Used by the
        Jaccard strategy; cheap to construct once and reuse for every
        query.
    """

    page_id: str
    title: str
    body: str
    wikilinks: set[str] = field(default_factory=set)
    entity_tokens: set[str] = field(default_factory=set)


@dataclass
class PageIndex:
    """Per-page retrieval index over a wiki project.

    Build once with ``PageIndex.build(pages)``; look up candidates in
    O(1) per strategy. The index never mutates after construction — if
    a page changes, rebuild the index.
    """

    pages: dict[str, PageIndexEntry]

    @classmethod
    def build(cls, pages: list[Any]) -> "PageIndex":
        """Build an index from any list of objects exposing ``id``, ``title``,
        ``body``.

        Wikilinks are extracted via ``re.findall(r"\\[\\[([^\\]]+)\\]\\]", body)``
        and normalized to lowercased, whitespace-collapsed page ids. Entity
        tokens are the lowercase alphanumeric tokens of ``body`` — used by
        the Jaccard strategy.
        """
        entries: dict[str, PageIndexEntry] = {}
        for page in pages:
            page_id = str(getattr(page, "id", "") or "")
            if not page_id:
                continue
            title = str(getattr(page, "title", page_id) or "")
            body = str(getattr(page, "body", "") or "")
            wikilinks: set[str] = set()
            for match in _WIKILINK_RE.findall(body):
                # First segment before '|' (wiki alias syntax) + lowercase.
                target = match.split("|", 1)[0].strip().lower()
                # Internal whitespace → '-'.
                target = re.sub(r"\s+", "-", target)
                if target:
                    wikilinks.add(target)
            tokens = {tok.lower() for tok in _TOKEN_RE.findall(body)}
            entries[page_id] = PageIndexEntry(
                page_id=page_id,
                title=title,
                body=body,
                wikilinks=wikilinks,
                entity_tokens=tokens,
            )
        return cls(pages=entries)

    def get(self, page_id: str) -> PageIndexEntry | None:
        """Return the index entry for ``page_id``, or None if not indexed."""
        return self.pages.get(page_id)


# ---------------------------------------------------------------------------
# RetrievalCandidate + 6 retrieval strategies
# ---------------------------------------------------------------------------


@dataclass
class RetrievalCandidate:
    """One candidate target page surfaced by a retrieval strategy.

    ``score`` is in [0, 1]. ``kind`` distinguishes provenance so the
    review pipeline knows whether to trust the edge (EXPLICIT wikilinks
    are usually trustworthy; HEURISTIC vector neighbors require
    inspection). ``detail`` is a human-readable note about which
    strategy produced the candidate — useful for the LLM prompt and
    debugging.
    """

    target_page_id: str
    score: float
    kind: RelationSupportKind
    detail: str


def _safe_strategy(name: str, fn):
    """Run a retrieval strategy, swallowing any exception.

    Each strategy is wrapped so a single buggy heuristic (e.g. a
    Unicode-normalization corner case) can't crash the whole retrieval
    pipeline. Failures are logged at WARNING; an empty list is returned.
    """
    try:
        return list(fn() or [])
    except Exception:  # pragma: no cover — defensive, see docstring
        logger.warning("candidate_retrieval: %s strategy failed", name, exc_info=True)
        return []


def _strategy_wikilinks(
    source: PageIndexEntry, index: PageIndex
) -> list[RetrievalCandidate]:
    """Strategy 1: explicit [[wikilinks]] in the source body. Score=1.0."""
    candidates: list[RetrievalCandidate] = []
    for link in source.wikilinks:
        if link not in index.pages:
            continue
        if link == source.page_id:
            continue
        candidates.append(
            RetrievalCandidate(
                target_page_id=link,
                score=1.0,
                kind=RelationSupportKind.EXPLICIT,
                detail="wikilink",
            )
        )
    return candidates


def _strategy_entity_jaccard(
    source: PageIndexEntry, index: PageIndex, *, floor: float = 0.3
) -> list[RetrievalCandidate]:
    """Strategy 2: entity overlap (Jaccard) between token sets.

    A Jaccard of ``>= floor`` is required; the score is the Jaccard
    value itself. Sort happens at the top-level dedupe — within this
    strategy we just emit every candidate above the floor.
    """
    src_tokens = source.entity_tokens
    if not src_tokens:
        return []
    candidates: list[RetrievalCandidate] = []
    for entry in index.pages.values():
        if entry.page_id == source.page_id:
            continue
        if not entry.entity_tokens:
            continue
        intersection = src_tokens & entry.entity_tokens
        if not intersection:
            continue
        union = src_tokens | entry.entity_tokens
        score = len(intersection) / len(union)
        if score >= floor:
            candidates.append(
                RetrievalCandidate(
                    target_page_id=entry.page_id,
                    score=score,
                    kind=RelationSupportKind.INFERRED,
                    detail=f"jaccard={score:.2f}",
                )
            )
    return candidates


def _strategy_lexical(
    source: PageIndexEntry, index: PageIndex
) -> list[RetrievalCandidate]:
    """Strategy 3: shared >=5-character tokens (normalized).

    Lower-bar than Jaccard — surfaces page pairs that share at least
    one substantive term (≥5 chars), even if the Jaccard floor rejects
    them because of high background overlap. Score = #shared / #src.
    """
    src_tokens = source.entity_tokens
    if not src_tokens:
        return []
    src_long = {tok for tok in src_tokens if len(tok) >= 5}
    if not src_long:
        return []
    candidates: list[RetrievalCandidate] = []
    for entry in index.pages.values():
        if entry.page_id == source.page_id:
            continue
        shared = src_long & entry.entity_tokens
        if not shared:
            continue
        score = min(1.0, len(shared) / max(1, len(src_long)))
        candidates.append(
            RetrievalCandidate(
                target_page_id=entry.page_id,
                score=score,
                kind=RelationSupportKind.INFERRED,
                detail=f"lexical={len(shared)}",
            )
        )
    return candidates


_ACRONYM_RE = re.compile(r"\b[A-Z]{2,6}\b")


def _strategy_acronym(
    source: PageIndexEntry, index: PageIndex
) -> list[RetrievalCandidate]:
    """Strategy 4: acronym match (e.g. ``RAG`` ↔ ``Retrieval-Augmented Generation``).

    Only multi-word target titles are considered (single-word titles have
    no expansion to compare against). The match is case-insensitive.
    """
    src_acronyms = {m.group(0).lower() for m in _ACRONYM_RE.finditer(source.body)}
    if not src_acronyms:
        return []
    candidates: list[RetrievalCandidate] = []
    for entry in index.pages.values():
        if entry.page_id == source.page_id:
            continue
        title = entry.title.strip()
        if not title or (" " not in title and "-" not in title):
            # Single-word titles don't have an acronym to compare.
            continue
        # Build the acronym of the target title by taking the first
        # letter of each whitespace-separated token.
        tokens = [t for t in re.split(r"[\s\-_]+", title) if t]
        letters: list[str] = []
        for tok in tokens:
            if not tok:
                continue
            first = tok[0]
            if first.isalpha():
                letters.append(first)
        if not letters:
            continue
        target_acronym = "".join(letters).lower()
        if target_acronym in src_acronyms:
            candidates.append(
                RetrievalCandidate(
                    target_page_id=entry.page_id,
                    score=0.6,  # mid-band; explicit wikilinks always beat this
                    kind=RelationSupportKind.INFERRED,
                    detail=f"acronym={target_acronym}",
                )
            )
    return candidates


def _strategy_alias(
    source: PageIndexEntry,
    index: PageIndex,
    aliases: dict[str, str],
) -> list[RetrievalCandidate]:
    """Strategy 5: alias dictionary lookup.

    The alias map is keyed by any form the LLM or wiki body might use
    (a slug, a title variant, an alternate id); values are the canonical
    target page id. Empty dict is the default — the slot is reserved
    so callers can inject aliases later without changing the contract.
    """
    if not aliases:
        return []
    src_title_key = source.title.strip().lower()
    candidates: list[RetrievalCandidate] = []
    for alias_form, target_id in aliases.items():
        if not target_id or target_id not in index.pages:
            continue
        if target_id == source.page_id:
            continue
        if alias_form == source.page_id or alias_form.lower() == src_title_key:
            candidates.append(
                RetrievalCandidate(
                    target_page_id=target_id,
                    score=0.7,
                    kind=RelationSupportKind.INFERRED,
                    detail=f"alias={alias_form}",
                )
            )
    return candidates


def _strategy_vector_neighbor(
    source: PageIndexEntry,
    vector_neighbors: list[tuple[str, float]] | None,
) -> list[RetrievalCandidate]:
    """Strategy 6: pre-computed vector neighbors (optional injection).

    When the caller passes ``vector_neighbors`` for the source page,
    each (page_id, similarity) becomes a HEURISTIC candidate. Scores
    must already be in [0, 1] — we trust whatever the vector store
    returned.
    """
    if not vector_neighbors:
        return []
    candidates: list[RetrievalCandidate] = []
    for target_id, similarity in vector_neighbors:
        if not target_id or target_id == source.page_id:
            continue
        score = max(0.0, min(1.0, float(similarity)))
        candidates.append(
            RetrievalCandidate(
                target_page_id=target_id,
                score=score,
                kind=RelationSupportKind.HEURISTIC,
                detail=f"vector={score:.2f}",
            )
        )
    return candidates


def _dedupe_candidates(
    candidates: list[RetrievalCandidate],
) -> list[RetrievalCandidate]:
    """Keep the highest score per target page id. ``EXPLICIT`` wins
    on ties (a wikilink is more reliable than a fuzzy match at the same
    score)."""
    best: dict[str, RetrievalCandidate] = {}
    for cand in candidates:
        existing = best.get(cand.target_page_id)
        if existing is None:
            best[cand.target_page_id] = cand
            continue
        # Higher score wins.
        if cand.score > existing.score:
            best[cand.target_page_id] = cand
            continue
        # Tied score: prefer EXPLICIT > INFERRED > HEURISTIC.
        if cand.score == existing.score:
            priority = {
                RelationSupportKind.EXPLICIT: 0,
                RelationSupportKind.INFERRED: 1,
                RelationSupportKind.LLM_DIRECT: 1,
                RelationSupportKind.HEURISTIC: 2,
            }
            if priority.get(cand.kind, 99) < priority.get(existing.kind, 99):
                best[cand.target_page_id] = cand
    return list(best.values())


def retrieve_candidates(
    source_page_id: str,
    index: PageIndex,
    *,
    max_candidates: int = MAX_CANDIDATES_PER_PAGE,
    vector_neighbors: list[tuple[str, float]] | None = None,
    aliases: dict[str, str] | None = None,
) -> list[RetrievalCandidate]:
    """Return up to ``max_candidates`` candidates for ``source_page_id``.

    Strategies run in priority order — explicit wikilinks, entity
    Jaccard, lexical overlap, acronym match, alias dictionary, optional
    vector neighbor. Each strategy is wrapped in ``_safe_strategy`` so a
    single failure can't poison the rest. Results are deduped by target
    page id (highest score wins; ties broken by kind priority), capped
    at ``max_candidates``, and sorted score-desc then target_page_id-asc
    for determinism.

    Parameters
    ----------
    source_page_id:
        The page whose outgoing edges we're scoring.
    index:
        A :class:`PageIndex` built over the wiki (or a subset of pages).
    max_candidates:
        Hard cap on returned rows. ``MAX_CANDIDATES_PER_PAGE = 30`` is
        the default; the cap is **clamped** rather than raised so
        callers can't blow past the LLM's effective context window.
    vector_neighbors:
        Optional list of ``(page_id, similarity)`` pairs produced by a
        vector store. When provided, they are added as HEURISTIC
        candidates. ``None`` (the default) skips strategy 6.
    aliases:
        Optional alias map. None means no aliases registered.
    """
    if max_candidates <= 0:
        return []
    # Clamp the cap to the global constant — caller passes a larger
    # value? Hard-cap it; we never want more than 30 rows in the LLM
    # prompt.
    effective_cap = min(max_candidates, MAX_CANDIDATES_PER_PAGE)

    source = index.get(source_page_id)
    if source is None:
        return []

    raw: list[RetrievalCandidate] = []
    raw.extend(_safe_strategy("wikilink", lambda: _strategy_wikilinks(source, index)))
    raw.extend(_safe_strategy("jaccard", lambda: _strategy_entity_jaccard(source, index)))
    raw.extend(_safe_strategy("lexical", lambda: _strategy_lexical(source, index)))
    raw.extend(_safe_strategy("acronym", lambda: _strategy_acronym(source, index)))
    raw.extend(
        _safe_strategy(
            "alias", lambda: _strategy_alias(source, index, aliases or {})
        )
    )
    raw.extend(
        _safe_strategy(
            "vector", lambda: _strategy_vector_neighbor(source, vector_neighbors)
        )
    )

    deduped = _dedupe_candidates(raw)
    deduped.sort(key=lambda c: (-c.score, c.target_page_id))
    return deduped[:effective_cap]


# ---------------------------------------------------------------------------
# LLM prompt rendering + edge parsing (controlled ontology)
# ---------------------------------------------------------------------------


def render_llm_prompt(
    source_page: PageIndexEntry,
    candidates: list[RetrievalCandidate],
) -> str:
    """Render the LLM input prompt.

    The prompt is bounded to the candidate list and the
    ``ALLOWED_PREDICATES_FOR_LLM`` whitelist — the LLM never sees the
    full relation ontology and cannot produce UNRESOLVED directly.
    """
    allowed = ", ".join(ALLOWED_PREDICATES_FOR_LLM)
    lines: list[str] = []
    lines.append(f"Source page: {source_page.title}")
    lines.append("Candidates (cite target_page_id verbatim):")
    for idx, cand in enumerate(candidates, start=1):
        lines.append(
            f"  {idx}. target={cand.target_page_id} "
            f"(score={cand.score:.2f}, kind={cand.kind.value})"
        )
    lines.append("")
    lines.append("Allowed predicates (use EXACTLY these):")
    lines.append(f"  {allowed}")
    lines.append("")
    lines.append("Return JSON:")
    lines.append(
        '  {"edges": [{"target": "...", "predicate": "...", "context": "..."}]}'
    )
    return "\n".join(lines)


def _strip_json_fence(text: str) -> str:
    """Remove ```json ... ``` fences from a model response."""
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    return match.group(1) if match else text.strip()


def parse_llm_edges(
    raw: str,
    *,
    source_page_id: str,
    candidates: list[RetrievalCandidate],
    extractor_fingerprint: str,
) -> list[RelationAssertion]:
    """Parse the LLM JSON response into ``RelationAssertion`` rows.

    Rules (Task 25 contract):

    * Unknown predicate → ``RelationPredicate.UNRESOLVED`` +
      ``RelationSupportStatus.UNRESOLVED`` (the LLM didn't know the
      predicate; we surface the evidence rather than drop it silently).
    * Target page id not in the candidate list →
      ``RelationSupportStatus.REJECTED`` (the LLM invented a target).
    * Self-loop (source == target) →
      ``RelationSupportStatus.REJECTED``.
    * Every edge produces a ``RelationAssertion`` — we never raise on
      bad JSON. Garbage JSON yields an empty list (no assertions).

    The ``support_kind`` of every returned assertion is
    ``RelationSupportKind.LLM_DIRECT`` because the row is produced by
    the LLM, regardless of what retrieval strategy produced the
    underlying candidate.
    """
    candidate_ids = {c.target_page_id for c in candidates}
    try:
        payload = json.loads(_strip_json_fence(raw))
    except (ValueError, TypeError):
        logger.warning("parse_llm_edges: invalid JSON from LLM")
        return []

    edges = payload.get("edges", []) if isinstance(payload, dict) else []
    if not isinstance(edges, list):
        return []

    assertions: list[RelationAssertion] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        target_id = str(edge.get("target", "") or "").strip()
        if not target_id:
            continue
        raw_predicate = str(edge.get("predicate", "") or "").strip()
        predicate = coerce(raw_predicate)
        context = str(edge.get("context", "") or "")

        if predicate is not RelationPredicate.UNRESOLVED:
            status = RelationSupportStatus.SUPPORTED
        else:
            status = RelationSupportStatus.UNRESOLVED

        # Self-loop or off-list target → REJECTED (overrides status).
        if target_id == source_page_id:
            status = RelationSupportStatus.REJECTED
        elif target_id not in candidate_ids:
            status = RelationSupportStatus.REJECTED

        key = RelationKey(source_page_id, predicate, target_id)
        assertions.append(
            RelationAssertion(
                key=key,
                relation_id=key.relation_id(),
                support_kind=RelationSupportKind.LLM_DIRECT,
                support_status=status,
                evidence_refs=[{"context": context}] if context else [],
                claim_ids=[],
                confidence=0.5,
                extractor_fingerprint=extractor_fingerprint,
            )
        )

    return assertions


__all__ = [
    "MAX_CANDIDATES_PER_PAGE",
    "ALLOWED_PREDICATES_FOR_LLM",
    "PageIndexEntry",
    "PageIndex",
    "RetrievalCandidate",
    "retrieve_candidates",
    "render_llm_prompt",
    "parse_llm_edges",
]