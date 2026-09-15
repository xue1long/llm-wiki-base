"""LLMClient — minimal abstraction layer for the V7 extract pipeline.

Why this exists
---------------
The V7 extract pipeline makes several LLM calls per source file
(classify, structure-recognize, topic-cluster, slot-fill, relation-extract).
Calling the real LLM during unit tests is expensive and non-deterministic.

This module provides:

* ``LLMClient`` — abstract interface (the contract every real call site
  depends on).
* ``AnthropicLLMClient`` — concrete adapter wrapping the project's
  existing provider factory (`src.llm.provider_factory`).
* ``FakeLLMClient`` — deterministic in-memory client used by unit tests,
  returning scripted responses keyed by ``prompt_kind``.

Per M9-V5 of the plan-audit v5: without this abstraction the pipeline
cannot be unit-tested, because every change to a prompt would invalidate
the test suite.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMClient(ABC):
    """Abstract LLM interface used by the V7 extract pipeline.

    All call sites should depend on this type, not on a concrete
    ``Provider`` or ``httpx`` client. Production code wires up
    :class:`AnthropicLLMClient`; tests wire up :class:`FakeLLMClient`.
    """

    @abstractmethod
    async def complete(
        self,
        *,
        prompt_kind: str,
        user_prompt: str,
        system_prompt: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> str:
        """Return the model's text completion for the given prompt.

        Args:
            prompt_kind: short identifier like ``"classify"`` /
                ``"cluster"``/ ``"fill_slots"``. Used by fakes to
                dispatch scripted responses and by analytics to count
                prompt-kind usage.
            user_prompt: the actual prompt body.
            system_prompt: optional system message; pass-through for
                the Anthropic / OpenAI clients.
            max_tokens: upper bound on generated tokens.
            temperature: sampling temperature. Tests / production
                classification passes should use ``0.0``.

        Returns:
            The raw text content of the model's response. The caller
            is responsible for parsing (JSON / regex / etc.).
        """
        raise NotImplementedError


class FakeLLMClient(LLMClient):
    """In-memory LLM client that returns scripted responses by prompt_kind.

    Usage in tests::

        fake = FakeLLMClient()
        fake.script("classify", '{"doc_type": "single_method"}')
        fake.script("cluster", '{"topics": [{"title": "..."}, ...]}')
        # ... inject into the pipeline
    """

    def __init__(self) -> None:
        self._scripts: dict[str, list[str]] = {}
        self.calls: list[dict[str, Any]] = []  # log for assertions

    def script(self, prompt_kind: str, response: str) -> None:
        """Queue a response for the next call of *prompt_kind*."""
        self._scripts.setdefault(prompt_kind, []).append(response)

    async def complete(
        self,
        *,
        prompt_kind: str,
        user_prompt: str,
        system_prompt: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> str:
        self.calls.append({
            "prompt_kind": prompt_kind,
            "user_prompt_len": len(user_prompt),
            "system_prompt_len": len(system_prompt),
            "max_tokens": max_tokens,
            "temperature": temperature,
        })
        queue = self._scripts.get(prompt_kind, [])
        if not queue:
            return ""  # honest: tests assert against calls log
        return queue.pop(0)


class AnthropicLLMClient(LLMClient):
    """Concrete LLMClient backed by the project's provider factory.

    Wraps ``src.llm.provider_factory.create_llm_provider`` so the rest of
    the pipeline never imports from ``src.llm`` directly. This keeps the
    dependency direction ``pipeline.v7_extract → llm`` one-way.
    """

    def __init__(self, default_provider_name: str | None = None) -> None:
        # Lazy import: avoid hard import at module-load time so test
        # environments that never invoke .complete() don't need the
        # llm registry on disk.
        from ...llm.provider_factory import create_llm_provider
        from ...llm.registry import ProviderRegistry

        if default_provider_name is None:
            default_provider_name = ProviderRegistry.get_default_name()
            if default_provider_name is None:
                # No default configured; caller must supply one.
                raise RuntimeError(
                    "No default LLM provider configured. Either set one via "
                    "src.llm.registry.ProviderRegistry.set_default() or pass "
                    "default_provider_name explicitly."
                )
        self._provider_name = default_provider_name
        self._provider = create_llm_provider(default_provider_name)

    @property
    def provider_name(self) -> str:
        return self._provider_name

    async def complete(
        self,
        *,
        prompt_kind: str,
        user_prompt: str,
        system_prompt: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> str:
        # The provider contract accepts chat messages and returns an
        # LLMResponse. Provider-specific errors
        # (rate limits, timeouts) propagate up — the pipeline's
        # wiki_writer stage retries up to N times before giving up
        # (see plan-audit v5 F-A-V5 / F-B-V5).
        messages = [{"role": "user", "content": user_prompt}]
        if system_prompt:
            messages.insert(0, {"role": "system", "content": system_prompt})
        response = await self._provider.complete(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if getattr(response, "truncated", False):
            from ...llm.types import TruncatedResponseError

            content = getattr(response, "content", "")
            raise TruncatedResponseError(
                "LLM response was truncated by max_tokens",
                content_length=getattr(response, "content_length", 0)
                or (len(content) if isinstance(content, str) else 0),
            )
        return response.content
