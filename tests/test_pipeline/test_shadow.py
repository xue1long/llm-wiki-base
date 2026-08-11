"""Tests for shadow mode — dual-run pipeline comparison."""

import json
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeLLMResponse:
    def __init__(self, content):
        self.content = content


def _make_candidate_json_response(source_path="raw/sources/test.md"):
    return {
        "source_id": source_path,
        "type": "concept",
        "title": "Test Concept",
        "claims": [
            {"statement": "Claim 1", "confidence": 0.9, "evidence_refs": [0]},
        ],
        "evidence": [
            {"source_path": source_path, "page": None, "quote": "evidence"},
        ],
    }


def _make_wiki_page_response():
    return {
        "pages": [{
            "id": "test-slug",
            "type": "concept",
            "title": "Test Concept",
            "slots": {
                "definition": "A definition.",
                "characteristics": "- char 1",
                "examples": "n/a",
                "related_concepts": "- [[x]]",
                "references": "- [[src]]",
            },
            "relations": [],
            "tags": ["tag/val"],
            "grade": "B",
        }]
    }


def _bootstrap_project(tmp_path):
    root = tmp_path / "test_shadow_proj"
    for d in ["wiki/sources", "wiki/entities", "wiki/concepts", "wiki/synthesis",
              "raw/sources", ".llm-wiki", ".index"]:
        (root / d).mkdir(parents=True, exist_ok=True)
    src_file = root / "raw/sources/test.md"
    src_file.write_text("# Test\nContent here.", encoding="utf-8")
    from src.wiki.core.paths import WikiPaths
    return root, src_file, WikiPaths(root)


# ---------------------------------------------------------------------------
# Tests: shadow module unit tests
# ---------------------------------------------------------------------------


class TestShadowModule:
    def test_run_shadow_ingest_writes_output(self, tmp_path, monkeypatch):
        """run_shadow_ingest writes output.json to .index/shadow/<task_id>/"""
        import asyncio

        monkeypatch.setenv("RUFLO_PIPELINE_MODE", "candidate")
        root, src_file, paths = _bootstrap_project(tmp_path)

        analyzer_resp = FakeLLMResponse(
            json.dumps(_make_candidate_json_response(str(src_file)), ensure_ascii=False)
        )
        generator_resp = FakeLLMResponse(
            json.dumps(_make_wiki_page_response(), ensure_ascii=False)
        )
        provider = MagicMock()
        provider.complete = AsyncMock(side_effect=[analyzer_resp, generator_resp])

        from src.pipeline.shadow import run_shadow_ingest

        shadow_pages, shadow_meta = asyncio.run(
            run_shadow_ingest(
                paths=paths,
                source_path=src_file,
                source_text="# Test",
                provider=provider,
                task_id="kb-shadow-test",
                shadow_mode="legacy",
            )
        )

        shadow_dir = paths.index / "shadow" / "kb-shadow-test"
        assert shadow_dir.exists()
        output_file = shadow_dir / "output.json"
        assert output_file.exists()

        output = json.loads(output_file.read_text(encoding="utf-8"))
        assert output["task_id"] == "kb-shadow-test"
        assert output["mode"] == "legacy"
        assert "page_count" in output

    def test_shadow_ingest_failure_returns_none(self, tmp_path, monkeypatch):
        """Shadow failure returns (None, None) without raising."""
        import asyncio

        monkeypatch.setenv("RUFLO_PIPELINE_MODE", "candidate")
        root, src_file, paths = _bootstrap_project(tmp_path)

        provider = MagicMock()
        provider.complete = AsyncMock(side_effect=RuntimeError("LLM down"))

        from src.pipeline.shadow import run_shadow_ingest

        shadow_pages, shadow_meta = asyncio.run(
            run_shadow_ingest(
                paths=paths,
                source_path=src_file,
                source_text="# Test",
                provider=provider,
                task_id="kb-fail",
                shadow_mode="legacy",
            )
        )

        assert shadow_pages is None
        assert shadow_meta is None

    def test_write_comparison_report_structure(self, tmp_path):
        """Report has main, shadow, and comparison sections."""
        from src.pipeline.shadow import write_comparison_report
        from src.wiki.core.types import PageType, WikiPage

        shadow_dir = tmp_path / "shadow" / "kb-rpt"
        shadow_dir.mkdir(parents=True, exist_ok=True)

        main_pages = [
            WikiPage(id="a", title="A", type=PageType.CONCEPT, grade="A", body="body"),
            WikiPage(id="b", title="B", type=PageType.SOURCE, grade="B", body="body"),
        ]
        shadow_pages = [
            WikiPage(id="a2", title="A2", type=PageType.CONCEPT, grade="A", body="body2"),
        ]
        main_meta = {"rejected": False, "source_grade": "A"}
        shadow_meta = {"rejected": False, "source_grade": "B"}

        report_path = write_comparison_report(
            shadow_dir=shadow_dir,
            main_pages=main_pages,
            shadow_pages=shadow_pages,
            main_meta=main_meta,
            shadow_meta=shadow_meta,
            task_id="kb-rpt",
        )

        assert report_path.exists()
        report = json.loads(report_path.read_text(encoding="utf-8"))

        assert report["main"]["page_count"] == 2
        assert report["shadow"]["page_count"] == 1
        assert report["main"]["type_distribution"] == {"concept": 1, "source": 1}
        assert report["shadow"]["type_distribution"] == {"concept": 1}
        assert report["comparison"]["page_count_delta"] == 1

    def test_comparison_report_with_none_shadow(self, tmp_path):
        """Report handles shadow_pages=None (shadow failed)."""
        from src.pipeline.shadow import write_comparison_report
        from src.wiki.core.types import PageType, WikiPage

        shadow_dir = tmp_path / "shadow" / "kb-none"
        shadow_dir.mkdir(parents=True, exist_ok=True)

        main_pages = [
            WikiPage(id="a", title="A", type=PageType.CONCEPT, grade="A", body="body"),
        ]

        report_path = write_comparison_report(
            shadow_dir=shadow_dir,
            main_pages=main_pages,
            shadow_pages=None,
            main_meta={},
            shadow_meta=None,
            task_id="kb-none",
        )

        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["shadow"]["available"] is False
        assert report["comparison"]["page_count_delta"] is None


# ---------------------------------------------------------------------------
# Tests: shadow mode wired into run_ingest
# ---------------------------------------------------------------------------


class TestShadowModeInRunIngest:
    def test_shadow_mode_on_writes_shadow_dir(self, tmp_path, monkeypatch):
        """RUFLO_SHADOW_MODE=true writes shadow output alongside main output."""
        import asyncio

        monkeypatch.setenv("RUFLO_PIPELINE_MODE", "candidate")
        monkeypatch.setenv("RUFLO_SHADOW_MODE", "true")
        root, src_file, paths = _bootstrap_project(tmp_path)

        # Main path (candidate): analyzer + generator → pages + commit
        analyzer_resp = FakeLLMResponse(
            json.dumps(_make_candidate_json_response(str(src_file)), ensure_ascii=False)
        )
        generator_resp = FakeLLMResponse(
            json.dumps(_make_wiki_page_response(), ensure_ascii=False)
        )
        # Shadow path (legacy): unified_generate call
        legacy_resp = FakeLLMResponse(
            json.dumps(_make_wiki_page_response(), ensure_ascii=False)
        )
        provider = MagicMock()
        provider.complete = AsyncMock(side_effect=[
            analyzer_resp,   # main: analyzer (json)
            generator_resp,  # main: generator
            legacy_resp,     # shadow: unified_generate (legacy)
        ])

        from src.pipeline.ingest import run_ingest

        pages = asyncio.run(
            run_ingest(
                paths=paths,
                source_path=src_file,
                source_text="# 测试标题\n中文内容段落。这是用于测试的中文文档。" * 3,
                provider=provider,
                task_id="kb-shadow-e2e",
            )
        )

        # Main path: pages committed to wiki
        assert len(pages) >= 1

        # Shadow output exists
        shadow_dir = paths.index / "shadow" / "kb-shadow-e2e"
        assert shadow_dir.exists()
        assert (shadow_dir / "output.json").exists()
        assert (shadow_dir / "comparison.json").exists()

    def test_shadow_mode_off_no_shadow_dir(self, tmp_path, monkeypatch):
        """Without RUFLO_SHADOW_MODE, no shadow dir is created."""
        import asyncio

        monkeypatch.setenv("RUFLO_PIPELINE_MODE", "candidate")
        # NOT setting RUFLO_SHADOW_MODE
        root, src_file, paths = _bootstrap_project(tmp_path)

        analyzer_resp = FakeLLMResponse(
            json.dumps(_make_candidate_json_response(str(src_file)), ensure_ascii=False)
        )
        generator_resp = FakeLLMResponse(
            json.dumps(_make_wiki_page_response(), ensure_ascii=False)
        )
        provider = MagicMock()
        provider.complete = AsyncMock(side_effect=[analyzer_resp, generator_resp])

        from src.pipeline.ingest import run_ingest

        pages = asyncio.run(
            run_ingest(
                paths=paths,
                source_path=src_file,
                source_text="# 测试标题\n中文内容段落。用于通过预过滤器的测试文档。" * 3,
                provider=provider,
                task_id="kb-no-shadow",
            )
        )

        assert len(pages) >= 1
        shadow_dir = paths.index / "shadow"
        assert not shadow_dir.exists()

    def test_shadow_failure_does_not_block_main(self, tmp_path, monkeypatch):
        """If shadow path fails, main pages are still returned."""
        import asyncio

        monkeypatch.setenv("RUFLO_PIPELINE_MODE", "candidate")
        monkeypatch.setenv("RUFLO_SHADOW_MODE", "true")
        root, src_file, paths = _bootstrap_project(tmp_path)

        # Main path succeeds
        analyzer_resp = FakeLLMResponse(
            json.dumps(_make_candidate_json_response(str(src_file)), ensure_ascii=False)
        )
        generator_resp = FakeLLMResponse(
            json.dumps(_make_wiki_page_response(), ensure_ascii=False)
        )
        # Shadow path (legacy) will fail because provider raises on 3rd call
        provider = MagicMock()
        provider.complete = AsyncMock(side_effect=[
            analyzer_resp,   # main: analyzer
            generator_resp,  # main: generator
            RuntimeError("legacy LLM unavailable"),  # shadow: fails
        ])

        from src.pipeline.ingest import run_ingest

        pages = asyncio.run(
            run_ingest(
                paths=paths,
                source_path=src_file,
                source_text="# 测试标题\n中文内容段落。用于通过预过滤器的测试文档。" * 3,
                provider=provider,
                task_id="kb-shadow-fail",
            )
        )

        # Main path still succeeds
        assert len(pages) >= 1
