"""BudgetedLLM — chunk long prompts to fit LLM context window.

MVP: globally wraps all LLM calls (per spec MVP). Caller does not need
to know about chunking; just call provider.complete() and the wrapper
auto-splits.

Token metrics: records prompt/completion tokens and retry counts to
.index/metrics/ for optimization analysis.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Optional, Union

from .context_budget import chunk_by_budget, estimate_tokens
from ..llm.token_metrics import TokenMetric, record_metric


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

# Configurable timeout for LLM calls
# MiniMax users should set RUFLO_LLM_TIMEOUT=120
# OpenAI/Anthropic users can use default 60
DEFAULT_LLM_TIMEOUT = int(os.environ.get("RUFLO_LLM_TIMEOUT", "60"))


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
        self._provider_name = self._extract_provider_name(provider)
        self.context_window = context_window_tokens or get_model_context_window(model)
        self._chunks_processed: int = 0
        self._retry_count: int = 0

    @staticmethod
    def _extract_provider_name(provider: Any) -> str:
        """Extract a human-readable provider name from provider object."""
        if provider is None:
            return "unknown"
        # Check for config.name (our ProviderConfig pattern)
        if hasattr(provider, "config") and hasattr(provider.config, "name"):
            return provider.config.name
        # Check for model attribute (Ollama pattern)
        if hasattr(provider, "model"):
            model_name = provider.model
            # Truncate long model names
            return f"ollama-{model_name[:20]}" if len(model_name) > 20 else f"ollama-{model_name}"
        # Fallback to class name
        cls_name = type(provider).__name__
        return cls_name.lower().replace("provider", "")

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
        self._retry_count = 0
        threshold = int(self.context_window * SINGLE_CALL_THRESHOLD)
        prompt_tokens = estimate_tokens(prompt)

        if prompt_tokens <= threshold:
            # Single call
            self._chunks_processed = 1
            try:
                response = await self._single_call(prompt, response_format, system)
                self._record_success(response, prompt_tokens)
                return response
            except Exception as e:
                self._retry_count += 1
                self._record_failure(type(e).__name__, prompt_tokens)
                raise

        # Multi-chunk
        chunk_max = int(self.context_window * SAFETY_FACTOR)
        chunks = chunk_by_budget(prompt, max_tokens=chunk_max)
        self._chunks_processed = len(chunks)
        results = []
        for i, chunk in enumerate(chunks):
            try:
                result = await self._single_call(chunk, response_format, system)
                results.append(result)
            except Exception as e:
                self._retry_count += 1
                self._record_failure(type(e).__name__, estimate_tokens(chunk))
                raise

        # Record success for the overall call
        if results:
            self._record_success(results[0], prompt_tokens)
        return results if len(results) > 1 else results[0]

    def _extract_usage_tokens(self, response: Any) -> tuple[int, int]:
        """Extract prompt and completion tokens from LLMResponse.

        Handles:
        - LLMResponse.usage as dict (OpenAI/Anthropic pattern)
        - Ollama's different field names (prompt_eval_count / eval_count)
        - Missing usage field
        """
        if response is None:
            return 0, 0

        usage = getattr(response, "usage", None)
        if usage is None:
            return 0, 0

        # usage is a dict, handle both naming conventions
        if isinstance(usage, dict):
            prompt = usage.get("prompt_tokens") or usage.get("prompt_eval_count", 0)
            completion = usage.get("completion_tokens") or usage.get("eval_count", 0)
            return int(prompt), int(completion)

        # Fallback for object-style usage
        prompt = getattr(usage, "prompt_tokens", 0) or getattr(usage, "prompt_eval_count", 0)
        completion = getattr(usage, "completion_tokens", 0) or getattr(usage, "eval_count", 0)
        return int(prompt), int(completion)

    def _record_success(self, response: Any, prompt_tokens: int) -> None:
        """Record a successful LLM call to metrics."""
        completion_tokens = self._extract_usage_tokens(response)[1]
        record_metric(TokenMetric(
            timestamp=int(time.time()),
            prompt_name=self.op,
            provider=self._provider_name,
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            retry_count=self._retry_count,
            success=True,
        ))

    def _record_failure(self, error_type: str, prompt_tokens: int) -> None:
        """Record a failed LLM call to metrics."""
        record_metric(TokenMetric(
            timestamp=int(time.time()),
            prompt_name=self.op,
            provider=self._provider_name,
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=0,
            retry_count=self._retry_count,
            success=False,
            error_type=error_type,
        ))

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
            timeout=DEFAULT_LLM_TIMEOUT,
        )
