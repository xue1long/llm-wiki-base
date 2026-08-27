"""Tests for C-0 Commit 3: document _ko_extra.provenance as a preserved field.

Plan ref: docs/superpowers/plans/2026-08-26-kc-spec-roadmap.md §C-0 Commit 3.

Background
----------
``_ko_extra.provenance`` is an Evidence-internal field (per spec §5.7) and is
deliberately **not** migrated to a top-level ``WikiPage.provenance`` field.
It is set by the Generator on freshly captured pages so downstream
Evidence persistence code (``src/kc/adapters/wiki_writer.py`` and any
re-attached Evidence payloads) can find a single ``_ko_extra.provenance``
key without needing a parallel top-level field.

The serialization layer (``WikiPage.to_frontmatter_dict`` /
``WikiPage.from_dict``) MUST therefore round-trip the
``_ko_extra.provenance`` payload byte-for-byte so that pages carrying it
survive read/write cycles unchanged.

Behavior under test (round-trip preservation only — write path is owned by
``src/pipeline/generator.py`` and is unchanged here):

1. Provenance-only payload round-trips unchanged.
2. Provenance + ``decision_record`` (Commit 2 migrated key) coexist.
3. Provenance + ``memory`` (legacy sub-key from before Commit 2)
   coexist; migrating ``memory.decision`` to ``decision_record`` MUST NOT
   drop ``provenance``.
4. Byte-for-byte equivalence across serialize -> deserialize.
5. Absence case: a page without provenance does not gain a phantom empty
   ``_ko_extra.provenance`` dict on round-trip.
"""
from src.wiki.core.types import PageType, WikiPage


# ---------------------------------------------------------------------------
# Test 1: provenance-only payload round-trips unchanged
# ---------------------------------------------------------------------------
def test_ko_extra_provenance_only_round_trips():
    """A page whose _ko_extra only carries provenance must keep it intact
    through to_frontmatter_dict -> from_dict."""
    payload = {"sources": ["a.pdf"], "parser_version": "1.0"}
    page = WikiPage(
        id="prov-only",
        title="Provenance Only",
        type=PageType.SOURCE,
    )
    page._ko_extra = {"provenance": payload}

    d = page.to_frontmatter_dict()
    page2 = WikiPage.from_dict(d)

    assert hasattr(page2, "_ko_extra")
    assert isinstance(page2._ko_extra, dict)
    assert "provenance" in page2._ko_extra
    assert page2._ko_extra["provenance"] == payload


# ---------------------------------------------------------------------------
# Test 2: provenance + decision_record coexist
# ---------------------------------------------------------------------------
def test_ko_extra_provenance_and_decision_record_coexist():
    """Both _ko_extra.provenance (preserved) and decision_record (Commit 2
    migrated field) must survive round-trip independently."""
    provenance = {"source_path": "paper.pdf", "page": 7, "quote": "key quote"}
    decision = {"status": "approved", "by": "reviewer-1"}

    page = WikiPage(
        id="prov-decision",
        title="Prov + Decision",
        type=PageType.CLAIM,
        decision_record=decision,
    )
    page._ko_extra = {"provenance": provenance}

    d = page.to_frontmatter_dict()
    page2 = WikiPage.from_dict(d)

    # Top-level decision_record survives as-is
    assert page2.decision_record == decision
    # _ko_extra.provenance survives unchanged
    assert page2._ko_extra["provenance"] == provenance


# ---------------------------------------------------------------------------
# Test 3: provenance + legacy memory coexist (memory.decision lift must not
# drop provenance)
# ---------------------------------------------------------------------------
def test_ko_extra_provenance_and_legacy_memory_coexist():
    """When _ko_extra carries both provenance and a legacy memory.decision
    payload, the Commit 2 lift of memory.decision -> decision_record must
    leave provenance intact."""
    provenance = {"source_path": "book.pdf", "page": 12}
    legacy_decision = {"status": "pending", "by": "human"}

    fm = {
        "id": "legacy-mix",
        "title": "Legacy Mix",
        "type": "claim",
        "workflow_state": "draft",
        "_ko_extra": {
            "provenance": provenance,
            "memory": {"decision": legacy_decision},
        },
    }
    page = WikiPage.from_dict(fm)

    # Commit 2 lift of memory.decision -> decision_record
    assert page.decision_record == legacy_decision
    # Provenance survives the lift unchanged
    assert page._ko_extra["provenance"] == provenance


# ---------------------------------------------------------------------------
# Test 4: byte-for-byte equivalence across round-trip
# ---------------------------------------------------------------------------
def test_ko_extra_provenance_byte_for_byte_round_trip():
    """A non-trivial provenance payload (nested dict + list + unicode)
    must serialize -> deserialize to a structurally equal dict."""
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
    page = WikiPage(
        id="bytewise",
        title="Bytewise",
        type=PageType.SOURCE,
    )
    page._ko_extra = {"provenance": payload}

    d = page.to_frontmatter_dict()
    page2 = WikiPage.from_dict(d)

    assert page2._ko_extra["provenance"] == payload


# ---------------------------------------------------------------------------
# Test 5: absence case — no provenance, no phantom key
# ---------------------------------------------------------------------------
def test_no_provenance_no_phantom_ko_extra_provenance():
    """A page with empty _ko_extra (no provenance key) must not gain a
    phantom _ko_extra.provenance dict on round-trip."""
    page = WikiPage(
        id="no-prov",
        title="No Provenance",
        type=PageType.CONCEPT,
    )
    page._ko_extra = {}

    d = page.to_frontmatter_dict()
    # to_frontmatter_dict writes _ko_extra if it's a dict (even empty),
    # but the empty dict must NOT silently gain a provenance key.
    page2 = WikiPage.from_dict(d)
    assert hasattr(page2, "_ko_extra")
    assert "provenance" not in page2._ko_extra


# ---------------------------------------------------------------------------
# Test 6 (bonus): to_frontmatter_dict writes _ko_extra.provenance as-is
# (not migrated, not stripped). This documents the preservation contract.
# ---------------------------------------------------------------------------
def test_to_frontmatter_dict_writes_provenance_verbatim():
    """to_frontmatter_dict must write _ko_extra.provenance verbatim with
    no transformation. Documents the preservation contract from
    src/wiki/core/types.py:95-97."""
    payload = {"source_path": "x.pdf", "page": 1, "quote": "q"}
    page = WikiPage(
        id="verbatim",
        title="Verbatim",
        type=PageType.SOURCE,
    )
    page._ko_extra = {"provenance": payload}

    d = page.to_frontmatter_dict()
    assert "_ko_extra" in d
    assert d["_ko_extra"]["provenance"] == payload