"""LLM provider management subcommands."""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


def cmd_llm_providers_list(_args: argparse.Namespace) -> None:
    """List all configured LLM providers."""
    from ..llm.registry import ProviderRegistry

    providers = ProviderRegistry.load()
    if not providers:
        print("No providers configured.")
        return
    print(f"{'Name':<20} {'Type':<12} {'Base URL':<40} {'Default':<20}")
    print("-" * 95)
    for p in providers.values():
        print(f"{p.name:<20} {p.type:<12} {p.base_url:<40} {p.default_chat_model:<20}")


def cmd_llm_providers_show(args: argparse.Namespace) -> None:
    """Print full ProviderConfig JSON (api_key masked)."""
    from ..llm.registry import ProviderNotFoundError, ProviderRegistry

    try:
        p = ProviderRegistry.require(args.name)
    except ProviderNotFoundError as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)
    # redact=True: never print the plaintext API key (I-llm-12).
    print(json.dumps(p.to_dict(redact=True), indent=2, ensure_ascii=False))


def cmd_llm_providers_add(args: argparse.Namespace) -> None:
    """Add a new provider."""
    from ..llm.registry import ProviderRegistry
    from ..llm.types import ModelInfo, ProviderConfig

    if args.type == "ollama":
        base_url = args.base_url or "http://127.0.0.1:11434"
        # Auto-fetch installed models
        installed: list[str] = []
        try:
            import httpx
            resp = httpx.get(f"{base_url}/api/tags", timeout=5)
            resp.raise_for_status()
            installed = [m["name"] for m in resp.json().get("models", [])]
        except Exception as e:
            print(f"Could not reach Ollama at {base_url}: {e}", file=sys.stderr)
        print(f"Available models at {base_url}:")
        for i, m in enumerate(installed, 1):
            print(f"  {i}. {m}")
        chat_model = args.model or (installed[0] if installed else "")
        embed_model = installed[1] if len(installed) > 1 else (installed[0] if installed else "")
    else:
        base_url = ""
        chat_model = args.model or ""
        embed_model = ""

    config = ProviderConfig(
        name=args.name,
        type=args.type,
        base_url=base_url,
        api_key=args.api_key or "",
        models={chat_model: ModelInfo(name=chat_model)} if chat_model else {},
        default_chat_model=chat_model,
        default_embedding_model=embed_model,
    )
    ProviderRegistry.upsert(config)
    print(f"Added provider '{args.name}' (type={args.type}, default={chat_model})")


def cmd_llm_providers_remove(args: argparse.Namespace) -> None:
    """Remove a provider from registry."""
    from ..llm.registry import ProviderRegistry

    if not ProviderRegistry.remove(args.name):
        print(f"Provider not found: {args.name}", file=sys.stderr)
        sys.exit(2)
    print(f"Removed provider '{args.name}'")


def cmd_llm_providers_test(args: argparse.Namespace) -> None:
    """Ping a provider; show installed models + missing config warnings."""
    from ..llm.provider_factory import _create_from_config
    from ..llm.registry import ProviderNotFoundError, ProviderRegistry

    try:
        config = ProviderRegistry.require(args.name)
    except ProviderNotFoundError as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)

    async def _run():
        provider = _create_from_config(config)
        try:
            return provider, await provider.health_check()
        finally:
            await provider.close()

    try:
        provider, health = asyncio.run(_run())
    except Exception as e:
        print(f"✗ {args.name}: error creating provider ({e})", file=sys.stderr)
        sys.exit(2)

    if not health.get("ok"):
        print(f"✗ {args.name}: unreachable ({health.get('detail')})")
        sys.exit(1)
    version = health.get("version")
    version_str = f" (version {version})" if version else ""
    print(f"✓ {args.name}: reachable ({health.get('detail')}){version_str}")


def cmd_llm_providers_set_default(args: argparse.Namespace) -> None:
    """Persist the default provider name for all callers.

    Two persistence targets:

    1. ``ProviderRegistry.set_default(name)`` — writes the explicit
       default into the JSON registry so that ``get_default()`` resolves
       it immediately (slot tier 2: ``get_default_name()``). This covers
       all current-process callers — no env var or shell restart needed.

    2. ``~/.config/ruflo-kb/env`` — writes ``RUFLO_LLM_PROVIDER=<name>``
       so future shell sessions pick up the default via env var (slot
       tier 1). The user should ``source`` this file in their shell rc.

    These two mechanisms are complementary, not redundant. The env file
    survives registry file deletion / corruption; the JSON persistence
    works for callers that don't source the env file.
    """
    from ..llm.registry import ProviderRegistry

    ProviderRegistry.get(args.name)  # Validate existence; raises KeyError if missing

    # Persist to JSON registry — takes effect immediately.
    ProviderRegistry.set_default(args.name)

    # Persist to shell env file — takes effect in future sessions.
    config_dir = Path(os.path.expanduser("~/.config/ruflo-kb"))
    config_dir.mkdir(parents=True, exist_ok=True)
    env_file = config_dir / "env"
    existing = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    lines = [l for l in existing.split("\n") if not l.startswith("RUFLO_LLM_PROVIDER=")]
    lines.append(f"RUFLO_LLM_PROVIDER={args.name}")
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Default provider set to: {args.name}")
    print(f"Add to shell rc: source {env_file}")
