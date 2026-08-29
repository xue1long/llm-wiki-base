"""Tests for Book / Chapter / KnowledgeBlock / OutlineProposal contract (B-T1).

Roadmap §12.5 (Book Contract) — A8 (简化 Book 视图):

    book:
      id, title, template_id, outline_version, publication_version, chapter_ids

    chapter:
      id, book_id, stable_key, title, order,
      knowledge_block_ids, source_knowledge_unit_ids, publication_version

    knowledge_block:
      id, chapter_id,
      block_type: definition | principle | method | example | perspective | conflict
      knowledge_unit_ids, statement_refs,
      evidence_refs, knowledge_mode: observed | synthesized

    outline_proposal:
      id, book_id, trigger_knowledge_unit_ids, affected_chapter_ids,
      migration_mapping, rollback_mapping,
      status: proposed | approved | rejected | applied
      reviewer

Plus the inner ``StatementRef`` (object_type + object_id).

TDD coverage (B-T1 scope — dataclass + serialization + enum validation only):
1. Book round-trip preserves all fields incl. defaults
2. Chapter round-trip preserves all fields incl. defaults
3. KnowledgeBlock round-trip incl. nested StatementRef list
4. OutlineProposal round-trip incl. dict mapping fields
5. Enum validation rejects unknown values
6. Default values match spec exactly (outline_version=1, publication_version=0, etc.)
7. Empty list / dict defaults
8. id_policy generators produce correctly formatted strings
9. id_policy slug normalization (lowercase, strip, fallback to "untitled")
"""
from __future__ import annotations

import pytest

# Imports intentionally fail before implementation is added — TDD red phase.
from src.kc.views.book import (
    Book,
    Chapter,
    KnowledgeBlock,
    KnowledgeBlockType,
    KnowledgeMode,
    OutlineProposal,
    OutlineProposalStatus,
    StatementRef,
    generate_book_id,
    generate_chapter_id,
    generate_knowledge_block_id,
    generate_outline_proposal_id,
)


# ─── Helpers ────────────────────────────────────────────────────────────


def _statement_ref(object_type: str = "claim", object_id: str = "cl-001"):
    return StatementRef(object_type=object_type, object_id=object_id)


# ─── Test 1: Book round-trip ────────────────────────────────────────────


def test_book_roundtrip_preserves_all_fields():
    """to_dict → from_dict reproduces an identical Book instance."""
    original = Book(
        id="book_abcdef01_overview",
        title="Overview",
        template_id="tpl-default",
        outline_version=3,
        publication_version=7,
        chapter_ids=["ch_a1b2c3d4_intro", "ch_e5f6g7h8_body"],
    )
    payload = original.to_dict()
    restored = Book.from_dict(payload)
    assert restored == original
    # Spot-check field values
    assert restored.id == "book_abcdef01_overview"
    assert restored.title == "Overview"
    assert restored.outline_version == 3
    assert restored.publication_version == 7
    assert restored.chapter_ids == ["ch_a1b2c3d4_intro", "ch_e5f6g7h8_body"]


# ─── Test 2: Chapter round-trip ─────────────────────────────────────────


def test_chapter_roundtrip_preserves_all_fields():
    """to_dict → from_dict reproduces an identical Chapter instance."""
    original = Chapter(
        id="ch_12345678_introduction",
        book_id="book_abcdef01_overview",
        stable_key="intro",
        title="Introduction",
        order=0,
        knowledge_block_ids=["kb_11111111_def", "kb_22222222_ex"],
        source_knowledge_unit_ids=["ku-001", "ku-002"],
        publication_version=2,
    )
    payload = original.to_dict()
    restored = Chapter.from_dict(payload)
    assert restored == original
    assert restored.stable_key == "intro"
    assert restored.knowledge_block_ids == ["kb_11111111_def", "kb_22222222_ex"]
    assert restored.source_knowledge_unit_ids == ["ku-001", "ku-002"]
    assert restored.publication_version == 2


# ─── Test 3: KnowledgeBlock round-trip with nested StatementRef ─────────


def test_knowledge_block_roundtrip_with_nested_statement_refs():
    """KnowledgeBlock round-trip preserves nested StatementRef list."""
    original = KnowledgeBlock(
        id="kb_87654321_definition",
        chapter_id="ch_12345678_introduction",
        block_type=KnowledgeBlockType.DEFINITION,
        knowledge_unit_ids=["ku-001"],
        statement_refs=[
            StatementRef(object_type="claim", object_id="cl-001"),
            StatementRef(object_type="structured_fact", object_id="sf-002"),
        ],
        evidence_refs=["ev-001", "ev-002"],
        knowledge_mode="observed",
    )
    payload = original.to_dict()
    # statement_refs must round-trip as nested dicts, not strings
    assert isinstance(payload["statement_refs"], list)
    assert payload["statement_refs"][0] == {
        "object_type": "claim",
        "object_id": "cl-001",
    }
    restored = KnowledgeBlock.from_dict(payload)
    assert restored == original
    assert restored.statement_refs[0].object_type == "claim"
    assert restored.statement_refs[1].object_type == "structured_fact"
    assert restored.block_type == KnowledgeBlockType.DEFINITION
    assert restored.knowledge_mode == "observed"


# ─── Test 4: OutlineProposal round-trip ─────────────────────────────────


def test_outline_proposal_roundtrip_with_mapping_dicts():
    """OutlineProposal round-trip preserves mapping dicts + status enum."""
    original = OutlineProposal(
        id="op_11111111_split",
        book_id="book_abcdef01_overview",
        trigger_knowledge_unit_ids=["ku-099"],
        affected_chapter_ids=["ch_12345678_introduction"],
        migration_mapping={"ch_12345678_introduction": "ch_22222222_intro_v2"},
        rollback_mapping={"ch_22222222_intro_v2": "ch_12345678_introduction"},
        status=OutlineProposalStatus.PROPOSED,
        reviewer=None,
    )
    payload = original.to_dict()
    # Mapping fields round-trip as plain dicts
    assert payload["migration_mapping"] == {
        "ch_12345678_introduction": "ch_22222222_intro_v2",
    }
    restored = OutlineProposal.from_dict(payload)
    assert restored == original
    assert restored.status == OutlineProposalStatus.PROPOSED
    assert restored.reviewer is None
    assert restored.affected_chapter_ids == ["ch_12345678_introduction"]


# ─── Test 5: Enum validation rejects unknown values ─────────────────────


@pytest.mark.parametrize(
    "bad_value",
    ["narrative", "summary", "claim", "Definition", "", "OBSERVED"],
)
def test_knowledge_block_type_from_dict_rejects_unknown(bad_value):
    """KnowledgeBlock.from_dict must raise ValueError on unknown block_type."""
    payload = {
        "id": "kb_11111111_x",
        "chapter_id": "ch_22222222_y",
        "block_type": bad_value,
        "knowledge_unit_ids": [],
        "statement_refs": [],
        "evidence_refs": [],
        "knowledge_mode": "observed",
    }
    with pytest.raises(ValueError) as excinfo:
        KnowledgeBlock.from_dict(payload)
    # The error message must surface the field name and the rejected value
    msg = str(excinfo.value)
    assert "block_type" in msg
    assert str(bad_value) in msg


@pytest.mark.parametrize(
    "bad_value",
    ["draft", "pending", "PROPOSED", "Approved", "", "approved "],
)
def test_outline_proposal_status_from_dict_rejects_unknown(bad_value):
    """OutlineProposal.from_dict must raise ValueError on unknown status."""
    payload = {
        "id": "op_11111111_x",
        "book_id": "book_22222222_y",
        "trigger_knowledge_unit_ids": [],
        "affected_chapter_ids": [],
        "migration_mapping": {},
        "rollback_mapping": {},
        "status": bad_value,
        "reviewer": None,
    }
    with pytest.raises(ValueError) as excinfo:
        OutlineProposal.from_dict(payload)
    msg = str(excinfo.value)
    assert "status" in msg
    assert str(bad_value) in msg


def test_knowledge_mode_from_dict_rejects_unknown():
    """KnowledgeBlock.from_dict must reject unknown knowledge_mode values.

    Per the B-T1 spec note: ``knowledge_mode`` defaults to the string
    ``"observed"`` (NOT an enum default) — the YAML example uses bare
    strings. Validation still rejects unknowns.
    """
    payload = {
        "id": "kb_11111111_x",
        "chapter_id": "ch_22222222_y",
        "block_type": "definition",
        "knowledge_unit_ids": [],
        "statement_refs": [],
        "evidence_refs": [],
        "knowledge_mode": "guessed",
    }
    with pytest.raises(ValueError) as excinfo:
        KnowledgeBlock.from_dict(payload)
    assert "knowledge_mode" in str(excinfo.value)


# ─── Test 6: Default values match spec exactly ──────────────────────────


def test_book_default_outline_version_is_one():
    """Book.outline_version defaults to 1 (spec §12.5)."""
    book = Book(id="book_aaaa0000_x", title="T", template_id="tpl")
    assert book.outline_version == 1


def test_book_default_publication_version_is_zero():
    """Book.publication_version defaults to 0 (spec §12.5)."""
    book = Book(id="book_aaaa0000_x", title="T", template_id="tpl")
    assert book.publication_version == 0


def test_knowledge_block_default_knowledge_mode_is_observed_string():
    """KnowledgeBlock.knowledge_mode defaults to "observed" string.

    Per B-T1 spec: default is the bare string ``"observed"`` matching the
    example YAML, NOT an enum default.
    """
    block = KnowledgeBlock(
        id="kb_aaaa0000_x",
        chapter_id="ch_bbbb0000_y",
        block_type=KnowledgeBlockType.DEFINITION,
    )
    assert block.knowledge_mode == "observed"
    assert isinstance(block.knowledge_mode, str)


def test_outline_proposal_default_status_is_proposed_string():
    """OutlineProposal.status defaults to "proposed" string."""
    prop = OutlineProposal(
        id="op_aaaa0000_x",
        book_id="book_bbbb0000_y",
    )
    # Default is the string "proposed" — from_dict will validate it
    assert prop.status == "proposed"
    assert prop.reviewer is None
    # And the value is acceptable to from_dict validation
    restored = OutlineProposal.from_dict(prop.to_dict())
    assert restored == prop


# ─── Test 7: Empty list / empty dict defaults ───────────────────────────


def test_book_default_chapter_ids_is_empty_list():
    """Book.chapter_ids defaults to []."""
    book = Book(id="book_aaaa0000_x", title="T", template_id="tpl")
    assert book.chapter_ids == []


def test_chapter_default_knowledge_block_ids_is_empty_list():
    """Chapter.knowledge_block_ids and source_knowledge_unit_ids default to []."""
    chapter = Chapter(
        id="ch_aaaa0000_x",
        book_id="book_bbbb0000_y",
        stable_key="k",
        title="Title",
        order=0,
    )
    assert chapter.knowledge_block_ids == []
    assert chapter.source_knowledge_unit_ids == []
    assert chapter.publication_version == 0


def test_knowledge_block_default_collections_are_empty():
    """KnowledgeBlock collections default to []."""
    block = KnowledgeBlock(
        id="kb_aaaa0000_x",
        chapter_id="ch_bbbb0000_y",
        block_type=KnowledgeBlockType.METHOD,
    )
    assert block.knowledge_unit_ids == []
    assert block.statement_refs == []
    assert block.evidence_refs == []


def test_outline_proposal_default_collections_and_mappings_are_empty():
    """OutlineProposal collections + mappings default to empty."""
    prop = OutlineProposal(
        id="op_aaaa0000_x",
        book_id="book_bbbb0000_y",
    )
    assert prop.trigger_knowledge_unit_ids == []
    assert prop.affected_chapter_ids == []
    assert prop.migration_mapping == {}
    assert prop.rollback_mapping == {}


# ─── Test 8: id_policy generators ──────────────────────────────────────


def test_generate_book_id_format():
    """generate_book_id returns '<prefix><uuid8>_<slug>'."""
    bid = generate_book_id("overview")
    assert bid.startswith("book_")
    parts = bid.split("_")
    # book_<uuid8>_<slug>
    assert parts[0] == "book"
    assert len(parts[1]) == 8  # uuid hex[:8]
    assert parts[2] == "overview"


def test_generate_chapter_id_format():
    """generate_chapter_id returns 'ch_<uuid8>_<slug>'."""
    cid = generate_chapter_id("intro")
    assert cid.startswith("ch_")
    parts = cid.split("_")
    assert parts[0] == "ch"
    assert len(parts[1]) == 8
    assert parts[2] == "intro"


def test_generate_knowledge_block_id_format():
    """generate_knowledge_block_id returns 'kb_<uuid8>_<slug>'."""
    kid = generate_knowledge_block_id("definition")
    assert kid.startswith("kb_")
    parts = kid.split("_")
    assert parts[0] == "kb"
    assert len(parts[1]) == 8
    assert parts[2] == "definition"


def test_generate_outline_proposal_id_format():
    """generate_outline_proposal_id returns 'op_<uuid8>_<slug>'."""
    oid = generate_outline_proposal_id("split")
    assert oid.startswith("op_")
    parts = oid.split("_")
    assert parts[0] == "op"
    assert len(parts[1]) == 8
    assert parts[2] == "split"


def test_id_generators_produce_unique_values():
    """Each generator must produce different IDs across calls."""
    a = generate_book_id("foo")
    b = generate_book_id("foo")
    assert a != b  # uuid portion is random


# ─── Test 9: id_policy slug normalization ───────────────────────────────


@pytest.mark.parametrize(
    "raw,expected_slug",
    [
        ("Overview", "overview"),
        ("Hello World", "hello-world"),
        ("  Trim-Me  ", "trim-me"),
        ("Multi   Space", "multi-space"),
        ("UPPER_lower", "upper-lower"),
        ("Special!@#Chars", "special-chars"),
        ("", "untitled"),
        ("   ", "untitled"),
        ("---", "untitled"),
        ("!!!", "untitled"),
    ],
)
def test_slug_normalization_lowercase_strip_fallback(raw, expected_slug):
    """Slugs are lowercased, non-[a-z0-9] runs collapse to '-', leading/trailing
    '-' stripped, empty after cleanup falls back to 'untitled'."""
    bid = generate_book_id(raw)
    # The slug portion is everything after the uuid
    slug = bid.split("_", 2)[2]
    assert slug == expected_slug


def test_slug_length_capped_at_40_chars():
    """Slugs longer than 40 chars are truncated (B-T1 spec)."""
    long_slug = "a" * 100
    bid = generate_book_id(long_slug)
    slug = bid.split("_", 2)[2]
    assert len(slug) == 40
    assert slug == "a" * 40
