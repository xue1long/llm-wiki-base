"""Tests for src/services/capture.py — fast capture service.

Plan Task 3: POST /capture API (TDD).
"""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.services.capture import capture_page, _TYPE_MAP


class TestCapturePage:
    """Unit tests for capture_page service function."""

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="Invalid capture type"):
            capture_page("fake-project", type="foo", title="test")

    def test_empty_title_raises(self):
        with pytest.raises(ValueError, match="Title is required"):
            capture_page("fake-project", type="article", title="")

    def test_whitespace_title_raises(self):
        with pytest.raises(ValueError, match="Title is required"):
            capture_page("fake-project", type="article", title="   ")

    def test_type_map_coverage(self):
        """All three capture types map to valid base PageTypes."""
        assert _TYPE_MAP["article"] == "source"
        assert _TYPE_MAP["video-transcript"] == "source"
        assert _TYPE_MAP["inspiration"] == "concept"


class TestCapturePageIntegration:
    """Integration tests requiring a real project on disk."""

    @pytest.fixture
    def project_dir(self, tmp_path_factory):
        """Create a minimal project structure."""
        import os
        # Use workspace tmp to avoid sandbox permission issues
        base = Path(os.environ.get("DSH_WORKSPACE", str(Path(__file__).parent.parent.parent))) / "tmp_test_capture"
        base.mkdir(parents=True, exist_ok=True)
        tmp_path = base / "project"
        tmp_path.mkdir(parents=True, exist_ok=True)
        # Create wiki structure
        wiki = tmp_path / "wiki"
        for d in ["sources", "entities", "concepts", "synthesis", "_stubs"]:
            (wiki / d).mkdir(parents=True, exist_ok=True)
        (wiki / "index.md").write_text("# Wiki Index\n\n", encoding="utf-8")
        (wiki / "log.md").write_text("# Wiki Operation Log\n\n", encoding="utf-8")
        # Create minimal project metadata
        llm = tmp_path / ".llm-wiki"
        llm.mkdir(parents=True, exist_ok=True)
        import json
        (llm / "project.json").write_text(
            json.dumps({"id": "test-capture", "name": "test-capture", "schema_version": 2}),
            encoding="utf-8",
        )
        # Create schema.md
        (tmp_path / "schema.md").write_text(
            "# Wiki Schema\n\n## Page Types\n\n| type | directory |\n|------|-----------|\n| source | wiki/sources |\n| entity | wiki/entities |\n| concept | wiki/concepts |\n| synthesis | wiki/synthesis |\n",
            encoding="utf-8",
        )
        # Create taxonomy.md (empty — allows empty category)
        (tmp_path / "taxonomy.md").write_text("", encoding="utf-8")
        yield tmp_path
        # Cleanup
        import shutil
        shutil.rmtree(base, ignore_errors=True)

    @patch("src.services.capture.resolve_project")
    def test_capture_article_creates_source_page(self, mock_resolve, project_dir):
        from src.wiki.core.paths import WikiPaths
        from src.project.context import ProjectContext
        paths = WikiPaths(project_dir)
        ctx = MagicMock(spec=ProjectContext)
        ctx.path = project_dir
        mock_resolve.return_value = (ctx, paths)

        result = capture_page(
            "test-capture", type="article", title="Test Article",
            content="This is test content about writing.",
            url="https://example.com/article1",
        )
        assert result["status"] == "ok"
        assert "sources" in result["path"].replace("\\", "/")
        assert result["is_skeleton"] is False
        assert result["page_id"].startswith("card_")

        # Verify file exists and has correct content
        page_path = Path(result["path"])
        assert page_path.exists()
        text = page_path.read_text(encoding="utf-8")
        assert "custom_type: ''" in text  # F1: custom_type is empty
        # C-0 Commit 1: source_status migrated to workflow_state
        assert "workflow_state: complete" in text
        assert "capture-type: article" in text  # body comment
        assert "This is test content" in text   # content filled

    @patch("src.services.capture.resolve_project")
    def test_capture_inspiration_creates_concept_page(self, mock_resolve, project_dir):
        from src.wiki.core.paths import WikiPaths
        from src.project.context import ProjectContext
        paths = WikiPaths(project_dir)
        ctx = MagicMock(spec=ProjectContext)
        ctx.path = project_dir
        mock_resolve.return_value = (ctx, paths)

        result = capture_page(
            "test-capture", type="inspiration", title="A Great Idea",
        )
        assert result["status"] == "ok"
        assert "concepts" in result["path"].replace("\\", "/")
        assert result["is_skeleton"] is True

        page_path = Path(result["path"])
        text = page_path.read_text(encoding="utf-8")
        assert "capture-type: inspiration" in text
        assert "源文档内容为空" in text

    @patch("src.services.capture.resolve_project")
    def test_capture_video_transcript_creates_source_page(self, mock_resolve, project_dir):
        from src.wiki.core.paths import WikiPaths
        from src.project.context import ProjectContext
        paths = WikiPaths(project_dir)
        ctx = MagicMock(spec=ProjectContext)
        ctx.path = project_dir
        mock_resolve.return_value = (ctx, paths)

        result = capture_page(
            "test-capture", type="video-transcript", title="Video Notes",
            content="Key points from the video...",
            url="https://bilibili.com/video/xxx",
        )
        assert result["status"] == "ok"
        assert "sources" in result["path"].replace("\\", "/")

        page_path = Path(result["path"])
        text = page_path.read_text(encoding="utf-8")
        assert "capture-type: video-transcript" in text

    @patch("src.services.capture.resolve_project")
    def test_capture_empty_content_creates_skeleton(self, mock_resolve, project_dir):
        from src.wiki.core.paths import WikiPaths
        from src.project.context import ProjectContext
        paths = WikiPaths(project_dir)
        ctx = MagicMock(spec=ProjectContext)
        ctx.path = project_dir
        mock_resolve.return_value = (ctx, paths)

        result = capture_page("test-capture", type="article", title="Empty Note")
        assert result["is_skeleton"] is True
        assert result["status"] == "ok"

        page_path = Path(result["path"])
        text = page_path.read_text(encoding="utf-8")
        assert "源文档内容为空" in text
        # C-0 Commit 1: source_status migrated to workflow_state
        assert "workflow_state: empty" in text

    @patch("src.services.capture.resolve_project")
    def test_capture_with_url_and_tags(self, mock_resolve, project_dir):
        from src.wiki.core.paths import WikiPaths
        from src.project.context import ProjectContext
        paths = WikiPaths(project_dir)
        ctx = MagicMock(spec=ProjectContext)
        ctx.path = project_dir
        mock_resolve.return_value = (ctx, paths)

        # write_page validates tags for new files — use empty tags to avoid
        # mandatory UGC tag requirements (capture is personal, not UGC)
        result = capture_page(
            "test-capture", type="article", title="Tagged Article",
            content="content", url="https://example.com",
            tags=[],
        )
        assert result["status"] == "ok"

        page_path = Path(result["path"])
        text = page_path.read_text(encoding="utf-8")
        assert "https://example.com" in text

    @patch("src.services.capture.resolve_project")
    def test_capture_no_custom_type_on_page(self, mock_resolve, project_dir):
        """F1: page.custom_type must be empty to bypass SchemaRegistry check."""
        from src.wiki.core.paths import WikiPaths
        from src.project.context import ProjectContext
        paths = WikiPaths(project_dir)
        ctx = MagicMock(spec=ProjectContext)
        ctx.path = project_dir
        mock_resolve.return_value = (ctx, paths)

        result = capture_page("test-capture", type="article", title="No Custom Type")
        page_path = Path(result["path"])
        text = page_path.read_text(encoding="utf-8")
        assert "custom_type: ''" in text

    @patch("src.services.capture.resolve_project")
    def test_capture_page_id_format(self, mock_resolve, project_dir):
        """M4: page_id must be card_<hex>_<hex>_<slug> format."""
        from src.wiki.core.paths import WikiPaths
        from src.project.context import ProjectContext
        paths = WikiPaths(project_dir)
        ctx = MagicMock(spec=ProjectContext)
        ctx.path = project_dir
        mock_resolve.return_value = (ctx, paths)

        result = capture_page("test-capture", type="article", title="ID Test")
        import re
        assert re.match(r"^card_[0-9a-f]{13}_[0-9a-f]{8}_", result["page_id"])

    @patch("src.services.capture.resolve_project")
    def test_capture_ko_extra_persisted(self, mock_resolve, project_dir):
        """C-0 Commit 1: capture completeness lives on workflow_state, not _ko_extra."""
        from src.wiki.core.paths import WikiPaths
        from src.project.context import ProjectContext
        paths = WikiPaths(project_dir)
        ctx = MagicMock(spec=ProjectContext)
        ctx.path = project_dir
        mock_resolve.return_value = (ctx, paths)

        result = capture_page("test-capture", type="article", title="KO Extra Test", content="some content")
        page_path = Path(result["path"])
        text = page_path.read_text(encoding="utf-8")
        assert "workflow_state: complete" in text

        # Verify round-trip: read back and check workflow_state
        from src.wiki.storage.page_writer import read_page
        page = read_page(page_path)
        assert page.workflow_state == "complete"
        # _ko_extra.source_status must NOT be present after migration
        ko_extra = getattr(page, "_ko_extra", None)
        if ko_extra is not None:
            assert "source_status" not in ko_extra
