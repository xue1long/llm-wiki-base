# Multi-Provider LLM Design Spec

**Date:** 2026-07-21
**Status:** Approved (pending user sign-off)
**Target codebase:** ruflo-kb (Python 3.11+, master @ 5492827, post-chat-agent spec)
**Inspired by:** llm_wiki-main `src/lib/llm-providers.ts` (5 HTTP providers + 2 subprocess)

## Goal

Extend ruflo-kb's LLM provider layer beyond OpenAI and Anthropic to support local and self-hosted models, unlocking zero-cost and privacy-first deployments.

Two new providers land in this spec:

1. **Ollama** — local LLM runtime (llama3.1, qwen2.5, mistral, etc.); zero-cost, fully offline.
2. **OpenAI-compatible generic** — LM Studio, vLLM, LocalAI, llama.cpp server, or any HTTP service implementing `/v1/chat/completions` and `/v1/embeddings`.

Both providers implement the full `LLMProvider` interface (`complete` + `complete_stream` + `embed`). A `NonStreamingToStreamingAdapter` future-proofs the contract: any future provider without native streaming can still satisfy the chat-agent runtime by being wrapped.

Provider configurations live in a **global registry** at `~/.config/ruflo-kb/llm-providers.json` (per-user, cross-project). Each project's `.llm-wiki/settings.json` can override `provider_registry_name` and `model` per-project. CLI startup runs health checks to surface unreachable Ollama servers or missing model pulls.

## Non-goals

- No Google Gemini / Anthropic Bedrock / Azure OpenAI in this spec (deferred; OpenAI/Anthropic already supported).
- No subprocess CLI providers (Claude Code CLI, Codex CLI) — different transport (stdin/stdout), deferred.
- No vision / image input — no use case without image extraction (deferred).
- No provider-level rate limiting / cost attribution (chat-agent cost cap already covers cost; provider-specific rate limit deferred).
- No automatic model selection / routing (user picks model explicitly).
- No model quantization / LoRA management (Ollama handles internally).
- No fine-tuning interface.

## Architecture

### Provider layer

```
┌──────────────────────────────────────────────────────────────┐
│ Global config (~/.config/ruflo-kb/llm-providers.json)        │
│ {                                                            │
│   "providers": {                                             │
│     "ollama": {                                              │
│       "baseUrl": "http://127.0.0.1:11434",                   │
│       "models": {                                            │
│         "llama3.1:8b":       {"contextWindow": 128000},     │
│         "qwen2.5:7b":        {"contextWindow": 32000},      │
│         "nomic-embed-text":  {"type": "embedding"}          │
│       },                                                     │
│       "defaultChatModel": "qwen2.5:7b",                     │
│       "defaultEmbeddingModel": "nomic-embed-text"           │
│     },                                                       │
│     "openai-compatible": {                                  │
│       "baseUrl": "http://127.0.0.1:1234/v1",                │
│       "apiKey": "lm-studio",                                │
│       "defaultChatModel": "qwen2.5-7b-instruct",            │
│       "defaultEmbeddingModel": "text-embedding-nomic-embed" │
│     }                                                        │
│   }                                                          │
│ }                                                            │
└──────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────┐
│ Per-project override (<project>/.llm-wiki/settings.json)      │
│ {                                                            │
│   "llm": {                                                   │
│     "providerRegistryName": "ollama",                        │
│     "model": "llama3.1:8b"                                  │
│   },                                                         │
│   "embedding": {                                             │
│     "providerRegistryName": "ollama",                        │
│     "model": "nomic-embed-text"                              │
│   }                                                          │
│ }                                                            │
└──────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────┐
│ Provider Registry (ProviderRegistry)                        │
│ load_global() / upsert() / remove() / get() / list()        │
└──────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────┐
│ Provider instances                                          │
│ ┌────────────────┐ ┌────────────────┐ ┌────────────────┐       │
│ │ OpenAI         │ │ Anthropic      │ │ Ollama ⭐     │       │
│ │ (existing)     │ │ (existing)     │ │ NEW           │       │
│ └────────────────┘ └────────────────┘ └────────────────┘       │
│ ┌────────────────┐ ┌────────────────┐                        │
│ │ OpenAI-Compatible│ │ Streaming      │                        │
│ │ ⭐ NEW          │ │ Adapter ⭐      │                        │
│ │ (LM Studio...)  │ │ (fallback)     │                        │
│ └────────────────┘ └────────────────┘                        │
└──────────────────────────────────────────────────────────────┘
                                │
                                ▼
              LLMProvider interface (existing):
              - complete(prompt, response_format, ...) -> dict
              - complete_stream(prompt, response_format, ...) -> AsyncIterator[StreamChunk]
              - embed(texts) -> list[list[float]]
```

### Resolution chain

```
ProjectContext (settings.llm)            Global Registry (llm-providers.json)
        │                                           │
        ▼                                           ▼
settings.llm.providerRegistryName   →   ProviderRegistry.get(name)   →   ProviderConfig
settings.llm.model (optional)        →   or provider_config.defaultChatModel
        │                                           │
        └──────────────────┬────────────────────────┘
                           ▼
              create_llm_provider(config, model)
                           │
                           ▼
                  OpenAIProvider / AnthropicProvider / OllamaProvider / OpenAICompatibleProvider
```

## Components

### New modules

```
src/llm/
├── base.py                (extended with ProviderCapabilities)
├── ollama_provider.py     ⭐ NEW
├── openai_compatible_provider.py  ⭐ NEW
├── streaming_adapter.py    ⭐ NEW (fallback wrapper)
├── registry.py             ⭐ NEW (global config + resolution)
├── health.py               ⭐ NEW (Ollama / OpenAI-compat health check)
└── provider_factory.py     (extended to dispatch to new providers)

src/cli_ext/
└── llm_providers_cmd.py    ⭐ NEW

tests/test_llm/
├── test_ollama_provider.py
├── test_openai_compatible_provider.py
├── test_streaming_adapter.py
├── test_registry.py
├── test_health.py
└── test_provider_factory.py

tests/test_cli_ext/
└── test_cmd_llm_providers.py
```

### Modified modules

| Path | Change |
|---|---|
| `src/llm/base.py` | Add `ProviderCapabilities`, `StreamChunk`, `LLMResponse` dataclasses |
| `src/llm/provider_factory.py` | `create_llm_provider(registry_name, model_override=None)` dispatches to all 4 providers |
| `src/project/settings.py` | `LLMSettings` and `EmbeddingSettings` add `provider_registry_name` field |
| `src/project/context.py` | `ProjectContext` adds `provider_registry` (loaded from global on init) |
| `src/cli.py` | `configure --provider ollama` adds `--base-url` flag |
| `pyproject.toml` | No new dependencies |

## Data structures

```python
# src/llm/base.py (additions)
@dataclass
class StreamChunk:
    delta: str                               # incremental text
    usage: dict | None = None                # {"prompt_tokens": ..., "completion_tokens": ...}
    finish_reason: str | None = None

@dataclass
class ProviderCapabilities:
    supports_streaming: bool = True
    supports_json_mode: bool = True          # response_format=json_schema or tool use
    supports_embedding: bool = True
    supports_vision: bool = False
    max_context_window: int = 8192

# Extended LLMProvider interface (existing, no breaking change)
class LLMProvider(Protocol):
    capabilities: ProviderCapabilities
    
    async def complete(self, prompt, response_format=None, system=None, max_retries=1) -> dict: ...
    async def complete_stream(self, prompt, response_format=None, system=None, max_retries=1) -> AsyncIterator[StreamChunk]: ...
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
    async def health_check(self) -> dict: ...
    async def close(self) -> None: ...
```

```python
# src/llm/registry.py
@dataclass
class ModelInfo:
    name: str                                # "llama3.1:8b"
    type: Literal["chat", "embedding"]
    context_window: int = 4096
    parameters: dict = field(default_factory=dict)

@dataclass
class ProviderConfig:
    name: str                                # "ollama" | "openai-compatible"
    type: Literal["ollama", "openai-compatible", "openai", "anthropic"]
    base_url: str                            # "http://127.0.0.1:11434"
    api_key: str | None = None
    models: dict[str, ModelInfo]
    default_chat_model: str
    default_embedding_model: str | None = None
    extra_headers: dict[str, str] = field(default_factory=dict)
    timeout_seconds: int = 60
    capabilities: ProviderCapabilities
    
    GLOBAL_CONFIG_PATH_TEMPLATE = "{config_dir}/llm-providers.json"
    
    def save(self) -> None: ...
    @classmethod
    def load_global(cls) -> dict[str, "ProviderConfig"]: ...

class ProviderRegistry:
    @staticmethod
    def get(name: str) -> ProviderConfig:
        """Look up provider config by name. Raises if not found."""
        ...
    
    @staticmethod
    def upsert(config: ProviderConfig) -> None:
        """Save config to global file."""
        ...
    
    @staticmethod
    def remove(name: str) -> None: ...
    @staticmethod
    def list() -> list[ProviderConfig]: ...
    
    @staticmethod
    def resolve_for_chat(ctx: ProjectContext) -> tuple[ProviderConfig, str]:
        """Resolve provider + model for chat. Returns (config, model_name).
        Priority: ctx.settings.llm.provider_registry_name → first configured.
        """
        settings = ctx.settings.llm
        config = ProviderRegistry.get(settings.provider_registry_name)
        model = settings.model or config.default_chat_model
        return config, model
    
    @staticmethod
    def resolve_for_embedding(ctx: ProjectContext) -> tuple[ProviderConfig, str]:
        settings = ctx.settings.embedding
        config = ProviderRegistry.get(settings.provider_registry_name)
        model = settings.model or config.default_embedding_model or config.default_chat_model
        return config, model
```

## Ollama provider

```python
# src/llm/ollama_provider.py
class OllamaProvider(LLMProvider):
    """Provider for local Ollama server (https://ollama.com)."""
    
    capabilities = ProviderCapabilities(
        supports_streaming=True,
        supports_json_mode=True,            # Ollama supports format="json" (no schema strict)
        supports_embedding=True,
        max_context_window=128000,           # Model-dependent; default to large
    )
    
    def __init__(self, config: ProviderConfig):
        self.config = config
        self.base_url = config.base_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=config.timeout_seconds)
    
    async def complete(self, prompt: str, response_format: dict | None = None,
                       system: str | None = None, max_retries: int = 1) -> dict:
        body = self._build_body(prompt, response_format, system, stream=False)
        for attempt in range(max_retries + 1):
            try:
                resp = await self.client.post(f"{self.base_url}/api/chat", json=body)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    raise OllamaModelNotFoundError(body["model"], self.base_url) from e
                if attempt == max_retries:
                    raise
                await asyncio.sleep(2 ** attempt)
    
    async def complete_stream(self, prompt: str, response_format: dict | None = None,
                                system: str | None = None, max_retries: int = 1) -> AsyncIterator[StreamChunk]:
        body = self._build_body(prompt, response_format, system, stream=True)
        async with self.client.stream("POST", f"{self.base_url}/api/chat", json=body) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                chunk = json.loads(line)
                if "message" in chunk and "content" in chunk["message"]:
                    yield StreamChunk(
                        delta=chunk["message"]["content"],
                        usage=self._extract_usage(chunk),
                    )
                if chunk.get("done"):
                    break
    
    async def embed(self, texts: list[str]) -> list[list[float]]:
        # Ollama doesn't support batch embed; loop per text
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
        """GET /api/version + /api/tags."""
        try:
            version_resp = await self.client.get(f"{self.base_url}/api/version")
            version = version_resp.json().get("version") if version_resp.status_code == 200 else None
            tags_resp = await self.client.get(f"{self.base_url}/api/tags")
            installed = {m["name"] for m in tags_resp.json().get("models", [])}
            configured = {self.config.default_chat_model, self.config.default_embedding_model}
            missing = configured - installed
            return {
                "reachable": True,
                "version": version,
                "installedModels": sorted(installed),
                "missingModels": sorted(missing),
            }
        except (httpx.HTTPError, httpx.ConnectError) as e:
            return {"reachable": False, "error": str(e)}
    
    def _build_body(self, prompt, response_format, system, stream) -> dict:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        
        body = {
            "model": self.config.default_chat_model,
            "messages": messages,
            "stream": stream,
        }
        if response_format:
            body["format"] = "json"   # Ollama supports json mode (no strict schema)
        return body
```

## OpenAI-compatible generic provider

```python
# src/llm/openai_compatible_provider.py
class OpenAICompatibleProvider(LLMProvider):
    """For LM Studio / vLLM / LocalAI / llama.cpp server / any /v1/chat/completions compatible service."""
    
    capabilities = ProviderCapabilities(
        supports_streaming=True,
        supports_json_mode=True,            # response_format=json_object (most servers support)
        supports_embedding=True,            # /v1/embeddings (most servers support)
        max_context_window=32768,
    )
    
    def __init__(self, config: ProviderConfig):
        self.config = config
        base_url = config.base_url.rstrip("/")
        if not base_url.endswith("/v1"):
            base_url += "/v1"
        self.base_url = base_url
        headers = dict(config.extra_headers)
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        self.client = httpx.AsyncClient(timeout=config.timeout_seconds, headers=headers)
    
    async def complete(self, prompt, response_format=None, system=None, max_retries=1) -> dict:
        body = self._build_body(prompt, response_format, system, stream=False)
        for attempt in range(max_retries + 1):
            try:
                resp = await self.client.post(f"{self.base_url}/chat/completions", json=body)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                if attempt == max_retries:
                    raise
                await asyncio.sleep(2 ** attempt)
    
    async def complete_stream(self, prompt, response_format=None, system=None, max_retries=1) -> AsyncIterator[StreamChunk]:
        body = self._build_body(prompt, response_format, system, stream=True)
        async with self.client.stream("POST", f"{self.base_url}/chat/completions", json=body) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[len("data: "):].strip()
                if payload == "[DONE]":
                    break
                chunk = json.loads(payload)
                if "choices" in chunk and chunk["choices"]:
                    delta = chunk["choices"][0].get("delta", {}).get("content", "")
                    if delta:
                        yield StreamChunk(delta=delta, usage=self._extract_usage(chunk))
    
    async def embed(self, texts: list[str]) -> list[list[float]]:
        resp = await self.client.post(
            f"{self.base_url}/embeddings",
            json={"model": self.config.default_embedding_model, "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()
        return [item["embedding"] for item in data["data"]]
    
    async def health_check(self) -> dict:
        """GET /models (OpenAI-compatible list endpoint)."""
        try:
            resp = await self.client.get(f"{self.base_url}/models")
            resp.raise_for_status()
            installed = {m["id"] for m in resp.json().get("data", [])}
            configured = {self.config.default_chat_model, self.config.default_embedding_model}
            missing = configured - installed
            return {
                "reachable": True,
                "installedModels": sorted(installed),
                "missingModels": sorted(missing),
            }
        except (httpx.HTTPError, httpx.ConnectError) as e:
            return {"reachable": False, "error": str(e)}
    
    def _build_body(self, prompt, response_format, system, stream) -> dict:
        messages = []
        if system:
            messages.append({"role": "system", "content": prompt})
        messages.append({"role": "user", "content": prompt})
        
        body = {
            "model": self.config.default_chat_model,
            "messages": messages,
            "stream": stream,
        }
        if response_format:
            # Most servers support json_object; strict schema support varies
            body["response_format"] = {"type": "json_object"}
        return body
```

## Streaming adapter (fallback)

```python
# src/llm/streaming_adapter.py
class NonStreamingToStreamingAdapter(LLMProvider):
    """Wraps a non-streaming provider so it satisfies the streaming interface.
    
    Used as a fallback for future providers that only support complete().
    """
    
    def __init__(self, inner: LLMProvider, chunk_size: int = 20):
        self.inner = inner
        self.chunk_size = chunk_size
        # Inherit capabilities but flag streaming as synthesized
        self.capabilities = ProviderCapabilities(
            supports_streaming=True,
            supports_json_mode=inner.capabilities.supports_json_mode,
            supports_embedding=inner.capabilities.supports_embedding,
            max_context_window=inner.capabilities.max_context_window,
        )
    
    async def complete(self, *args, **kwargs) -> dict:
        return await self.inner.complete(*args, **kwargs)
    
    async def complete_stream(self, prompt, response_format=None, system=None, max_retries=1):
        result = await self.inner.complete(prompt, response_format, system, max_retries)
        # Extract content from OpenAI-style response
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        # Yield in chunks (one character at a time yields too many; 20 chars is reasonable)
        for i in range(0, len(content), self.chunk_size):
            yield StreamChunk(delta=content[i:i + self.chunk_size])
            await asyncio.sleep(0)  # yield control to event loop
    
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await self.inner.embed(texts)
    
    async def health_check(self) -> dict:
        return await self.inner.health_check()
    
    async def close(self) -> None:
        await self.inner.close()
```

## Provider factory

```python
# src/llm/provider_factory.py (additions)
def create_llm_provider(registry_name: str = None, model_override: str | None = None) -> LLMProvider:
    """Resolve provider from registry and instantiate.
    
    Args:
        registry_name: name from llm-providers.json (default: from env or "openai")
        model_override: override the default_chat_model
    """
    if registry_name is None:
        registry_name = os.environ.get("RUFLO_LLM_PROVIDER", "openai")
    
    config = ProviderRegistry.get(registry_name)
    if model_override:
        config = dataclasses.replace(config, default_chat_model=model_override)
    
    if config.type == "openai":
        return OpenAIProvider(config)
    elif config.type == "anthropic":
        return AnthropicProvider(config)
    elif config.type == "ollama":
        return OllamaProvider(config)
    elif config.type == "openai-compatible":
        return OpenAICompatibleProvider(config)
    else:
        raise ValueError(f"Unknown provider type: {config.type}")

def create_embedding_provider(registry_name: str = None, model_override: str | None = None) -> EmbeddingProvider:
    # Similar dispatch
    ...
```

## Health check

```python
# src/llm/health.py
@dataclass
class ProviderHealth:
    name: str
    reachable: bool
    version: str | None = None
    installed_models: list[str] = field(default_factory=list)
    missing_models: list[str] = field(default_factory=list)
    error: str | None = None
    
    def render(self) -> str:
        """Human-readable status text."""
        if not self.reachable:
            return f"[✗] {self.name}: unreachable ({self.error})"
        lines = [f"[✓] {self.name}: reachable"]
        if self.version:
            lines.append(f"  version: {self.version}")
        if self.installed_models:
            lines.append(f"  installed: {', '.join(self.installed_models)}")
        if self.missing_models:
            lines.append(f"  ⚠ missing: {', '.join(self.missing_models)}")
            lines.append(f"    run: ollama pull <model>  # or equivalent for your provider")
        return "\n".join(lines)


class HealthChecker:
    """Runs health check on all configured providers at CLI startup."""
    
    @staticmethod
    async def check_all(providers: list[str] | None = None) -> list[ProviderHealth]:
        results = []
        for name in (providers or [c.name for c in ProviderRegistry.list()]):
            try:
                config = ProviderRegistry.get(name)
                provider = create_llm_provider(name)
                health_data = await provider.health_check()
                results.append(ProviderHealth(
                    name=name,
                    reachable=health_data.get("reachable", False),
                    version=health_data.get("version"),
                    installed_models=health_data.get("installedModels", []),
                    missing_models=health_data.get("missingModels", []),
                    error=health_data.get("error"),
                ))
                await provider.close()
            except Exception as e:
                results.append(ProviderHealth(name=name, reachable=False, error=str(e)))
        return results
```

**Startup integration**:

```python
# src/cli.py main()
async def main():
    parser = argparse.ArgumentParser(...)
    # ... parse args ...
    
    # Health check (only if not a daemon/mcp subcommand)
    if args.command not in ("serve", "mcp"):
        await _print_health_warnings()
    
    args.func(args)

async def _print_health_warnings():
    """Non-blocking health check; prints warnings if any provider has issues."""
    try:
        results = await HealthChecker.check_all()
        for h in results:
            if not h.reachable or h.missing_models:
                print(h.render(), file=sys.stderr)
    except Exception:
        pass  # Health check failures should not block CLI startup
```

## CLI surface

```
python -m src.cli llm-providers list
    # List all configured providers (global + per-project override indicator)
    
python -m src.cli llm-providers show <name>
    # Print full ProviderConfig JSON

python -m src.cli llm-providers add <name> [--type ollama|openai-compatible] [--base-url URL] \
                                  [--api-key KEY] [--model MODEL] [--embedding MODEL] \
                                  [--timeout SECONDS]
    # Add a provider to global registry
    # If --type ollama: auto-fetch /api/tags and prompt user to pick from installed models
    # If --type openai-compatible: requires --base-url and --api-key

python -m src.cli llm-providers remove <name>
    # Remove from global registry (refuses if any project uses it)

python -m src.cli llm-providers test <name>
    # Run health_check + print ProviderHealth.render()

python -m src.cli llm-providers set-default <name>
    # Set RUFLO_LLM_PROVIDER env var in shell config (writes to ~/.config/ruflo-kb/env)

python -m src.cli configure --provider ollama --base-url http://127.0.0.1:11434 --model qwen2.5:7b
    # Updates per-project settings (existing configure command, extended with new providers)
```

### Example `llm-providers add` interactive flow

```
$ python -m src.cli llm-providers add my-ollama --type ollama --base-url http://127.0.0.1:11434

[✓] Ollama reachable at http://127.0.0.1:11434 (version 0.5.7)

Available models:
  1. llama3.1:8b       (chat, 128K context)
  2. qwen2.5:7b        (chat, 32K context)
  3. nomic-embed-text  (embedding, 2K context)
  4. mxbai-embed-large (embedding, 512 context)

Chat model? [default: 2] 
Embedding model? [default: 3] 

[✓] Provider 'my-ollama' saved to ~/.config/ruflo-kb/llm-providers.json
[✓] Default chat: qwen2.5:7b
[✓] Default embedding: nomic-embed-text

Set as project default? [y/N] y
[✓] Project settings.json updated
```

## Settings extension

```python
# src/project/settings.py
@dataclass
class LLMSettings:
    # NEW
    provider_registry_name: str = "openai"
    model: str | None = None                # None = use registry default
    
    # Existing
    api_key_env: str | None = None
    timeout_seconds: int = 60
    max_retries: int = 2

@dataclass
class EmbeddingSettings:
    # NEW
    provider_registry_name: str = "openai"
    model: str | None = None                # None = use registry default
    
    # Existing
    api_key_env: str | None = None
    dimension: int | None = None
```

`ProjectContext.__init__` loads `ProviderRegistry.list()` once on init.

## Error handling

| Stage | Error | Strategy |
|---|---|---|
| Ollama connect | Server unreachable | 503 + "Ollama not running at {base_url}. Start with `ollama serve`." |
| Ollama 404 on model | Model not pulled | 503 + `ollama pull <model>` command in error message |
| Ollama streaming | Connection drop mid-stream | Yield error event; agent loop continues with empty observation |
| Ollama JSON mode | Server returns invalid JSON | 1 retry with stricter prompt; if 2nd fail, return raw text + warning |
| OpenAI-compatible connect | Server unreachable | 503 + check `{base_url}` + `ollama serve` or `lms server start` hint |
| OpenAI-compatible 401 | API key invalid | 502 + "Set api_key in `llm-providers add <name> --api-key <KEY>`" |
| OpenAI-compatible 404 on chat/completions | Endpoint not supported | 502 + "Server doesn't expose /v1/chat/completions; check it's OpenAI-compatible" |
| OpenAI-compatible response_format unsupported | Some servers don't accept response_format | Fallback: omit response_format; rely on prompt-level JSON instruction + regex extract |
| Registry load | Corrupt JSON | Backup to `.bak` + start with empty registry; warn user |
| Provider override | Name not in global | 502 + "Provider '{name}' not configured. Run `llm-providers add {name}`." |
| Model override | settings.llm.model not in provider's installed models | Use anyway (Ollama models are dynamic); warn but don't fail |
| Embedding | Provider has no embedding model | 503 + "Provider '{name}' has no embedding model configured" |
| Embedding dimension mismatch | Provider returns different dim than settings.embedding.dimension | Raise `EmbeddingDimensionMismatchError`; user must update settings |
| Health check | Ollama `/api/tags` 404 (older version) | Fallback: skip model listing; report reachable but no models known |
| Health check | Timeout (5s) | Mark as unreachable |

## Backwards compatibility

- New `llm-providers` subcommands: purely additive.
- Existing `OpenAIProvider` / `AnthropicProvider`: no API changes (existing default config).
- `LLMSettings.provider_registry_name`: defaults to `"openai"` — existing projects continue working.
- `LLMSettings.model`: defaults to `None` — falls back to provider's default_chat_model.
- No file format change to `~/.config/ruflo-kb/registry.json` (project registry unchanged).
- New file `~/.config/ruflo-kb/llm-providers.json`: created on first `llm-providers add`.
- Health check at startup: warnings only (non-blocking); never delays startup > 2 seconds.

## Testing strategy

### Unit tests

| Module | Test focus |
|---|---|
| `src/llm/ollama_provider.py` | httpx mock; complete / complete_stream / embed; JSON mode; retry on 5xx |
| `src/llm/ollama_provider.py` | 404 on missing model → OllamaModelNotFoundError with `ollama pull` hint |
| `src/llm/openai_compatible_provider.py` | httpx mock; auto-append `/v1` to base_url; stream parse `data: [DONE]` terminator |
| `src/llm/openai_compatible_provider.py` | Bearer auth header when api_key set; absent when not |
| `src/llm/streaming_adapter.py` | inner non-streaming → adapter yields content in chunks |
| `src/llm/registry.py` | global load/save/upsert/remove; corrupt recovery; per-project resolution priority |
| `src/llm/health.py` | Ollama `/api/tags` success + missing model detection; OpenAI-compatible `/models` |
| `src/llm/provider_factory.py` | `create_llm_provider("ollama")` returns OllamaProvider; "openai-compatible" returns right class |
| `src/cli_ext/llm_providers_cmd.py` | list / add / remove / test / show; corrupt registry handling |

### Integration tests

```
tests/test_integration/test_ollama_e2e.py (opt-in, requires running Ollama):
    @pytest.mark.real_ollama
    async def test_real_ollama_full_flow():
        # Skip if ollama not running
        # Run actual chat completion + embedding + health check
        
    @pytest.mark.real_ollama
    async def test_real_ollama_streaming():
        # Verify ndjson chunk parsing against real Ollama server

tests/test_integration/test_provider_switch.py:
    def test_per_project_provider_override():
        # Project A: settings.llm.provider_registry_name = "ollama"
        # Project B: settings.llm.provider_registry_name = "openai"
        # Verify: different provider instances, independent models

    def test_global_provider_change_propagates():
        # Project has no override → uses global default
        # Change global default → project uses new default (no restart needed)
```

## Implementation order

8 phases, each independently committable:

1. **Foundation** — `src/llm/base.py` + `ProviderCapabilities` + `StreamChunk` + `src/llm/registry.py` + global config + tests
2. **Ollama provider** — `src/llm/ollama_provider.py` + complete / complete_stream / embed / health_check + tests
3. **OpenAI-compatible provider** — `src/llm/openai_compatible_provider.py` + tests
4. **Streaming adapter** — `src/llm/streaming_adapter.py` + tests
5. **Health check** — `src/llm/health.py` + `HealthChecker.check_all` + tests
6. **Per-project resolution** — `src/project/settings.py` + `provider_registry_name` field + `ProjectContext.provider_registry` + `ProviderRegistry.resolve_for_chat/embedding` + tests
7. **Provider factory + CLI** — `src/llm/provider_factory.py` dispatch + `src/cli_ext/llm_providers_cmd.py` + `configure --provider ollama` + tests
8. **Integration** — real Ollama E2E (opt-in) + per-project switch + tests

Each phase follows TDD per-task rhythm; one commit per task.

## Cost estimation

- New code: ~1500 lines (2 providers + registry + health + adapter + CLI + tests)
- New dependencies: zero (httpx already required)
- Operational cost:
  - Ollama: free (local compute)
  - OpenAI-compatible generic: free (self-hosted)
- Deployment scenario:
  - Zero monthly cost + 100% privacy (local only)
  - No rate limits / no API quota

## Open questions / deferred (v3.0+)

- **Google Gemini** — separate API key + different content schema (nested `generationConfig`); high value, deferred
- **Anthropic Bedrock / Vertex AI** — enterprise users; deferred
- **Subprocess CLI providers** (Claude Code CLI, Codex CLI) — different transport (stdin/stdout); complex
- **Vision / image input** — needs image extraction pipeline first
- **Provider-level rate limiting** — needed for cost attribution across projects
- **Model auto-selection** — pick model based on task type / cost budget
- **Provider-specific retry / backoff policies** — uniform 2^n backoff is fine for v1
- **Model quantization / LoRA management** — Ollama handles internally
- **Multi-region / failover** — one provider per project is sufficient for v1
- **Provider metrics** (latency p50/p95, error rate) — deferred

## Dependency graph

```
src/llm/base.py (extended)
       │
       ├──► src/llm/ollama_provider.py
       ├──► src/llm/openai_compatible_provider.py
       ├──► src/llm/streaming_adapter.py
       │
       └──► src/llm/registry.py ──► src/llm/health.py
                                        │
                                        ▼
                              src/llm/provider_factory.py
                                        │
                                        ▼
                              src/project/context.py (uses ProviderRegistry)
                                        │
                                        ▼
                              src/cli_ext/llm_providers_cmd.py
```