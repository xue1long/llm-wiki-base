# ruflo-kb/tests/test_searcher/test_searcher.py
import pytest
from src.searcher.qa import generate_answer

@pytest.mark.asyncio
async def test_generate_answer_no_context():
    """Test answer generation with no context"""
    result = await generate_answer("test query", [])
    assert result is None

@pytest.mark.asyncio
async def test_generate_answer_with_context():
    """Test answer generation with context"""
    context = [{"content": "This is a test document about Python."}]
    result = await generate_answer("test query", context)
    assert result is not None
    assert "根据搜索结果" in result
