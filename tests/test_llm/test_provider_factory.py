"""Provider-type resolution for the embedding factory.

MiniMax registers with ``type="openai"`` (OpenAI-compatible chat API) but its
embedding endpoint is MiniMax-native (``vectors`` not ``data``), so the
embedding provider class must be MiniMax regardless of the chat type. The
server previously used ``cfg.type`` directly and built an OpenAI-compatible
embedding provider pointed at MiniMax, which raised ``IndexError`` reading
``data[0]`` and silently degraded semantic search to keyword-only.
"""
from src.llm.provider_factory import _env_var_for_provider, resolve_embedding_provider_type


def test_minimax_name_maps_to_minimax_even_when_type_is_openai():
    assert resolve_embedding_provider_type("minimax", "openai") == "minimax"


def test_openai_name_uses_type():
    assert resolve_embedding_provider_type("openai", "openai") == "openai"


def test_openai_compatible_name_uses_type():
    assert resolve_embedding_provider_type("custom", "openai-compatible") == "openai-compatible"


def test_anthropic_name_uses_type():
    assert resolve_embedding_provider_type("anthropic", "anthropic") == "anthropic"


def test_ollama_name_uses_type():
    assert resolve_embedding_provider_type("ollama", "ollama") == "ollama"


def test_common_compatible_provider_uses_matching_env_key():
    assert _env_var_for_provider("deepseek") == "DEEPSEEK_API_KEY"
    assert _env_var_for_provider("moonshot") == "KIMI_API_KEY"
