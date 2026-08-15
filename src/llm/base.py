# ruflo-kb/src/llm/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

@dataclass
class LLMResponse:
    content: str
    model: str
    usage: Optional[dict] = None
    # True when the endpoint reported finish_reason="length" (response was
    # cut off mid-generation, e.g. by a max_tokens cap). JSON callers must
    # treat the content as incomplete — retry with higher max_tokens.
    truncated: bool = False

@dataclass
class EmbeddingResponse:
    embedding: list[float]
    model: str

class LLMProvider(ABC):
    """LLM Provider 抽象接口.

    The canonical chat call is ``complete(messages=[...])`` which always
    returns an :class:`LLMResponse`. JSON-typed outputs are stringified
    JSON in ``response.content``; callers should
    ``json.loads(response.content)`` themselves rather than relying on
    the provider to parse.

    Subclasses MUST implement ``complete`` and ``embed``. The base class
    provides no-op defaults for ``health_check`` and ``close`` so they
    can be safely called on any provider; concrete providers with
    long-lived resources (e.g. Ollama's AsyncClient) override them.
    """

    @abstractmethod
    async def complete(
        self,
        messages: list[dict],
        *,
        response_format: Optional[dict] = None,
        system: Optional[str] = None,
        timeout: Optional[float] = None,
        **kwargs,
    ) -> LLMResponse:
        """Generate a chat completion.

        Args:
            messages: list of chat messages, each ``{"role": ..., "content": ...}``.
                Roles include ``"user"``, ``"assistant"``, optionally ``"system"``
                (provider lifts system messages to the appropriate API field).
            response_format: optional schema dict for JSON-typed outputs.
            system: optional top-level system prompt. Some providers prefer
                this over a system-role message; see concrete impls.
            timeout: optional per-call timeout in seconds. If None, uses
                the provider's default timeout. Falls back to 300s when
                the caller's timeout would exceed the provider default.
            **kwargs: provider-specific passthrough (model, temperature, etc.).

        Returns:
            LLMResponse with ``.content`` (str) carrying the model output.
        """
        raise NotImplementedError

    # Chat is an alias for complete — both names exist for caller convenience.
    async def chat(
        self,
        messages: list[dict],
        *,
        response_format: Optional[dict] = None,
        system: Optional[str] = None,
        timeout: Optional[float] = None,
        **kwargs,
    ) -> LLMResponse:
        """Alias for :meth:`complete`."""
        return await self.complete(
            messages,
            response_format=response_format,
            system=system,
            timeout=timeout,
            **kwargs,
        )

    @abstractmethod
    async def embed(self, text: str) -> EmbeddingResponse:
        """Generate a single-text embedding (for legacy callers)."""
        raise NotImplementedError

    async def health_check(self) -> dict:
        """Return ``{"ok": bool, "detail": str, ...}`` describing reachability.

        Standardised contract (audit I2): every concrete provider
        implements this so callers (CLI, server lifespan, tests) can
        consume the result uniformly without per-provider branching.
        Subclasses override to perform an actual probe.
        Base default returns ``{"ok": True, "detail": "no probe"}``.
        """
        return {"ok": True, "detail": "no probe"}

    async def check_response_format(self) -> dict:
        """Probe whether the endpoint accepts the pipeline's non-standard
        ``response_format`` shape (``{"type": "object", "properties": {...}}``).

        Standardised contract mirroring :meth:`health_check`: return
        ``{"ok": bool, "detail": str, ...}``. ``ok=False`` means the provider
        would reject the pipeline's structured-output requests with HTTP 400
        (→ permanent failure → source-only stub pages). Providers that do not
        send ``response_format`` to the wire (Anthropic) or that map it to a
        native construct (Ollama) return ``{"ok": True}`` by default.
        """
        return {"ok": True, "detail": "no probe"}

    async def close(self) -> None:
        """Release any unmanaged resources. Subclasses override; default is a no-op
        for stateless or per-call providers (OpenAI/Anthropic use httpx per-call)."""
        return None

class EmbeddingProvider(ABC):
    """Embedding 专用 Provider"""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[EmbeddingResponse]:
        """批量生成 embedding"""
        pass
