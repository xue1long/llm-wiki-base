"""hybrid_search top_k bounds — focused tests (regression of the
behaviour enforced by test_empty_query)."""
import pytest

from src.searcher.hybrid_search import hybrid_search, MAX_TOP_K


@pytest.mark.asyncio
async def test_top_k_one_accepted():
    """top_k=1 is the lower bound and must NOT raise."""
    # We don't care about the result content here (no embedding provider,
    # no Knowledge dir) — only that the validation doesn't reject it.
    result = await hybrid_search("anything", top_k=1)
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_top_k_max_accepted():
    """top_k=MAX_TOP_K is the upper bound and must NOT raise."""
    result = await hybrid_search("anything", top_k=MAX_TOP_K)
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_top_k_just_above_max_rejected():
    with pytest.raises(ValueError):
        await hybrid_search("anything", top_k=MAX_TOP_K + 1)
