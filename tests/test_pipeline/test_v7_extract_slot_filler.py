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
        # v3.1 (T1): LLM cites by zero-based item_index into `sources`.
        "definition": {"item_index": 0, "source_text_excerpt": "openings are important"},
        "characteristics": {"item_index": 0, "source_text_excerpt": "three techniques"},
        "examples": {"item_index": 0, "source_text_excerpt": "examples from"},
        "related_concepts": {"item_index": 0, "source_text_excerpt": "see conflict"},
        "references": {"item_index": 0, "source_text_excerpt": "raw source 1"},
    },
}

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
        source_text=_VALID_SOURCE_TEXT,
    )
    assert page.id == "p1"
    assert page.title == "How to write openings"
    assert all(name in page.slots for name in CONCEPT_SLOTS)
    assert page.has_evidence is True
    assert page.needs_review_slots == ()
    # item_index 0 → sources[0] == "raw-1" → SlotEvidence.item_id canonical id
    for name in CONCEPT_SLOTS:
        assert page.slot_evidence[name].evidence.item_id == "raw-1"


def test_payload_to_page_marks_unknown_item_id_as_needs_review():
    """Out-of-range / missing item_index → no canonical item_id → needs_review (D7)."""
    payload = {
        "slots": _VALID_PAYLOAD["slots"],
        "evidence": {
            "definition": {"item_index": 99, "source_text_excerpt": "..."},
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
    # Invalid index → empty canonical id, NOT a coerced bogus value
    assert page.slot_evidence["definition"].evidence.item_id == ""


def test_payload_to_page_marks_missing_excerpt_as_no_needs_review():
    """Empty excerpt + valid item_index → has_evidence=True (item_index check passes).

    v3.1: the excerpt is no longer substring-gated. Empty excerpt is fine;
    the LLM may simply omit the human-reference excerpt.
    """
    payload = {
        "slots": _VALID_PAYLOAD["slots"],
        "evidence": {
            "definition": {"item_index": 0, "source_text_excerpt": ""},
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
    # has_evidence is True because item_index 0 → "raw-1" (canonical id).
    assert page.slot_evidence["definition"].evidence.has_evidence is True
    assert page.slot_evidence["definition"].needs_review is False
    assert page.slot_evidence["definition"].evidence.item_id == "raw-1"


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


def test_payload_to_page_excerpt_not_in_source_does_not_mark_needs_review():
    """v3.1 (T1): excerpt is human reference only, NOT a substring gate.

    Previously this case marked the slot needs_review because the excerpt
    wasn't found in source_text. The new contract trusts the integer
    item_index for canonical provenance and keeps the excerpt for human
    reviewers verbatim — it does NOT auto-flip needs_review.
    """
    payload = {
        "slots": _VALID_PAYLOAD["slots"],
        "evidence": {
            "definition": {
                "item_index": 0,
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
    # item_index is valid (0 → "raw-1"), so has_evidence is True.
    assert page.slot_evidence["definition"].evidence.has_evidence is True
    # needs_review is NOT auto-flipped just because excerpt is missing.
    assert page.slot_evidence["definition"].needs_review is False
    # The excerpt is preserved verbatim for human reviewers.
    assert (
        page.slot_evidence["definition"].evidence.source_text_excerpt
        == "completely fabricated quote that never appeared"
    )


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
    # v3.1: LLM cites by item_index integer into Topic.item_ids, not by item_id string.
    fake.script(
        "fill_slots",
        '{"slots": '
        '{"definition":"How to write openings",'
        '"characteristics":"3 techniques",'
        '"examples":"Examples",'
        '"related_concepts":"conflict",'
        '"references":"raw source 1"}, '
        '"evidence": '
        '{"definition":{"item_index":0,"source_text_excerpt":"openings are important"},'
        '"characteristics":{"item_index":0,"source_text_excerpt":"three techniques"},'
        '"examples":{"item_index":0,"source_text_excerpt":"examples from published"},'
        '"related_concepts":{"item_index":0,"source_text_excerpt":"see conflict"},'
        '"references":{"item_index":0,"source_text_excerpt":"raw source 1"}}}',
    )

    topic = Topic(id="p1", title="How to write openings", item_ids=["raw-1"])
    page = await fill_slots(
        topic, _VALID_SOURCE_TEXT, llm=fake,
        item_texts={"raw-1": _VALID_SOURCE_TEXT},
        project_root=None,
    )
    assert page is not None
    assert page.has_evidence is True
    # Script-owned canonical item_id mapping
    assert page.slot_evidence["definition"].evidence.item_id == "raw-1"


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


# ---------------------------------------------------------------------------
# T1 / H2 加固 — Stage 5 evidence input contract:
#   - LLM receives numbered item list
#   - LLM returns item_index (int), NOT item_id (string)
#   - Script maps item_index → Topic.item_ids[index] (canonical ID)
#   - Invalid index / missing evidence / empty body → needs_review
#   - source_text_excerpt is preserved as human reference, NOT a hard gate
# ---------------------------------------------------------------------------


# Two item_ids for a single topic — simulates Stage 4 assigning two items
# to one topic. The LLM is asked to cite evidence by zero-based index.
_TOPIC_ITEM_IDS = [
    "raw/sources/source_a.md#section-1",
    "raw/sources/source_a.md#section-2",
]


def test_payload_to_page_maps_item_index_to_canonical_item_id():
    """Valid item_index → SlotEvidence.item_id == Topic.item_ids[index]."""
    payload = {
        "slots": {name: f"<{name}>" for name in CONCEPT_SLOTS},
        "evidence": {
            "definition": {"item_index": 0, "source_text_excerpt": "openings"},
            "characteristics": {"item_index": 1, "source_text_excerpt": "techniques"},
            "examples": {"item_index": 0, "source_text_excerpt": "examples"},
            "related_concepts": {"item_index": 1, "source_text_excerpt": "related"},
            "references": {"item_index": 0, "source_text_excerpt": "refs"},
        },
    }
    page = _payload_to_page(
        payload=payload,
        topic_id="topic-a",
        title="Topic A",
        sources=list(_TOPIC_ITEM_IDS),
        item_texts={},
        source_text="anything",
    )
    # Every slot's evidence.item_id must equal Topic.item_ids[item_index].
    for name in CONCEPT_SLOTS:
        ev = page.slot_evidence[name].evidence
        expected = _TOPIC_ITEM_IDS[payload["evidence"][name]["item_index"]]
        assert ev.item_id == expected, (
            f"slot {name}: item_index→canonical mapping failed: "
            f"got {ev.item_id!r}, expected {expected!r}"
        )
        assert ev.has_evidence is True
        assert ev.needs_review is False
    assert page.has_evidence is True


@pytest.mark.parametrize("bad_index", [-1, 99, 1.5, "0", None, True])
def test_payload_to_page_marks_invalid_item_index_as_needs_review(bad_index):
    """Out-of-range / non-integer index → needs_review, no canonical item_id."""
    payload = {
        "slots": {name: f"<{name}>" for name in CONCEPT_SLOTS},
        "evidence": {
            "definition": {"item_index": bad_index, "source_text_excerpt": "..."},
        },
    }
    page = _payload_to_page(
        payload=payload,
        topic_id="topic-a",
        title="Topic A",
        sources=list(_TOPIC_ITEM_IDS),  # 2 items
        item_texts={},
        source_text="",
    )
    # Bad index → that slot has no valid evidence.
    assert page.slot_evidence["definition"].evidence.has_evidence is False
    assert page.slot_evidence["definition"].evidence.needs_review is True
    # item_id must NOT be silently coerced to a bogus canonical id
    assert page.slot_evidence["definition"].evidence.item_id == ""
    # Page-level has_evidence is False (at least one slot is needs_review)
    assert page.has_evidence is False


def test_payload_to_page_empty_body_marks_needs_review():
    """Empty body string → that slot goes to needs_review (no fabricated fill)."""
    payload = {
        "slots": {
            "definition": "",
            "characteristics": "ok",
            "examples": "ok",
            "related_concepts": "ok",
            "references": "ok",
        },
        "evidence": {
            "definition": {"item_index": 0, "source_text_excerpt": "..."},
            "characteristics": {"item_index": 0, "source_text_excerpt": "..."},
            "examples": {"item_index": 0, "source_text_excerpt": "..."},
            "related_concepts": {"item_index": 0, "source_text_excerpt": "..."},
            "references": {"item_index": 0, "source_text_excerpt": "..."},
        },
    }
    page = _payload_to_page(
        payload=payload,
        topic_id="topic-a",
        title="Topic A",
        sources=list(_TOPIC_ITEM_IDS),
        item_texts={},
        source_text="",
    )
    assert "definition" in page.needs_review_slots


def test_payload_to_page_keeps_excerpt_even_when_not_in_source():
    """source_text_excerpt is now a human reference, NOT a substring gate.

    The LLM may paraphrase. We still record the excerpt verbatim but do NOT
    flip needs_review just because the literal substring isn't in source_text.
    """
    payload = {
        "slots": {name: f"<{name}>" for name in CONCEPT_SLOTS},
        "evidence": {
            "definition": {
                "item_index": 0,
                "source_text_excerpt": "completely fabricated text not in source",
            },
            "characteristics": {"item_index": 0, "source_text_excerpt": "x"},
            "examples": {"item_index": 0, "source_text_excerpt": "x"},
            "related_concepts": {"item_index": 0, "source_text_excerpt": "x"},
            "references": {"item_index": 0, "source_text_excerpt": "x"},
        },
    }
    page = _payload_to_page(
        payload=payload,
        topic_id="topic-a",
        title="Topic A",
        sources=list(_TOPIC_ITEM_IDS),
        item_texts={},
        source_text="nothing matches here",
    )
    ev = page.slot_evidence["definition"].evidence
    # has_evidence remains True (item_index maps to a valid item_id).
    assert ev.has_evidence is True
    # The excerpt is preserved verbatim for human reviewers.
    assert ev.source_text_excerpt == "completely fabricated text not in source"
    # needs_review is NOT auto-flipped just because excerpt is missing.
    assert ev.needs_review is False


def test_payload_to_page_missing_evidence_marks_all_needs_review():
    """Missing evidence payload → every slot has has_evidence=False.

    No canonical item_id is ever assigned. The page is "blocked" — extract_pilot
    routes it to review_queue (D7), never to WikiWriter.
    """
    payload = {"slots": {name: f"<{name}>" for name in CONCEPT_SLOTS}, "evidence": {}}
    page = _payload_to_page(
        payload=payload,
        topic_id="topic-a",
        title="Topic A",
        sources=list(_TOPIC_ITEM_IDS),
        item_texts={},
        source_text="",
    )
    for name in CONCEPT_SLOTS:
        assert page.slot_evidence[name].evidence.has_evidence is False
        assert page.slot_evidence[name].evidence.item_id == ""
    assert page.has_evidence is False
    assert set(page.needs_review_slots) == set(CONCEPT_SLOTS)


def test_payload_to_page_stable_page_id_distinct_for_two_sources_same_topic():
    """Cross-document uniqueness: same topic id ('writing-techniques') under
    two different sources must produce two distinct page IDs via _page_id.

    This is the H2 加固 invariant from
    .superpowers/sdd/.../wave0/shared-fixture.md: the script owns page IDs
    end-to-end, so two sources that happen to share a topic slug never
    collide. extract_pilot constructs the page ID; here we simulate by
    calling _page_id directly with the relative paths.
    """
    from src.pipeline.v7_extract._page_id import _stable_page_id, validate_page_id

    id_a = _stable_page_id("v7_control_plane/source_a.md", "writing-techniques")
    id_b = _stable_page_id("v7_control_plane/source_b.md", "writing-techniques")
    assert id_a != id_b
    # Both IDs must validate — no accidental slashes or '..' injected.
    validate_page_id(id_a)
    validate_page_id(id_b)


@pytest.mark.asyncio
async def test_fill_slots_records_numbered_item_list_in_prompt():
    """The user prompt fed to the LLM carries the items as a numbered list,
    NOT a comma-separated source_id string. The LLM uses these indexes to
    cite evidence via item_index (int)."""
    captured: list[dict] = []

    class _CaptureLLM:
        async def complete(self, *, prompt_kind, user_prompt, **_kw):
            captured.append({"prompt_kind": prompt_kind, "user_prompt": user_prompt})
            return '{"slots": {}, "evidence": {}}'

    topic = Topic(
        id="t1",
        title="写作技法",
        item_ids=[
            "raw/sources/source_a.md#section-1",
            "raw/sources/source_a.md#section-2",
        ],
    )
    await fill_slots(topic, "source body", llm=_CaptureLLM(), project_root=None)

    assert captured, "fill_slots should have called the LLM"
    user_prompt = captured[0]["user_prompt"]
    # Numbered list: each item_id is preceded by a zero-based index marker.
    assert "0:" in user_prompt, f"prompt missing index 0 marker:\n{user_prompt}"
    assert "1:" in user_prompt, f"prompt missing index 1 marker:\n{user_prompt}"
    # Both canonical item_ids appear so the LLM can map index → id.
    assert "raw/sources/source_a.md#section-1" in user_prompt
    assert "raw/sources/source_a.md#section-2" in user_prompt
    # Contract: prompt tells the LLM the citation is by integer index.
    assert "item_index" in user_prompt
    assert "integer" in user_prompt.lower()
