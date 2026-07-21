import pytest
from src.shared.test_helpers import ScriptedLLMProvider
from src.lib.budgeted import BudgetedLLM


@pytest.mark.asyncio
async def test_budgeted_short_prompt_single_call():
    """Short prompt → 1 LLM call, no chunking."""
    provider = ScriptedLLMProvider([{"choices": [{"message": {"content": "ok"}}]}])
    async with BudgetedLLM(model="gpt-4o-mini", op="test", provider=provider) as bl:
        result = await bl.call(prompt="short", response_format=None)
    assert result == {"choices": [{"message": {"content": "ok"}}]}
    assert bl.chunks_processed == 1


@pytest.mark.asyncio
async def test_budgeted_long_prompt_chunks():
    """Long prompt → multiple calls + merge."""
    # Set window to 100 tokens, SAFETY_FACTOR=0.6 → chunk_max=60 tokens → 120 chars/chunk
    # 1000 chars → ~9 chunks
    scripted = [{"choices": [{"message": {"content": '{"items": ["a"]}'}}]}] * 10
    provider = ScriptedLLMProvider(scripted)
    long_prompt = "x" * 1000   # 500 tokens, way over 100
    async with BudgetedLLM(model="gpt-4o-mini", op="test", provider=provider,
                            context_window_tokens=100) as bl:
        result = await bl.call(prompt=long_prompt, response_format=None)
    # 1000 chars / 120 chars per chunk ≈ 9 chunks (no good split point → hard split by 120)
    assert bl.chunks_processed >= 2   # multiple chunks
    assert isinstance(result, list)
    assert len(result) == bl.chunks_processed


@pytest.mark.asyncio
async def test_budgeted_unknown_model_default_window():
    """Unknown model uses default 8192 token window."""
    provider = ScriptedLLMProvider([{"choices": [{"message": {"content": "ok"}}]}])
    async with BudgetedLLM(model="unknown-model-xyz", op="test", provider=provider) as bl:
        result = await bl.call(prompt="short", response_format=None)
    assert bl.chunks_processed == 1
