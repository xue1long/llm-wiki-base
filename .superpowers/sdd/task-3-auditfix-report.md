# Task 3 Auditfix Report — Fix LLM provider default endpoint + return contract

**Status**: DONE
**Branch**: `fix/2026-07-23-full-audit`
**Base commit**: `964d247`
**Brief**: `.superpowers/sdd/task-3-brief.md`

## Audit findings resolved

- **C-21 / I-llm-13**: Chat endpoint routing — `OpenAIProvider.complete()` now
  goes through `client.chat.completions.create(...)` (or
  `httpx POST /chat/completions`); the legacy `/v1/completions` path is gone.
- **C-22 / I-llm-3**: Anthropic default URL is
  `https://api.anthropic.com/v1` (was `https://api.anthropic.com`).
- **I-llm-5**: Anthropic default base URL fix (above).
- **I-llm-6**: Anthropic `system` messages lifted to top-level `system` field,
  joined with `"\n\n"`; no `system` role entries in messages array.
- **I-llm-7**: Ollama provider uses one cached `AsyncClient` per `base_url`;
  `close()` is idempotent across instances.
- **I-llm-8**: `ProviderRegistry.aclose_all()` keeps failed-close providers
  in `_loaded_providers` (operator can retry without losing the resource
  reference); successful-close providers are removed.
- **I-llm-10**: `ProviderConfig.timeout_seconds` and `extra_headers` are
  forwarded to provider constructors via `create_llm_provider`.
- **I-llm-11**: `LLMProvider` interface advertises `health_check()` and
  `close()` (defaults: `True` and no-op); OpenAI/Anthropic override with
  `self._sdk.models.list()` (catch-all) and a no-op respectively.
- **I-llm-13**: Already in C-21.
- **I-llm-14**: `RegistryCorruptError` raised when registry file exists but
  parses as invalid JSON.
- **Bonus**: `RUFLO_LLM_PROVIDER` env var takes precedence in
  `ProviderRegistry.get_default()` (over named "default" and first-inserted).

## Files modified

| File | Purpose |
|---|---|
| `src/llm/base.py` | `LLMProvider.complete(messages, ...)` + `chat` alias; `health_check`/`close` defaults |
| `src/llm/openai_provider.py` | Chat-completion routing; supports SDK or httpx; `dimensions`; validation |
| `src/llm/anthropic_provider.py` | Lifts system to top-level; SDK + httpx dual paths; default URL `/v1` |
| `src/llm/ollama_provider.py` | Cached `AsyncClient` per base_url; idempotent `close()` |
| `src/llm/registry.py` | `RegistryCorruptError`; env-var precedence; `aclose_all` retry safety; `/v1` fix |
| `src/llm/provider_factory.py` | Forwards `timeout_seconds` + `extra_headers`; uses new constructor signatures |
| `src/pipeline/analyzer.py` | Switches to `response.content` → `_parse_llm_response` helper |
| `src/pipeline/generator.py` | Same |
| `src/agent/runtime.py` | Same; `AgentLoopAction.from_json(response.content)` |
| `src/lib/budgeted.py` | Wraps `prompt` → `messages=[{user}]` for new chat contract |
| `src/shared/test_helpers.py` | `ScriptedLLMProvider` accepts both old (prompt=...) and new (messages=...) forms; wraps scripted dicts as `LLMResponse(content=json.dumps(...))` |

## Tests added (19 total)

- `tests/test_llm/test_openai_endpoint.py` (3)
- `tests/test_llm/test_anthropic_url.py` (1)
- `tests/test_llm/test_anthropic_system.py` (3)
- `tests/test_llm/test_registry_default_env.py` (5)
- `tests/test_llm/test_ollama_close.py` (4)
- `tests/test_llm/test_openai_dimension.py` (3)

## Test summary

- **19/19 new tests pass**
- **109/109 regression tests pass** (`tests/test_llm tests/test_pipeline tests/test_agent tests/test_server`)
- **472/472 full suite pass** (no test_lib regressions; `test_budgeted.py` updated to match canonical contract)

## Concerns / Notes

- The brief's `test_env_var_missing_falls_back_to_named_default` example used
  the old `"default": "<name>"` schema key (which is not part of the current
  registry schema — see the registry README/spec). I rewrote that one
  assertion to use the actual schema: a provider **named** `"default"` in
  the registry dict. The contract is unchanged from what the brief describes
  in prose ("Provider explicitly named `default` in the registry").
- `LLMProvider.embed` is still abstract on the base class, but
  `OpenAIProvider.embed(text)` was a legacy single-text entrypoint kept for
  call sites. I preserved it.
- `OllamaProvider.embed(texts)` returns `list[list[float]]` (legacy
  contract) rather than `list[EmbeddingResponse]`. The wrapping adapter in
  `provider_factory.py` already converts; this preserves the legacy test
  `test_health_check_*` shape (`{"reachable": ..., "version": ...}`) on
  `OllamaProvider.health_check()`.
- The fixed `make` for `OpenAIProvider` accepts both the legacy direct-arg
  style (`api_key=`, `endpoint=`, `model=`, `dimension=`) and the new
  `ProviderConfig`-driven `(config, model_override=)` style — same goes for
  `OpenAIEmbeddingProvider`. This keeps the factory and any tests passing
  either way.
- Two commits needed to NOT be created (per brief: ONE commit). Captured in
  the `git commit` step below.

## Commit

`fix(llm): chat endpoint, /v1 URL, system msg, env default, dimension; add lifecycle`
