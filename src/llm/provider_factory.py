"""Factory to instantiate LLM provider from registry entry.

Existing OpenAI/Anthropic providers take simple kwargs (api_key/endpoint/model).
This module adapts the new ``ProviderConfig`` shape into those constructors so we
do not have to refactor the well-tested legacy providers.
"""
import os

from .base import LLMProvider, EmbeddingProvider
from .types import ProviderConfig


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
            config = ProviderConfig(
                name=config.name,
                type=config.type,
                base_url=config.base_url,
                api_key=os.environ[env_key],
                models=config.models,
                default_chat_model=config.default_chat_model,
                default_embedding_model=config.default_embedding_model,
                timeout_seconds=config.timeout_seconds,
                extra_headers=config.extra_headers,
            )

    model = model_override or config.default_chat_model

    if config.type == "ollama":
        from .ollama_provider import OllamaProvider
        return OllamaProvider(config, model_override=model_override)
    elif config.type == "openai":
        from .openai_provider import OpenAIProvider
        return OpenAIProvider(
            api_key=config.api_key or None,
            endpoint=config.base_url,
            model=model or "gpt-4o-mini",
        )
    elif config.type == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(
            api_key=config.api_key or None,
            endpoint=config.base_url,
            model=model or "claude-haiku-4-5",
        )
    raise ValueError(f"Unknown provider type: {config.type}")


def create_embedding_provider(
    provider: str = "openai",
    api_key=None,
    endpoint=None,
    model=None,
    dimension: int = 1536,
) -> EmbeddingProvider:
    """Legacy embedding-provider factory used by existing pipeline code."""
    if provider == "openai":
        from .openai_provider import OpenAIEmbeddingProvider
        return OpenAIEmbeddingProvider(
            api_key=api_key,
            endpoint=endpoint,
            model=model or "text-embedding-3-small",
            dimension=dimension,
        )
    elif provider == "ollama":
        # Convenience: build a thin EmbeddingProvider-compatible wrapper that
        # delegates to OllamaProvider.embed.
        from .ollama_provider import OllamaProvider
        from .types import ProviderConfig
        cfg = ProviderConfig(
            name="ollama", type="ollama",
            base_url=endpoint or "http://127.0.0.1:11434",
            default_chat_model=model or "",
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
        "anthropic": "ANTHROPIC_API_KEY",
        "ollama": None,
    }.get(name)
