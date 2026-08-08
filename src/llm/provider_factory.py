"""Factory to instantiate LLM provider from registry entry.

Each branch forwards ``ProviderConfig.timeout_seconds`` and
``extra_headers`` to the provider constructor so time-sensitive callers
can tune their LLM calls.
"""
import logging
import os

from .base import LLMProvider, EmbeddingProvider
from .types import ProviderConfig


_logger = logging.getLogger(__name__)


def create_llm_provider(
    registry_name: str,
    model_override: str | None = None,
) -> LLMProvider:
    """Create an LLM provider instance from a global registry entry."""
    from .registry import ProviderRegistry
    config = ProviderRegistry.get(registry_name)
    return _create_from_config(config, model_override)


def _create_from_config(config: ProviderConfig, model_override: str | None = None) -> LLMProvider:
    # Env-var override for API key when config leaves it blank.
    if not config.api_key:
        env_key = _env_var_for_provider(config.name)
        if env_key and os.environ.get(env_key):
            from dataclasses import replace
            config = replace(config, api_key=os.environ[env_key])

    if config.type == "ollama":
        from .ollama_provider import OllamaProvider
        return OllamaProvider(config, model_override=model_override)
    if config.type in ("openai", "openai-compatible"):
        from .openai_provider import OpenAIProvider
        return OpenAIProvider(config, model_override=model_override)
    if config.type == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(config, model_override=model_override)
    raise ValueError(f"Unknown provider type: {config.type}")


def resolve_embedding_provider_type(name: str, provider_type: str) -> str:
    """Map a registry entry to the embedding-provider class key.

    MiniMax registers with ``type="openai"`` for its OpenAI-compatible chat
    API, but its embedding endpoint is MiniMax-native (``vectors`` not
    ``data``), so it must use ``MiniMaxEmbeddingProvider`` regardless of the
    chat type. Without this special case the server built an OpenAI-compatible
    embedding provider pointed at MiniMax, which raised ``IndexError`` reading
    ``data[0]`` and silently degraded semantic search to keyword-only.
    """
    return "minimax" if name == "minimax" else provider_type


def create_embedding_provider(
    provider: str = "openai",
    api_key=None,
    endpoint=None,
    model=None,
    dimension: int = 1536,
) -> EmbeddingProvider:
    """Legacy embedding-provider factory used by existing pipeline code."""
    if provider in ("openai", "openai-compatible"):
        from .openai_provider import OpenAIEmbeddingProvider
        return OpenAIEmbeddingProvider(
            api_key=api_key,
            endpoint=endpoint,
            model=model or "text-embedding-3-small",
            dimension=dimension,
        )
    if provider == "minimax":
        from .minimax_embed import MiniMaxEmbeddingProvider
        return MiniMaxEmbeddingProvider(
            api_key=api_key or "",
            endpoint=endpoint or "https://api.minimax.chat/v1",
            model=model or "embo-01",
        )
    if provider == "ollama":
        from .ollama_provider import OllamaProvider
        from .types import ProviderConfig
        cfg = ProviderConfig(
            name="ollama", type="ollama",
            base_url=endpoint or "http://127.0.0.1:11434",
            default_chat_model="",
            default_embedding_model=model or "",
        )
        ollama = OllamaProvider(cfg)

        class _OllamaEmbeddingAdapter(EmbeddingProvider):
            async def embed(self, texts):
                if isinstance(texts, str):
                    texts = [texts]
                vecs = await ollama.embed(texts)
                from .base import EmbeddingResponse
                return [EmbeddingResponse(embedding=v, model=cfg.default_embedding_model) for v in vecs]
        return _OllamaEmbeddingAdapter()
    raise ValueError(f"Unknown embedding provider: {provider}")


def _env_var_for_provider(name: str) -> str | None:
    return {
        "openai": "OPENAI_API_KEY",
        "openai-compatible": None,
        "anthropic": "ANTHROPIC_API_KEY",
        "ollama": None,
    }.get(name)
