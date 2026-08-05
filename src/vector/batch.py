"""Batch embedding operations for efficient vector processing.

Provides utilities for embedding multiple texts in batch,
reducing API calls from O(n) to O(n/batch_size).

Configuration:
    RUFLO_EMBED_BATCH_SIZE: Maximum texts per batch (default: 100)
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..llm.base import EmbeddingProvider
    from ..types import VectorChunk

logger = logging.getLogger(__name__)

# Default batch size (OpenAI supports up to 2048, but 100 is safer)
DEFAULT_BATCH_SIZE = 100


def _get_batch_size() -> int:
    """Get configured batch size from environment."""
    return int(os.environ.get("RUFLO_EMBED_BATCH_SIZE", str(DEFAULT_BATCH_SIZE)))


async def embed_texts_batch(
    texts: list[str],
    provider: "EmbeddingProvider",
    batch_size: int | None = None,
) -> list[list[float]]:
    """Embed multiple texts in batch.

    Args:
        texts: List of texts to embed
        provider: Embedding provider (must support async embed())
        batch_size: Maximum texts per batch (default: RUFLO_EMBED_BATCH_SIZE)

    Returns:
        List of embedding vectors in same order as input texts

    Example:
        embeddings = await embed_texts_batch(
            ["hello", "world"],
            provider,
            batch_size=50
        )
    """
    if not texts:
        return []

    batch_size = batch_size or _get_batch_size()
    all_embeddings: list[list[float]] = []

    # Process in batches
    total = len(texts)
    for i in range(0, total, batch_size):
        batch = texts[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (total + batch_size - 1) // batch_size

        logger.debug(
            "[BatchEmbed] Processing batch %d/%d (%d texts)",
            batch_num, total_batches, len(batch)
        )

        try:
            # Call provider's batch embed API
            responses = await provider.embed(batch)

            # Extract embeddings
            for resp in responses:
                all_embeddings.append(resp.embedding)

        except Exception as e:
            logger.error(
                "[BatchEmbed] Batch %d/%d failed: %s",
                batch_num, total_batches, e
            )
            raise

    logger.info(
        "[BatchEmbed] Completed %d texts in %d batches",
        total, (total + batch_size - 1) // batch_size
    )

    return all_embeddings


async def upsert_vectors_batch(
    chunks: list["VectorChunk"],
    provider: "EmbeddingProvider",
    batch_size: int | None = None,
    table=None,
) -> int:
    """Embed and upsert multiple chunks in batch.

    This is an optimized version of the single-chunk loop:
    - Single embedding API call for all chunks (vs N calls)
    - Single vector store write (vs N writes)

    Args:
        chunks: List of VectorChunk (embedding field will be populated)
        provider: Embedding provider
        batch_size: Maximum texts per batch
        table: Optional LanceDB table (default: use active project)

    Returns:
        Number of chunks processed

    Example:
        chunks = [
            VectorChunk(id="c1", task_id="t1", content="hello", path="a.md"),
            VectorChunk(id="c2", task_id="t1", content="world", path="a.md"),
        ]
        count = await upsert_vectors_batch(chunks, provider)
    """
    if not chunks:
        return 0

    from ..vector.store import get_table
    from ..vector.upsert import upsert_chunks_to_table

    table = table or get_table()
    batch_size = batch_size or _get_batch_size()

    # Extract texts for embedding
    texts = [c.content for c in chunks]

    logger.info(
        "[BatchUpsert] Embedding %d chunks in batches of %d",
        len(chunks), batch_size
    )

    # Embed in batch
    embeddings = await embed_texts_batch(texts, provider, batch_size)

    # Populate embeddings into chunks
    for i, chunk in enumerate(chunks):
        chunk.embedding = embeddings[i]

    # Write to vector store in single operation
    upsert_chunks_to_table(table, chunks)

    logger.info(
        "[BatchUpsert] Upserted %d chunks to vector store",
        len(chunks)
    )

    return len(chunks)


async def embed_and_index_batch(
    items: list[dict],
    provider: "EmbeddingProvider",
    table=None,
    batch_size: int | None = None,
) -> int:
    """Embed texts and add to vector index.

    Convenience function for the common pattern:
    1. Extract text from items
    2. Embed in batch
    3. Write to vector store

    Args:
        items: List of dicts with keys: id, task_id, content, path, updated_at
        provider: Embedding provider
        table: Optional LanceDB table
        batch_size: Maximum texts per batch

    Returns:
        Number of items indexed

    Example:
        items = [
            {"id": "c1", "task_id": "t1", "content": "hello", "path": "a.md", "updated_at": 123},
        ]
        count = await embed_and_index_batch(items, provider)
    """
    from ..types import VectorChunk

    # Convert dicts to VectorChunks (without embedding)
    chunks = [
        VectorChunk(
            id=item["id"],
            task_id=item["task_id"],
            content=item["content"],
            embedding=[],  # Will be populated
            path=item["path"],
            updated_at=item["updated_at"],
        )
        for item in items
    ]

    return await upsert_vectors_batch(chunks, provider, batch_size, table)


# Utility function for chunking with overlap
def chunk_texts(
    texts: list[str],
    max_batch_size: int | None = None,
) -> list[list[str]]:
    """Split texts into batches respecting API limits.

    Args:
        texts: List of texts to chunk
        max_batch_size: Maximum texts per batch

    Returns:
        List of batches
    """
    max_batch_size = max_batch_size or _get_batch_size()
    return [
        texts[i:i + max_batch_size]
        for i in range(0, len(texts), max_batch_size)
    ]