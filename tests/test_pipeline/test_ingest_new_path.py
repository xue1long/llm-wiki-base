"""Tests for the new candidate pipeline path in run_ingest.

Verifies: json analyzer → Reviewer → Promoter → generate_from_candidate
with RUFLO_PIPELINE_MODE=candidate.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_candidate_json_response(source_path="raw/sources/test.md"):
    """Return a valid JSON analyzer response dict."""
    return {
        "source_id": source_path,
        "type": "concept",
        "title": "测试概念",
        "claims": [
            {"statement": "Claim 1", "confidence": 0.9, "evidence_refs": [0]},
            {"statement": "Claim 2", "confidence": 0.8, "evidence_refs": [0]},
        ],
        "evidence": [
            {"source_path": source_path, "page": None, "quote": "evidence text"},
        ],
    }


def _make_wiki_page_response():
    """Return a valid generator JSON response (concept page with all slots)."""
    return {
        "pages": [{
            "id": "test-slug",
            "type": "concept",
            "title": "测试概念",
            "slots": {
                "definition": "A test definition.",
                "characteristics": "- char 1\n- char 2",
                "examples": "来源未提供具体例子",
                "related_concepts": "- [[other-page]]",
                "references": "- [[test-source]]",
            },
            "relations": [],
            "tags": ["功能/教程"],
            "grade": "B",
        }]
    }


class FakeLLMResponse:
    """Minimal mock for LLMResponse with .content attribute."""
    def __init__(self, content):
        self.content = content


def _bootstrap_project(tmp_path):
    """Create minimal project structure, return (root, src_file, paths)."""
    root = tmp_path / "test_proj"
    for d in ["wiki/sources", "wiki/entities", "wiki/concepts", "wiki/synthesis",
              "raw/sources", ".llm-wiki", ".index"]:
        (root / d).mkdir(parents=True, exist_ok=True)
    src_file = root / "raw/sources/test.md"
    src_file.write_text("# Test\nContent here.", encoding="utf-8")
    from src.wiki.core.paths import WikiPaths
    paths = WikiPaths(root)
    return root, src_file, paths


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCandidatePipelinePath:
    """Verify the RUFLO_PIPELINE_MODE=candidate path end-to-end."""

    def test_candidate_path_produces_pages(self, tmp_path, monkeypatch):
        """Full happy path: json analyzer → Reviewer → Promoter → Generator."""
        import asyncio

        monkeypatch.setenv("RUFLO_PIPELINE_MODE", "candidate")
        root, src_file, paths = _bootstrap_project(tmp_path)

        # Mock provider: first call = analyzer (JSON), second = generator
        analyzer_resp = FakeLLMResponse(
            json.dumps(
                _make_candidate_json_response(str(src_file)),
                ensure_ascii=False,
            )
        )
        generator_resp = FakeLLMResponse(
            json.dumps(_make_wiki_page_response(), ensure_ascii=False)
        )
        provider = MagicMock()
        provider.complete = AsyncMock(side_effect=[analyzer_resp, generator_resp])

        from src.pipeline.ingest import generate_ingest

        pages, extra, meta = asyncio.run(
            generate_ingest(
                paths=paths,
                source_path=src_file,
                source_text="# Test\nContent here.",
                provider=provider,
                task_id="kb-test",
            )
        )

        # Should produce at least 2 pages: the concept page + source page
        assert len(pages) >= 2
        page_types = {p.type.value for p in pages}
        assert "concept" in page_types
        assert "source" in page_types
        assert not meta.get("rejected")

    def test_candidate_path_rejected_candidate_no_writes(self, tmp_path, monkeypatch):
        """REJECTED candidate returns empty pages with rejected=True."""
        import asyncio

        monkeypatch.setenv("RUFLO_PIPELINE_MODE", "candidate")
        root, src_file, paths = _bootstrap_project(tmp_path)

        # Analyzer returns empty source_id + no claims → REJECTED by parser
        rejected_json = {
            "source_id": "",
            "type": "concept",
            "title": "",
            "claims": [],
            "evidence": [],
        }
        analyzer_resp = FakeLLMResponse(json.dumps(rejected_json, ensure_ascii=False))
        provider = MagicMock()
        provider.complete = AsyncMock(return_value=analyzer_resp)

        from src.pipeline.ingest import generate_ingest

        pages, extra, meta = asyncio.run(
            generate_ingest(
                paths=paths,
                source_path=src_file,
                source_text="x",
                provider=provider,
                task_id="kb-test",
            )
        )

        # REJECTED: zero pages, flagged in meta
        assert pages == []
        assert extra == []
        assert meta.get("rejected") is True

    def test_legacy_mode_still_works(self, tmp_path, monkeypatch):
        """RUFLO_PIPELINE_MODE=legacy uses old markdown analyzer path."""
        import asyncio

        monkeypatch.setenv("RUFLO_PIPELINE_MODE", "legacy")
        root, src_file, paths = _bootstrap_project(tmp_path)

        # Legacy path: unified_generate (first try) → pages.
        # Provide multiple copies — unified_generate retries up to 3 times
        # if slot validation fails.
        _wiki_resp = json.dumps({
            "pages": [{
                "id": "test",
                "type": "concept",
                "title": "Test",
                "slots": {
                    "definition": "ok", "characteristics": "- a",
                    "examples": "n/a", "related_concepts": "- [[x]]",
                    "references": "- 来源",
                },
                "relations": [],
                "tags": [],
                "grade": "B",
            }]
        }, ensure_ascii=False)
        _wiki_page = FakeLLMResponse(_wiki_resp)
        provider = MagicMock()
        provider.complete = AsyncMock(side_effect=[_wiki_page] * 6)

        from src.pipeline.ingest import generate_ingest

        pages, extra, meta = asyncio.run(
            generate_ingest(
                paths=paths,
                source_path=src_file,
                source_text="# Test\nContent here.",
                provider=provider,
                task_id="kb-test",
            )
        )

        # Legacy path should produce pages
        assert len(pages) >= 2  # concept + source
        assert not meta.get("rejected")
