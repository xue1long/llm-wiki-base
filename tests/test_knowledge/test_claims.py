"""Test Claim + Evidence model (Task 2.1)."""
import time

import pytest

from src.knowledge.claims.model import Claim, ClaimStatus, ClaimType, Evidence


# ---------------------------------------------------------------------------
# ClaimType enum
# ---------------------------------------------------------------------------


class TestClaimTypeEnum:
    """ClaimType has exactly 4 values."""

    def test_all_four_values_exist(self):
        """All 4 ClaimType values are defined."""
        assert hasattr(ClaimType, "FACT")
        assert hasattr(ClaimType, "OPINION")
        assert hasattr(ClaimType, "HYPOTHESIS")
        assert hasattr(ClaimType, "WARNING")

    def test_values_serialize_to_correct_strings(self):
        """Each ClaimType value serializes to the expected string."""
        assert ClaimType.FACT.value == "fact"
        assert ClaimType.OPINION.value == "opinion"
        assert ClaimType.HYPOTHESIS.value == "hypothesis"
        assert ClaimType.WARNING.value == "warning"

    def test_values_deserialize_from_strings(self):
        """Each string deserializes to the correct ClaimType."""
        assert ClaimType("fact") == ClaimType.FACT
        assert ClaimType("opinion") == ClaimType.OPINION
        assert ClaimType("hypothesis") == ClaimType.HYPOTHESIS
        assert ClaimType("warning") == ClaimType.WARNING

    def test_total_count_is_four(self):
        """ClaimType has exactly 4 members."""
        members = list(ClaimType)
        assert len(members) == 4, (
            f"Expected 4, got {len(members)}: {[m.value for m in members]}"
        )

    def test_fact_is_default_claim_type(self):
        """FACT is the first enum member (used as default in Claim)."""
        assert list(ClaimType)[0] == ClaimType.FACT


# ---------------------------------------------------------------------------
# ClaimStatus enum
# ---------------------------------------------------------------------------


class TestClaimStatusEnum:
    """ClaimStatus has exactly 3 values."""

    def test_all_three_values_exist(self):
        """All 3 ClaimStatus values are defined."""
        assert hasattr(ClaimStatus, "PENDING")
        assert hasattr(ClaimStatus, "VERIFIED")
        assert hasattr(ClaimStatus, "REJECTED")

    def test_values_serialize_to_correct_strings(self):
        """Each ClaimStatus value serializes to the expected string."""
        assert ClaimStatus.PENDING.value == "pending"
        assert ClaimStatus.VERIFIED.value == "verified"
        assert ClaimStatus.REJECTED.value == "rejected"

    def test_values_deserialize_from_strings(self):
        """Each string deserializes to the correct ClaimStatus."""
        assert ClaimStatus("pending") == ClaimStatus.PENDING
        assert ClaimStatus("verified") == ClaimStatus.VERIFIED
        assert ClaimStatus("rejected") == ClaimStatus.REJECTED

    def test_total_count_is_three(self):
        """ClaimStatus has exactly 3 members."""
        members = list(ClaimStatus)
        assert len(members) == 3, (
            f"Expected 3, got {len(members)}: {[m.value for m in members]}"
        )

    def test_pending_is_default_status(self):
        """PENDING is the first enum member (used as default in Claim)."""
        assert list(ClaimStatus)[0] == ClaimStatus.PENDING


# ---------------------------------------------------------------------------
# Evidence dataclass
# ---------------------------------------------------------------------------


class TestEvidenceCreation:
    """Evidence dataclass creation and default values."""

    def test_create_with_required_field_only(self):
        """Evidence can be created with only source_path."""
        e = Evidence(source_path="/docs/source.md")
        assert e.source_path == "/docs/source.md"

    def test_default_values_are_correct(self):
        """Evidence defaults: page=None, quote="", added_at auto-set."""
        before = int(time.time() * 1000)
        e = Evidence(source_path="/x.pdf")
        after = int(time.time() * 1000)

        assert e.page is None
        assert e.quote == ""
        assert isinstance(e.added_at, int)
        # added_at should be within the time window (allow small clock drift)
        assert before - 100 <= e.added_at <= after + 100, (
            f"added_at {e.added_at} not in [{before}, {after}]"
        )

    def test_create_with_all_fields(self):
        """Evidence accepts all optional fields."""
        e = Evidence(
            source_path="/doc.pdf",
            page=3,
            quote="the quick brown fox",
            added_at=1722556800000,
        )
        assert e.source_path == "/doc.pdf"
        assert e.page == 3
        assert e.quote == "the quick brown fox"
        assert e.added_at == 1722556800000

    def test_page_accepts_none(self):
        """Evidence.page can be None (e.g. for non-paginated sources)."""
        e = Evidence(source_path="/video.mp4", page=None)
        assert e.page is None

    def test_quote_can_be_multiline(self):
        """Evidence.quote can hold multi-line excerpts."""
        multiline = "Line 1\nLine 2\nLine 3"
        e = Evidence(source_path="/doc.md", quote=multiline)
        assert e.quote == multiline

    def test_added_at_is_millisecond_timestamp(self):
        """Evidence.added_at is an integer millisecond timestamp."""
        e = Evidence(source_path="/doc.md")
        now_sec = int(time.time())
        # millisecond timestamp should be roughly now * 1000
        assert e.added_at // 1000 == now_sec or e.added_at // 1000 == now_sec - 1, (
            f"added_at {e.added_at} does not correspond to current time "
            f"(now_sec={now_sec}, ms_to_sec={e.added_at // 1000})"
        )

    def test_explicit_added_at_not_overwritten(self):
        """When added_at is explicitly provided, __post_init__ should not overwrite it."""
        e = Evidence(source_path="/doc.md", added_at=42)
        assert e.added_at == 42

    def test_evidence_equality(self):
        """Two Evidence instances with same fields are equal."""
        e1 = Evidence(source_path="/a.md", page=1, quote="hello", added_at=1000)
        e2 = Evidence(source_path="/a.md", page=1, quote="hello", added_at=1000)
        assert e1 == e2

    def test_evidence_inequality(self):
        """Two Evidence instances with different fields are not equal."""
        e1 = Evidence(source_path="/a.md", page=1)
        e2 = Evidence(source_path="/a.md", page=2)
        assert e1 != e2


# ---------------------------------------------------------------------------
# Claim dataclass — creation and defaults
# ---------------------------------------------------------------------------


class TestClaimCreation:
    """Claim dataclass creation with required and optional fields."""

    def test_create_with_required_fields_only(self):
        """Claim can be created with only id and statement."""
        before = int(time.time() * 1000)
        c = Claim(id="cl-001", statement="The sky is blue.")
        after = int(time.time() * 1000)

        assert c.id == "cl-001"
        assert c.statement == "The sky is blue."

    def test_default_values_are_correct(self):
        """Claim defaults match spec."""
        c = Claim(id="cl-002", statement="Water boils at 100C.")
        assert c.type == ClaimType.FACT
        assert c.confidence == 0.0
        assert c.evidence == []
        assert c.status == ClaimStatus.PENDING
        assert c.source_objects == []

    def test_created_at_and_updated_at_auto_set(self):
        """Claim created_at and updated_at are auto-set to now (ms)."""
        before = int(time.time() * 1000)
        c = Claim(id="cl-t", statement="Test")
        after = int(time.time() * 1000)

        assert isinstance(c.created_at, int)
        assert isinstance(c.updated_at, int)
        assert before - 100 <= c.created_at <= after + 100
        assert before - 100 <= c.updated_at <= after + 100
        assert c.created_at == c.updated_at

    def test_created_at_not_overwritten_when_explicit(self):
        """When created_at is explicitly set, __post_init__ keeps it."""
        c = Claim(id="cl-e", statement="Explicit", created_at=42, updated_at=99)
        assert c.created_at == 42
        assert c.updated_at == 99

    def test_create_with_all_fields(self):
        """Claim accepts all optional fields."""
        e1 = Evidence(source_path="/a.md", page=1, quote="evidence")
        c = Claim(
            id="cl-full",
            statement="All fields set.",
            type=ClaimType.HYPOTHESIS,
            confidence=0.87,
            evidence=[e1],
            status=ClaimStatus.VERIFIED,
            source_objects=["ko-001", "ko-002"],
            created_at=1722556800000,
            updated_at=1722556801000,
        )
        assert c.id == "cl-full"
        assert c.statement == "All fields set."
        assert c.type == ClaimType.HYPOTHESIS
        assert c.confidence == 0.87
        assert len(c.evidence) == 1
        assert c.evidence[0] == e1
        assert c.status == ClaimStatus.VERIFIED
        assert c.source_objects == ["ko-001", "ko-002"]
        assert c.created_at == 1722556800000
        assert c.updated_at == 1722556801000


# ---------------------------------------------------------------------------
# Claim — evidence association
# ---------------------------------------------------------------------------


class TestClaimEvidenceAssociation:
    """Evidence list on Claim works correctly."""

    def test_empty_evidence_list_by_default(self):
        """Claim.evidence defaults to empty list."""
        c = Claim(id="c", statement="S")
        assert c.evidence == []
        assert len(c.evidence) == 0

    def test_single_evidence_item(self):
        """Claim.evidence can hold a single Evidence object."""
        e = Evidence(source_path="/x.md")
        c = Claim(id="c", statement="S", evidence=[e])
        assert len(c.evidence) == 1
        assert c.evidence[0] is e
        assert c.evidence[0].source_path == "/x.md"

    def test_multiple_evidence_items(self):
        """Claim.evidence can hold multiple Evidence objects."""
        e1 = Evidence(source_path="/a.md", page=1, quote="first")
        e2 = Evidence(source_path="/b.md", page=5, quote="second")
        e3 = Evidence(source_path="/c.md", page=10, quote="third")
        c = Claim(
            id="cl-multi",
            statement="Multi evidence.",
            evidence=[e1, e2, e3],
        )
        assert len(c.evidence) == 3
        assert c.evidence[0].source_path == "/a.md"
        assert c.evidence[1].source_path == "/b.md"
        assert c.evidence[2].source_path == "/c.md"

    def test_evidence_list_mutation(self):
        """Claim.evidence list can be mutated after creation."""
        c = Claim(id="c", statement="S")
        e1 = Evidence(source_path="/a.md")
        e2 = Evidence(source_path="/b.md")
        c.evidence.append(e1)
        c.evidence.append(e2)
        assert len(c.evidence) == 2
        assert c.evidence[0].source_path == "/a.md"
        assert c.evidence[1].source_path == "/b.md"

    def test_evidence_instances_are_distinct(self):
        """Claim references the same Evidence objects (not copies)."""
        e = Evidence(source_path="/x.md", quote="original")
        c = Claim(id="c", statement="S", evidence=[e])
        # Mutate the original evidence object
        e.quote = "modified"
        assert c.evidence[0].quote == "modified"


# ---------------------------------------------------------------------------
# Claim — source_objects association
# ---------------------------------------------------------------------------


class TestClaimSourceObjects:
    """source_objects list on Claim works correctly."""

    def test_empty_source_objects_by_default(self):
        """Claim.source_objects defaults to empty list."""
        c = Claim(id="c", statement="S")
        assert c.source_objects == []
        assert len(c.source_objects) == 0

    def test_single_source_object(self):
        """Claim.source_objects can hold a single source ID."""
        c = Claim(id="c", statement="S", source_objects=["ko-001"])
        assert c.source_objects == ["ko-001"]

    def test_multiple_source_objects(self):
        """Claim.source_objects can hold multiple source IDs."""
        c = Claim(
            id="c",
            statement="S",
            source_objects=["ko-001", "ko-002", "ko-003"],
        )
        assert len(c.source_objects) == 3
        assert c.source_objects[0] == "ko-001"
        assert c.source_objects[2] == "ko-003"

    def test_source_objects_mutation(self):
        """Claim.source_objects can be mutated after creation."""
        c = Claim(id="c", statement="S")
        c.source_objects.append("ko-001")
        c.source_objects.append("ko-002")
        assert c.source_objects == ["ko-001", "ko-002"]


# ---------------------------------------------------------------------------
# Claim — all ClaimType / ClaimStatus combinations
# ---------------------------------------------------------------------------


class TestClaimTypeStatusCombinations:
    """Claim works with every ClaimType and ClaimStatus combination."""

    def test_all_claim_types_work(self):
        """Claim accepts every ClaimType value."""
        for ct in ClaimType:
            c = Claim(
                id=f"cl-{ct.value}",
                statement=f"Statement for {ct.value}",
                type=ct,
            )
            assert c.type == ct, f"Failed for {ct}"

    def test_all_claim_statuses_work(self):
        """Claim accepts every ClaimStatus value."""
        for cs in ClaimStatus:
            c = Claim(
                id=f"cl-{cs.value}",
                statement=f"Statement with status {cs.value}",
                status=cs,
            )
            assert c.status == cs, f"Failed for {cs}"

    def test_all_type_status_combinations(self):
        """Claim works with every ClaimType x ClaimStatus combination."""
        for ct in ClaimType:
            for cs in ClaimStatus:
                c = Claim(
                    id=f"cl-{ct.value}-{cs.value}",
                    statement=f"{ct.value} + {cs.value}",
                    type=ct,
                    status=cs,
                )
                assert c.type == ct
                assert c.status == cs


# ---------------------------------------------------------------------------
# Claim — confidence edge cases
# ---------------------------------------------------------------------------


class TestClaimConfidence:
    """Claim.confidence field edge cases."""

    def test_confidence_zero(self):
        """Claim accepts confidence=0.0."""
        c = Claim(id="c", statement="S", confidence=0.0)
        assert c.confidence == 0.0

    def test_confidence_one(self):
        """Claim accepts confidence=1.0."""
        c = Claim(id="c", statement="S", confidence=1.0)
        assert c.confidence == 1.0

    def test_confidence_mid_range(self):
        """Claim accepts mid-range confidence."""
        c = Claim(id="c", statement="S", confidence=0.73)
        assert c.confidence == 0.73

    def test_confidence_stores_passed_type(self):
        """Claim.confidence stores whatever numeric type is passed (no coercion)."""
        c = Claim(id="c", statement="S", confidence=0.5)
        assert isinstance(c.confidence, float)
        # Passing an int stores an int (standard Python dataclass behavior)
        c2 = Claim(id="c2", statement="S2", confidence=1)
        assert c2.confidence == 1
        assert isinstance(c2.confidence, (int, float))


# ---------------------------------------------------------------------------
# Claim — timestamp types and behavior
# ---------------------------------------------------------------------------


class TestClaimTimestamps:
    """Claim created_at / updated_at timestamp behavior."""

    def test_timestamps_are_ints(self):
        """created_at and updated_at are integers."""
        c = Claim(id="c", statement="S")
        assert isinstance(c.created_at, int)
        assert isinstance(c.updated_at, int)

    def test_timestamps_are_millisecond_range(self):
        """Auto-set timestamps are roughly time.time() * 1000."""
        c = Claim(id="c", statement="S")
        now_ms = int(time.time() * 1000)
        # Should be within 2 seconds of now
        assert abs(c.created_at - now_ms) < 2000, (
            f"created_at {c.created_at} too far from now_ms {now_ms}"
        )
        assert abs(c.updated_at - now_ms) < 2000, (
            f"updated_at {c.updated_at} too far from now_ms {now_ms}"
        )

    def test_explicit_timestamps_preserved(self):
        """Explicit timestamps are not overwritten."""
        c = Claim(
            id="c",
            statement="S",
            created_at=1722556800000,
            updated_at=1722556801000,
        )
        assert c.created_at == 1722556800000
        assert c.updated_at == 1722556801000

    def test_updated_at_differs_from_created_at_when_explicit(self):
        """updated_at can be different from created_at when explicitly set."""
        c = Claim(
            id="c",
            statement="S",
            created_at=1000,
            updated_at=2000,
        )
        assert c.updated_at > c.created_at


# ---------------------------------------------------------------------------
# Claim — immutability / mutation behavior
# ---------------------------------------------------------------------------


class TestClaimMutation:
    """Claim instances are mutable dataclasses."""

    def test_statement_can_be_updated(self):
        """Claim.statement can be mutated after creation."""
        c = Claim(id="c", statement="Original")
        c.statement = "Updated"
        assert c.statement == "Updated"

    def test_confidence_can_be_updated(self):
        """Claim.confidence can be mutated after creation."""
        c = Claim(id="c", statement="S", confidence=0.3)
        c.confidence = 0.9
        assert c.confidence == 0.9

    def test_status_can_be_updated(self):
        """Claim.status can transition through lifecycle."""
        c = Claim(id="c", statement="S")
        assert c.status == ClaimStatus.PENDING
        c.status = ClaimStatus.VERIFIED
        assert c.status == ClaimStatus.VERIFIED
        c.status = ClaimStatus.REJECTED
        assert c.status == ClaimStatus.REJECTED

    def test_updated_at_should_be_bumped_manually(self):
        """updated_at is NOT auto-bumped on mutation (caller responsibility)."""
        c = Claim(id="c", statement="S", created_at=1000, updated_at=1000)
        c.statement = "Changed"
        # updated_at is NOT auto-bumped — the dataclass only sets it in __post_init__
        assert c.updated_at == 1000


# ---------------------------------------------------------------------------
# Claim — equality behavior
# ---------------------------------------------------------------------------


class TestClaimEquality:
    """Claim equality semantics."""

    def test_equal_claims_with_same_fields(self):
        """Two Claims with identical fields are equal."""
        e = Evidence(source_path="/a.md", page=1, quote="q", added_at=1000)
        c1 = Claim(
            id="cl-1",
            statement="Same",
            type=ClaimType.FACT,
            confidence=0.5,
            evidence=[e],
            status=ClaimStatus.PENDING,
            source_objects=["ko-1"],
            created_at=1000,
            updated_at=1000,
        )
        e2 = Evidence(source_path="/a.md", page=1, quote="q", added_at=1000)
        c2 = Claim(
            id="cl-1",
            statement="Same",
            type=ClaimType.FACT,
            confidence=0.5,
            evidence=[e2],
            status=ClaimStatus.PENDING,
            source_objects=["ko-1"],
            created_at=1000,
            updated_at=1000,
        )
        assert c1 == c2

    def test_unequal_claims_differ_by_id(self):
        """Two Claims with different ids are not equal."""
        c1 = Claim(id="cl-1", statement="Same")
        c2 = Claim(id="cl-2", statement="Same")
        assert c1 != c2

    def test_unequal_claims_differ_by_statement(self):
        """Two Claims with different statements are not equal."""
        c1 = Claim(id="cl-1", statement="A")
        c2 = Claim(id="cl-1", statement="B")
        assert c1 != c2


# ---------------------------------------------------------------------------
# __init__.py re-exports
# ---------------------------------------------------------------------------


class TestInitReExports:
    """src.knowledge.claims.__init__ re-exports all key symbols."""

    def test_re_exports_from_package(self):
        """Claim, ClaimType, ClaimStatus, Evidence are accessible from package."""
        from src.knowledge.claims import Claim, ClaimStatus, ClaimType, Evidence

        # Instantiate to confirm these are the real classes, not stubs
        e = Evidence(source_path="/test.md")
        c = Claim(id="cl-test", statement="test re-export")
        assert isinstance(e, Evidence)
        assert isinstance(c, Claim)
        assert c.type == ClaimType.FACT
        assert c.status == ClaimStatus.PENDING

    def test_all_exports_match_spec(self):
        """__all__ contains exactly the 4 expected symbols."""
        from src.knowledge import claims

        assert hasattr(claims, "__all__")
        assert set(claims.__all__) == {"Claim", "ClaimStatus", "ClaimType", "Evidence"}
