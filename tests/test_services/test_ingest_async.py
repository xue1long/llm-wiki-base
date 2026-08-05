"""Tests for async ingest enqueue operations."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from src.services.ingest import enqueue_source_async


class TestEnqueueSourceAsync:
    """Tests for enqueue_source_async function."""

    @pytest.fixture
    def mock_project(self, tmp_path):
        """Create a mock project structure."""
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        (project_dir / "raw" / "sources").mkdir(parents=True)
        (project_dir / "wiki" / "sources").mkdir(parents=True)
        (project_dir / ".index").mkdir(parents=True)
        return project_dir

    @pytest.mark.asyncio
    async def test_enqueue_url(self, mock_project):
        """Test enqueueing a URL."""
        mock_ctx = MagicMock()
        mock_ctx.id = "test-project-id"
        mock_paths = MagicMock()
        mock_paths.root = mock_project

        with patch("src.services.ingest.resolve_project") as mock_resolve, \
             patch("src.services.ingest.enqueue_task") as mock_enqueue, \
             patch("src.services.ingest.generate_task_hash") as mock_hash:

            mock_resolve.return_value = (mock_ctx, mock_paths)
            mock_hash.return_value = "test-hash"
            mock_enqueue.return_value = "task-123"

            result = await enqueue_source_async(
                "test-project-id",
                "https://example.com/file.pdf"
            )

        assert result["status"] == "queued"
        assert result["taskId"] == "task-123"

    @pytest.mark.asyncio
    async def test_enqueue_duplicate_url(self, mock_project):
        """Test duplicate URL is ignored."""
        mock_ctx = MagicMock()
        mock_ctx.id = "test-project-id"
        mock_paths = MagicMock()
        mock_paths.root = mock_project

        with patch("src.services.ingest.resolve_project") as mock_resolve, \
             patch("src.services.ingest.enqueue_task") as mock_enqueue, \
             patch("src.services.ingest.generate_task_hash") as mock_hash:

            mock_resolve.return_value = (mock_ctx, mock_paths)
            mock_hash.return_value = "test-hash"
            mock_enqueue.return_value = ""  # Empty = duplicate

            result = await enqueue_source_async(
                "test-project-id",
                "https://example.com/file.pdf"
            )

        assert result["status"] == "ignored"
        assert result["reason"] == "Duplicate"

    @pytest.mark.asyncio
    async def test_enqueue_file(self, mock_project):
        """Test enqueueing a file path."""
        mock_ctx = MagicMock()
        mock_ctx.id = "test-project-id"
        mock_paths = MagicMock()
        mock_paths.root = mock_project

        with patch("src.services.ingest.resolve_project") as mock_resolve, \
             patch("src.services.ingest._normalize_absolute_path") as mock_norm, \
             patch("src.services.ingest.enqueue_task") as mock_enqueue, \
             patch("src.services.ingest.generate_task_hash") as mock_hash:

            mock_resolve.return_value = (mock_ctx, mock_paths)
            mock_norm.return_value = "raw/sources/test.md"
            mock_hash.return_value = "test-hash"
            mock_enqueue.return_value = "task-456"

            result = await enqueue_source_async(
                "test-project-id",
                "raw/sources/test.md"
            )

        assert result["status"] == "queued"
        assert result["taskId"] == "task-456"

    @pytest.mark.asyncio
    async def test_enqueue_folder(self, mock_project):
        """Test enqueueing a folder."""
        mock_ctx = MagicMock()
        mock_ctx.id = "test-project-id"
        mock_paths = MagicMock()
        mock_paths.root = mock_project

        # Create test files
        sources = mock_project / "raw" / "sources"
        (sources / "file1.md").write_text("content1")
        (sources / "file2.md").write_text("content2")

        with patch("src.services.ingest.resolve_project") as mock_resolve, \
             patch("src.services.ingest._normalize_absolute_path") as mock_norm, \
             patch("src.services.ingest.collect_files") as mock_collect, \
             patch("src.services.ingest._get_ingested_paths") as mock_ingested, \
             patch("src.services.ingest.enqueue_batch") as mock_enqueue, \
             patch("src.services.ingest.generate_task_hash") as mock_hash, \
             patch("src.services.ingest.get_default_queue_service") as mock_queue:

            mock_resolve.return_value = (mock_ctx, mock_paths)
            mock_norm.return_value = "raw/sources"
            mock_collect.return_value = [
                sources / "file1.md",
                sources / "file2.md",
            ]
            mock_ingested.return_value = set()
            mock_hash.return_value = "test-hash"
            mock_enqueue.return_value = ["task-1", "task-2"]
            mock_queue.return_value = MagicMock(advance=MagicMock())

            result = await enqueue_source_async(
                "test-project-id",
                {"folder": "raw/sources"}
            )

        assert result["status"] == "batch_queued"
        assert result["enqueued"] == 2

    @pytest.mark.asyncio
    async def test_enqueue_folder_with_already_ingested(self, mock_project):
        """Test folder enqueue skips already ingested files."""
        mock_ctx = MagicMock()
        mock_ctx.id = "test-project-id"
        mock_paths = MagicMock()
        mock_paths.root = mock_project

        sources = mock_project / "raw" / "sources"
        (sources / "file1.md").write_text("content1")
        (sources / "file2.md").write_text("content2")

        with patch("src.services.ingest.resolve_project") as mock_resolve, \
             patch("src.services.ingest._normalize_absolute_path") as mock_norm, \
             patch("src.services.ingest.collect_files") as mock_collect, \
             patch("src.services.ingest._get_ingested_paths") as mock_ingested, \
             patch("src.services.ingest.enqueue_batch") as mock_enqueue, \
             patch("src.services.ingest.generate_task_hash") as mock_hash, \
             patch("src.services.ingest.get_default_queue_service") as mock_queue:

            mock_resolve.return_value = (mock_ctx, mock_paths)
            mock_norm.return_value = "raw/sources"
            mock_collect.return_value = [
                sources / "file1.md",
                sources / "file2.md",
            ]
            # file1.md already ingested
            mock_ingested.return_value = {"raw/sources/file1.md"}
            mock_hash.return_value = "test-hash"
            mock_enqueue.return_value = ["task-2"]
            mock_queue.return_value = MagicMock(advance=MagicMock())

            result = await enqueue_source_async(
                "test-project-id",
                {"folder": "raw/sources"}
            )

        assert result["status"] == "batch_queued"
        assert result["enqueued"] == 1
        assert result["alreadyIngested"] == 1


class TestEnqueueSourceAsyncErrors:
    """Tests for error handling in enqueue_source_async."""

    @pytest.mark.asyncio
    async def test_project_not_found(self):
        """Test project not found raises error."""
        from src.project.context import ProjectNotFoundError

        with patch("src.services.ingest.resolve_project") as mock_resolve:
            mock_resolve.side_effect = ProjectNotFoundError("not found")

            with pytest.raises(ProjectNotFoundError):
                await enqueue_source_async("invalid-id", "test.md")

    @pytest.mark.asyncio
    async def test_folder_not_found(self, tmp_path):
        """Test folder not found raises IngestPathError."""
        from src.services.ingest import IngestPathError

        mock_ctx = MagicMock()
        mock_ctx.id = "test-project-id"
        mock_paths = MagicMock()
        mock_paths.root = tmp_path

        with patch("src.services.ingest.resolve_project") as mock_resolve, \
             patch("src.services.ingest._normalize_absolute_path") as mock_norm:

            mock_resolve.return_value = (mock_ctx, mock_paths)
            mock_norm.return_value = "nonexistent"

            with pytest.raises(IngestPathError):
                await enqueue_source_async(
                    "test-project-id",
                    {"folder": "nonexistent"}
                )