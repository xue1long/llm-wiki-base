"""Global LLM provider registry — ~/.config/ruflo-kb/llm-providers.json."""
import json
import logging
import os
from pathlib import Path

from .types import ProviderConfig


_logger = logging.getLogger(__name__)


def _config_path() -> Path:
    from ..project.paths import config_dir
    return config_dir() / "llm-providers.json"


class ProviderRegistry:
    @staticmethod
    def load() -> dict[str, ProviderConfig]:
        path = _config_path()
        if not path.exists():
            return _default_providers()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return {
                k: ProviderConfig.from_dict(v)
                for k, v in data.get("providers", {}).items()
            }
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            _logger.warning("[registry] corrupt llm-providers.json (%s); using defaults", e)
            return _default_providers()

    @staticmethod
    def save(providers: dict[str, ProviderConfig]) -> None:
        path = _config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"version": 1, "providers": {k: v.to_dict() for k, v in providers.items()}}
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    @staticmethod
    def get(name: str) -> ProviderConfig:
        providers = ProviderRegistry.load()
        if name not in providers:
            raise KeyError(f"Provider not found: {name}")
        return providers[name]

    @staticmethod
    def upsert(config: ProviderConfig) -> None:
        providers = ProviderRegistry.load()
        providers[config.name] = config
        ProviderRegistry.save(providers)

    @staticmethod
    def remove(name: str) -> bool:
        providers = ProviderRegistry.load()
        if name not in providers:
            return False
        providers.pop(name)
        ProviderRegistry.save(providers)
        return True


def _default_providers() -> dict[str, ProviderConfig]:
    return {
        "openai": ProviderConfig(
            name="openai",
            type="openai",
            base_url="https://api.openai.com/v1",
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            default_chat_model="gpt-4o-mini",
            default_embedding_model="text-embedding-3-small",
        ),
        "anthropic": ProviderConfig(
            name="anthropic",
            type="anthropic",
            base_url="https://api.anthropic.com",
            api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            default_chat_model="claude-haiku-4-5",
        ),
        "ollama": ProviderConfig(
            name="ollama",
            type="ollama",
            base_url="http://127.0.0.1:11434",
            default_chat_model="qwen2.5:7b",
            default_embedding_model="nomic-embed-text",
        ),
    }
