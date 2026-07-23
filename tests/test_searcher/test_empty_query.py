"""hybrid_search must validate its inputs.

Empty/whitespace-only queries and out-of-bounds top_k values must raise
``ValueError`` so callers fail fast instead of silently receiving an
empty result set.
"""
import pytest

from src.searcher.hybrid_search import hybrid_search, MAX_TOP_K


@pytest.mark.asyncio
async def test_empty_query_string_raises():
    with pytest.raises(ValueError, match="query"):
        await hybrid_search("", top_k=5)


@pytest.mark.asyncio
async def test_whitespace_only_query_raises():
    with pytest.raises(ValueError, match="query"):
        await hybrid_search("   ", top_k=5)


@pytest.mark.asyncio
async def test_tab_and_newline_query_raises():
    with pytest.raises(ValueError, match="query"):
        await hybrid_search("\t\n  \n", top_k=5)


@pytest.mark.asyncio
async def test_top_k_zero_raises():
    with pytest.raises(ValueError, match="top_k"):
        await hybrid_search("anything", top_k=0)


@pytest.mark.asyncio
async def test_top_k_negative_raises():
    with pytest.raises(ValueError, match="top_k"):
        await hybrid_search("anything", top_k=-1)


@pytest.mark.asyncio
async def test_top_k_exceeds_max_raises():
    with pytest.raises(ValueError, match="top_k"):
        await hybrid_search("anything", top_k=MAX_TOP_K + 1)


def test_max_top_k_default_is_100():
    """Brief: MAX_TOP_K default = 100 (sensible cap)."""
    assert MAX_TOP_K == 100
