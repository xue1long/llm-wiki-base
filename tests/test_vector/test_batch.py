"""Tests for batch embedding operations."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

from src.vector.batch import (
    embed_texts_batch,
    upsert_vectors_batch,
    embed_and_index_batch,
    chunk_texts,
    DEFAULT_BATCH_SIZE,
)
from src.types import VectorChunk


class TestEmbedTextsBatch:
    """Tests for embed_texts_batch function."""

    @pytest.fixture
    def mock_provider(self):
        """Create a mock embedding provider."""
        provider = MagicMock()
        provider.embed = AsyncMock()
        return provider

    @pytest.mark.asyncio
    async def test_empty_input(self, mock_provider):
        """Test empty input returns empty list."""
        result = await embed_texts_batch([], mock_provider)
        assert result == []
        mock_provider.embed.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_text(self, mock_provider):
        """Test single text embedding."""
        mock_provider.embed.return_value = [
            MagicMock(embedding=[0.1, 0.2, 0.3])
        ]

        result = await embed_texts_batch(["hello"], mock_provider)

        assert len(result) == 1
        assert result[0] == [0.1, 0.2, 0.3]
        mock_provider.embed.assert_called_once_with(["hello"])

    @pytest.mark.asyncio
    async def test_batch_within_limit(self, mock_provider):
        """Test batch within limit uses single API call."""
        texts = [f"text{i}" for i in range(10)]
        mock_provider.embed.return_value = [
            MagicMock(embedding=[float(i)]) for i in range(10)
        ]

        result = await embed_texts_batch(texts, mock_provider, batch_size=100)

        assert len(result) == 10
        # Single API call for all 10 texts
        mock_provider.embed.assert_called_once_with(texts)

    @pytest.mark.asyncio
    async def test_batch_exceeds_limit(self, mock_provider):
        """Test batch exceeds limit splits into multiple calls."""
        texts = [f"text{i}" for i in range(25)]

        # Mock two batches
        mock_provider.embed.side_effect = [
            [MagicMock(embedding=[float(i)]) for i in range(20)],
            [MagicMock(embedding=[float(i)]) for i in range(5)],
        ]

        result = await embed_texts_batch(texts, mock_provider, batch_size=20)

        assert len(result) == 25
        # Two API calls
        assert mock_provider.embed.call_count == 2
        mock_provider.embed.assert_any_call(texts[:20])
        mock_provider.embed.assert_any_call(texts[20:])

    @pytest.mark.asyncio
    async def test_batch_exact_multiple(self, mock_provider):
        """Test batch size exact multiple of input."""
        texts = [f"text{i}" for i in range(20)]

        # Two batches, each returning 10 embeddings
        mock_provider.embed.side_effect = [
            [MagicMock(embedding=[float(i)]) for i in range(10)],
            [MagicMock(embedding=[float(i)]) for i in range(10, 20)],
        ]

        result = await embed_texts_batch(texts, mock_provider, batch_size=10)

        assert len(result) == 20
        # Two API calls
        assert mock_provider.embed.call_count == 2

    @pytest.mark.asyncio
    async def test_error_propagates(self, mock_provider):
        """Test that embedding errors propagate."""
        mock_provider.embed.side_effect = RuntimeError("API error")

        with pytest.raises(RuntimeError, match="API error"):
            await embed_texts_batch(["test"], mock_provider)


class TestUpsertVectorsBatch:
    """Tests for upsert_vectors_batch function."""

    @pytest.fixture
    def mock_provider(self):
        """Create mock provider."""
        provider = MagicMock()
        provider.embed = AsyncMock(return_value=[
            MagicMock(embedding=[0.1, 0.2, 0.3])
        ])
        return provider

    @pytest.fixture
    def mock_table(self):
        """Create mock LanceDB table."""
        table = MagicMock()
        return table

    @pytest.mark.asyncio
    async def test_empty_chunks(self, mock_provider, mock_table):
        """Test empty input."""
        result = await upsert_vectors_batch([], mock_provider, table=mock_table)
        assert result == 0
        mock_provider.embed.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_chunk(self, mock_provider, mock_table):
        """Test single chunk processing."""
        chunk = VectorChunk(
            id="c1",
            task_id="t1",
            content="hello",
            embedding=[],
            path="test.md",
            updated_at=123,
        )

        with patch("src.vector.upsert.upsert_chunks_to_table") as mock_upsert:
            result = await upsert_vectors_batch([chunk], mock_provider, table=mock_table)

        assert result == 1
        assert chunk.embedding == [0.1, 0.2, 0.3]
        mock_provider.embed.assert_called_once_with(["hello"])

    @pytest.mark.asyncio
    async def test_multiple_chunks(self, mock_provider, mock_table):
        """Test multiple chunks batch processing."""
        chunks = [
            VectorChunk(
                id=f"c{i}",
                task_id="t1",
                content=f"text{i}",
                embedding=[],
                path="test.md",
                updated_at=123,
            )
            for i in range(5)
        ]

        mock_provider.embed.return_value = [
            MagicMock(embedding=[float(i)]) for i in range(5)
        ]

        with patch("src.vector.upsert.upsert_chunks_to_table") as mock_upsert:
            result = await upsert_vectors_batch(chunks, mock_provider, table=mock_table)

        assert result == 5
        # Verify all embeddings populated
        for i, chunk in enumerate(chunks):
            assert chunk.embedding == [float(i)]


class TestEmbedAndIndexBatch:
    """Tests for embed_and_index_batch function."""

    @pytest.fixture
    def mock_provider(self):
        """Create mock provider."""
        provider = MagicMock()
        provider.embed = AsyncMock(return_value=[
            MagicMock(embedding=[0.1, 0.2])
        ])
        return provider

    @pytest.mark.asyncio
    async def test_empty_items(self, mock_provider):
        """Test empty input."""
        result = await embed_and_index_batch([], mock_provider)
        assert result == 0

    @pytest.mark.asyncio
    async def test_single_item(self, mock_provider):
        """Test single item processing."""
        items = [{
            "id": "c1",
            "task_id": "t1",
            "content": "hello",
            "path": "test.md",
            "updated_at": 123,
        }]

        with patch("src.vector.batch.upsert_vectors_batch") as mock_upsert:
            mock_upsert.return_value = 1
            result = await embed_and_index_batch(items, mock_provider)

        assert result == 1


class TestChunkTexts:
    """Tests for chunk_texts utility function."""

    def test_empty_input(self):
        """Test empty input."""
        result = chunk_texts([])
        assert result == []

    def test_single_batch(self):
        """Test single batch."""
        texts = ["a", "b", "c"]
        result = chunk_texts(texts, max_batch_size=10)
        assert result == [texts]

    def test_multiple_batches(self):
        """Test multiple batches."""
        texts = [f"t{i}" for i in range(25)]
        result = chunk_texts(texts, max_batch_size=10)

        assert len(result) == 3
        assert len(result[0]) == 10
        assert len(result[1]) == 10
        assert len(result[2]) == 5

    def test_exact_multiple(self):
        """Test exact multiple."""
        texts = [f"t{i}" for i in range(20)]
        result = chunk_texts(texts, max_batch_size=10)

        assert len(result) == 2
        assert all(len(batch) == 10 for batch in result)

    def test_default_batch_size(self):
        """Test default batch size is used."""
        texts = [f"t{i}" for i in range(DEFAULT_BATCH_SIZE + 1)]
        result = chunk_texts(texts)

        assert len(result) == 2
        assert len(result[0]) == DEFAULT_BATCH_SIZE
        assert len(result[1]) == 1