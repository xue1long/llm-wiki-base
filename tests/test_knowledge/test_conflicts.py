"""Test ConflictDetector — two-stage contradiction detection (Task 2.5)."""
import time


from src.knowledge.claims.model import Claim
from src.knowledge.conflicts.detector import ConflictDetector, ConflictReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_claim(cid: str, statement: str) -> Claim:
    """Create a minimal Claim for testing."""
    return Claim(id=cid, statement=statement)


def _make_claims(statements: list[tuple[str, str]]) -> list[Claim]:
    """Create multiple claims from (id, statement) pairs."""
    return [Claim(id=cid, statement=stmt) for cid, stmt in statements]


# ---------------------------------------------------------------------------
# Test 1: No conflict — identical claims
# ---------------------------------------------------------------------------


class TestNoConflictIdenticalClaims:
    """Two claims with the same statement produce no conflict."""

    def test_identical_statements_no_conflict(self):
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "Kafka guarantees message ordering."),
            _make_claim("2", "Kafka guarantees message ordering."),
        ]
        reports = detector.detect(claims)
        assert reports == [], (
            f"Identical statements should not conflict, got {len(reports)} reports"
        )

    def test_near_identical_statements_no_conflict(self):
        """Claims that differ only by punctuation/case are near-identical."""
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "Kafka guarantees ordering"),
            _make_claim("2", "Kafka guarantees ordering."),
        ]
        reports = detector.detect(claims)
        # After tokenization these are identical → no conflict
        assert len(reports) == 0


# ---------------------------------------------------------------------------
# Test 2: Negation contradiction
# ---------------------------------------------------------------------------


class TestNegationContradiction:
    """Claims with opposing negation patterns are detected as contradictions."""

    def test_direct_negation_contradiction(self):
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "Kafka guarantees ordering"),
            _make_claim("2", "Kafka does not guarantee ordering"),
        ]
        reports = detector.detect(claims)
        assert len(reports) == 1, f"Expected 1 conflict, got {len(reports)}"
        r = reports[0]
        assert r.claim_a in ("1", "2")
        assert r.claim_b in ("1", "2")
        assert r.claim_a != r.claim_b

    def test_contradiction_report_has_correct_type(self):
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "Data is encrypted at rest"),
            _make_claim("2", "Data is not encrypted at rest"),
        ]
        reports = detector.detect(claims)
        assert len(reports) == 1
        assert reports[0].conflict_type == "contradiction"

    def test_contradiction_confidence_is_high(self):
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "The system supports failover"),
            _make_claim("2", "The system does not support failover"),
        ]
        reports = detector.detect(claims)
        assert len(reports) == 1
        assert reports[0].confidence >= 0.8, (
            f"Expected high confidence for contradiction, got {reports[0].confidence}"
        )


# ---------------------------------------------------------------------------
# Test 3: No conflict — different topics
# ---------------------------------------------------------------------------


class TestNoConflictDifferentTopics:
    """Claims about unrelated topics should not be flagged."""

    def test_unrelated_topics_no_conflict(self):
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "Python is slow"),
            _make_claim("2", "Java has generics"),
        ]
        reports = detector.detect(claims)
        assert reports == [], (
            f"Unrelated topics should not conflict, got {len(reports)} reports"
        )

    def test_unrelated_with_negation_still_no_conflict(self):
        """Negation in one claim doesn't matter if topics are unrelated."""
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "Python is not a compiled language"),
            _make_claim("2", "Java has garbage collection"),
        ]
        reports = detector.detect(claims)
        assert reports == [], (
            f"Unrelated topics with negation should not conflict, "
            f"got {len(reports)} reports"
        )


# ---------------------------------------------------------------------------
# Test 4: conflict_type is set
# ---------------------------------------------------------------------------


class TestConflictTypeIsSet:
    """Every ConflictReport must have a valid conflict_type."""

    _VALID_TYPES = {"contradiction", "disagreement", "inconsistency"}

    def test_detected_conflicts_have_valid_type(self):
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "Kafka guarantees ordering"),
            _make_claim("2", "Kafka does not guarantee ordering"),
            _make_claim("3", "Data is encrypted"),
            _make_claim("4", "Data is not encrypted"),
        ]
        reports = detector.detect(claims)
        assert len(reports) >= 1
        for r in reports:
            assert r.conflict_type in self._VALID_TYPES, (
                f"Invalid conflict_type: {r.conflict_type}"
            )

    def test_contradiction_type_used_for_negation(self):
        """Negation-based conflicts should use 'contradiction' type."""
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "X is true"),
            _make_claim("2", "X is false"),
        ]
        reports = detector.detect(claims)
        # "false" is a negation keyword → one has negation → contradiction
        assert len(reports) == 1
        assert reports[0].conflict_type == "contradiction"


# ---------------------------------------------------------------------------
# Test 5: Empty claims list
# ---------------------------------------------------------------------------


class TestEmptyClaimsList:
    """Empty input produces empty output."""

    def test_empty_list_returns_empty(self):
        detector = ConflictDetector()
        reports = detector.detect([])
        assert reports == []

    def test_empty_list_with_entity_name(self):
        detector = ConflictDetector()
        reports = detector.detect([], entity_name="Kafka")
        assert reports == []


# ---------------------------------------------------------------------------
# Test 6: Single claim
# ---------------------------------------------------------------------------


class TestSingleClaim:
    """A single claim cannot conflict with itself."""

    def test_single_claim_no_conflict(self):
        detector = ConflictDetector()
        claims = [_make_claim("1", "Kafka guarantees ordering")]
        reports = detector.detect(claims)
        assert reports == [], (
            f"Single claim should not conflict, got {len(reports)} reports"
        )

    def test_single_claim_with_entity_name(self):
        detector = ConflictDetector()
        claims = [_make_claim("1", "Kafka guarantees ordering")]
        reports = detector.detect(claims, entity_name="Kafka")
        assert reports == []


# ---------------------------------------------------------------------------
# Test 7: Multiple conflicts
# ---------------------------------------------------------------------------


class TestMultipleConflicts:
    """When multiple claim pairs conflict, all should be detected."""

    def test_two_independent_conflict_pairs(self):
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "Kafka guarantees ordering"),
            _make_claim("2", "Kafka does not guarantee ordering"),
            _make_claim("3", "Data is encrypted at rest"),
            _make_claim("4", "Data is not encrypted at rest"),
        ]
        reports = detector.detect(claims)
        assert len(reports) == 2, (
            f"Expected 2 conflicts (two independent pairs), got {len(reports)}"
        )

    def test_each_report_has_unique_claim_pair(self):
        detector = ConflictDetector()
        # Use distinctive terms so cross-pair false positives don't occur
        claims = [
            _make_claim("1", "AlphaService guarantees ordering"),
            _make_claim("2", "AlphaService never guarantees ordering"),
            _make_claim("3", "BetaService encrypts traffic"),
            _make_claim("4", "BetaService does not encrypt traffic"),
        ]
        reports = detector.detect(claims)
        assert len(reports) == 2, f"Expected 2 conflicts, got {len(reports)}"
        # Each report should reference a different pair
        pairs = {frozenset([r.claim_a, r.claim_b]) for r in reports}
        assert len(pairs) == 2, (
            f"Expected 2 distinct pairs, got {len(pairs)}"
        )


# ---------------------------------------------------------------------------
# Test 8: Negation keyword coverage
# ---------------------------------------------------------------------------


class TestNegationKeywordCoverage:
    """Various negation patterns should all be detected."""

    def test_never_keyword(self):
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "The system fails"),
            _make_claim("2", "The system never fails"),
        ]
        reports = detector.detect(claims)
        assert len(reports) == 1
        assert reports[0].conflict_type == "contradiction"

    def test_cannot_keyword(self):
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "Users can delete data"),
            _make_claim("2", "Users cannot delete data"),
        ]
        reports = detector.detect(claims)
        assert len(reports) == 1

    def test_doesnt_keyword(self):
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "The API requires authentication"),
            _make_claim("2", "The API doesn't require authentication"),
        ]
        reports = detector.detect(claims)
        assert len(reports) == 1

    def test_dont_keyword(self):
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "Users need admin rights"),
            _make_claim("2", "Users don't need admin rights"),
        ]
        reports = detector.detect(claims)
        assert len(reports) == 1

    def test_wont_keyword(self):
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "The process will complete"),
            _make_claim("2", "The process won't complete"),
        ]
        reports = detector.detect(claims)
        assert len(reports) == 1

    def test_false_keyword(self):
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "The claim is true"),
            _make_claim("2", "The claim is false"),
        ]
        reports = detector.detect(claims)
        assert len(reports) == 1

    def test_incorrect_keyword(self):
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "The answer is correct"),
            _make_claim("2", "The answer is incorrect"),
        ]
        reports = detector.detect(claims)
        assert len(reports) == 1

    def test_wrong_keyword(self):
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "The result is right"),
            _make_claim("2", "The result is wrong"),
        ]
        reports = detector.detect(claims)
        assert len(reports) == 1

    def test_no_keyword(self):
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "There is a solution"),
            _make_claim("2", "There is no solution"),
        ]
        reports = detector.detect(claims)
        assert len(reports) == 1

    def test_negation_not_triggered_by_substrings(self):
        """Words like 'another' should NOT trigger the 'not' keyword."""
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "Pick another option"),
            _make_claim("2", "Pick a different option"),
        ]
        reports = detector.detect(claims)
        # "another" contains "not" as substring but tokenization prevents match
        # These are similar but neither has negation → disagreement
        if reports:
            # If similarity > 0.5 they might be flagged as disagreement
            assert reports[0].conflict_type != "contradiction", (
                "'another' should not match 'not' negation keyword"
            )


# ---------------------------------------------------------------------------
# Test 9: suggested_resolution is non-empty
# ---------------------------------------------------------------------------


class TestSuggestedResolution:
    """Every ConflictReport must have a human-readable resolution suggestion."""

    def test_suggested_resolution_non_empty_for_contradiction(self):
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "Kafka is fast"),
            _make_claim("2", "Kafka is not fast"),
        ]
        reports = detector.detect(claims)
        assert len(reports) == 1
        assert reports[0].suggested_resolution, (
            "suggested_resolution should not be empty"
        )
        assert len(reports[0].suggested_resolution) > 10, (
            "suggested_resolution should be a meaningful sentence"
        )

    def test_suggested_resolution_for_each_conflict_type(self):
        """Each conflict type should have its own resolution template."""
        # We test that the field is set correctly regardless of which
        # conflict type is detected
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "X supports Y"),
            _make_claim("2", "X does not support Y"),
            _make_claim("3", "A is correct"),
            _make_claim("4", "A is incorrect"),
        ]
        reports = detector.detect(claims)
        for r in reports:
            assert r.suggested_resolution, (
                f"suggested_resolution empty for {r.conflict_type}"
            )
            assert len(r.suggested_resolution) > 10


# ---------------------------------------------------------------------------
# Test 10: Entity grouping
# ---------------------------------------------------------------------------


class TestEntityGrouping:
    """When entity_name is provided, only claims about that entity are compared."""

    def test_entity_name_filters_claims(self):
        """Claims not mentioning the entity are excluded."""
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "Alice is not tall"),
            _make_claim("2", "Bob is tall"),
        ]
        # Without entity_name, these could be flagged as contradiction
        # (both mention "is" and "tall", one has "not")
        reports_without = detector.detect(claims)
        assert len(reports_without) == 1, (
            "Without entity filter, should detect contradiction"
        )

        # With entity_name="Alice", claim 2 ("Bob is tall") is filtered out
        reports_with = detector.detect(claims, entity_name="Alice")
        assert len(reports_with) == 0, (
            f"With entity_name='Alice', claim about Bob should be excluded, "
            f"got {len(reports_with)} reports"
        )

    def test_entity_name_appears_in_report(self):
        """When entity_name is provided, it populates the report."""
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "Kafka guarantees ordering"),
            _make_claim("2", "Kafka does not guarantee ordering"),
        ]
        reports = detector.detect(claims, entity_name="Kafka")
        assert len(reports) == 1
        assert reports[0].entity == "Kafka"

    def test_entity_name_empty_by_default(self):
        """Without entity_name, report.entity is empty string."""
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "Kafka guarantees ordering"),
            _make_claim("2", "Kafka does not guarantee ordering"),
        ]
        reports = detector.detect(claims)
        assert len(reports) == 1
        assert reports[0].entity == ""

    def test_entity_filter_leaves_no_claims(self):
        """When no claim mentions the entity, empty result."""
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "Kafka is fast"),
            _make_claim("2", "Kafka is slow"),
        ]
        reports = detector.detect(claims, entity_name="PostgreSQL")
        assert reports == []

    def test_entity_filter_leaves_single_claim(self):
        """When only one claim mentions the entity, no conflicts possible."""
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "Kafka is fast"),
            _make_claim("2", "PostgreSQL is slow"),
        ]
        reports = detector.detect(claims, entity_name="Kafka")
        assert reports == []


# ---------------------------------------------------------------------------
# Test 11: Large entity performance boundary
# ---------------------------------------------------------------------------


class TestLargeEntityPerformance:
    """When > 500 claims, sample mode is used and completes quickly."""

    def test_large_entity_uses_sample_mode(self):
        """501 claims should complete in under 2 seconds."""
        detector = ConflictDetector()

        # Generate 501 claims — all mention the entity so sample mode triggers
        claims: list[Claim] = []
        # Neutral claims (all contain "Entity" for filter pass-through)
        for i in range(400):
            claims.append(_make_claim(f"n{i}", f"Entity property alpha {i}"))
        # Conflicting pairs (must also contain "Entity" for filter)
        for i in range(50):
            claims.append(_make_claim(f"c{i}a", f"Entity feature {i} is supported"))
            claims.append(_make_claim(f"c{i}b", f"Entity feature {i} is not supported"))
        # One extra to exceed 500
        claims.append(_make_claim("extra", "Entity additional neutral claim here"))

        assert len(claims) == 501

        start = time.perf_counter()
        reports = detector.detect(claims, entity_name="Entity")
        elapsed = time.perf_counter() - start

        assert elapsed < 2.0, (
            f"Large entity detection took {elapsed:.2f}s, expected < 2.0s"
        )
        # Sample mode should still find some conflicts from the sample
        assert isinstance(reports, list), "Should return a list even in sample mode"

    def test_exactly_500_uses_full_mode(self):
        """Exactly 500 claims should use full detection (not sample mode)."""
        detector = ConflictDetector()
        claims = [_make_claim(f"c{i}", f"Claim number {i} is valid") for i in range(500)]
        # 500 is NOT > 500, so full mode is used
        start = time.perf_counter()
        reports = detector.detect(claims)
        elapsed = time.perf_counter() - start
        assert elapsed < 10.0, (
            f"Full detection on 500 claims took {elapsed:.2f}s"
        )
        assert isinstance(reports, list)


# ---------------------------------------------------------------------------
# Test 12: _screen_candidates filters correctly
# ---------------------------------------------------------------------------


class TestScreenCandidates:
    """Stage 1 candidate screening only returns similar claim pairs."""

    def test_screen_candidates_returns_only_similar_pairs(self):
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "Kafka guarantees ordering"),
            _make_claim("2", "Kafka does not guarantee ordering"),
            _make_claim("3", "Python is a programming language"),
        ]
        candidates = detector._screen_candidates(claims)

        # Only (1, 2) should be a candidate — claim 3 shares no words
        candidate_pairs = {(a.id, b.id) for a, b in candidates}
        assert len(candidates) == 1, (
            f"Expected 1 candidate pair, got {len(candidates)}: {candidate_pairs}"
        )
        assert ("1", "2") in candidate_pairs or ("2", "1") in candidate_pairs

    def test_screen_candidates_excludes_low_similarity(self):
        """Pairs with Jaccard < 0.25 should not be candidates."""
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "The quick brown fox jumps"),
            _make_claim("2", "A completely different sentence here"),
        ]
        candidates = detector._screen_candidates(claims)
        assert len(candidates) == 0, (
            "Low similarity pair should not be a candidate"
        )

    def test_screen_candidates_includes_high_similarity(self):
        """Pairs with Jaccard >= 0.25 should be candidates."""
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "Kafka processes messages quickly"),
            _make_claim("2", "Kafka processes events quickly"),
        ]
        candidates = detector._screen_candidates(claims)
        # Jaccard: {kafka, processes, messages, quickly} ∩ {kafka, processes, events, quickly} = {kafka, processes, quickly}
        # Union = {kafka, processes, messages, quickly, events} = 5
        # Jaccard = 3/5 = 0.6 >= 0.25
        assert len(candidates) == 1

    def test_screen_candidates_empty_for_single_claim(self):
        detector = ConflictDetector()
        claims = [_make_claim("1", "Only claim")]
        candidates = detector._screen_candidates(claims)
        assert candidates == []


# ---------------------------------------------------------------------------
# ConflictReport dataclass
# ---------------------------------------------------------------------------


class TestConflictReportDataclass:
    """ConflictReport behaves as a proper dataclass."""

    def test_create_conflict_report(self):
        r = ConflictReport(
            claim_a="cl-1",
            claim_b="cl-2",
            entity="Kafka",
            conflict_type="contradiction",
            suggested_resolution="Review both claims.",
            confidence=0.9,
        )
        assert r.claim_a == "cl-1"
        assert r.claim_b == "cl-2"
        assert r.entity == "Kafka"
        assert r.conflict_type == "contradiction"
        assert r.suggested_resolution == "Review both claims."
        assert r.confidence == 0.9

    def test_equality(self):
        r1 = ConflictReport(
            claim_a="a", claim_b="b", entity="e",
            conflict_type="contradiction",
            suggested_resolution="fix", confidence=0.5,
        )
        r2 = ConflictReport(
            claim_a="a", claim_b="b", entity="e",
            conflict_type="contradiction",
            suggested_resolution="fix", confidence=0.5,
        )
        assert r1 == r2

    def test_inequality(self):
        r1 = ConflictReport(
            claim_a="a", claim_b="b", entity="e",
            conflict_type="contradiction",
            suggested_resolution="fix", confidence=0.5,
        )
        r2 = ConflictReport(
            claim_a="a", claim_b="c", entity="e",
            conflict_type="contradiction",
            suggested_resolution="fix", confidence=0.5,
        )
        assert r1 != r2


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Additional edge case coverage."""

    def test_negation_in_both_same_topic(self):
        """Both claims have negation keywords → inconsistency, not contradiction."""
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "The system is not fast"),
            _make_claim("2", "The system is not slow"),
        ]
        reports = detector.detect(claims)
        # Both have "not" → inconsistency (if Jaccard passes screening)
        if reports:
            assert reports[0].conflict_type == "inconsistency"

    def test_disagreement_no_negation(self):
        """High similarity without negation → disagreement."""
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "Kafka guarantees exactly-once semantics"),
            _make_claim("2", "Kafka guarantees at-least-once semantics"),
        ]
        reports = detector.detect(claims)
        # Jaccard: 4/6 ≈ 0.67 > 0.5 → disagreement
        assert len(reports) == 1, f"Expected 1 report, got {len(reports)}"
        assert reports[0].conflict_type == "disagreement"

    def test_no_keyword_exact_match(self):
        """Word-boundary matching: 'no' should match 'no' but not 'another'."""
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "There is no error in the log"),
            _make_claim("2", "There is an error in the log"),
        ]
        reports = detector.detect(claims)
        assert len(reports) == 1, (
            "'no' should be detected as negation keyword"
        )


# ---------------------------------------------------------------------------
# Integration-style tests
# ---------------------------------------------------------------------------


class TestDetectorIntegration:
    """Tests that exercise the detector end-to-end with realistic claim sets."""

    def test_mixed_claim_set(self):
        """A mix of conflicting and non-conflicting claims."""
        detector = ConflictDetector()
        claims = [
            _make_claim("1", "Kafka guarantees ordering"),
            _make_claim("2", "Kafka does not guarantee ordering"),  # conflicts with 1
            _make_claim("3", "Python is a dynamic language"),
            _make_claim("4", "Java is a static language"),
            _make_claim("5", "Data is encrypted at rest"),
            _make_claim("6", "Data is not encrypted at rest"),  # conflicts with 5
        ]
        reports = detector.detect(claims)
        # Should detect 2 conflicts: (1,2) and (5,6)
        assert len(reports) == 2, f"Expected 2 conflicts, got {len(reports)}"
        # Verify the right pairs
        conflict_pairs = {frozenset([r.claim_a, r.claim_b]) for r in reports}
        assert frozenset(["1", "2"]) in conflict_pairs
        assert frozenset(["5", "6"]) in conflict_pairs
        # Non-conflicting pairs should not appear
        assert frozenset(["3", "4"]) not in conflict_pairs
