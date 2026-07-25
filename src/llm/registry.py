"""Global LLM provider registry — ~/.config/ruflo-kb/llm-providers.json."""
import json
import logging
import os
from dataclasses import replace
from pathlib import Path

from ..lib.write_hooks import safe_write
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
    def save(providers: dict[str, ProviderConfig], default_name: Optional[str] = None) -> None:
        """Persist providers + (optional) explicit default name.

        When `default_name` is None, the file's "default" field is set to
        null (preserves the existing "no explicit default" semantic).
        Migration: older files have no "default" key at all; load() returns
        None for the default-name slot in that case, and get_default()
        falls through to the legacy 4-tier resolution.
        """
        path = _config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Keep env-sourced entries discoverable across save/reload, but strip
        # their credentials before persistence. The provider factory resolves
        # a blank key from os.environ only when the provider is instantiated.
        persisted = {
            k: replace(v, api_key="") if v.sourced_from_env else v
            for k, v in providers.items()
        }
        data = {
            "version": 1,
            "providers": {k: v.to_dict() for k, v in persisted.items()},
            "default": default_name,  # NEW: explicit default slot (Task 4 P2)
        }
        # Plan 20 binding constraint: route through safe_write so the
        # write is atomic (no torn file on crash mid-write) AND
        # AtomicContext-aware (a future caller inside an AtomicContext
        # will defer the write to the commit point instead of
        # short-circuiting the transactional boundary).
        safe_write(
            path,
            json.dumps(data, indent=2, ensure_ascii=False),
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
    def list() -> dict[str, ProviderConfig]:
        """Alias for load() — matches the spec's "list" verb.

        Kept for ergonomics; load() remains the canonical name.
        """
        return ProviderRegistry.load()

    @staticmethod
    def get_default_name() -> Optional[str]:
        """Return the explicit default provider name (slot tier 2), or None.

        Reads the registry file directly (not via load()) to avoid
        double-parsing. Returns None if the file has no "default" key
        (legacy files predate this feature).
        """
        path = _config_path()
        if not path.exists():
            return None
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None  # corrupt — fall through to legacy tiers
        return data.get("default")

    @staticmethod
    def set_default(name: str) -> None:
        """Set the explicit default provider (slot tier 2 in get_default).

        Persistence: rewrites the registry file with the new
        ``"default"`` field. Other providers are preserved.

        Raises:
            ProviderNotFoundError: if no provider with the given name
                is currently registered.
        """
        providers = ProviderRegistry.load()
        if name not in providers:
            raise ProviderNotFoundError(name)
        ProviderRegistry.save(providers, default_name=name)

    @staticmethod
    def upsert(config: ProviderConfig) -> None:
        providers = ProviderRegistry.load()
        providers[config.name] = config
        ProviderRegistry.save(providers)

    @staticmethod
    def remove(name: str) -> bool:
        """Remove a provider by name and persist the post-removal state.

        Returns:
            bool: ``True`` if the provider was present and removed;
                  ``False`` if it was already absent (no-op).

        Note: `remove()` persists across saves — env-sourced providers do NOT
        re-derive on subsequent `load()` while the file exists. To re-enable,
        delete the registry file or re-add explicitly via `upsert()`.
        """
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
          2. Provider explicitly named ``"default"`` in the registry
             (back-compat alias — kept because some installs saved their
             preferred provider under the literal name "default").
          3. First persisted (non-env-sourced) provider in insertion order.
             This honours ``llm-providers add ... --default`` — the user
             added this provider explicitly, so it should win over the
             env-sourced OpenAI/Anthropic entries that auto-register from
             environment variables.
          4. First provider in insertion order (legacy fallback when no
             persisted entry exists).

        Raises:
            ProviderNotFoundError: when no providers exist.
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

        # #2: explicit default set via ProviderRegistry.set_default()
        # (NEW in Task 4 P2 — sits between env override and legacy
        # named-default so env vars still win for testing/overriding)
        explicit = ProviderRegistry.get_default_name()
        if explicit is not None:
            if explicit not in providers:
                raise ProviderNotFoundError(
                    f"explicit default {explicit!r} is set but not in the "
                    f"registry (was it removed?). Available: "
                    f"{sorted(providers.keys())}"
                )
            return providers[explicit]

        if not providers:
            raise ProviderNotFoundError(
                "default (none configured; run: ruflo-kb llm-providers add)"
            )

        # #3: legacy named-default
        named = providers.get("default")
        if named is not None:
            return named

        # #3: prefer explicitly-added (non-env) providers over env-sourced
        # ones. The env-sourced entries are auto-registered from env vars
        # (OPENAI_API_KEY etc.) and should never silently win over a user
        # who ran ``llm-providers add ollama ...``.
        #
        # ``sourced_from_env`` is not part of the serialised schema (it's a
        # runtime-only hint that the audit cleanup explicitly excluded from
        # ``to_dict``), so after a save→load roundtrip every provider looks
        # "persisted". We recover the distinction by comparing the loaded
        # set against ``_default_providers()``: a provider whose config
        # matches the env-derived default exactly is treated as env-sourced.
        defaults = _default_providers()
        env_sourced_names = {
            name for name, default_cfg in defaults.items()
            if name in providers
            and not providers[name].api_key
            and providers[name].base_url == default_cfg.base_url
            and providers[name].default_chat_model == default_cfg.default_chat_model
        }
        persisted = [
            (name, cfg) for name, cfg in providers.items()
            if name not in env_sourced_names
        ]
        if persisted:
            return persisted[0][1]

        # #4: legacy fallback — first in insertion order.
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
            # user add. Registry.save() persists this entry with a blank key;
            # the factory resolves the credential from env when used.
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
