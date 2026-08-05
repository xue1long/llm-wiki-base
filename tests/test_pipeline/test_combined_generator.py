"""Tests for CombinedGeneratorStage."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.pipeline.stages.combined_generator import CombinedGeneratorStage
from src.pipeline.ports import PipelineContext, StageResult
from src.wiki.core.types import WikiPage, PageType


class TestCombinedGeneratorStage:
    """Tests for combined generator stage."""

    def test_stage_name(self):
        """Test stage has correct name."""
        stage = CombinedGeneratorStage()
        assert stage.name == "combined_generator"

    def test_missing_collector_result(self):
        """Test returns error when collector_result is missing."""
        import asyncio
        stage = CombinedGeneratorStage()
        ctx = PipelineContext(
            task_id="test-123",
            source="test.md",
            source_type="file",
            project_id="test-project",
            paths=MagicMock(),
            provider=MagicMock(),
        )
        ctx.collector_result = None

        result = asyncio.run(stage.run(ctx, None))
        assert result.success is False
        assert "error" in result.payload

    @pytest.mark.asyncio
    async def test_successful_generation(self):
        """Test successful page generation from source."""
        stage = CombinedGeneratorStage()

        # Mock collector result
        collector_result = MagicMock()
        collector_result.content = "张三是软件工程师，在北京工作。"
        collector_result.raw_path = "test.md"
        collector_result.extracted_at = 1234567890

        # Mock provider with config
        provider = MagicMock()
        provider.config = MagicMock()
        provider.config.name = "test-provider"
        provider.complete = AsyncMock(return_value="""
```json
{
  "frontmatter": {
    "id": "zhang-san",
    "title": "张三",
    "type": "entity",
    "grade": "B",
    "processing_depth": "concept",
    "tags": ["角色/人物"]
  },
  "body": {
    "summary": "张三是软件工程师。",
    "content": "## 基本信息\\n\\n张三是一名软件工程师。",
    "relations": []
  }
}
```
""")

        # Build context
        paths = MagicMock()
        paths.root = MagicMock()

        ctx = PipelineContext(
            task_id="test-123",
            source="test.md",
            source_type="file",
            project_id="test-project",
            paths=paths,
            provider=provider,
        )
        ctx.collector_result = collector_result
        ctx.source_path = "test.md"
        ctx.folder_context = ""

        result = await stage.run(ctx, None)

        assert result.success is True
        assert "pages" in result.payload
        assert "knowledge_object" in result.payload

        pages = result.payload["pages"]
        assert len(pages) == 1
        assert pages[0].id == "zhang-san"
        assert pages[0].title == "张三"
        assert pages[0].type == PageType.ENTITY

    @pytest.mark.asyncio
    async def test_llm_failure_returns_error(self):
        """Test LLM failure returns error result."""
        stage = CombinedGeneratorStage()

        collector_result = MagicMock()
        collector_result.content = "test content"
        collector_result.raw_path = "test.md"

        provider = MagicMock()
        provider.call = AsyncMock(side_effect=Exception("API error"))

        paths = MagicMock()
        paths.root = MagicMock()

        ctx = PipelineContext(
            task_id="test-123",
            source="test.md",
            source_type="file",
            project_id="test-project",
            paths=paths,
            provider=provider,
        )
        ctx.collector_result = collector_result
        ctx.source_path = "test.md"

        result = await stage.run(ctx, None)

        assert result.success is False
        assert "error" in result.payload

    def test_build_page_defaults(self):
        """Test page building with missing fields uses defaults."""
        stage = CombinedGeneratorStage()

        result = {
            "frontmatter": {},
            "body": {}
        }

        page = stage._build_page(result, "test.md", MagicMock())

        assert page.id  # Should have generated ID
        assert page.title == "Untitled"
        assert page.type == PageType.ENTITY
        assert page.grade == "B"

    def test_parse_relations(self):
        """Test relation parsing from LLM response."""
        from src.wiki.features.relations import Relation
        stage = CombinedGeneratorStage()

        relations_data = [
            {"target": "page-1", "type": "relates_to", "context": "test"},
            {"target": "page-2", "type": "references"},
            {"invalid": "data"},
        ]

        relations = stage._parse_relations(relations_data)

        assert len(relations) == 2
        assert relations[0].target_id == "page-1"
        assert relations[0].type == "relates_to"
        assert relations[1].target_id == "page-2"


class TestCombinedGenerationConfig:
    """Tests for combined generation configuration."""

    def test_env_var_disabled_by_default(self, monkeypatch):
        """Test combined generation is disabled by default."""
        import importlib
        import src.pipeline.service as service_mod

        # Reload to pick up env
        importlib.reload(service_mod)

        # Should be False by default
        assert service_mod.USE_COMBINED_GENERATION is False

    def test_env_var_enabled(self, monkeypatch):
        """Test combined generation can be enabled via env."""
        import importlib
        import src.pipeline.service as service_mod

        monkeypatch.setenv("RUFLO_COMBINED_GENERATION", "true")
        importlib.reload(service_mod)

        assert service_mod.USE_COMBINED_GENERATION is True

    def test_shadow_mode_requires_combined(self, monkeypatch):
        """Test shadow mode only works with combined generation."""
        import importlib
        import src.pipeline.service as service_mod

        monkeypatch.setenv("RUFLO_SHADOW_MODE", "true")
        monkeypatch.setenv("RUFLO_COMBINED_GENERATION", "false")
        importlib.reload(service_mod)

        # Shadow mode is True but combined is False
        # Logic should still use standard path
        assert service_mod.SHADOW_MODE is True
        assert service_mod.USE_COMBINED_GENERATION is False