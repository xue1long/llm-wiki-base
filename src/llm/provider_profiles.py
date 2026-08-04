"""Provider capability profiles for prompt optimization.

Different LLM providers have different context windows, output limits,
and feature support. This module centralizes these capabilities so
the pipeline can adapt (e.g., source text truncation length).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .types import ProviderConfig


@dataclass
class ProviderProfile:
    """Capability profile for a specific LLM provider."""
    name: str
    max_context_tokens: int
    max_output_tokens: int
    recommended_source_chars: int
    supports_response_format: bool  # JSON schema in API
    supports_json_mode: bool  # "format": "json" in body


# Provider profiles based on official documentation and testing.
# recommended_source_chars is ~25% of (context_window * 0.6) to leave room
# for prompts, templates, and response.
PROVIDER_PROFILES: dict[str, ProviderProfile] = {
    "openai": ProviderProfile(
        name="openai",
        max_context_tokens=128000,
        max_output_tokens=16384,
        recommended_source_chars=20000,
        supports_response_format=True,
        supports_json_mode=True,
    ),
    "anthropic": ProviderProfile(
        name="anthropic",
        max_context_tokens=200000,
        max_output_tokens=8192,
        recommended_source_chars=30000,
        supports_response_format=False,  # Anthropic has no native JSON mode
        supports_json_mode=False,
    ),
    "ollama": ProviderProfile(
        name="ollama",
        max_context_tokens=4096,  # Default; actual depends on model config
        max_output_tokens=2048,
        recommended_source_chars=4000,
        supports_response_format=False,
        supports_json_mode=True,  # Ollama supports "format": "json"
    ),
    # MiniMax uses OpenAI-compatible API but rejects response_format
    "minimax": ProviderProfile(
        name="minimax",
        max_context_tokens=128000,
        max_output_tokens=8192,
        recommended_source_chars=20000,
        supports_response_format=False,
        supports_json_mode=False,
    ),
    # DeepSeek reasoning models
    "deepseek": ProviderProfile(
        name="deepseek",
        max_context_tokens=64000,
        max_output_tokens=8192,
        recommended_source_chars=10000,
        supports_response_format=False,
        supports_json_mode=False,
    ),
}


def get_provider_profile(provider_name: str) -> ProviderProfile:
    """Get the profile for a provider name (case-insensitive partial match)."""
    provider_lower = provider_name.lower()

    # Exact match
    if provider_lower in PROVIDER_PROFILES:
        return PROVIDER_PROFILES[provider_lower]

    # Partial match (e.g., "ollama-qwen" matches "ollama")
    for key, profile in PROVIDER_PROFILES.items():
        if key in provider_lower or provider_lower.startswith(key):
            return profile

    # Fallback to OpenAI profile
    return PROVIDER_PROFILES["openai"]


def get_source_char_limit(
    provider_name: str,
    model: str = "",
    config: "ProviderConfig | None" = None,
) -> int:
    """Get the recommended source text truncation length.

    Considers:
    1. Provider's default profile
    2. Model-specific context window from config (for Ollama)
    3. Safety margins for prompts and responses

    Args:
        provider_name: Provider identifier (e.g., "ollama", "openai")
        model: Model name (for logging/debugging)
        config: ProviderConfig with optional models dict containing context_window

    Returns:
        Recommended max characters for source text before truncation.
    """
    profile = get_provider_profile(provider_name)

    # Ollama: check if config specifies a larger context window
    if "ollama" in provider_name.lower() and config and config.models:
        model_info = config.models.get(model)
        if model_info and model_info.context_window:
            # Use 60% for input, 25% of that for source text
            # This leaves room for prompts, templates, and system messages
            safe_limit = int(model_info.context_window * 0.6 * 0.25)
            # Assume ~4 chars per token for Chinese text
            return safe_limit * 4

    return profile.recommended_source_chars


def supports_response_format(provider_name: str) -> bool:
    """Check if the provider supports JSON response_format in API."""
    return get_provider_profile(provider_name).supports_response_format