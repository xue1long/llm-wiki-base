from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from src.kc.views.book import (
    Chapter,
    ChapterRender,
    CompiledBlock,
    EvidenceRef,
    KnowledgeBlock,
    KnowledgeBlockType,
    BookTemplate,
    BookView,
    compute_book_rendered_hash,
    render_chapter,
    render_chapter_from_dict,
)


def _chapter() -> Chapter:
    return Chapter("ch-1", "book-1", "intro", "Introduction", 1)


def _ref(eid: str = "ev-1", strength: str = "strong") -> EvidenceRef:
    return EvidenceRef(eid, strength, "direct_quote", "quote", "hash", "doc-1", "blk-1")


def _block(block_id: str = "kb-1", kind: KnowledgeBlockType = KnowledgeBlockType.DEFINITION) -> CompiledBlock:
    block = KnowledgeBlock(
        id=block_id,
        chapter_id="ch-1",
        block_type=kind,
        knowledge_unit_ids=[f"ku-{block_id}"],
        knowledge_mode="observed",
    )
    return CompiledBlock(block, (_ref(),), False, ())


def _render(*blocks: CompiledBlock | None, conflicts=None) -> ChapterRender:
    return ChapterRender(
        chapter=_chapter(),
        blocks=tuple(b for b in blocks if b is not None),
        publication_version=7,
        rendered_at=123,
        integrity_report=SimpleNamespace(temporal_status="current"),
        reason_codes=(),
        unsupported_fact_count=0,
        conflicts=conflicts,
    )


def test_render_chapter_renders_ordered_sections_and_evidence_anchors():
    view = render_chapter(_render(_block(), _block("kb-2", KnowledgeBlockType.METHOD)))

    assert view.knowledge_unit_ids == ("ku-kb-1", "ku-kb-2")
    assert view.sections_content["header"].startswith("# Introduction")
    assert "publication_version: 7" in view.sections_content["header"]
    assert "## Block kb-1" in view.sections_content["knowledge_blocks"]
    assert "[evidence: ev-1]" in view.sections_content["knowledge_blocks"]
    assert "- ev-1: [direct_quote/strong] doc=doc-1 block=blk-1" in view.sections_content["evidence_chain"]
    assert view.markdown == "\n\n".join(view.sections_content[s] for s in view.sections)


def test_conflicts_support_block_source_fallback_and_empty_state():
    block = _block("conflict-1", KnowledgeBlockType.CONFLICT)
    block = CompiledBlock(
        KnowledgeBlock("conflict-1", "ch-1", KnowledgeBlockType.CONFLICT, ["ku-1"], [], ["ev-2"]),
        (_ref("ev-2", "weak"),), False, (),
    )
    assert "## Conflict conflict-1" in render_chapter(_render(block)).sections_content["conflicts"]

    fallback = render_chapter(_render(conflicts=[SimpleNamespace(perspective="p", actual="a", conditional="c")]))
    assert "- perspective: p" in fallback.sections_content["conflicts"]
    assert "(no conflicts)" in render_chapter(_render()).sections_content["conflicts"]


def test_book_view_hash_is_deterministic_and_includes_evidence_refs():
    args = dict(book_id="book-1", chapter_id="ch-1", knowledge_unit_ids=("ku-1",),
                sections=("header",), sections_content={"header": "x"}, publication_version=1)
    first = compute_book_rendered_hash(**args, evidence_refs=(("ev-1", "strong"),))
    second = compute_book_rendered_hash(**args, evidence_refs=(("ev-1", "weak"),))
    assert first != second


def test_template_custom_renderer_unknown_section_dict_entry_and_frozen_view():
    template = BookTemplate(sections=("header", "custom"), custom_renderers={"custom": lambda render: "custom"})
    view = render_chapter_from_dict({"chapter": _chapter(), "blocks": (), "publication_version": 1,
                                     "rendered_at": 2, "integrity_report": None, "reason_codes": (),
                                     "unsupported_fact_count": 0}, template=template)
    assert view.sections_content["custom"] == "custom"
    with pytest.raises(FrozenInstanceError):
        view.sections = ()


def test_render_chapter_from_dict_accepts_nested_dicts():
    view = render_chapter_from_dict({
        "chapter": {"id": "ch-1", "book_id": "book-1", "stable_key": "intro", "title": "Introduction"},
        "blocks": [{"knowledge_block": {"id": "kb-1", "knowledge_unit_ids": ["ku-1"], "knowledge_mode": "observed", "block_type": "definition"}, "evidence_refs": []}],
        "publication_version": 1, "rendered_at": 2, "integrity_report": None,
        "reason_codes": (), "unsupported_fact_count": 0,
    })
    assert view.chapter_id == "ch-1"
