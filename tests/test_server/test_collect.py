from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestCollectService:
    @pytest.mark.asyncio
    async def test_collect_file_txt(self, tmp_path):
        (tmp_path / "raw" / "sources").mkdir(parents=True)
        (tmp_path / "wiki" / "sources").mkdir(parents=True)
        mock_ctx = MagicMock(id="test-id")
        with patch(
            "src.services.collect.resolve_project",
            return_value=(mock_ctx, MagicMock(root=tmp_path)),
        ):
            from src.services.collect import collect_file

            result = await collect_file("test-id", "notes.txt", b"Hello World")
        assert result["status"] == "ok"
        assert result["source_type"] == "text"
        assert result["title"] == "Hello World"

    @pytest.mark.asyncio
    async def test_collect_file_rejects_unsupported_extension(self, tmp_path):
        mock_ctx = MagicMock(id="test-id")
        with patch(
            "src.services.collect.resolve_project",
            return_value=(mock_ctx, MagicMock(root=tmp_path)),
        ):
            from src.services.collect import CollectPathError, collect_file

            with pytest.raises(CollectPathError):
                await collect_file("test-id", "file.xyz", b"data")

