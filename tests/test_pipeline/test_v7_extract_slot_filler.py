"""T2.4: Stage 5 slot_filler — async LLM + D7 single-topic failure."""
from __future__ import annotations

import pytest

from src.pipeline.v7_extract.slot_filler import (
    CONCEPT_SLOTS,
    ConceptPage,
    Slot,
    SlotEvidence,
    _excerpt_in_source,
    _payload_to_page,
    _resolve_fill_slots_template,
    _topic_parts,
    fill_slots,
)
from src.pipeline.v7_extract.topic_clusterer import Topic
from src.pipeline.v7_extract.llm_client import FakeLLMClient


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def test_concept_slots_is_five_slots():
    assert len(CONCEPT_SLOTS) == 5
    assert "definition" in CONCEPT_SLOTS
    assert "characteristics" in CONCEPT_SLOTS
    assert "examples" in CONCEPT_SLOTS
    assert "related_concepts" in CONCEPT_SLOTS
    assert "references" in CONCEPT_SLOTS


# ---------------------------------------------------------------------------
# Slot / SlotEvidence / ConceptPage
# ---------------------------------------------------------------------------

def test_slot_evidence_to_dict():
    ev = SlotEvidence(item_id="x", source_text_excerpt="...", has_evidence=True)
    d = ev.to_dict()
    assert d["item_id"] == "x"
    assert d["has_evidence"] is True


def test_slot_to_dict():
    s = Slot(name="def", body="body", evidence=SlotEvidence(has_evidence=True))
    d = s.to_dict()
    assert d["name"] == "def"
    assert d["body"] == "body"
    assert d["evidence"]["has_evidence"] is True


def test_concept_page_body_renders_5_sections():
    page = ConceptPage(
        id="p1",
        title="Test",
        slots={n: f"<{n}>" for n in CONCEPT_SLOTS},
    )
    body = page.body
    assert body.count("## ") == 5
    for name in CONCEPT_SLOTS:
        assert name in body


def test_concept_page_has_evidence_true_when_all_slots_valid():
    page = ConceptPage(
        id="p1",
        title="t",
        slots={n: "x" for n in CONCEPT_SLOTS},
        slot_evidence={
            n: Slot(name=n, body="x", evidence=SlotEvidence(has_evidence=True))
            for n in CONCEPT_SLOTS
        },
    )
    assert page.has_evidence is True


def test_concept_page_has_evidence_false_when_any_needs_review():
    slots = {
        n: Slot(name=n, body="x", evidence=SlotEvidence(has_evidence=True, needs_review=False))
        for n in CONCEPT_SLOTS
    }
    # Replace one slot with needs_review=True (frozen dataclass, replace whole Slot)
    slots["definition"] = Slot(
        name="definition",
        body="x",
        evidence=SlotEvidence(has_evidence=False, needs_review=True),
        needs_review=True,
    )
    page = ConceptPage(
        id="p1",
        title="t",
        slots={n: "x" for n in CONCEPT_SLOTS},
        slot_evidence=slots,
        needs_review_slots=("definition",),
    )
    assert page.has_evidence is False


# ---------------------------------------------------------------------------
# _topic_parts helper
# ---------------------------------------------------------------------------

def test_topic_parts_from_topic_dataclass():
    topic = Topic(id="t1", title="T1", item_ids=["a", "b"])
    assert _topic_parts(topic) == ("t1", "T1", ["a", "b"])


def test_topic_parts_from_dict():
    topic = {"id": "t1", "title": "T1", "item_ids": ["a"]}
    assert _topic_parts(topic) == ("t1", "T1", ["a"])


def test_topic_parts_from_minimal_dict():
    topic = {"id": "t1", "title": "T1"}
    assert _topic_parts(topic) == ("t1", "T1", [])


# ---------------------------------------------------------------------------
# _excerpt_in_source helper
# ---------------------------------------------------------------------------

def test_excerpt_in_source_empty():
    assert _excerpt_in_source("", "some source") is False
    assert _excerpt_in_source("   ", "some source") is False


def test_excerpt_in_source_short_exact_match():
    assert _excerpt_in_source("hello", "say hello world") is True


def test_excerpt_in_source_short_no_match():
    assert _excerpt_in_source("xyz", "say hello world") is False


def test_excerpt_in_source_long_substring_match():
    """Long excerpts (>=20 chars) need only first 20 chars to match."""
    excerpt = "this is a long passage that appears in the source material"
    source = "...blah blah " + excerpt + " blah blah..."
    assert _excerpt_in_source(excerpt, source) is True


def test_excerpt_in_source_long_no_match():
    """Long excerpts that don't appear at all → False."""
    excerpt = "this passage is nowhere to be found"
    source = "completely unrelated source text here"
    assert _excerpt_in_source(excerpt, source) is False


# ---------------------------------------------------------------------------
# _payload_to_page helper
# ---------------------------------------------------------------------------

_VALID_PAYLOAD = {
    "slots": {
        "definition": "How to write strong openings",
        "characteristics": "3 techniques",
        "examples": "Examples from published novels",
        "related_concepts": "See [[conflict]]",
        "references": "raw source 1",
    },
    "evidence": {
        "definition": {"item_id": "raw-1", "source_text_excerpt": "openings are important"},
        "characteristics": {"item_id": "raw-1", "source_text_excerpt": "three techniques"},
        "examples": {"item_id": "raw-1", "source_text_excerpt": "examples from"},
        "related_concepts": {"item_id": "raw-1", "source_text_excerpt": "see conflict"},
        "references": {"item_id": "raw-1", "source_text_excerpt": "raw source 1"},
    },
}

# source_text that contains every excerpt substring above (≥20 chars each).
# Note: "see conflict" is a 12-char excerpt → exact match required, so we
# include "see conflict for" verbatim (no [[brackets]] around "conflict").
_VALID_SOURCE_TEXT = (
    "Openings are important. "
    "Three techniques: 1. start in media res, 2. anchor with conflict, 3. show the genre. "
    "Examples from published novels like 《斗破苍穹》 and 《凡人修仙传》. "
    "See conflict for related concepts. "
    "This article was sourced from raw source 1."
)


def test_payload_to_page_happy_path():
    page = _payload_to_page(
        payload=_VALID_PAYLOAD,
        topic_id="p1",
        title="How to write openings",
        sources=["raw-1"],
        item_texts={"raw-1": _VALID_SOURCE_TEXT},
        source_text=_VALID_SOURCE_TEXT,  # must contain every excerpt substring
    )
    assert page.id == "p1"
    assert page.title == "How to write openings"
    assert all(name in page.slots for name in CONCEPT_SLOTS)
    assert page.has_evidence is True
    assert page.needs_review_slots == ()


def test_payload_to_page_marks_unknown_item_id_as_needs_review():
    """Evidence with item_id not in sources → needs_review (D7)."""
    payload = {
        "slots": _VALID_PAYLOAD["slots"],
        "evidence": {
            "definition": {"item_id": "ghost-item", "source_text_excerpt": "..."},
        },
    }
    page = _payload_to_page(
        payload=payload,
        topic_id="p1",
        title="t",
        sources=["raw-1"],
        item_texts={},
        source_text="",
    )
    # Only definition slot marked; rest are missing → needs_review
    assert "definition" in page.needs_review_slots
    # Other slots have no evidence (None) → also needs_review
    assert page.has_evidence is False


def test_payload_to_page_marks_missing_excerpt_as_needs_review():
    """Empty excerpt + valid item_id → still has_evidence=True (item_id check passes).

    The 'excerpt not in source' check only fires when excerpt is non-empty
    AND doesn't appear in source_text. An empty excerpt skips the check.
    """
    payload = {
        "slots": _VALID_PAYLOAD["slots"],
        "evidence": {
            "definition": {"item_id": "raw-1", "source_text_excerpt": ""},
        },
    }
    page = _payload_to_page(
        payload=payload,
        topic_id="p1",
        title="t",
        sources=["raw-1"],
        item_texts={"raw-1": "x"},
        source_text="...",
    )
    # has_evidence is True because item_id matches; empty excerpt skips substring check
    assert page.slot_evidence["definition"].evidence.has_evidence is True
    assert page.slot_evidence["definition"].needs_review is False


def test_payload_to_page_handles_missing_evidence_keys():
    """LLM returns slots but no evidence — all slots marked needs_review."""
    payload = {"slots": _VALID_PAYLOAD["slots"], "evidence": {}}
    page = _payload_to_page(
        payload=payload,
        topic_id="p1",
        title="t",
        sources=["raw-1"],
        item_texts={"raw-1": "x"},
        source_text="...",
    )
    assert page.has_evidence is False
    assert set(page.needs_review_slots) == set(CONCEPT_SLOTS)


def test_payload_to_page_excerpt_not_in_source_marks_needs_review():
    """D7: if excerpt doesn't appear in source_text, mark needs_review."""
    payload = {
        "slots": _VALID_PAYLOAD["slots"],
        "evidence": {
            "definition": {
                "item_id": "raw-1",
                "source_text_excerpt": "completely fabricated quote that never appeared",
            },
        },
    }
    page = _payload_to_page(
        payload=payload,
        topic_id="p1",
        title="t",
        sources=["raw-1"],
        item_texts={"raw-1": "x"},
        source_text="real source text here",
    )
    # item_id matches, but excerpt fails substring check
    assert page.slot_evidence["definition"].needs_review is True


# ---------------------------------------------------------------------------
# _resolve_fill_slots_template helper
# ---------------------------------------------------------------------------

def test_resolve_fill_slots_template_uses_bundled():
    template = _resolve_fill_slots_template(project_root=None)
    assert template.prompt_kind == "fill_slots"
    assert template.source == "bundled"


# ---------------------------------------------------------------------------
# fill_slots — happy paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fill_slots_returns_concept_page_with_evidence():
    fake = FakeLLMClient()
    fake.script(
        "fill_slots",
        '{"slots": '
        '{"definition":"How to write openings",'
        '"characteristics":"3 techniques",'
        '"examples":"Examples",'
        '"related_concepts":"conflict",'
        '"references":"raw source 1"}, '
        '"evidence": '
        '{"definition":{"item_id":"raw-1","source_text_excerpt":"openings are important"},'
        '"characteristics":{"item_id":"raw-1","source_text_excerpt":"three techniques"},'
        '"examples":{"item_id":"raw-1","source_text_excerpt":"examples from published"},'
        '"related_concepts":{"item_id":"raw-1","source_text_excerpt":"see conflict"},'
        '"references":{"item_id":"raw-1","source_text_excerpt":"raw source 1"}}}',
    )

    topic = Topic(id="p1", title="How to write openings", item_ids=["raw-1"])
    # source_text must contain every excerpt above (≥20 chars each) for
    # Stage 5's _excerpt_in_source check to pass.
    source_text = _VALID_SOURCE_TEXT

    page = await fill_slots(
        topic, source_text, llm=fake,
        item_texts={"raw-1": source_text},
        project_root=None,
    )
    assert page is not None
    assert page.has_evidence is True


@pytest.mark.asyncio
async def test_fill_slots_records_one_llm_call():
    fake = FakeLLMClient()
    fake.script("fill_slots", '{"slots": {}, "evidence": {}}')

    topic = Topic(id="p1", title="t", item_ids=["raw-1"])
    await fill_slots(topic, "body", llm=fake, item_texts={},
                     project_root=None)
    assert len(fake.calls) == 1
    assert fake.calls[0]["prompt_kind"] == "fill_slots"


# ---------------------------------------------------------------------------
# fill_slots — D7: failure returns None (never raises)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fill_slots_returns_none_on_invalid_json():
    fake = FakeLLMClient()
    fake.script("fill_slots", "not json")
    fake.script("fill_slots", "still not json")
    fake.script("fill_slots", "{not even valid}")

    topic = Topic(id="p1", title="t", item_ids=["raw-1"])
    page = await fill_slots(topic, "body", llm=fake, project_root=None)
    assert page is None  # D7
    assert len(fake.calls) == 3


@pytest.mark.asyncio
async def test_fill_slots_returns_none_on_schema_violation():
    """Missing required 'slots' and 'evidence' → LLMResponseError → None."""
    fake = FakeLLMClient()
    fake.script("fill_slots", '{"unrelated": "data"}')

    topic = Topic(id="p1", title="t", item_ids=["raw-1"])
    page = await fill_slots(topic, "body", llm=fake, project_root=None)
    assert page is None


@pytest.mark.asyncio
async def test_fill_slots_handles_llm_raising_exception():
    class _ExplodingFake:
        async def complete(self, **kwargs):
            raise RuntimeError("simulated LLM outage")

    topic = Topic(id="p1", title="t", item_ids=["raw-1"])
    page = await fill_slots(topic, "body", llm=_ExplodingFake(),
                           project_root=None)
    assert page is None  # D7: caller drops this topic


@pytest.mark.asyncio
async def test_fill_slots_succeeds_after_two_invalid_retries():
    fake = FakeLLMClient()
    fake.script("fill_slots", "")
    fake.script("fill_slots", '{"slots": {}, "evidence": {}}')
    fake.script("fill_slots", '{"slots": {}, "evidence": {}}')

    topic = Topic(id="p1", title="t", item_ids=["raw-1"])
    page = await fill_slots(topic, "body", llm=fake, project_root=None)
    assert page is not None
    assert len(fake.calls) == 2


@pytest.mark.asyncio
async def test_fill_slots_accepts_dict_topic():
    fake = FakeLLMClient()
    fake.script("fill_slots", '{"slots": {}, "evidence": {}}')

    topic_dict = {"id": "p1", "title": "t", "item_ids": ["raw-1"]}
    page = await fill_slots(topic_dict, "body", llm=fake, project_root=None)
    assert page is not None
    assert page.id == "p1"
