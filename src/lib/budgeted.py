"""BudgetedLLM — chunk long prompts to fit LLM context window.

MVP: globally wraps all LLM calls (per spec MVP). Caller does not need
to know about chunking; just call provider.complete() and the wrapper
auto-splits.
"""
import asyncio
import logging
from typing import Any, Callable, Optional

from .context_budget import chunk_by_budget, estimate_tokens


_logger = logging.getLogger(__name__)


# Default context window per model (tokens)
DEFAULT_MODEL_WINDOWS = {
    "gpt-4o-mini": 128000,
    "gpt-4o": 128000,
    "claude-haiku-4-5": 200000,
    "claude-sonnet-4": 200000,
    "qwen2.5:7b": 32768,
    "qwen2.5-7b-instruct": 32768,
}

# Safety: only use 60% of window for input (40% reserved for output)
SAFETY_FACTOR = 0.6
SINGLE_CALL_THRESHOLD = 0.8


def get_model_context_window(model: str) -> int:
    """Get context window for model; default 8192 if unknown."""
    for prefix, window in DEFAULT_MODEL_WINDOWS.items():
        if model.startswith(prefix):
            return window
    return 8192


class BudgetedLLM:
    """Context manager: chunked LLM calls with automatic aggregation.

    Usage:
        provider = create_llm_provider(...)
        async with BudgetedLLM(model="gpt-4o-mini", op="analyzer", provider=provider) as bl:
            result = await bl.call(prompt=long_text, response_format=AnalysisResult)
    """

    def __init__(
        self,
        model: str,
        op: str = "general",
        provider: Any = None,
        context_window_tokens: Optional[int] = None,
    ):
        self.model = model
        self.op = op
        self.provider = provider
        self.context_window = context_window_tokens or get_model_context_window(model)
        self._chunks_processed: int = 0

    async def __aenter__(self) -> "BudgetedLLM":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        pass

    @property
    def chunks_processed(self) -> int:
        return self._chunks_processed

    async def call(self, prompt: str, response_format: Optional[dict] = None, system: Optional[str] = None) -> Any:
        """Call LLM, chunking if prompt exceeds context window.

        Returns:
        - dict if single call
        - list of dicts if chunked
        """
        threshold = int(self.context_window * SINGLE_CALL_THRESHOLD)
        prompt_tokens = estimate_tokens(prompt)

        if prompt_tokens <= threshold:
            # Single call
            self._chunks_processed = 1
            return await self._single_call(prompt, response_format, system)

        # Multi-chunk
        chunk_max = int(self.context_window * SAFETY_FACTOR)
        chunks = chunk_by_budget(prompt, max_tokens=chunk_max)
        self._chunks_processed = len(chunks)
        tasks = [self._single_call(c, response_format, system) for c in chunks]
        results = await asyncio.gather(*tasks)
        return list(results)

    async def _single_call(self, prompt: str, response_format: Optional[dict], system: Optional[str]):
        # Build a single-turn user message out of the prompt. Real providers
        # implement `complete(messages=[...])` (chat contract). This wrapper
        # preserves the legacy `prompt=...` calling shape so existing callers
        # (analyzer/generator) don't have to wrap each call site.
        messages = [{"role": "user", "content": prompt}]
        return await self.provider.complete(
            messages=messages,
            response_format=response_format,
            system=system,
        )
