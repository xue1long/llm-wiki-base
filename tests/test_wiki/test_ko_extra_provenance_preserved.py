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
    """A page with _ko_extra carrying provenance must keep it in memory
    through from_dict (read-side round-trip)."""
    payload = {"sources": ["a.pdf"], "parser_version": "1.0"}
    page = WikiPage(
        id="prov-only",
        title="Provenance Only",
        type=PageType.SOURCE,
    )
    page._ko_extra = {"provenance": payload}

    # V4: to_frontmatter_dict() drops _ko_extra entirely.
    d = page.to_frontmatter_dict()
    assert "_ko_extra" not in d

    # But from_dict restores it from legacy frontmatter input.
    legacy_d = {**d, "_ko_extra": {"provenance": payload}}
    page2 = WikiPage.from_dict(legacy_d)
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
# Test 6 (V4 rewrite): to_frontmatter_dict() does NOT emit _ko_extra
# ---------------------------------------------------------------------------
def test_to_frontmatter_dict_does_not_emit_ko_extra_v4():
    """V4 contract: to_frontmatter_dict() drops _ko_extra entirely.

    Documents that the V4 8-key whitelist excludes _ko_extra.provenance
    (and any other KO mirror fields). The provenance payload remains in
    memory on the WikiPage for code that reads it, but new writes do
    not serialize it. See ADR-002.
    """
    payload = {"source_path": "x.pdf", "page": 1, "quote": "q"}
    page = WikiPage(
        id="verbatim",
        title="Verbatim",
        type=PageType.SOURCE,
    )
    page._ko_extra = {"provenance": payload}

    d = page.to_frontmatter_dict()
    assert "_ko_extra" not in d, (
        "V4: to_frontmatter_dict() never emits _ko_extra"
    )