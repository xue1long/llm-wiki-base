# ruflo-kb/src/llm/provider_factory.py
from typing import Optional
from .base import LLMProvider, EmbeddingProvider
from .openai_provider import OpenAIProvider, OpenAIEmbeddingProvider
from .anthropic_provider import AnthropicProvider

def create_llm_provider(
    provider: str = "openai",
    api_key: Optional[str] = None,
    endpoint: Optional[str] = None,
    model: Optional[str] = None,
) -> LLMProvider:
    """创建 LLM Provider 实例"""
    if provider == "openai":
        return OpenAIProvider(api_key=api_key, endpoint=endpoint, model=model or "gpt-4")
    elif provider == "anthropic":
        return AnthropicProvider(api_key=api_key, endpoint=endpoint, model=model or "claude-3-sonnet-20240229")
    else:
        raise ValueError(f"Unknown provider: {provider}")

def create_embedding_provider(
    provider: str = "openai",
    api_key: Optional[str] = None,
    endpoint: Optional[str] = None,
    model: Optional[str] = None,
    dimension: int = 1536,
) -> EmbeddingProvider:
    """创建 Embedding Provider 实例"""
    if provider == "openai":
        return OpenAIEmbeddingProvider(
            api_key=api_key,
            endpoint=endpoint,
            model=model or "text-embedding-3-small",
            dimension=dimension,
        )
    else:
        raise ValueError(f"Unknown embedding provider: {provider}")
