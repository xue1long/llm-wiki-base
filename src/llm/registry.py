"""Global LLM provider registry — ~/.config/ruflo-kb/llm-providers.json."""
import json
import logging
import os
from pathlib import Path

from .types import ProviderConfig


class ProviderNotFoundError(KeyError):
    """Raised when a requested provider is not in the registry.

    Subclasses KeyError for backward compatibility with code that
    catches the old `KeyError` from ProviderRegistry.get(). Prefer
    `ProviderRegistry.require(name)` or `get_default()` for new code.
    """
    def __init__(self, name: str):
        super().__init__(name)
        self.name = name

    def __str__(self) -> str:
        return (
            f"Provider '{self.name}' not configured. "
            f"Run: ruflo-kb llm-providers add {self.name}"
        )


_logger = logging.getLogger(__name__)


def _config_path() -> Path:
    from ..project.paths import config_dir
    return config_dir() / "llm-providers.json"


class ProviderRegistry:
    # Tracks provider instances that hold unmanaged resources (httpx
    # AsyncClient, connection pools, etc.). aclose_all() closes them in
    # bulk — call from app shutdown (FastAPI lifespan) to avoid leaks.
    # Providers auto-register on __init__ and are removed by aclose_all().
    _loaded_providers: set = set()

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

    @staticmethod
    def require(name: str) -> ProviderConfig:
        """Get provider by name; raise ProviderNotFoundError (subclass of KeyError).

        Use this from CLI / service code that wants a friendly error
        message with a hint to run `llm-providers add`. Falls back to
        `KeyError` semantics via inheritance, so existing `except KeyError`
        blocks keep working.
        """
        try:
            return ProviderRegistry.get(name)
        except KeyError as e:
            raise ProviderNotFoundError(name) from e

    @staticmethod
    def get_default() -> ProviderConfig:
        """Return the 'default' provider, or the first one available.

        Resolution order:
          1. A provider named "default" in the registry
          2. The first provider (insertion order)

        Raises:
            ProviderNotFoundError: if no providers are configured.
        """
        providers = ProviderRegistry.load()
        if not providers:
            raise ProviderNotFoundError(
                "default (none configured; run: ruflo-kb llm-providers add)"
            )
        return providers.get("default") or next(iter(providers.values()))

    @staticmethod
    async def aclose_all() -> None:
        """Close all tracked provider instances that expose an async close().

        Idempotent: a second call is a no-op. Errors from individual close()
        calls are logged but do not prevent other providers from being closed.
        Call this from app shutdown (e.g. FastAPI lifespan) to release
        httpx.AsyncClient and similar resources.
        """
        # Snapshot to allow providers to mutate the set during iteration
        # (defensive — current close() implementations don't, but future ones might).
        snapshot = list(ProviderRegistry._loaded_providers)
        for provider in snapshot:
            close = getattr(provider, "close", None)
            if close is None:
                continue
            try:
                result = close()
                if hasattr(result, "__await__"):
                    await result
            except Exception as e:
                _logger.warning(
                    "[registry] aclose_all: failed to close %r: %s",
                    provider, e,
                )
        ProviderRegistry._loaded_providers.clear()


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
