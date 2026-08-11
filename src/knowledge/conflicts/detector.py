"""ConflictDetector — two-stage contradiction detection for claims.

Stage 1 — Candidate Screening:
    Group claims by entity, then compute text similarity (Jaccard word overlap).
    Only compare claim pairs with similarity >= 0.25.

Stage 2 — Contradiction Determination:
    Use negation keyword list + lightweight heuristics.
    LLM is reserved for the large-entity path (Phase 2+).

Performance boundary: when an entity has > 500 claims, skip pairwise
comparison and sample 100 claims for pairwise detection instead.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

from src.knowledge.claims.model import Claim


# ---------------------------------------------------------------------------
# Report type
# ---------------------------------------------------------------------------
@dataclass
class ConflictReport:
    """A detected conflict between two claims about the same entity."""

    claim_a: str          # Claim ID
    claim_b: str          # Claim ID
    entity: str           # Entity name these claims are about
    conflict_type: str    # "contradiction" | "disagreement" | "inconsistency"
    suggested_resolution: str  # Human-readable suggestion
    confidence: float     # How confident the detector is that this is a real conflict


# ---------------------------------------------------------------------------
# Resolution templates per conflict type
# ---------------------------------------------------------------------------
_RESOLUTION_TEMPLATES: dict[str, str] = {
    "contradiction": (
        "Claims contradict each other. Verify which claim has stronger evidence."
    ),
    "disagreement": (
        "Claims disagree on the same topic. Check source reliability and "
        "evidence quality."
    ),
    "inconsistency": (
        "Both claims contain negation patterns. May need human review to "
        "determine the factual state."
    ),
}

# ---------------------------------------------------------------------------
# ConflictDetector
# ---------------------------------------------------------------------------
class ConflictDetector:
    """Two-stage conflict detection for claims about the same entity.

    Stage 1 — Candidate Screening:
        Group claims by entity, then compute embedding similarity.
        Only compare claim pairs within the same entity group with
        similarity >= 0.25 (Jaccard word overlap).

    Stage 2 — Contradiction Determination:
        Use negation keyword list + lightweight heuristics.
        LLM判定 is called for borderline cases only.

    Performance boundary: when an entity has > 500 claims, skip pairwise
    comparison and sample 100 claims for a pairwise detection instead.
    """

    # Word-level negation keywords (single tokens)
    _NEGATION_WORDS: set[str] = {
        "not",
        "never",
        "no",
        "cannot",
        "false",
        "incorrect",
        "wrong",
        "contrary",
        "opposite",
        "however",
    }

    # Contraction → expanded form mapping (applied before tokenization)
    _CONTRACTION_MAP: dict[str, str] = {
        "doesn't": "does not",
        "don't": "do not",
        "won't": "will not",
        "can't": "cannot",
        "isn't": "is not",
        "aren't": "are not",
        "wasn't": "was not",
        "weren't": "were not",
        "haven't": "have not",
        "hasn't": "has not",
        "hadn't": "had not",
        "shouldn't": "should not",
        "wouldn't": "would not",
        "couldn't": "could not",
        "mightn't": "might not",
        "mustn't": "must not",
        "needn't": "need not",
    }

    # Phrase-level negation patterns (substring matched in raw text)
    _NEGATION_PHRASES: list[str] = [
        "in fact",
        "but actually",
    ]

    _WORD_OVERLAP_THRESHOLD: float = 0.25

    _LARGE_ENTITY_THRESHOLD: int = 500
    _SAMPLE_SIZE: int = 100

    _NEAR_IDENTICAL_THRESHOLD: float = 0.9

    def __init__(self, llm_provider=None):
        """Initialise the detector.

        Args:
            llm_provider: Optional LLM provider for Phase 2+ large-entity
                detection. Not used in Phase 1.
        """
        self.negation_keywords = sorted(self._NEGATION_WORDS)
        self.llm = llm_provider

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(
        self, claims: list[Claim], entity_name: str = ""
    ) -> list[ConflictReport]:
        """Run conflict detection on a set of claims.

        If *entity_name* is provided, claims whose statement does not
        mention the entity are excluded before comparison.  This prevents
        cross-entity false positives.

        Args:
            claims: The claims to check for conflicts.
            entity_name: Optional entity scope — only claims mentioning
                this name are compared.

        Returns:
            A list of ConflictReport, one per detected conflict pair.
            Empty list when there are 0 or 1 claims.
        """
        if len(claims) <= 1:
            return []

        # Filter by entity_name if provided
        if entity_name:
            claims = self._filter_by_entity(claims, entity_name)
            if len(claims) <= 1:
                return []

        # Performance boundary: large entity → sample mode
        if len(claims) > self._LARGE_ENTITY_THRESHOLD:
            return self._handle_large_entity(claims, entity_name)

        return self._detect_full(claims, entity_name)

    # ------------------------------------------------------------------
    # Stage 1 — Candidate Screening
    # ------------------------------------------------------------------

    def _screen_candidates(self, claims: list[Claim]) -> list[tuple[Claim, Claim]]:
        """Stage 1: find claim pairs that might conflict.

        Uses Jaccard word-overlap similarity as the primary method.
        If an embedding provider were configured, cosine similarity with
        threshold 0.85 would be used instead (Phase 2+).

        Returns:
            List of (claim_a, claim_b) tuples sorted by descending similarity.
        """
        candidates: list[tuple[Claim, Claim]] = []
        n = len(claims)

        for i in range(n):
            for j in range(i + 1, n):
                similarity = self._compute_similarity(claims[i], claims[j])
                if similarity >= self._WORD_OVERLAP_THRESHOLD:
                    candidates.append((claims[i], claims[j]))

        return candidates

    # ------------------------------------------------------------------
    # Stage 2 — Contradiction Determination
    # ------------------------------------------------------------------

    def _check_contradiction(
        self, claim_a: Claim, claim_b: Claim
    ) -> ConflictReport | None:
        """Stage 2: determine if two similar claims actually contradict each other.

        Returns a ConflictReport if a conflict is detected, or None.
        """
        text_a = claim_a.statement.lower().strip()
        text_b = claim_b.statement.lower().strip()

        # Identical statements are not conflicts
        if text_a == text_b:
            return None

        # Near-identical statements (Jaccard > 0.9) are not conflicts
        similarity = self._compute_similarity(claim_a, claim_b)
        if similarity > self._NEAR_IDENTICAL_THRESHOLD:
            return None

        has_neg_a = self._has_negation(text_a)
        has_neg_b = self._has_negation(text_b)

        # Core heuristic: one claim has negation, the other doesn't → contradiction
        if has_neg_a != has_neg_b:
            return ConflictReport(
                claim_a=claim_a.id,
                claim_b=claim_b.id,
                entity="",
                conflict_type="contradiction",
                suggested_resolution=_RESOLUTION_TEMPLATES["contradiction"],
                confidence=0.9,
            )

        # Both have negation → inconsistency
        if has_neg_a and has_neg_b:
            return ConflictReport(
                claim_a=claim_a.id,
                claim_b=claim_b.id,
                entity="",
                conflict_type="inconsistency",
                suggested_resolution=_RESOLUTION_TEMPLATES["inconsistency"],
                confidence=0.5,
            )

        # High similarity without negation → disagreement (weaker signal)
        if similarity > 0.5:
            return ConflictReport(
                claim_a=claim_a.id,
                claim_b=claim_b.id,
                entity="",
                conflict_type="disagreement",
                suggested_resolution=_RESOLUTION_TEMPLATES["disagreement"],
                confidence=0.6,
            )

        return None

    def _check_negation(self, text_a: str, text_b: str) -> bool:
        """Check if statements contain opposing negation patterns.

        Returns True when exactly one of the two texts contains negation
        keywords, indicating a potential contradiction.
        """
        has_neg_a = self._has_negation(text_a)
        has_neg_b = self._has_negation(text_b)
        return has_neg_a != has_neg_b

    # ------------------------------------------------------------------
    # Large entity handling
    # ------------------------------------------------------------------

    def _handle_large_entity(
        self, claims: list[Claim], entity_name: str
    ) -> list[ConflictReport]:
        """For entities with > 500 claims: sample 100, check pairwise within sample.

        This avoids O(N^2) comparison on very large claim sets while still
        providing meaningful conflict detection on a representative sample.
        """
        sampled = random.sample(claims, min(self._SAMPLE_SIZE, len(claims)))
        return self._detect_full(sampled, entity_name)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """Tokenize text into lowercase word set, stripping punctuation."""
        return set(re.findall(r"\b\w+\b", text.lower()))

    @staticmethod
    def _compute_similarity(claim_a: Claim, claim_b: Claim) -> float:
        """Compute Jaccard word-overlap similarity between two claims.

        Returns a float in [0.0, 1.0].
        """
        words_a = ConflictDetector._tokenize(claim_a.statement)
        words_b = ConflictDetector._tokenize(claim_b.statement)
        if not words_a or not words_b:
            return 0.0
        intersection = words_a & words_b
        union = words_a | words_b
        return len(intersection) / len(union)

    def _has_negation(self, text: str) -> bool:
        """Check if text contains negation keywords or phrases."""
        lower = text.lower()

        # Check phrase-level patterns (substring match in raw text)
        for phrase in self._NEGATION_PHRASES:
            if phrase in lower:
                return True

        # Normalize contractions (e.g. "doesn't" → "does not") so that
        # single-word negation keywords like "not" and "cannot" are
        # detected via tokenization.
        normalized = lower
        for contraction, expanded in self._CONTRACTION_MAP.items():
            normalized = normalized.replace(contraction, expanded)

        # Check single-word tokens (exact word match via tokenization)
        tokens = self._tokenize(normalized)
        if tokens & self._NEGATION_WORDS:
            return True

        return False

    @staticmethod
    def _filter_by_entity(
        claims: list[Claim], entity_name: str
    ) -> list[Claim]:
        """Filter claims to only those mentioning the given entity name."""
        entity_lower = entity_name.lower()
        return [c for c in claims if entity_lower in c.statement.lower()]

    def _detect_full(
        self, claims: list[Claim], entity_name: str
    ) -> list[ConflictReport]:
        """Run full two-stage detection on a claim set.

        This is the core algorithm shared by both normal and sampled paths.
        """
        # Stage 1 — Candidate Screening
        candidates = self._screen_candidates(claims)

        # Stage 2 — Contradiction Determination
        reports: list[ConflictReport] = []
        for claim_a, claim_b in candidates:
            report = self._check_contradiction(claim_a, claim_b)
            if report is not None:
                report.entity = entity_name
                reports.append(report)

        return reports
