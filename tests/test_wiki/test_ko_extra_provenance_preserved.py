"""Tests for C-0 Commit 3: document _ko_extra.provenance as a preserved field.

V4 (ADR-002, 2026-08-31) update:
- to_frontmatter_dict() does NOT emit _ko_extra (V4 8-key whitelist)
- from_dict() still restores _ko_extra for read-side backward compat
- provenance is in-memory only (carried on WikiPage._ko_extra)

These tests now verify the read-side round-trip: legacy pages carrying
``_ko_extra.provenance`` are loaded into the in-memory WikiPage correctly,
even though new writes drop it.
"""
from src.wiki.core.types import PageType, WikiPage


# ---------------------------------------------------------------------------
# Test 1: provenance-only payload round-trips (read-side)
# ---------------------------------------------------------------------------
def test_ko_extra_provenance_only_round_trips():
    """A page with _ko_extra carrying provenance must round-trip cleanly.

    V6 (post-ADR-002 migration): _ko_extra IS emitted to disk. The
    round-trip is full: page → frontmatter → page, with provenance
    preserved across the boundary.
    """
    payload = {"sources": ["a.pdf"], "parser_version": "1.0"}
    page = WikiPage(
        id="prov-only",
        title="Provenance Only",
        type=PageType.SOURCE,
    )
    page._ko_extra = {"provenance": payload}

    # V6: to_frontmatter_dict() emits _ko_extra to disk.
    d = page.to_frontmatter_dict()
    assert "_ko_extra" in d
    assert d["_ko_extra"]["provenance"] == payload

    # Round-trip back: from_dict restores _ko_extra from frontmatter.
    page2 = WikiPage.from_dict(d)
    assert hasattr(page2, "_ko_extra")
    assert isinstance(page2._ko_extra, dict)
    assert "provenance" in page2._ko_extra
    assert page2._ko_extra["provenance"] == payload


# ---------------------------------------------------------------------------
# Test 2: provenance + decision_record coexist (read-side)
# ---------------------------------------------------------------------------
def test_ko_extra_provenance_and_decision_record_coexist():
    """Both _ko_extra.provenance (preserved) and decision_record (Commit 2
    migrated field) must survive read-side round-trip independently."""
    provenance = {"source_path": "paper.pdf", "page": 7, "quote": "key quote"}
    decision = {"status": "approved", "by": "reviewer-1"}

    fm = {
        "id": "prov-decision",
        "title": "Prov + Decision",
        # V4 has no CLAIM; decision content uses concept.
        "type": "concept",
        "decision_record": decision,
        "_ko_extra": {"provenance": provenance},
    }
    page2 = WikiPage.from_dict(fm)

    assert page2.decision_record == decision
    assert page2._ko_extra["provenance"] == provenance


# ---------------------------------------------------------------------------
# Test 3: provenance + legacy memory coexist (read-side)
# ---------------------------------------------------------------------------
def test_ko_extra_provenance_and_legacy_memory_coexist():
    """When _ko_extra carries both provenance and a legacy memory.decision
    payload, the Commit 2 lift of memory.decision -> decision_record must
    leave provenance intact on the read side."""
    provenance = {"source_path": "book.pdf", "page": 12}
    legacy_decision = {"status": "pending", "by": "human"}

    fm = {
        "id": "legacy-mix",
        "title": "Legacy Mix",
        "type": "concept",
        "_ko_extra": {
            "provenance": provenance,
            "memory": {"decision": legacy_decision},
        },
    }
    page = WikiPage.from_dict(fm)

    assert page.decision_record == legacy_decision
    assert page._ko_extra["provenance"] == provenance


# ---------------------------------------------------------------------------
# Test 4: byte-for-byte equivalence across read-side round-trip
# ---------------------------------------------------------------------------
def test_ko_extra_provenance_byte_for_byte_round_trip():
    """A non-trivial provenance payload (nested dict + list + unicode)
    must deserialize back to a structurally equal dict."""
    payload = {
        "source_path": "paper.pdf",
        "page": 3,
        "quote": "包含中文的 quote — " "with em-dash",
        "metadata": {
            "parser": "pypdf",
            "version": "4.0",
            "flags": ["bold", "italic"],
        },
    }

    fm = {
        "id": "bytewise",
        "title": "Bytewise",
        "type": "source",
        "_ko_extra": {"provenance": payload},
    }
    page = WikiPage.from_dict(fm)
    assert page._ko_extra["provenance"] == payload


# ---------------------------------------------------------------------------
# Test 5: absence case — no provenance, no phantom key (read-side)
# ---------------------------------------------------------------------------
def test_no_provenance_no_phantom_ko_extra_provenance():
    """A page with empty _ko_extra (no provenance key) must not gain a
    phantom _ko_extra.provenance dict on read-side round-trip."""
    fm = {
        "id": "no-prov",
        "title": "No Provenance",
        "type": "concept",
        "_ko_extra": {},
    }
    page = WikiPage.from_dict(fm)
    assert hasattr(page, "_ko_extra")
    assert "provenance" not in page._ko_extra


# ---------------------------------------------------------------------------
# NOTE: Test 6 (to_frontmatter_dict_does_not_emit_ko_extra_v4) was REMOVED.
# V6 (post-ADR-002 migration) DOES emit _ko_extra.provenance to disk.
# The V4 contract (8-key whitelist) is no longer in force.
# ---------------------------------------------------------------------------
