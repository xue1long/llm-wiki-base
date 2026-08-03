"""Tests for generate_from_candidate — candidate→WikiPage rendering."""

import pytest
from unittest.mock import MagicMock, AsyncMock

from src.knowledge.core.candidate import CandidateStatus, KnowledgeCandidate
from src.knowledge.core.object import KnowledgeType
from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType


@pytest.fixture
def sample_candidate():
    """A minimal VALIDATED KnowledgeCandidate with 2 claims + 2 evidence items."""
    return KnowledgeCandidate(
        id="cand_abc123",
        source_id="raw/sources/test.md",
        type=KnowledgeType.CONCEPT,
        title="测试概念",
        claims=[
            {
                "statement": "网络小说创作中，人物塑造是最核心的要素",
                "confidence": 0.9,
                "evidence_refs": [0, 1],
            },
            {
                "statement": "好的开篇需要在500字内建立读者期待",
                "confidence": 0.8,
                "evidence_refs": [1],
            },
        ],
        confidence=0.85,
        evidence=[
            {"source_path": "raw/sources/test.md", "page": None, "quote": "人物是小说的灵魂"},
            {"source_path": "raw/sources/test.md", "page": None, "quote": "开篇即决战"},
        ],
        raw_llm_output={},
        status=CandidateStatus.VALIDATED,
    )


@pytest.fixture
def sample_paths(tmp_path):
    """Create minimal WikiPaths with template dirs so list_resolved works."""
    root = tmp_path / "test_project"
    root.mkdir()
    for d in ["wiki", "wiki/sources", "wiki/entities", "wiki/concepts", "wiki/synthesis",
              ".llm-wiki"]:
        (root / d).mkdir(parents=True, exist_ok=True)
    return WikiPaths(root)


def _make_mock_provider(response_dict):
    """Return an AsyncMock provider whose .complete() returns the given dict."""
    provider = MagicMock()
    provider.complete = AsyncMock()
    # Simulate what provider.complete returns — an LLMResponse or object with .content
    import json
    resp = MagicMock()
    resp.content = json.dumps(response_dict, ensure_ascii=False)
    provider.complete.return_value = resp
    return provider


class TestGenerateFromCandidate:
    def test_returns_list_of_wiki_pages(self, sample_candidate, sample_paths):
        """Happy path: mock LLM returns one concept page → verify WikiPage output."""
        provider = _make_mock_provider({
            "pages": [{
                "id": "ceshi-gainian",
                "type": "concept",
                "title": "测试概念",
                "slots": {
                    "definition": "人物塑造是网络小说创作中最核心的要素，决定了作品的吸引力和读者的代入感。",
                    "characteristics": "- 人物是小说的灵魂\n- 好的开篇需要在500字内建立读者期待",
                    "examples": "来源未提供具体例子",
                    "related_concepts": "- [[ceshi-abc12345]]\n- [[xiaoshuo-kaipian]]",
                },
                "relations": [],
                "tags": ["功能/教程"],
                "grade": "B",
            }]
        })

        from src.pipeline.generator import generate_from_candidate

        pages = pytest.importorskip("asyncio").run(
            generate_from_candidate(
                candidate=sample_candidate,
                paths=sample_paths,
                existing_wiki_index="- ceshi-gainian (entity)",
                provider=provider,
                source_slug_map={"raw/sources/test.md": "ceshi-abc12345"},
                source_text="人物是小说的灵魂。开篇即决战。",
            )
        )

        assert isinstance(pages, list)
        assert len(pages) >= 1
        page = pages[0]
        assert page.type == PageType.CONCEPT
        assert page.title == "测试概念"
        assert "人物塑造" in page.body

    def test_uses_candidate_title_as_page_title(self, sample_candidate, sample_paths):
        """Page title comes from candidate.title, not LLM invention."""
        provider = _make_mock_provider({
            "pages": [{
                "id": "test-slug",
                "type": "concept",
                "title": "测试概念",
                "slots": {
                    "definition": "Overview text here.",
                    "characteristics": "- point 1",
                    "examples": "来源未提供具体例子",
                    "related_concepts": "- [[other-page]]",
                },
                "relations": [],
                "tags": [],
                "grade": "B",
            }]
        })

        from src.pipeline.generator import generate_from_candidate
        import asyncio

        pages = asyncio.run(
            generate_from_candidate(
                candidate=sample_candidate,
                paths=sample_paths,
                existing_wiki_index="",
                provider=provider,
            )
        )

        assert pages[0].title == "测试概念"

    def test_candidate_claims_appear_in_prompt(self, sample_candidate, sample_paths):
        """The LLM prompt must include the candidate's claims."""
        provider = _make_mock_provider({
            "pages": [{
                "id": "test",
                "type": "concept",
                "title": "Test",
                "slots": {
                    "definition": "OK",
                    "characteristics": "- point 1",
                    "examples": "来源未提供具体例子",
                    "related_concepts": "- [[other]]",
                },
                "relations": [],
                "tags": [],
                "grade": "B",
            }]
        })

        from src.pipeline.generator import generate_from_candidate
        import asyncio

        asyncio.run(
            generate_from_candidate(
                candidate=sample_candidate,
                paths=sample_paths,
                existing_wiki_index="",
                provider=provider,
            )
        )

        # Verify the prompt contains the claim statements
        call_args = provider.complete.call_args
        messages = call_args.kwargs.get("messages") or call_args.args[0]
        prompt_text = messages[0]["content"] if isinstance(messages, list) else str(messages)
        assert "人物塑造是最核心的要素" in prompt_text
        assert "开篇即决战" in prompt_text

    def test_confidence_in_prompt(self, sample_candidate, sample_paths):
        """The candidate's confidence score must appear in the prompt."""
        provider = _make_mock_provider({
            "pages": [{
                "id": "test",
                "type": "concept",
                "title": "Test",
                "slots": {
                    "definition": "OK",
                    "characteristics": "- p1",
                    "examples": "来源未提供具体例子",
                    "related_concepts": "- [[other]]",
                },
                "relations": [],
                "tags": [],
                "grade": "B",
            }]
        })

        from src.pipeline.generator import generate_from_candidate
        import asyncio

        asyncio.run(
            generate_from_candidate(
                candidate=sample_candidate,
                paths=sample_paths,
                existing_wiki_index="",
                provider=provider,
            )
        )

        call_args = provider.complete.call_args
        messages = call_args.kwargs.get("messages") or call_args.args[0]
        prompt_text = messages[0]["content"] if isinstance(messages, list) else str(messages)
        assert "0.85" in prompt_text

    def test_source_slug_map_in_prompt(self, sample_candidate, sample_paths):
        """The source slug map must appear in the prompt for wikilink generation."""
        provider = _make_mock_provider({
            "pages": [{
                "id": "test",
                "type": "concept",
                "title": "Test",
                "slots": {
                    "definition": "OK",
                    "characteristics": "- p1",
                    "examples": "来源未提供具体例子",
                    "related_concepts": "- [[other]]",
                },
                "relations": [],
                "tags": [],
                "grade": "B",
            }]
        })

        from src.pipeline.generator import generate_from_candidate
        import asyncio

        asyncio.run(
            generate_from_candidate(
                candidate=sample_candidate,
                paths=sample_paths,
                existing_wiki_index="",
                provider=provider,
                source_slug_map={"raw/sources/test.md": "ceshi-abc12345"},
            )
        )

        call_args = provider.complete.call_args
        messages = call_args.kwargs.get("messages") or call_args.args[0]
        prompt_text = messages[0]["content"] if isinstance(messages, list) else str(messages)
        assert "ceshi-abc12345" in prompt_text

    def test_empty_llm_response_returns_empty_list(self, sample_candidate, sample_paths):
        """When LLM returns no pages, return empty list (no crash)."""
        provider = _make_mock_provider({"pages": []})

        from src.pipeline.generator import generate_from_candidate
        import asyncio

        pages = asyncio.run(
            generate_from_candidate(
                candidate=sample_candidate,
                paths=sample_paths,
                existing_wiki_index="",
                provider=provider,
            )
        )

        assert pages == []
