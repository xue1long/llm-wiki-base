"""ProviderAdapter — bridges ``src.llm.LLMProvider`` to ``v7_extract.LLMClient``.

Why this exists
---------------
The V7 ingest bridge (Task 4 of the V7 replace Plan Stage 0) needs a
``LLMClient`` instance to drive Stage 1-7. The existing
``AnthropicLLMClient`` (in ``llm_client.py``) constructs its own provider
via ``create_llm_provider(name)`` — that means callers cannot reuse an
already-constructed provider instance.

``ProviderAdapter`` instead **wraps an existing ``LLMProvider``** so
that:
  1. The provider construction stays in one place (the ingest
     pipeline's ``_get_provider(project_id=...)``).
  2. The project-level provider override
     (``.llm-wiki/project.json`` ``llm_provider`` field) propagates
     naturally to the V7 stages.
  3. Tests can substitute any ``LLMProvider`` subclass (real network
     stub, FakeLLMClient-style in-memory double) without going through
     the registry.

The interface is intentionally minimal — V7's ``LLMClient.complete``
takes ``prompt_kind`` for analytics; we record it but pass it through
to the underlying provider's LLMResponse, not into the message list.

Cost / budget
-------------
``calls_count`` increments per ``complete()`` call. The V7 bridge
(Task 4) reads this to enforce the ``RUFLO_V7_MAX_CALLS`` budget.
The wrapped provider's own ``usage`` field is not consumed here —
V7's own cost ledger (``AnthropicLLMClient`` / ``BaseURLLLMClient``
pattern) lives in Task 4.
"""
from __future__ import annotations

from .llm_client import LLMClient


class ProviderAdapter(LLMClient):
    """Adapts an already-constructed ``LLMProvider`` to V7's ``LLMClient`` interface.

    Difference from ``AnthropicLLMClient`` (in ``llm_client.py``):
    - ``AnthropicLLMClient.__init__`` accepts a provider NAME and
      constructs the provider via ``create_llm_provider(name)``.
    - ``ProviderAdapter.__init__`` accepts an already-constructed
      ``LLMProvider`` instance — no registry round-trip.

    The ingest pipeline (``src.pipeline.ingest``) constructs the
    provider once per request via ``_get_provider(project_id=...)``
    and passes it to ``run_ingest``. Reusing the existing instance
    via ``ProviderAdapter`` avoids double-construction and respects
    the project-level provider override configured in
    ``.llm-wiki/project.json``.
    """

    def __init__(self, provider) -> None:
        self._provider = provider
        self._calls_count = 0

    @property
    def provider_name(self) -> str:
        """Return the wrapped provider's name for analytics / ledger."""
        # OpenAIProvider / AnthropicProvider / OllamaProvider all expose
        # the name on .config.name. Fallback to class name for custom
        # test doubles that don't follow the convention.
        config = getattr(self._provider, "config", None)
        if config is not None and getattr(config, "name", None):
            return str(config.name)
        return type(self._provider).__name__

    @property
    def calls_count(self) -> int:
        """Number of ``complete()`` calls made so far. Used by the V7
        bridge (Task 4) to enforce ``RUFLO_V7_MAX_CALLS`` budget."""
        return self._calls_count

    async def complete(
        self,
        *,
        prompt_kind: str,
        user_prompt: str,
        system_prompt: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> str:
        """Translate V7's ``complete()`` shape to the provider's chat contract.

        The wrapped provider's ``complete(messages, *, system, ...)``
        accepts OpenAI-style messages. We build a 1- or 2-element
        message list depending on whether ``system_prompt`` is empty,
        then return ``response.content`` (str).
        """
        messages: list[dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        response = await self._provider.complete(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        self._calls_count += 1
        return response.content

    async def health_check(self) -> dict:
        """Forward to the wrapped provider's health_check()."""
        return await self._provider.health_check()


__all__ = ["ProviderAdapter"]
