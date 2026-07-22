"""Tests for ProviderConfig + ModelInfo."""
from src.llm.types import ProviderConfig, ModelInfo


def test_provider_config_to_dict():
    c = ProviderConfig(
        name="ollama",
        type="ollama",
        base_url="http://127.0.0.1:11434",
        models={"qwen2.5:7b": ModelInfo(name="qwen2.5:7b", type="chat")},
        default_chat_model="qwen2.5:7b",
        default_embedding_model="nomic-embed-text",
    )
    d = c.to_dict()
    assert d["name"] == "ollama"
    assert d["models"]["qwen2.5:7b"]["name"] == "qwen2.5:7b"
    assert d["default_chat_model"] == "qwen2.5:7b"


def test_model_info_defaults():
    m = ModelInfo(name="x")
    assert m.type == "chat"
    assert m.context_window == 8192


def test_provider_config_round_trip():
    c = ProviderConfig(
        name="anthropic",
        type="anthropic",
        base_url="https://api.anthropic.com",
        api_key="secret-xyz",
        models={"claude-haiku-4-5": ModelInfo(name="claude-haiku-4-5", context_window=200_000)},
        default_chat_model="claude-haiku-4-5",
    )
    d = c.to_dict()
    restored = ProviderConfig.from_dict(d)
    assert restored.name == "anthropic"
    assert restored.api_key == "secret-xyz"
    assert "claude-haiku-4-5" in restored.models
