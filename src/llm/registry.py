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


class RegistryCorruptError(Exception):
    """Raised when the registry JSON file exists but is unparseable.

    Previously ``ProviderRegistry.load()`` would silently swallow parse
    errors and fall back to defaults, hiding config corruption from the
    user. We now raise so a CLI invocation can surface the mistake.
    """


_logger = logging.getLogger(__name__)


def _config_path() -> Path:
    from ..project.paths import config_dir
    return config_dir() / "llm-providers.json"


# Env var that overrides default-resolution order (highest precedence)
RUFLO_LLM_PROVIDER_ENV = "RUFLO_LLM_PROVIDER"


class ProviderRegistry:
    # Tracks provider instances that hold unmanaged resources (httpx
    # AsyncClient, connection pools, etc.). aclose_all() closes them in
    # bulk — call from app shutdown (FastAPI lifespan) to avoid leaks.
    # Providers auto-register on __init__ and are removed by aclose_all()
    # ONLY after a successful close(). Failed-close entries are kept so
    # the operator can retry without losing the ownership reference.
    _loaded_providers: set = set()

    @staticmethod
    def load() -> dict[str, ProviderConfig]:
        path = _config_path()
        if not path.exists():
            return _default_providers()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return _default_providers()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            # File exists but is invalid JSON — surface the corruption
            # instead of silently masking the user error with defaults.
            raise RegistryCorruptError(
                f"Failed to parse {path}: {e}. Fix or delete the file."
            ) from e
        try:
            return {
                k: ProviderConfig.from_dict(v)
                for k, v in data.get("providers", {}).items()
            }
        except (KeyError, TypeError) as e:
            # Structure error (missing 'name'/'type') is also corruption.
            raise RegistryCorruptError(
                f"Invalid provider entry in {path}: {e}"
            ) from e

    @staticmethod
    def save(providers: dict[str, ProviderConfig]) -> None:
        path = _config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Skip env-sourced entries (sourced_from_env=True) — env vars
        # are the single source of truth for those api_keys; persisting
        # them would leak credentials onto disk on first save. User
        # adds via `llm-providers add` set sourced_from_env=False and
        # ARE persisted.
        persisted = {
            k: v for k, v in providers.items() if not v.sourced_from_env
        }
        data = {
            "version": 1,
            "providers": {k: v.to_dict() for k, v in persisted.items()},
        }
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        # Restrict permissions on the registry file — it contains plaintext
        # API keys. On POSIX this enforces 0o600 (owner read/write only);
        # on Windows chmod is a best-effort no-op for most permission bits,
        # but we still try so the operator gets the strongest guarantee
        # the platform supports. Swallow OSError/NotImplementedError so
        # we don't fail save() on systems that don't support chmod.
        try:
            os.chmod(path, 0o600)
        except (OSError, NotImplementedError, AttributeError):
            pass

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
        """Return the resolved default provider.

        Resolution order (highest precedence first):
          1. ``$RUFLO_LLM_PROVIDER`` env var (if non-empty AND matches a
             registered provider name — otherwise we raise).
          2. Provider explicitly named ``"default"`` in the registry.
          3. First provider in insertion order.

        Raises:
            ProviderNotFoundError: when #2/#3 produce no provider.
            ValueError: when the env var names a provider not present.
            RegistryCorruptError: propagated from :meth:`load`.
        """
        providers = ProviderRegistry.load()

        env_name = os.environ.get(RUFLO_LLM_PROVIDER_ENV, "").strip()
        if env_name:
            if env_name not in providers:
                raise ValueError(
                    f"{RUFLO_LLM_PROVIDER_ENV}={env_name} but no such "
                    f"provider is registered. Available: "
                    f"{sorted(providers.keys())}"
                )
            return providers[env_name]

        if not providers:
            raise ProviderNotFoundError(
                "default (none configured; run: ruflo-kb llm-providers add)"
            )

        named = providers.get("default")
        if named is not None:
            return named
        return next(iter(providers.values()))

    @staticmethod
    async def aclose_all() -> None:
        """Close all tracked provider instances that expose an async close().

        Idempotent: a second call after a successful full sweep is a no-op.
        Errors from individual close() calls are logged but do not prevent
        other providers from being closed. Providers whose close() raised
        are KEPT in :attr:`_loaded_providers` (we don't lose ownership of
        the resource reference — the caller can retry or explicitly drop it).

        Call this from app shutdown (e.g. FastAPI lifespan) to release
        httpx.AsyncClient and similar resources.
        """
        snapshot = list(ProviderRegistry._loaded_providers)
        for provider in snapshot:
            close = getattr(provider, "close", None)
            if close is None:
                # No close() — nothing to release; safe to drop the tracker.
                ProviderRegistry._loaded_providers.discard(provider)
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
                # Keep the reference so the caller can retry.
                continue
            # Only remove on success.
            ProviderRegistry._loaded_providers.discard(provider)


def _default_providers() -> dict[str, ProviderConfig]:
    return {
        "openai": ProviderConfig(
            name="openai",
            type="openai",
            base_url="https://api.openai.com/v1",
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            default_chat_model="gpt-4o-mini",
            default_embedding_model="text-embedding-3-small",
            # Env-sourced: api_key came from os.environ, not an explicit
            # user add. Registry.save() will skip persistence — env vars
            # remain the source of truth.
            sourced_from_env=True,
        ),
        "anthropic": ProviderConfig(
            name="anthropic",
            type="anthropic",
            # MUST include /v1 path; the Anthropic SDK is mounted at /v1/messages.
            base_url="https://api.anthropic.com/v1",
            api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            default_chat_model="claude-haiku-4-5",
            sourced_from_env=True,
        ),
        "ollama": ProviderConfig(
            name="ollama",
            type="ollama",
            base_url="http://127.0.0.1:11434",
            default_chat_model="qwen2.5:7b",
            default_embedding_model="nomic-embed-text",
            # Ollama has no env-sourced key — persist normally.
        ),
    }
