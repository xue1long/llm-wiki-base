"""Tests for generate_from_knowledge_object — KnowledgeObject→WikiPage rendering."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.knowledge.core.candidate import CandidateStatus, KnowledgeCandidate
from src.knowledge.core.object import (
    KnowledgeObject,
    KnowledgeType,
    LifecycleState,
    Provenance,
    VersionRef,
)
from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_candidate():
    return KnowledgeCandidate(
        id="cand_abc123",
        source_id="raw/sources/test.md",
        type=KnowledgeType.CONCEPT,
        title="测试概念",
        claims=[
            {"statement": "Claim A", "confidence": 0.9, "evidence_refs": [0]},
            {"statement": "Claim B", "confidence": 0.8, "evidence_refs": [0]},
        ],
        confidence=0.85,
        evidence=[
            {"source_path": "raw/sources/test.md", "page": 3, "quote": "evidence text"},
        ],
        raw_llm_output={},
        status=CandidateStatus.VALIDATED,
    )


@pytest.fixture
def sample_ko(sample_candidate):
    """KnowledgeObject promoted from sample_candidate."""
    return KnowledgeObject(
        id=sample_candidate.id,
        type=KnowledgeType.CONCEPT,
        title="测试概念",
        content="",
        lifecycle=LifecycleState.PROCESSING,
        confidence=0.85,
        provenance=Provenance(
            source_path="raw/sources/test.md",
            page=3,
            quote="evidence text",
            ingested_at=0,
            ingestor_version="2.0.0",
        ),
        grade="A",
        heat=50,
        relations=[],
        versions=[
            VersionRef(version_id="v1", timestamp=0, change_description="created from candidate"),
        ],
        created_at=0,
        updated_at=0,
    )


@pytest.fixture
def sample_paths(tmp_path):
    root = tmp_path / "test_project"
    for d in ["wiki/sources", "wiki/entities", "wiki/concepts", "wiki/synthesis", ".llm-wiki"]:
        (root / d).mkdir(parents=True, exist_ok=True)
    return WikiPaths(root)


def _make_mock_provider(response_dict):
    provider = MagicMock()
    provider.complete = AsyncMock()
    resp = MagicMock()
    resp.content = json.dumps(response_dict, ensure_ascii=False)
    provider.complete.return_value = resp
    return provider


def _minimal_concept_response():
    return {
        "pages": [{
            "id": "ceshi-gainian",
            "type": "concept",
            "title": "LLM覆盖的标题",
            "slots": {
                "definition": "Body content from LLM.",
                "characteristics": "- point 1\n- point 2",
                "examples": "来源未提供具体例子",
                "related_concepts": "- [[other-page]]",
            },
            "relations": [],
            "tags": ["功能/教程"],
            "grade": "C",
        }]
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGenerateFromKnowledgeObject:
    def test_custom_type_comes_from_knowledge_object(self, sample_ko, sample_candidate, sample_paths):
        from src.pipeline.generator import generate_from_knowledge_object
        from src.wiki.schema_registry import SchemaRegistry
        import asyncio

        sample_candidate.custom_type = "thesis"
        sample_ko.custom_type = "thesis"
        response = _minimal_concept_response()
        response["pages"][0]["type"] = "thesis"
        registry = SchemaRegistry.from_schema_text(
            "| type | directory |\n| thesis | wiki/thesis |"
        )
        pages = asyncio.run(generate_from_knowledge_object(
            ko=sample_ko, candidate=sample_candidate, paths=sample_paths,
            existing_wiki_index="", provider=_make_mock_provider(response),
            schema_registry=registry,
        ))
        assert pages[0].type == PageType.CONCEPT
        assert pages[0].custom_type == "thesis"

    def test_returns_list_of_wiki_pages(self, sample_ko, sample_candidate, sample_paths):
        """Happy path: KO + candidate → WikiPage list."""
        provider = _make_mock_provider(_minimal_concept_response())

        from src.pipeline.generator import generate_from_knowledge_object
        import asyncio

        pages = asyncio.run(
            generate_from_knowledge_object(
                ko=sample_ko,
                candidate=sample_candidate,
                paths=sample_paths,
                existing_wiki_index="",
                provider=provider,
            )
        )

        assert isinstance(pages, list)
        assert len(pages) >= 1
        assert pages[0].type == PageType.CONCEPT

    def test_ko_grade_overrides_llm_grade(self, sample_ko, sample_candidate, sample_paths):
        """KO grade='A' overrides LLM's grade='C'."""
        provider = _make_mock_provider(_minimal_concept_response())

        from src.pipeline.generator import generate_from_knowledge_object
        import asyncio

        pages = asyncio.run(
            generate_from_knowledge_object(
                ko=sample_ko,
                candidate=sample_candidate,
                paths=sample_paths,
                existing_wiki_index="",
                provider=provider,
            )
        )

        assert pages[0].grade == "A"

    def test_ko_title_overrides_llm_title(self, sample_ko, sample_candidate, sample_paths):
        """KO title overrides LLM-generated title."""
        provider = _make_mock_provider(_minimal_concept_response())

        from src.pipeline.generator import generate_from_knowledge_object
        import asyncio

        pages = asyncio.run(
            generate_from_knowledge_object(
                ko=sample_ko,
                candidate=sample_candidate,
                paths=sample_paths,
                existing_wiki_index="",
                provider=provider,
            )
        )

        assert pages[0].title == "测试概念"

    def test_ko_type_overrides_llm_type(self, sample_ko, sample_candidate, sample_paths):
        """KO type is respected even if LLM returns different type."""
        provider = _make_mock_provider(_minimal_concept_response())

        from src.pipeline.generator import generate_from_knowledge_object
        import asyncio

        pages = asyncio.run(
            generate_from_knowledge_object(
                ko=sample_ko,
                candidate=sample_candidate,
                paths=sample_paths,
                existing_wiki_index="",
                provider=provider,
            )
        )

        assert pages[0].type == PageType.CONCEPT

    def test_ko_provenance_set_on_page(self, sample_ko, sample_candidate, sample_paths):
        """_ko_extra.provenance is set from KO provenance."""
        provider = _make_mock_provider(_minimal_concept_response())

        from src.pipeline.generator import generate_from_knowledge_object
        import asyncio

        pages = asyncio.run(
            generate_from_knowledge_object(
                ko=sample_ko,
                candidate=sample_candidate,
                paths=sample_paths,
                existing_wiki_index="",
                provider=provider,
            )
        )

        assert hasattr(pages[0], "_ko_extra")
        assert pages[0]._ko_extra["provenance"]["page"] == 3
        assert pages[0]._ko_extra["provenance"]["quote"] == "evidence text"

    def test_llm_still_renders_body(self, sample_ko, sample_candidate, sample_paths):
        """LLM body content is preserved — only frontmatter is overridden."""
        provider = _make_mock_provider(_minimal_concept_response())

        from src.pipeline.generator import generate_from_knowledge_object
        import asyncio

        pages = asyncio.run(
            generate_from_knowledge_object(
                ko=sample_ko,
                candidate=sample_candidate,
                paths=sample_paths,
                existing_wiki_index="",
                provider=provider,
            )
        )

        assert "Body content from LLM" in pages[0].body

    def test_empty_llm_response_returns_empty_list(self, sample_ko, sample_candidate, sample_paths):
        """When LLM returns no pages, return empty list."""
        provider = _make_mock_provider({"pages": []})

        from src.pipeline.generator import generate_from_knowledge_object
        import asyncio

        pages = asyncio.run(
            generate_from_knowledge_object(
                ko=sample_ko,
                candidate=sample_candidate,
                paths=sample_paths,
                existing_wiki_index="",
                provider=provider,
            )
        )

        assert pages == []

    def test_ko_sources_set_from_provenance(self, sample_ko, sample_candidate, sample_paths):
        """WikiPage.sources is set from KO provenance.source_path."""
        provider = _make_mock_provider(_minimal_concept_response())

        from src.pipeline.generator import generate_from_knowledge_object
        import asyncio

        pages = asyncio.run(
            generate_from_knowledge_object(
                ko=sample_ko,
                candidate=sample_candidate,
                paths=sample_paths,
                existing_wiki_index="",
                provider=provider,
            )
        )

        assert "raw/sources/test.md" in pages[0].sources[0]
