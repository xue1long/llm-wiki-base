"""Tests for ConceptPage ↔ WikiPage adapter and source stub builder.

V7 Replace Plan Stage 0 Task 3.

Both ``adapt_concept_page`` and ``build_source_stub_page`` return a
``WikiPage`` instance that is later passed to ``commit_ingest`` for
disk persistence (via ``write_page`` → ``WikiPage.to_frontmatter_dict``).
This keeps the V7 ingest bridge's write path consistent with the
existing candidate pipeline (one place that does lineage, vector
intent, index append, gbrain wikilink rewrite).

V7's own ``WikiWriter.commit_and_index`` is **not** used by the bridge
(still available for ``scripts/extract_pilot.py`` dry-run and
``scripts/extract_full.py`` batch apply).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.pipeline.v7_extract.page_adapter import (
    CONCEPT_BODY_PREFIX,
    adapt_concept_page,
    build_source_stub_page,
)
from src.pipeline.v7_extract.segmentation import (
    SegmentationStatus,
    wrap_items_as_segmentation_result,
    extract_items_deterministic,
)
from src.pipeline.v7_extract.slot_filler import ConceptPage, Slot, SlotEvidence
from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType, WikiPage


# ---------- adapt_concept_page: 8-slot body ----------


def test_adapt_concept_page_basic_8_slots_yields_8_sections():
    """A ConceptPage with all 8 slots filled produces a WikiPage body
    containing 8 ``## {zh_heading}\\n{body}`` sections.
    """
    page = ConceptPage(
        id="concept-1",
        title="Test Concept",
        type="concept",
        sources=["raw/sources/test.md"],
        slots={
            "definition": "X is a thing.",
            "characteristics": "It has features.",
            "context": "Use in Y context.",
            "anti_patterns": "Don't do Z.",
            "evidence": "From source A.",
            "examples": "Example 1.",
            "related_concepts": "[[other-concept]]",
            "references": "[[sources/test]]",
        },
    )
    wp = adapt_concept_page(page)
    assert isinstance(wp, WikiPage)
    assert wp.id == "concept-1"
    assert wp.title == "Test Concept"
    assert wp.type == PageType.CONCEPT
    assert wp.processing_depth == "concept"
    # Body: 8 sections
    assert "## 定义" in wp.body
    assert "## 主要特点" in wp.body
    assert "## 适用场景" in wp.body
    assert "## 反模式与常见错误" in wp.body
    assert "## 证据强度" in wp.body
    assert "## 例子" in wp.body
    assert "## 相关概念" in wp.body
    assert "## 参考来源" in wp.body


def test_adapt_concept_page_strips_section_suffix_from_sources():
    """V7's deterministic splitter appends ``#author-N`` / ``#section-N``
    item ordinals to source paths. The H1 lint rule treats ``source`` as
    a literal file path, so the suffix would mark every source as
    "not found". adapt_concept_page strips it (originals are preserved
    in _ko_extra.slot_evidence).
    """
    page = ConceptPage(
        id="c",
        title="C",
        sources=["raw/sources/foo.md#author-1", "raw/sources/bar.md#section-3"],
        slots={"definition": "d"},
    )
    wp = adapt_concept_page(page)
    assert wp.sources == ["raw/sources/foo.md", "raw/sources/bar.md"]


def test_adapt_concept_page_partial_5_slots_yields_5_sections():
    """A ConceptPage with only 5 slots filled produces a body with 5 sections."""
    page = ConceptPage(
        id="partial",
        title="Partial",
        slots={
            "definition": "X is a thing.",
            "characteristics": "It has features.",
            "context": "Use in Y.",
            "anti_patterns": "Don't do Z.",
            "evidence": "From source A.",
        },
    )
    wp = adapt_concept_page(page)
    # All 8 sections present (empty sections for missing slots)
    assert wp.body.count("## ") == 8
    # Missing slots render as empty body (or absent content)
    assert "## 例子" in wp.body  # heading present even if body empty


def test_adapt_concept_page_preserves_id_title_type_sources():
    """id, title, type, sources fields flow through unchanged."""
    page = ConceptPage(
        id="foo-bar",
        title="Foo Bar Concept",
        type="concept",
        sources=["raw/a.md", "raw/b.md"],
        slots={"definition": "d"},
    )
    wp = adapt_concept_page(page)
    assert wp.id == "foo-bar"
    assert wp.title == "Foo Bar Concept"
    assert wp.type == PageType.CONCEPT
    assert wp.sources == ["raw/a.md", "raw/b.md"]


def test_adapt_concept_page_injects_wiki_template_version_comment():
    """The body starts with the wiki-template-version comment so lint
    (LINT-MISSING-SECTION) recognizes the page as concept-shaped.
    """
    page = ConceptPage(id="c", title="C", slots={"definition": "d"})
    wp = adapt_concept_page(page)
    assert wp.body.lstrip().startswith("<!-- wiki-template-version: 3.0.0 -->")


def test_adapt_concept_page_slot_evidence_goes_to_ko_extra():
    """ConceptPage.slot_evidence moves to WikiPage._ko_extra.slot_evidence."""
    ev = SlotEvidence(
        item_id="item-1", source_text_excerpt="excerpt", has_evidence=True, needs_review=False
    )
    page = ConceptPage(
        id="c",
        title="C",
        slots={"definition": "d", "characteristics": "c"},
        slot_evidence={
            "definition": Slot(name="definition", body="d", evidence=ev),
        },
    )
    wp = adapt_concept_page(page)
    assert "_ko_extra" in wp.__dict__
    slot_evidence = wp._ko_extra.get("slot_evidence") or {}
    assert "definition" in slot_evidence
    assert slot_evidence["definition"]["evidence"]["item_id"] == "item-1"


def test_adapt_concept_page_rejects_other_topic_id_sentinel():
    """OTHER_TOPIC_ID sentinel → InvalidInputError. The bridge is the
    only consumer; this lets it fail fast when Stage 4 returns a
    sentinel page.
    """
    from src.pipeline.v7_extract.topic_clusterer import OTHER_TOPIC_ID
    from src.lib.errors import InvalidInputError

    page = ConceptPage(
        id="__other__",
        title="Other",
        topic_id=OTHER_TOPIC_ID,
        slots={"definition": "d"},
    )
    with pytest.raises(InvalidInputError):
        adapt_concept_page(page)


def test_adapt_concept_page_round_trip_via_to_frontmatter_dict():
    """adapt_concept_page → to_frontmatter_dict preserves all fields the
    wiki system needs (id, title, type, sources, processing_depth).
    """
    page = ConceptPage(
        id="roundtrip",
        title="Round Trip",
        slots={"definition": "d", "characteristics": "c"},
        sources=["raw/x.md"],
    )
    wp = adapt_concept_page(page)
    fm = wp.to_frontmatter_dict()
    assert fm["id"] == "roundtrip"
    assert fm["title"] == "Round Trip"
    assert fm["type"] == "concept"
    assert fm["sources"] == ["raw/x.md"]
    assert fm["processing_depth"] == "concept"


# ---------- build_source_stub_page: 5-section source body ----------


def test_build_source_stub_minimal_5_sections(tmp_path: Path):
    """A source stub page has the 5 source-template sections
    (来源元数据 / 转录质量 / 摘要 / 关键观点 / 可信度声明).
    """
    src_path = Path("raw/sources/test/source.md")
    paths = WikiPaths(tmp_path)

    sp = build_source_stub_page(
        source_path=src_path,
        source_text="Some content.",
        task_id="kb-test-001",
        paths=paths,
    )
    assert isinstance(sp, WikiPage)
    assert sp.type == PageType.SOURCE
    assert sp.processing_depth == "source"
    # Body: 5 sections + wiki-template-version comment
    assert "<!-- wiki-template-version: 3.0.0 -->" in sp.body
    assert "## 来源元数据" in sp.body
    assert "## 转录质量" in sp.body
    assert "## 摘要" in sp.body
    assert "## 关键观点" in sp.body
    assert "## 可信度声明" in sp.body


def test_build_source_stub_with_relations_to_concept_pages(tmp_path: Path):
    """When concept_page_ids is provided, the source page builds relations
    + a 关键观点 list linking to them.
    """
    src_path = Path("raw/sources/test/source.md")
    paths = WikiPaths(tmp_path)

    sp = build_source_stub_page(
        source_path=src_path,
        source_text="x",
        task_id="kb-test-001",
        paths=paths,
        concept_page_ids=["c-1", "c-2"],
    )
    # Body lists the concepts
    assert "[[concepts/c-1]]" in sp.body
    assert "[[concepts/c-2]]" in sp.body
    # Relations wired
    rel_targets = {r.target_id for r in sp.relations}
    assert "c-1" in rel_targets
    assert "c-2" in rel_targets
    # All relations are 'references' type
    assert all(r.type == "references" for r in sp.relations)


def test_build_source_stub_no_concept_pages(tmp_path: Path):
    """Without concept_page_ids, 关键观点 is empty and no relations."""
    src_path = Path("raw/sources/test/source.md")
    paths = WikiPaths(tmp_path)

    sp = build_source_stub_page(
        source_path=src_path,
        source_text="x",
        task_id="kb-test-001",
        paths=paths,
    )
    # No concept list in body
    assert "## 关键观点" in sp.body
    # After "## 关键观点" → next section "## 可信度声明" is immediately there
    # (no list items between)
    assert sp.relations == []


def test_build_source_stub_path_and_id_format(tmp_path: Path):
    """source page id follows the existing ingest convention:
    {stem}-{8-char-path-hash}, with the path inside frontmatter.
    """
    src_path = Path("raw/sources/test/source.md")
    paths = WikiPaths(tmp_path)

    sp = build_source_stub_page(
        source_path=src_path,
        source_text="x",
        task_id="kb-test-001",
        paths=paths,
    )
    # id format: <stem>-<8-char-hex>
    assert sp.id.startswith("source-")
    assert len(sp.id.split("-")[-1]) == 8  # 8-char hash
    # sources field contains the relative path (cross-platform:
    # normalize Windows backslashes to forward slashes for assertion)
    assert "raw/sources/test/source.md" in sp.sources[0].replace("\\", "/")
