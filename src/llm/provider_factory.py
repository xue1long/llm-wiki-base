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
    *,
    retry_max_retries: int = 3,
) -> LLMProvider:
    """Create an LLM provider instance from a global registry entry.

    The returned provider is wrapped in ``RetryLLMProvider`` (plan 1.9 / C1):
    every ``complete()``/``chat()`` goes through ``retry_with_backoff``
    (429 Retry-After, 422 permanent isolation, transient backoff) and the
    shared ``"llm"`` circuit breaker.  This single factory-level wrapper
    covers all LLM call points at once (generator / analyzer via BudgetedLLM /
    c_grade_handler / QualityJudge) — no per-call-site wiring to miss.

    ``RetryLLMProvider`` is duck-compatible with ``LLMProvider`` (it exposes
    ``complete/chat/embed/health_check/check_response_format/close`` and
    delegates ``model``/``config``/``_response_format_ok`` via ``__getattr__``).
    """
    from .registry import ProviderRegistry
    config = ProviderRegistry.get(registry_name)
    return _wrap_retry(
        _create_from_config(config, model_override),
        max_retries=retry_max_retries,
    )


def _wrap_retry(provider, *, max_retries: int = 3) -> LLMProvider:
    """Wrap a concrete provider with the retry/breaker layer (lazy import to
    avoid a module-level import cycle: pipeline.retry is import-safe only
    after the pipeline package has been initialised)."""
    from ..pipeline.retry import RetryLLMProvider
    return RetryLLMProvider(provider, max_retries=max_retries)


def _create_from_config(config: ProviderConfig, model_override: str | None = None) -> LLMProvider:
    # Env-var override for API key when config leaves it blank.
    if not config.api_key:
        env_key = _env_var_for_provider(config.name)
        if env_key:
            from src.config import settings
            settings_val = getattr(settings(), _field_for_env(env_key), "") or os.environ.get(env_key, "")
            if settings_val:
                from dataclasses import replace
                config = replace(config, api_key=settings_val)

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
        "anthropic": "ANTHROPIC_API_KEY",
        "ollama": None,
        "minimax": "MINIMAX_API_KEY",
        "kimi": "KIMI_API_KEY",
        "moonshot": "KIMI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "glm": "GLM_API_KEY",
        "zhipu": "GLM_API_KEY",
        "qwen": "DASHSCOPE_API_KEY",
        "dashscope": "DASHSCOPE_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "google": "GOOGLE_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "groq": "GROQ_API_KEY",
        "mistral": "MISTRAL_API_KEY",
        "together": "TOGETHER_API_KEY",
        "cohere": "COHERE_API_KEY",
        "perplexity": "PERPLEXITY_API_KEY",
    }.get(name)


def _field_for_env(env_name: str) -> str:
    """Map an env var name to the equivalent :class:`src.config.Settings` field.

    Kept next to ``_env_var_for_provider`` so the provider→env→field chain
    stays in one place.
    """
    return {
        "OPENAI_API_KEY": "openai_api_key",
        "ANTHROPIC_API_KEY": "anthropic_api_key",
    }.get(env_name, "")
