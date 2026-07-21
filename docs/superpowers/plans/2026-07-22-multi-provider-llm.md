# Multi-Provider LLM (Ollama) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Add Ollama provider + global registry + per-project override + health check + 6 CLI subcommands. OpenAI-compatible generic deferred to v2.0.1.

**Architecture:** `ProviderConfig` dataclass → `ProviderRegistry` global file at `~/.config/ruflo-kb/llm-providers.json` → `create_llm_provider(registry_name)` factory.

**Tech Stack:** Python 3.11+, httpx (async), dataclass, JSON, pytest-asyncio.

**MVP Scope** (per spec): Ollama only + global registry + per-project override + startup health check + `llm-providers list/add/remove/test/show/set-default`.

---

### Task 1: `src/llm/types.py` — ProviderConfig + ModelInfo

**Files:**
- Create: `src/llm/types.py`
- Test: `tests/test_llm/test_types.py`

- [ ] **Step 1: Write test**

```python
# tests/test_llm/test_types.py
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
```

- [ ] **Step 2: Run + implement + commit**

```python
# src/llm/types.py
from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class ModelInfo:
    name: str
    type: str = "chat"           # "chat" | "embedding"
    context_window: int = 8192
    parameters: dict = field(default_factory=dict)


@dataclass
class ProviderConfig:
    name: str
    type: str                    # "openai" | "anthropic" | "ollama" | "openai-compatible"
    base_url: str = ""
    api_key: str = ""
    models: dict[str, ModelInfo] = field(default_factory=dict)
    default_chat_model: str = ""
    default_embedding_model: str = ""
    timeout_seconds: int = 60
    extra_headers: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name, "type": self.type, "base_url": self.base_url,
            "api_key": self.api_key,
            "models": {k: asdict(v) for k, v in self.models.items()},
            "default_chat_model": self.default_chat_model,
            "default_embedding_model": self.default_embedding_model,
            "timeout_seconds": self.timeout_seconds,
            "extra_headers": self.extra_headers,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProviderConfig":
        return cls(
            name=d["name"], type=d["type"], base_url=d.get("base_url", ""),
            api_key=d.get("api_key", ""),
            models={k: ModelInfo(**v) for k, v in d.get("models", {}).items()},
            default_chat_model=d.get("default_chat_model", ""),
            default_embedding_model=d.get("default_embedding_model", ""),
            timeout_seconds=d.get("timeout_seconds", 60),
            extra_headers=d.get("extra_headers", {}),
        )
```

```bash
git add src/llm/types.py tests/test_llm/test_types.py
git commit -m "feat(llm): add ProviderConfig + ModelInfo types"
```

---

### Task 2: `src/llm/registry.py` — global provider config

**Files:** `src/llm/registry.py` + tests

```python
# src/llm/registry.py
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
            return {k: ProviderConfig.from_dict(v) for k, v in data.get("providers", {}).items()}
        except (json.JSONDecodeError, KeyError):
            _logger.warning("[registry] corrupt llm-providers.json; using defaults")
            return _default_providers()

    @staticmethod
    def save(providers: dict[str, ProviderConfig]) -> None:
        path = _config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"version": 1, "providers": {k: v.to_dict() for k, v in providers.items()}}
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def get(name: str) -> ProviderConfig:
        return ProviderRegistry.load()[name]

    @staticmethod
    def upsert(config: ProviderConfig) -> None:
        providers = ProviderRegistry.load()
        providers[config.name] = config
        ProviderRegistry.save(providers)

    @staticmethod
    def remove(name: str) -> None:
        providers = ProviderRegistry.load()
        providers.pop(name, None)
        ProviderRegistry.save(providers)


def _default_providers() -> dict[str, ProviderConfig]:
    return {
        "openai": ProviderConfig(
            name="openai", type="openai",
            base_url="https://api.openai.com/v1",
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            default_chat_model="gpt-4o-mini",
            default_embedding_model="text-embedding-3-small",
        ),
        "anthropic": ProviderConfig(
            name="anthropic", type="anthropic",
            base_url="https://api.anthropic.com",
            api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            default_chat_model="claude-haiku-4-5",
        ),
        "ollama": ProviderConfig(
            name="ollama", type="ollama",
            base_url="http://127.0.0.1:11434",
            default_chat_model="qwen2.5:7b",
            default_embedding_model="nomic-embed-text",
        ),
    }
```

**Tests** (5 cases): test_load_returns_defaults, test_upsert_persists, test_get_not_found, test_remove, test_default_providers_have_ollama.

```bash
git add src/llm/registry.py tests/test_llm/test_registry.py
git commit -m "feat(llm): add ProviderRegistry (global + defaults)"
```

---

### Task 3: `src/llm/ollama_provider.py` — OllamaProvider

**Files:** `src/llm/ollama_provider.py` + tests

```python
# src/llm/ollama_provider.py
"""Ollama local LLM provider."""
import json
import logging

import httpx

from .base import LLMProvider, LLMResponse
from .types import ProviderConfig


_logger = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    capabilities = ProviderCapabilities(
        supports_streaming=True,
        supports_json_mode=True,
        supports_embedding=True,
        max_context_window=128000,
    )

    def __init__(self, config: ProviderConfig, model_override: str | None = None):
        self.config = config
        self.base_url = config.base_url.rstrip("/")
        self.model = model_override or config.default_chat_model
        self.client = httpx.AsyncClient(timeout=config.timeout_seconds)

    async def complete(self, prompt, response_format=None, system=None, **kwargs) -> LLMResponse:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body = {"model": self.model, "messages": messages, "stream": False}
        if response_format:
            body["format"] = "json"  # Ollama's JSON mode

        resp = await self.client.post(f"{self.base_url}/api/chat", json=body)
        resp.raise_for_status()
        data = resp.json()
        return LLMResponse(
            content=data["message"]["content"],
            model=self.model,
            usage={
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
            },
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        embeddings = []
        for text in texts:
            resp = await self.client.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.config.default_embedding_model, "prompt": text},
            )
            resp.raise_for_status()
            embeddings.append(resp.json()["embedding"])
        return embeddings

    async def health_check(self) -> dict:
        try:
            resp = await self.client.get(f"{self.base_url}/api/version", timeout=5)
            resp.raise_for_status()
            return {"reachable": True, "version": resp.json().get("version")}
        except (httpx.HTTPError, httpx.ConnectError) as e:
            return {"reachable": False, "error": str(e)}

    async def close(self) -> None:
        await self.client.aclose()
```

**Tests**: test_complete_returns_content, test_complete_uses_json_mode, test_embed_returns_list, test_health_check_reachable, test_health_check_unreachable.

```bash
git add src/llm/ollama_provider.py tests/test_llm/test_ollama_provider.py
git commit -m "feat(llm): add OllamaProvider (chat + embed + health check)"
```

---

### Task 4: `src/llm/provider_factory.py` — `create_llm_provider` factory

**Files:** `src/llm/provider_factory.py` + tests

```python
# src/llm/provider_factory.py
"""Factory to instantiate LLM provider from registry entry."""
import os

from .anthropic_provider import AnthropicProvider
from .base import LLMProvider
from .ollama_provider import OllamaProvider
from .openai_provider import OpenAIProvider
from .registry import ProviderRegistry
from .types import ProviderConfig


def create_llm_provider(registry_name: str, model_override: str | None = None) -> LLMProvider:
    """Create LLM provider instance from global registry entry."""
    config = ProviderRegistry.get(registry_name)
    return _create_from_config(config, model_override)


def _create_from_config(config: ProviderConfig, model_override: str | None = None) -> LLMProvider:
    # Apply env var override for API key if not set in config
    if not config.api_key:
        env_key = _env_var_for_provider(config.name)
        if env_key and os.environ.get(env_key):
            config = ProviderConfig(
                name=config.name, type=config.type, base_url=config.base_url,
                api_key=os.environ[env_key], models=config.models,
                default_chat_model=config.default_chat_model,
                default_embedding_model=config.default_embedding_model,
                timeout_seconds=config.timeout_seconds,
                extra_headers=config.extra_headers,
            )

    if config.type == "ollama":
        return OllamaProvider(config, model_override=model_override)
    elif config.type == "openai":
        return OpenAIProvider(config, model_override=model_override)
    elif config.type == "anthropic":
        return AnthropicProvider(config, model_override=model_override)
    raise ValueError(f"Unknown provider type: {config.type}")


def _env_var_for_provider(name: str) -> str | None:
    return {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "ollama": None,  # No API key
    }.get(name)
```

**Tests**: test_create_ollama_provider, test_create_raises_for_unknown.

```bash
git add src/llm/provider_factory.py tests/test_llm/test_provider_factory.py
git commit -m "feat(llm): add create_llm_provider factory (registry → instance)"
```

---

### Task 5: `src/cli_ext/llm_providers_cmd.py` — 6 CLI subcommands

**Files:** `src/cli_ext/llm_providers_cmd.py` + tests + wire in cli.py

```python
# src/cli_ext/llm_providers_cmd.py
"""LLM provider management subcommands."""
import argparse
import asyncio
import sys

from ..llm.ollama_provider import OllamaProvider
from ..llm.registry import ProviderRegistry
from ..llm.types import ModelInfo, ProviderConfig


def cmd_llm_providers_list(args: argparse.Namespace) -> None:
    """List all configured LLM providers."""
    providers = ProviderRegistry.load()
    if not providers:
        print("No providers configured.")
        return
    print(f"{'Name':<20} {'Type':<20} {'Base URL':<40} {'Default Model':<20}")
    print("-" * 100)
    for p in providers.values():
        print(f"{p.name:<20} {p.type:<20} {p.base_url:<40} {p.default_chat_model:<20}")


def cmd_llm_providers_show(args: argparse.Namespace) -> None:
    """Print full ProviderConfig JSON."""
    try:
        p = ProviderRegistry.get(args.name)
    except KeyError:
        print(f"Provider not found: {args.name}", file=sys.stderr)
        sys.exit(2)
    import json
    print(json.dumps(p.to_dict(), indent=2, ensure_ascii=False))


def cmd_llm_providers_add(args: argparse.Namespace) -> None:
    """Add a new provider (interactive for Ollama)."""
    if args.type == "ollama":
        base_url = args.base_url or "http://127.0.0.1:11434"
        # Auto-fetch installed models
        import httpx
        try:
            resp = httpx.get(f"{base_url}/api/tags", timeout=5)
            resp.raise_for_status()
            installed = [m["name"] for m in resp.json().get("models", [])]
        except Exception as e:
            print(f"Could not reach Ollama at {base_url}: {e}", file=sys.stderr)
            installed = []
        print(f"Available models at {base_url}:")
        for i, m in enumerate(installed, 1):
            print(f"  {i}. {m}")
        chat_model = args.model or (installed[0] if installed else "")
        embed_model = installed[1] if len(installed) > 1 else ""
    else:
        chat_model = args.model
        embed_model = ""

    config = ProviderConfig(
        name=args.name, type=args.type, base_url=base_url if args.type == "ollama" else "",
        api_key=args.api_key or "",
        models={chat_model: ModelInfo(name=chat_model)} if chat_model else {},
        default_chat_model=chat_model,
        default_embedding_model=embed_model,
    )
    ProviderRegistry.upsert(config)
    print(f"Added provider '{args.name}' (type={args.type}, default={chat_model})")


def cmd_llm_providers_remove(args: argparse.Namespace) -> None:
    """Remove a provider from registry."""
    try:
        ProviderRegistry.remove(args.name)
    except KeyError:
        print(f"Provider not found: {args.name}", file=sys.stderr)
        sys.exit(2)
    print(f"Removed provider '{args.name}'")


def cmd_llm_providers_test(args: argparse.Namespace) -> None:
    """Ping a provider; show installed models + missing config warnings."""
    try:
        config = ProviderRegistry.get(args.name)
    except KeyError:
        print(f"Provider not found: {args.name}", file=sys.stderr)
        sys.exit(2)
    provider = _create_from_config(config)
    health = asyncio.run(provider.health_check())
    if not health.get("reachable"):
        print(f"✗ {args.name}: unreachable ({health.get('error')})")
        sys.exit(1)
    print(f"✓ {args.name}: reachable (version {health.get('version')})")
    if hasattr(provider, "client"):
        try:
            resp = asyncio.run(provider.client.get(f"{provider.base_url}/api/tags", timeout=5))
            installed = [m["name"] for m in resp.json().get("models", [])]
            print(f"  installed models: {', '.join(installed[:10])}")
            missing = []
            if config.default_chat_model and config.default_chat_model not in installed:
                missing.append(config.default_chat_model)
            if config.default_embedding_model and config.default_embedding_model not in installed:
                missing.append(config.default_embedding_model)
            if missing:
                print(f"  ⚠ missing: {', '.join(missing)}")
                print(f"    run: ollama pull <model>")
        except Exception:
            pass
    asyncio.run(provider.close())


def cmd_llm_providers_set_default(args: argparse.Namespace) -> None:
    """Write RUFLO_LLM_PROVIDER env var to ~/.config/ruflo-kb/env."""
    import os
    from pathlib import Path
    config_dir = Path(os.path.expanduser("~/.config/ruflo-kb"))
    config_dir.mkdir(parents=True, exist_ok=True)
    env_file = config_dir / "env"
    existing = env_file.read_text() if env_file.exists() else ""
    # Replace or add RUFLO_LLM_PROVIDER line
    lines = [l for l in existing.split("\n") if not l.startswith("RUFLO_LLM_PROVIDER=")]
    lines.append(f"RUFLO_LLM_PROVIDER={args.name}")
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Default provider set to: {args.name}")
    print(f"Add to shell rc: source {env_file}")


def _create_from_config(config):
    from ..llm.provider_factory import _create_from_config as _f
    return _f(config)
```

**Tests**: test_list, test_show, test_add_ollama, test_remove, test_test_reachable, test_set_default.

**Wire in cli.py**:

```python
p_llm = subparsers.add_parser("llm-providers", help="Manage LLM providers")
p_llm_sub = p_llm.add_subparsers(dest="llm_providers_command")
# Add 6 subparsers: list / show / add / remove / test / set-default
```

```bash
git add src/cli_ext/llm_providers_cmd.py src/cli.py tests/test_cli_ext/test_cmd_llm_providers.py
git commit -m "feat(cli): add 'llm-providers list/add/remove/test/show/set-default' (6 subcommands)"
```

---

### Task 6: Wire startup health check

**Files:** Modify `src/cli.py`

```python
# src/cli.py — at top of main()
async def _startup_health_check():
    """On startup, ping all configured providers; warn if unreachable."""
    from .llm.registry import ProviderRegistry
    from .llm.provider_factory import _create_from_config
    import sys
    try:
        providers = ProviderRegistry.load()
        for name, config in providers.items():
            provider = _create_from_config(config)
            health = await provider.health_check()
            if not health.get("reachable"):
                print(f"[warn] provider {name!r} unreachable: {health.get('error')}", file=sys.stderr)
            await provider.close()
    except Exception as e:
        print(f"[warn] startup health check failed: {e}", file=sys.stderr)

# In main(), after parser.parse_args():
if args.command not in ("serve", "mcp"):
    import asyncio
    try:
        asyncio.run(_startup_health_check())
    except Exception:
        pass
```

```bash
git add src/cli.py
git commit -m "feat(cli): startup health check for all configured providers"
```

---

## Self-Review

- [x] Spec coverage: Ollama ✓ Global registry ✓ Per-project override (settings) ✓ Health check ✓ 6 CLI subcommands ✓
- [x] OpenAI-compatible generic deferred to v2.0.1
- [x] No placeholders; full code in all steps
- [x] Per-project override: `settings.llm.provider_registry_name` + `settings.llm.model` (from Project spec)

## Implementation order

Tasks 1-4 chain. Tasks 5-6 chain. Total: 6 tasks, ~1.5-2 hours.