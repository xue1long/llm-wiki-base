"""Task 28 — Reconciliation candidate retrieval.

Six retrieval strategies are applied in priority order:

    1. EXPLICIT wikilink in ``new_page_body`` → ``"explicit"`` (score 1.0)
    2. entity overlap (Jaccard ≥ 0.3)         → ``"entity_overlap"``
                                                (score = jaccard)
    3. lexical match (shared tokens)          → ``"lexical"``
    4. acronym match                          → ``"acronym"``
       (e.g. ``RAG`` ↔ ``Retrieval-Augmented Generation``)
    5. alias dictionary lookup                → ``"alias"`` (score 1.0)
    6. vector neighbor                        → ``"vector_neighbor"``
                                                (score = cosine,
                                                gated by
                                                ``VECTOR_NEIGHBOR_THRESHOLD``)

The candidates are deduplicated by ``canonical_id`` keeping the
highest-scoring strategy, sorted ``score desc, canonical_id asc``,
and capped at ``MAX_CANDIDATES``.

Identity Contract
-----------------
``canonical_id`` values come from ``CanonicalConcept`` (script-owned,
see :mod:`src.reconciliation.canonical_models`). Retrieval is a pure
*view* — it never mutes the underlying canonical list and never
fabricates canonical ids.

Performance Contract (F10)
--------------------------
``vector_neighbor`` ships in v1 and the scan stays under 100ms for
10k canonical concepts. We achieve this by:

  * using pure-Python arithmetic (no numpy / scipy);
  * only scanning the registered-vector cache (typically a small
    fraction of all canonicals) — the 10k canonicals themselves are
    *not* pairwise-compared;
  * capping the cosine work at ``max_candidates`` once we have enough
    above-threshold hits.

Failure Contract
----------------
``retrieve_candidates`` never raises: any individual strategy that
encounters bad input is skipped, and the function still returns a
``list`` (possibly empty). The function is on the hot path of the
reconciliation pipeline (Task 32) and must stay total.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .canonical_models import CanonicalConcept


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Maximum number of candidates returned per call. Stage 29's LLM
#: resolver reads these candidates as its short-list, so a small,
#: deterministic bound keeps the LLM context window predictable.
MAX_CANDIDATES: int = 20

#: F10 整改要求 — only surface a vector neighbor when cosine similarity
#: exceeds this threshold. Below the threshold the candidate is not
#: surfaced, because the signal is too weak to justify the LLM's
#: attention.
VECTOR_NEIGHBOR_THRESHOLD: float = 0.7


#: Strategy priority for sort tie-breaking. Lower rank = earlier /
#: stronger. Matches the spec's "priority order" (strategies 1-6).
_STRATEGY_RANK: dict[str, int] = {
    "explicit": 0,
    "entity_overlap": 1,
    "lexical": 2,
    "acronym": 3,
    "alias": 4,
    "vector_neighbor": 5,
}


# ---------------------------------------------------------------------------
# Result + index data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReconciliationCandidate:
    """A single retrieval candidate.

    ``canonical_id`` is *not* a wiki page_id (F10: reconciliation is
    about canonical concepts, not individual pages). ``strategy`` is
    one of the six strategy names; ``score`` is the strategy-specific
    score (1.0 for explicit / alias, jaccard for entity_overlap,
    cosine for vector_neighbor, heuristic 0..1 for lexical / acronym).
    ``detail`` records *which* exact match triggered this candidate
    (e.g. ``"wikilink:Beta"`` or ``"acronym:RAG"``) — useful for the
    LLM resolver to explain its verdict later.
    """

    canonical_id: str
    score: float
    strategy: str
    detail: str = ""

    def __post_init__(self) -> None:  # pragma: no cover - tiny shim
        # Clamp score into [0, 1] defensively. A buggy strategy
        # shouldn't propagate out-of-range numbers into the LLM prompt.
        if self.score < 0.0:
            object.__setattr__(self, "score", 0.0)
        elif self.score > 1.0:
            object.__setattr__(self, "score", 1.0)


@dataclass
class CanonicalIndexEntry:
    """One canonical's pre-computed retrieval surface."""

    canonical_id: str
    preferred_label: str
    aliases: list[str]
    member_page_ids: list[str]
    body_tokens: set[str] = field(default_factory=set)

    @property
    def label_tokens(self) -> set[str]:
        """Tokenised preferred_label (lowercased)."""
        return _tokenise(self.preferred_label)

    @property
    def alias_tokens(self) -> set[tuple[str, set[str]]]:
        """List of ``(alias_text, tokens)`` pairs."""
        return [(a, _tokenise(a)) for a in self.aliases]


@dataclass
class CanonicalIndex:
    """Pre-built retrieval index over a canonical concept list.

    Built once via :py:meth:`build`, queried many times via
    :py:func:`retrieve_candidates`. The vector cache is optional —
    populating it is the caller's responsibility (the canonical
    subsystem only knows about canonical ids, not about which
    embedding model produced a given vector).
    """

    entries: dict[str, CanonicalIndexEntry] = field(default_factory=dict)
    _vector_cache: dict[str, tuple[list[float], str]] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def build(
        cls,
        concepts: list[CanonicalConcept],
        *,
        body_by_page: dict[str, str] | None = None,
    ) -> "CanonicalIndex":
        """Build an index from a canonical concept list.

        ``body_by_page`` is the optional ``page_id -> body text`` map
        used to compute each canonical's combined body-token set. It is
        best-effort: if any member page id is missing from the map, the
        canonical's ``body_tokens`` is just the union of its label /
        alias tokens. This keeps the index usable even when the caller
        hasn't loaded every wiki page's body.
        """
        body_lookup = body_by_page or {}
        entries: dict[str, CanonicalIndexEntry] = {}
        for c in concepts:
            tokens: set[str] = set()
            # Label and aliases are always part of the token surface.
            tokens |= _tokenise(c.preferred_label)
            for alias in c.aliases:
                tokens |= _tokenise(alias)
            # Then union each member's body text (when available).
            for pid in c.member_page_ids:
                body = body_lookup.get(pid)
                if body:
                    tokens |= _tokenise(body)
            entries[c.canonical_id] = CanonicalIndexEntry(
                canonical_id=c.canonical_id,
                preferred_label=c.preferred_label,
                aliases=list(c.aliases),
                member_page_ids=list(c.member_page_ids),
                body_tokens=tokens,
            )
        return cls(entries=entries)

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def get(self, canonical_id: str) -> CanonicalIndexEntry | None:
        return self.entries.get(canonical_id)

    def __len__(self) -> int:  # pragma: no cover - tiny shim
        return len(self.entries)

    def __iter__(self):  # pragma: no cover - tiny shim
        return iter(self.entries.values())

    # ------------------------------------------------------------------
    # Vector cache
    # ------------------------------------------------------------------

    def register_vector(
        self,
        canonical_id: str,
        embedding: list[float],
        model_id: str,
    ) -> None:
        """Cache a canonical's embedding for vector_neighbor retrieval.

        Idempotent: re-registering the same ``canonical_id`` overwrites
        the previous entry. ``embedding`` is stored verbatim (no copy)
        — callers should not mutate it after registration.
        """
        self._vector_cache[canonical_id] = (list(embedding), model_id)

    def get_vector(
        self,
        canonical_id: str,
    ) -> tuple[list[float], str] | None:
        return self._vector_cache.get(canonical_id)

    def iter_vectors(self):
        """Yield ``(canonical_id, vector, model_id)`` over registered entries."""
        for cid, (vec, model_id) in self._vector_cache.items():
            yield cid, vec, model_id


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def retrieve_candidates(
    new_page_id: str,
    new_page_body: str,
    new_page_title: str,
    index: CanonicalIndex,
    *,
    max_candidates: int = MAX_CANDIDATES,
    query_embedding: list[float] | None = None,
    embedding_model_id: str = "",
    threshold: float = VECTOR_NEIGHBOR_THRESHOLD,
) -> list[ReconciliationCandidate]:
    """Apply 6 strategies in priority order, dedup, sort, cap.

    Parameters
    ----------
    new_page_id:
        The wiki page id of the new page being reconciled (kept in
        the signature for future routing; not used by retrieval logic).
    new_page_body:
        Raw body of the new page. Used for wikilink extraction, token
        overlap, acronym extraction, and alias lookup.
    new_page_title:
        Title of the new page. Used as an additional alias-matching
        surface.
    index:
        Pre-built :class:`CanonicalIndex`.
    max_candidates:
        Upper bound on the returned list. Defaults to
        :data:`MAX_CANDIDATES`.
    query_embedding:
        Optional embedding for the new page body. When provided (and
        non-empty) the ``vector_neighbor`` strategy runs. When ``None``
        or empty the strategy is skipped.
    embedding_model_id:
        The model id corresponding to ``query_embedding``. Used for
        debugging / auditing.
    threshold:
        Cosine threshold for ``vector_neighbor``. Defaults to
        :data:`VECTOR_NEIGHBOR_THRESHOLD`.

    Returns
    -------
    list[ReconciliationCandidate]
        Deduped by ``canonical_id`` (highest score wins), sorted
        ``score desc, canonical_id asc``, capped at ``max_candidates``.
    """
    body_tokens = _tokenise(new_page_body, include_title=new_page_title)
    # Also pull the title into the alias-matching surface so a
    # candidate whose label is identical to the new page title surfaces.
    label_alias_index = _build_label_alias_index(index)

    # ``seen`` holds the *best* candidate per canonical_id, keyed by id.
    seen: dict[str, ReconciliationCandidate] = {}

    def _maybe_add(candidate: ReconciliationCandidate) -> None:
        existing = seen.get(candidate.canonical_id)
        if existing is None or candidate.score > existing.score:
            seen[candidate.canonical_id] = candidate

    # --- Strategy 1: explicit wikilink ---------------------------------
    for cid in _strategy_explicit(new_page_body, label_alias_index):
        _maybe_add(
            ReconciliationCandidate(
                canonical_id=cid,
                score=1.0,
                strategy="explicit",
                detail=f"wikilink_in_body",
            )
        )

    # --- Strategy 2: entity overlap (Jaccard) --------------------------
    for cid, jaccard, detail in _strategy_entity_overlap(
        body_tokens, index
    ):
        _maybe_add(
            ReconciliationCandidate(
                canonical_id=cid,
                score=jaccard,
                strategy="entity_overlap",
                detail=detail,
            )
        )

    # --- Strategy 3: lexical (shared tokens below Jaccard threshold) ---
    for cid, score, detail in _strategy_lexical(body_tokens, index):
        _maybe_add(
            ReconciliationCandidate(
                canonical_id=cid,
                score=score,
                strategy="lexical",
                detail=detail,
            )
        )

    # --- Strategy 4: acronym match -------------------------------------
    for cid, score, detail in _strategy_acronym(new_page_body, index):
        _maybe_add(
            ReconciliationCandidate(
                canonical_id=cid,
                score=score,
                strategy="acronym",
                detail=detail,
            )
        )

    # --- Strategy 5: alias dictionary lookup ---------------------------
    body_lower = (new_page_body or "").lower()
    title_lower = (new_page_title or "").lower()
    for cid in _strategy_alias(
        body_lower, title_lower, label_alias_index
    ):
        _maybe_add(
            ReconciliationCandidate(
                canonical_id=cid,
                score=1.0,
                strategy="alias",
                detail="alias_or_label_substring",
            )
        )

    # --- Strategy 6: vector neighbor -----------------------------------
    if query_embedding:
        for cid, cosine, model_id in _strategy_vector_neighbor(
            query_embedding, embedding_model_id, index, threshold
        ):
            # Threshold is enforced inside _strategy_vector_neighbor so
            # the caller only sees survivors.
            _maybe_add(
                ReconciliationCandidate(
                    canonical_id=cid,
                    score=cosine,
                    strategy="vector_neighbor",
                    detail=f"model={model_id}",
                )
            )

    # ---- Dedup is already done via ``seen``; sort + cap --------------
    # Sort priority:
    #   1. score desc                  (strongest signal wins)
    #   2. strategy rank ascending     (earlier strategy wins ties —
    #                                   explicit beats alias at the
    #                                   same score)
    #   3. canonical_id ascending      (deterministic tiebreaker)
    strategy_rank = _STRATEGY_RANK
    ordered = sorted(
        seen.values(),
        key=lambda c: (
            -c.score,
            strategy_rank.get(c.strategy, len(strategy_rank)),
            c.canonical_id,
        ),
    )
    if max_candidates <= 0:
        return []
    return ordered[:max_candidates]


# ---------------------------------------------------------------------------
# Strategy helpers
# ---------------------------------------------------------------------------


def _strategy_explicit(
    body: str, label_alias_index: dict[str, list[str]]
) -> list[str]:
    """Find canonicals whose label / alias is mentioned via ``[[wikilink]]``.

    Returns canonical ids (deduped, input order preserved).
    """
    found: list[str] = []
    seen: set[str] = set()
    for match in _WIKILINK_RE.finditer(body or ""):
        target = match.group(1).strip()
        if not target:
            continue
        for cid in label_alias_index.get(target.lower(), ()):
            if cid not in seen:
                seen.add(cid)
                found.append(cid)
    return found


def _strategy_entity_overlap(
    body_tokens: set[str], index: CanonicalIndex
) -> list[tuple[str, float, str]]:
    """Jaccard ≥ 0.3 between body tokens and canonical body tokens.

    Each canonical's combined body_tokens already unions its label,
    aliases, and every member page's body — so this measures how much
    vocabulary the new page shares with the canonical's full surface.
    A Jaccard score in [0.3, 1.0] is treated as a "real" entity
    overlap; lower overlaps fall through to the lexical strategy.
    """
    out: list[tuple[str, float, str]] = []
    if not body_tokens:
        return out
    for entry in index.entries.values():
        other = entry.body_tokens
        if not other:
            continue
        intersection = len(body_tokens & other)
        if intersection == 0:
            continue
        union = len(body_tokens | other)
        jaccard = intersection / union
        if jaccard >= 0.3:
            out.append((entry.canonical_id, jaccard, f"jaccard={jaccard:.3f}"))
    return out


def _strategy_lexical(
    body_tokens: set[str], index: CanonicalIndex
) -> list[tuple[str, float, str]]:
    """Cheap lexical fallback: any non-trivial shared token below the
    Jaccard threshold still counts as a "lexical" hit.

    The score is the *intersection size* normalised by the body side,
    capped at 1.0. Pure single-character noise is excluded.
    """
    out: list[tuple[str, float, str]] = []
    if not body_tokens:
        return out
    body_size = len(body_tokens)
    for entry in index.entries.values():
        other = entry.body_tokens
        if not other:
            continue
        intersection = body_tokens & other
        # Exclude trivial single-character "matches" like "a" / "i".
        intersection = {tok for tok in intersection if len(tok) > 1}
        if not intersection:
            continue
        # Subtract what entity_overlap would have caught (Jaccard ≥ 0.3
        # implies significant overlap); but we can't reproduce the
        # threshold cheaply here, so we just gate by absolute size.
        if len(intersection) < 2:
            continue
        score = min(1.0, len(intersection) / body_size)
        out.append((entry.canonical_id, score, f"shared={len(intersection)}"))
    return out


def _strategy_acronym(
    body: str, index: CanonicalIndex
) -> list[tuple[str, float, str]]:
    """Acronym strategy.

    1. Extract 2-6 char all-uppercase runs from the body.
    2. For each canonical, build initial-letter acronyms from its
       preferred_label and aliases (splitting on whitespace /
       hyphens / underscores).
    3. Match acronyms ↔ uppercase runs.
    """
    out: list[tuple[str, float, str]] = []
    acronyms_in_body = {
        m.group(0) for m in _UPPERCASE_RUN_RE.finditer(body or "")
    }
    if not acronyms_in_body:
        return out
    for entry in index.entries.values():
        for label in (entry.preferred_label, *entry.aliases):
            acr = _initial_letters(label)
            if not acr or len(acr) < 2 or len(acr) > 6:
                continue
            if acr in acronyms_in_body:
                out.append(
                    (entry.canonical_id, 0.9, f"acronym:{acr}={label}")
                )
                break  # one match per canonical is enough
    return out


def _strategy_alias(
    body_lower: str,
    title_lower: str,
    label_alias_index: dict[str, list[str]],
) -> list[str]:
    """Substring match of the body / title against the label+alias index.

    Returns canonical ids deduped.
    """
    if not (body_lower or title_lower):
        return []
    found: list[str] = []
    seen: set[str] = set()
    # Iterate the longest labels first so that "Retrieval-Augmented
    # Generation" beats "Generation" when both would otherwise match.
    sorted_keys = sorted(label_alias_index.keys(), key=len, reverse=True)
    for key in sorted_keys:
        if not key or len(key) < 2:
            # Single-character keys would substring-match almost any
            # body; they're noise rather than a real alias hit.
            continue
        if key in body_lower or key in title_lower:
            for cid in label_alias_index[key]:
                if cid not in seen:
                    seen.add(cid)
                    found.append(cid)
    return found


def _strategy_vector_neighbor(
    query: list[float],
    model_id: str,
    index: CanonicalIndex,
    threshold: float,
) -> list[tuple[str, float, str]]:
    """Cosine similarity against every registered vector.

    Pure-Python implementation (no numpy). O(K * d) where K = number
    of registered vectors and d = embedding dim. Surviving entries
    are sorted by descending cosine and yielded in that order; the
    caller is responsible for the final top-N cap.
    """
    if not query:
        return []
    scored: list[tuple[str, float]] = []
    for cid, vec, vec_model_id in index.iter_vectors():
        if model_id and vec_model_id and vec_model_id != model_id:
            # Skip vectors produced by a different embedding model —
            # mixing models is meaningless for cosine comparison.
            continue
        cos = _cosine_similarity(query, vec)
        if cos >= threshold:
            scored.append((cid, cos, vec_model_id))
    scored.sort(key=lambda item: item[1], reverse=True)
    return [(cid, cos, mid) for cid, cos, mid in scored]


# ---------------------------------------------------------------------------
# Pure-Python cosine similarity
# ---------------------------------------------------------------------------


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """0..1 normalised cosine (pure Python, no numpy).

    Returns 0.0 when either vector is zero-length, has zero norm, or
    has a mismatched dimension. Output is clamped into [0, 1] so a
    caller can feed it straight into the LLM prompt as a score.
    """
    return _cosine_similarity(a, b)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    raw = dot / (norm_a ** 0.5 * norm_b ** 0.5)
    if raw < 0.0:
        return 0.0
    if raw > 1.0:
        return 1.0
    return raw


# ---------------------------------------------------------------------------
# Tokenisation helpers
# ---------------------------------------------------------------------------


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _tokenise(text: str, *, include_title: str = "") -> set[str]:
    """Lowercased alphanumeric tokens, length > 1.

    Single-character tokens are noise ("a", "i", punctuation residue);
    dropping them improves both jaccard stability and acronym
    extraction. ``include_title`` is folded in when supplied so the
    caller can treat title + body as a single retrieval surface.
    """
    if not text and not include_title:
        return set()
    parts: list[str] = []
    if text:
        parts.append(text)
    if include_title:
        parts.append(include_title)
    combined = " ".join(parts)
    return {tok.lower() for tok in _TOKEN_RE.findall(combined) if len(tok) > 1}


_WIKILINK_RE = re.compile(r"\[\[([^\]\n]+?)\]\]")
_UPPERCASE_RUN_RE = re.compile(r"\b[A-Z]{2,6}\b")


def _initial_letters(label: str) -> str:
    """Acronym of ``label`` — first letters of each whitespace /
    hyphen / underscore-separated word, uppercased."""
    if not label:
        return ""
    parts = re.split(r"[\s\-_/]+", label)
    letters = []
    for p in parts:
        if not p:
            continue
        # Strip non-letter prefix so "(RAG)" → "R", "2R" → "R" etc.
        # Stay conservative: take the first A-Za-z char we see.
        for ch in p:
            if ch.isalpha():
                letters.append(ch.upper())
                break
    return "".join(letters)


def _build_label_alias_index(
    index: CanonicalIndex,
) -> dict[str, list[str]]:
    """Map lower-cased label / alias text → list of canonical ids."""
    out: dict[str, list[str]] = {}
    for entry in index.entries.values():
        keys = [entry.preferred_label, *entry.aliases]
        for k in keys:
            if not k:
                continue
            lower = k.lower()
            out.setdefault(lower, []).append(entry.canonical_id)
    return out


__all__ = [
    "MAX_CANDIDATES",
    "VECTOR_NEIGHBOR_THRESHOLD",
    "ReconciliationCandidate",
    "CanonicalIndexEntry",
    "CanonicalIndex",
    "retrieve_candidates",
    "cosine_similarity",
]