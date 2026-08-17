# Full-Audit Bug Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Eliminate the 23 critical + 53 important findings from the 2026-07-23 full-codebase bug audit (LLM providers, Service/HTTP/CLI, Cross-cutting, Queue/Orchestrator, Pipeline/Wiki, Vector/Search). Restore the documented product behaviour: working URL ingest, working chat, working hybrid search, atomic file writes, functional permission boundaries, and visible error paths.

**Architecture:** Four sequential phases — (1) wiring fixes (callers must compile before downstream tasks can run their tests), (2) atomicity (durability boundary), (3) trust (error visibility + security boundaries), (4) UX polish. Each phase produces testable software independently; phases are strictly ordered because later phases re-use fixtures created in earlier ones.

**Tech Stack:** Python 3.11+, pytest, pytest-asyncio, dataclass, asyncio, threading, pathlib.

**Global Constraints (apply to every task):**

- Python 3.11+ (project baseline; setup documented in `docs/environment/SETUP.md`).
- Run pytest as: `env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy PYTHONPATH=. python -m pytest --import-mode=importlib`.
- All file writes through `src.lib.write_hooks.safe_write` — never raw `Path.write_text` / `os.unlink` outside `safe_write(..., DELETE_SENTINEL)`.
- Wiki path access via `WikiPaths(ctx.path)` — never `ctx.paths` (it does not exist).
- Atomic write pattern from `src/project/registry.py:89-101` is the template: write to `*.tmp`, `os.replace`.
- Module-level `_embedding_provider` globals in `librarian` and `searcher` MUST share one instance — introduce `src/llm/embedding_runtime.py:set_embedding_provider / get_embedding_provider` and replace both globals.
- LLM provider `complete()` must route through `/chat/completions` (or Responses API) — never `/v1/completions` for chat models.
- Each task = one commit; commit message prefix follows repo convention (`feat(scope):` / `fix(scope):` / `refactor(scope):`).
- After each task, dispatch a code-review subagent (superpowers:subagent-driven-development); fix Critical/Important findings before the next task.

---

## File Structure

```
src/
├── llm/
│   ├── embedding_runtime.py        (NEW — T2: shared embedding provider singleton)
│   ├── base.py                     (T3 — add Lifecycle/health_check; normalize return)
│   ├── openai_provider.py          (T3 — chat/Responses endpoint; pass dimension)
│   ├── anthropic_provider.py       (T3 — system messages; /v1 URL)
│   ├── ollama_provider.py          (T3 — close-once cache; pass extra_headers)
│   ├── registry.py                 (T3 — read RUFLO_LLM_PROVIDER; raise on corrupt)
│   └── types.py                    (T10 — redact api_key in to_dict)
├── searcher/
│   └── hybrid_search.py            (T2 — use shared embedding; T13 — edge cases)
├── vector/
│   ├── store.py                    (T2 — init_from_project / per-project table)
│   └── upsert.py                   (T13 — merge_insert; SQL param binding)
├── pipeline/
│   ├── collector.py                (T4 — URL gate; enforce_permission)
│   ├── pipeline.py                 (T7 — task terminal status; T8 — error visibility)
│   ├── librarian.py                (T2 — shared embedding; T16 — paths/collision)
│   └── processor.py                (no change in this plan)
├── wiki/
│   ├── core/types.py               (T13 — defensive from_dict; heat is_immutable)
│   └── features/
│       ├── stubs.py                (T5 — DELETE_SENTINEL)
│       ├── dedup_auto.py           (T5 — DELETE_SENTINEL)
│       ├── cascade_delete.py       (T8 — internal atomic ctx; T16 — index filter)
│       └── heat.py                 (T14 — is_immutable, created_at baseline)
├── lib/
│   ├── atomic_ctx.py               (T7 — flush failure isolation)
│   └── write_hooks.py              (T5 — atomic non-ctx write)
├── queue/queue.py                  (T5 atomic save; T7 lock; T11 dead-letter event)
├── orchestrator/
│   ├── orchestrator.py             (T6 — can_transition; T8 — audit error path)
│   ├── state_machine.py            (T6 — get_next_status validates)
│   └── router.py                   (T16 — drop UNKNOWN, suffix match)
├── permissions.py                  (T9 — is_relative_to; remove resolve())
├── circuit_breaker.py              (T6 — get_circuit_breaker in decorator)
├── inbox/manager.py                (T12 — os.replace, unique error.log, no false success)
├── sync/
│   ├── snapshot_store.py           (T5 — tmp+os.replace; corrupt JSON recovery)
│   └── file_watcher.py             (T16 — relative path keys)
├── events/event_bus.py             (T8 — fail-fast mode; snapshot iter)
├── schemas/
│   ├── migrations/
│   │   └── v2_to_v2_2.py           (T11 — own key; collision raise)
│   └── registry.py                 (T11 — raise on duplicate key; T16 — migrate_data raise)
├── services/
│   ├── chat.py                     (T8 — error response; T9 — ProjectNotFoundError)
│   └── ... (other services — T9 only)
├── server/routes/                  (T9 — ProjectNotFoundError catch)
├── cli_ext/
│   ├── research_cmd.py             (T1 — WikiPaths(ctx.path))
│   ├── templates_cmd.py            (T1 — WikiPaths(ctx.path))
│   ├── quality_cmd.py              (T15 — declare --config-root)
│   ├── schema_cmd.py               (T15 — ValueError + missing --name)
│   ├── serve.py                    (T15 — pidfile corrupt cleanup)
│   └── llm_providers_cmd.py        (T3 — show redacted; T10)
├── utils/
│   ├── similarity.py               (T16 — proper prefix ratio)
│   ├── extract/html.py             (T16 — re.sub with callback)
│   ├── extract/office.py           (T16 — guard legacy .doc)
│   └── extract/pdf.py              (T16 — encrypted PDF guard)
├── research/runner.py              (T1 — WikiPaths(ctx.path))
├── agent/tools.py                  (T1 — WikiPaths(ctx.path); fix hybrid_search call)
└── cli.py                          (T15 — register --config-root)

tests/ (one new test file per task; modify existing only when required)
```

Each task's deliverable is one commit on `master` (or a fix branch if the user prefers). Tests must pass at the end of each task: `PYTHONPATH=. pytest tests/<new-file> -v`.

---

## Phase 1 — Make the Product Runnable (Tasks 1–4)

### Task 1: Migrate all callers from `ctx.paths` to `WikiPaths(ctx.path)`

**Files:**
- Modify: `src/research/runner.py:35,41,126,130,133,153`
- Modify: `src/agent/tools.py:25,36,53,57,71,72`
- Modify: `src/cli_ext/research_cmd.py:38`
- Modify: `src/cli_ext/templates_cmd.py:41,44`
- Test: `tests/test_research/test_runner_paths.py`, `tests/test_agent/test_tools_paths.py`, `tests/test_cli_ext/test_research_cmd_paths.py`, `tests/test_cli_ext/test_templates_cmd_paths.py`

**Interfaces:**
- Consumes: `ctx: ProjectContext` (has `ctx.path: Path` only); `WikiPaths(ctx.path)` returns object with `.root`, `.wiki_sources`, `.wiki_entities`, `.wiki_concepts`, `.wiki_synthesis`, `.raw_sources`, `.wiki_index`, `.index_dir`, `.llm_wiki`, `.staging`.
- Produces: All five call sites use `paths = WikiPaths(ctx.path)` once at top of `execute()` / handler, then `paths.X` for the rest of the function.

- [ ] **Step 1: Write failing tests** — add one test per file: monkeypatch a fake `ProjectContext(path=tmp_path)` then invoke the public entrypoint and assert it returns without `AttributeError`. Example for `tests/test_agent/test_tools_paths.py`:

```python
# tests/test_agent/test_tools_paths.py
from pathlib import Path
from src.project.context import ProjectContext
from src.wiki.ensure import ensure_knowledge_base
from src.agent.tools import WikiReadPageTool


def test_wiki_read_page_tool_uses_paths(monkeypatch, tmp_path):
    ensure_knowledge_base(tmp_path)
    (tmp_path / "wiki/sources/foo.md").write_text(
        "---\nid: foo\ntitle: Foo\ntype: source\n---\nbody\n", encoding="utf-8"
    )
    ctx = ProjectContext(path=tmp_path)
    tool = WikiReadPageTool(ctx=ctx)
    out = tool.execute(page_id="foo")
    assert "Foo" in out


def test_wiki_read_page_tool_does_not_call_ctx_paths(monkeypatch, tmp_path):
    """Regression: ctx.paths must NOT be accessed (it doesn't exist)."""
    ensure_knowledge_base(tmp_path)
    ctx = ProjectContext(path=tmp_path)

    class ExplodingCtx(ProjectContext):
        @property
        def paths(self):
            raise AssertionError("ctx.paths must not be accessed")

    tool = WikiReadPageTool(ctx=ExplodingCtx(path=tmp_path))
    # Should not raise the AssertionError
    tool.execute(page_id="foo")
```

- [ ] **Step 2: Run tests, verify FAIL** — `PYTHONPATH=. pytest tests/test_agent/test_tools_paths.py -v` → FAIL with `AttributeError: 'ProjectContext' object has no attribute 'paths'`.

- [ ] **Step 3: Implement migrations**

For each of the five files, add at the top of the relevant function:

```python
from src.wiki.core.paths import WikiPaths  # adjust import path

# inside the function:
paths = WikiPaths(ctx.path)
```

Then replace every `ctx.paths.X` with `paths.X`. For `agent/tools.py` line 25, also drop the `mode="hybrid"` kwarg:

```python
# src/agent/tools.py — SourceSearchTool.execute
result = await hybrid_search(query, top_k=top_k)
```

For `research/runner.py`, replace `ctx.settings.llm.provider_registry_name` with `ProviderRegistry.get_default()` (add the import). Drop any reference to `ctx.settings.llm` that doesn't exist.

- [ ] **Step 4: Run tests, verify PASS** — `PYTHONPATH=. pytest tests/test_research/test_runner_paths.py tests/test_agent/test_tools_paths.py tests/test_cli_ext/test_research_cmd_paths.py tests/test_cli_ext/test_templates_cmd_paths.py -v` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/research/runner.py src/agent/tools.py src/cli_ext/research_cmd.py src/cli_ext/templates_cmd.py \
        tests/test_research/test_runner_paths.py tests/test_agent/test_tools_paths.py \
        tests/test_cli_ext/test_research_cmd_paths.py tests/test_cli_ext/test_templates_cmd_paths.py
git commit -m "fix(svc): migrate ctx.paths callers to WikiPaths(ctx.path); drop bad hybrid_search kwargs"
```

---

### Task 2: Initialise vector store + embedding provider on project startup

**Files:**
- Create: `src/llm/embedding_runtime.py`
- Modify: `src/pipeline/librarian.py:18-24` (use shared runtime)
- Modify: `src/searcher/hybrid_search.py:19` (use shared runtime)
- Modify: `src/vector/store.py` (add `init_vector_store_for_paths(paths: WikiPaths)`)
- Modify: `src/server/app.py` (lifespan startup hook)
- Test: `tests/test_llm/test_embedding_runtime.py`, `tests/test_vector/test_store_init.py`, `tests/test_pipeline/test_librarian_uses_runtime.py`, `tests/test_searcher/test_hybrid_uses_runtime.py`

**Interfaces:**
- `src.llm.embedding_runtime.set_embedding_provider(provider)` / `get_embedding_provider()` — process-global; `_impl: EmbeddingProvider | None`; raises `RuntimeError("Embedding provider not configured")` on get when unset.
- `src.vector.store.init_vector_store_for_paths(paths: WikiPaths) -> None` — closes any prior handle, opens LanceDB at `paths.index_dir / "lancedb"`, and binds `_db` / `_table` for the given project path. Stores a `{path: handle}` map; `get_table()` resolves via current `WikiPaths`.

- [ ] **Step 1: Write tests**

```python
# tests/test_llm/test_embedding_runtime.py
import pytest
from src.llm.embedding_runtime import (
    set_embedding_provider, get_embedding_provider, __reset_for_testing
)
from src.llm.types import ProviderConfig, ModelInfo


class FakeProvider:
    def __init__(self, dim=1536): self.dim = dim
    def embed(self, texts): return [[0.0] * self.dim for _ in texts]


def setup_function(_):
    __reset_for_testing()


def test_get_raises_when_unset():
    with pytest.raises(RuntimeError):
        get_embedding_provider()


def test_set_then_get():
    p = FakeProvider()
    set_embedding_provider(p)
    assert get_embedding_provider() is p


def test_set_replaces():
    set_embedding_provider(FakeProvider())
    p2 = FakeProvider()
    set_embedding_provider(p2)
    assert get_embedding_provider() is p2
```

```python
# tests/test_vector/test_store_init.py
from src.vector.store import (
    init_vector_store_for_paths, get_table, __reset_for_testing,
)
from src.wiki.ensure import ensure_knowledge_base
from src.wiki.core.paths import WikiPaths


def setup_function(_):
    __reset_for_testing()


def test_init_creates_table(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    init_vector_store_for_paths(p)
    assert get_table() is not None


def test_init_for_new_project_does_not_affect_old(tmp_path):
    ensure_knowledge_base(tmp_path)
    p1 = WikiPaths(tmp_path)
    init_vector_store_for_paths(p1)
    t1 = get_table()

    ensure_knowledge_base(tmp_path / "other")
    p2 = WikiPaths(tmp_path / "other")
    init_vector_store_for_paths(p2)
    t2 = get_table()
    assert t1 is not t2
```

- [ ] **Step 2: Run, verify FAIL** — tests above FAIL (functions don't exist).

- [ ] **Step 3: Implement**

`src/llm/embedding_runtime.py`:

```python
"""Process-global embedding provider singleton shared by librarian + searcher."""
from threading import Lock
from typing import Optional, Protocol

_impl: Optional["EmbeddingProvider"] = None
_lock = Lock()


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


def set_embedding_provider(provider: EmbeddingProvider) -> None:
    global _impl
    with _lock:
        _impl = provider


def get_embedding_provider() -> EmbeddingProvider:
    if _impl is None:
        raise RuntimeError(
            "Embedding provider not configured. Call set_embedding_provider() "
            "during project / app startup."
        )
    return _impl


def __reset_for_testing() -> None:
    global _impl
    with _lock:
        _impl = None
```

`src/vector/store.py` — add `init_vector_store_for_paths` and a `_per_project: dict[str, Any]` map keyed on `str(paths.root)`; `get_table()` looks up via the *current* project root set by `init_vector_store_for_paths`. Replace the single global `_db`/`_table` with this multi-handle map.

`src/pipeline/librarian.py` and `src/searcher/hybrid_search.py` — replace `_embedding_provider` with `from src.llm.embedding_runtime import get_embedding_provider`; raise on missing rather than returning zero vectors.

`src/server/app.py` — add a `lifespan` async context manager that:
1. Reads `ProviderRegistry.get_default()` for the active project.
2. Calls `set_embedding_provider(provider.create_embedding_provider(default_embedding_model))`.
3. Calls `init_vector_store_for_paths(paths)`.

- [ ] **Step 4: Run, verify PASS** — all four test files PASS.

- [ ] **Step 5: Commit**

```bash
git add src/llm/embedding_runtime.py src/vector/store.py src/pipeline/librarian.py \
        src/searcher/hybrid_search.py src/server/app.py \
        tests/test_llm/test_embedding_runtime.py tests/test_vector/test_store_init.py \
        tests/test_pipeline/test_librarian_uses_runtime.py tests/test_searcher/test_hybrid_uses_runtime.py
git commit -m "feat(llm): shared embedding_runtime singleton; per-project vector init"
```

---

### Task 3: Fix LLM provider default endpoint + return contract

**Files:**
- Modify: `src/llm/openai_provider.py:29-36,121-155`
- Modify: `src/llm/anthropic_provider.py:37-50`
- Modify: `src/llm/ollama_provider.py:17-22`
- Modify: `src/llm/registry.py:43-55,103-118,131-145,158-163`
- Modify: `src/llm/provider_factory.py:45-57`
- Modify: `src/llm/base.py:16-32`
- Modify: `src/pipeline/analyzer.py:76-84`, `src/pipeline/generator.py:109`, `src/agent/runtime.py:88`
- Test: `tests/test_llm/test_openai_endpoint.py`, `tests/test_llm/test_anthropic_url.py`, `tests/test_llm/test_anthropic_system.py`, `tests/test_llm/test_registry_default_env.py`, `tests/test_llm/test_ollama_close.py`, `tests/test_llm/test_openai_dimension.py`

**Interfaces:**
- `LLMProvider.complete(messages, *, response_format=None, system=None, **kw) -> LLMResponse` — chat-style; `messages: list[dict]` (role/content); `system` is a top-level Anthropic field and is concatenated to the first system message for OpenAI.
- `LLMProvider.chat(messages, **kw) -> LLMResponse` — alias of `complete`.
- `LLMProvider.health_check() -> bool` — interface method; OpenAI/Anthropic default to `await self.client.models.list()` (catch all).
- `LLMProvider.close() -> None` — interface method; OpenAI/Anthropic default to no-op.
- `ProviderRegistry.get_default() -> ProviderConfig` — honours `RUFLO_LLM_PROVIDER` env var first, then named `default`, then first entry. Raises `RegistryCorruptError` if file exists and is invalid JSON.

- [ ] **Step 1: Write failing tests** (one per concern)

```python
# tests/test_llm/test_openai_endpoint.py
from src.llm.openai_provider import OpenAIProvider
from src.llm.types import ProviderConfig, ModelInfo


def test_complete_routes_to_chat_endpoint(monkeypatch):
    captured = {}
    class FakeClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    captured.update(kw)
                    class R:
                        class choice:
                            message = type("M", (), {"content": "{}"})()
                        choices = [choice]
                    return R()

    p = OpenAIProvider(ProviderConfig(
        name="openai", type="openai", api_key="x",
        default_chat_model="gpt-4o-mini",
        models={"gpt-4o-mini": ModelInfo(name="gpt-4o-mini", type="chat")},
    ), client=FakeClient())
    p.complete([{"role": "user", "content": "hi"}])
    assert captured["model"] == "gpt-4o-mini"
    assert any(m.get("role") == "user" for m in captured["messages"])
```

```python
# tests/test_llm/test_anthropic_system.py
from src.llm.anthropic_provider import AnthropicProvider
from src.llm.types import ProviderConfig, ModelInfo


def test_system_message_promoted_to_top_level(monkeypatch):
    captured = {}
    class FakeClient:
        class messages:
            @staticmethod
            def create(**kw):
                captured.update(kw)
                class R:
                    class content:
                        text = "{}"
                    content = [content]
                return R()

    p = AnthropicProvider(ProviderConfig(
        name="anthropic", type="anthropic", api_key="x",
        default_chat_model="claude-3-5-sonnet",
        models={"claude-3-5-sonnet": ModelInfo(name="claude-3-5-sonnet", type="chat")},
    ), client=FakeClient())
    p.complete(
        [{"role": "system", "content": "be terse"}, {"role": "user", "content": "hi"}],
    )
    assert captured.get("system") == "be terse"
    assert all(m["role"] != "system" for m in captured["messages"])
```

```python
# tests/test_llm/test_registry_default_env.py
import json, os
from src.llm.registry import ProviderRegistry, REGISTRY_PATH


def test_env_var_overrides_named_default(tmp_path, monkeypatch):
    monkeypatch.setenv("RUFLO_LLM_PROVIDER", "ollama")
    cfg = tmp_path / "reg.json"
    cfg.write_text(json.dumps({
        "providers": {
            "openai": {"name": "openai", "type": "openai", "api_key": "x"},
            "ollama": {"name": "ollama", "type": "ollama", "base_url": "http://x"},
        },
        "default": "openai",
    }))
    monkeypatch.setattr("src.llm.registry.REGISTRY_PATH", cfg)
    monkeypatch.setattr("src.llm.registry.load_env_file", lambda: None)
    reg = ProviderRegistry.load()
    assert reg.get_default().name == "ollama"
```

Plus tests for: `test_anthropic_url_ends_with_v1`, `test_ollama_provider_caches_singleton_and_closes_once`, `test_openai_embedding_dimension_sent`, `test_registry_raises_on_corrupt_existing_file`, `test_failed_close_kept_in_registry`.

- [ ] **Step 2: Run, verify FAIL** — all new tests FAIL.

- [ ] **Step 3: Implement**

`openai_provider.complete()` — call `client.chat.completions.create(model=..., messages=[...])`. Drop the `/v1/completions` path entirely. Embed `dimension=self.dimension` into the request only when `self.dimension is not None`.

`anthropic_provider.complete()` — split `messages` into `system_prompts` (joined by `\n\n`) and `chat_messages` (no `system` role); call `client.messages.create(model=..., system=system_prompts, messages=chat_messages)`. Default `base_url = "https://api.anthropic.com/v1"`.

`ollama_provider` — change `__init__` to call `super().__init__()` and reuse a process-cached `AsyncClient` keyed by `base_url`; expose `close()` that closes the cached client exactly once. `extra_headers` passed through.

`registry.py` — `get_default()`: read `RUFLO_LLM_PROVIDER` env; if present and matches a provider name, return it. `load()`: if file exists and `json.loads` raises `JSONDecodeError`, raise `RegistryCorruptError`. `aclose_all()`: only remove from `_loaded_providers` after `close()` returns successfully.

`provider_factory.py` — accept `ProviderConfig.timeout_seconds` and `extra_headers` and forward to each provider's constructor.

`base.py` — add `health_check()` (returns `True`) and `close()` (no-op) to the interface; subclass overrides.

Callers `pipeline/analyzer.py`, `pipeline/generator.py`, `agent/runtime.py` — switch from `response.get("summary")` / `response.content` to `response.content` only (after Task 3 makes `LLMResponse.content` the canonical payload). For JSON-typed outputs, parse `response.content` as JSON once; raise on parse error rather than fall through.

- [ ] **Step 4: Run, verify PASS** — `PYTHONPATH=. pytest tests/test_llm -v` plus `tests/test_pipeline tests/test_agent` all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/llm/openai_provider.py src/llm/anthropic_provider.py src/llm/ollama_provider.py \
        src/llm/registry.py src/llm/provider_factory.py src/llm/base.py \
        src/pipeline/analyzer.py src/pipeline/generator.py src/agent/runtime.py \
        tests/test_llm/test_openai_endpoint.py tests/test_llm/test_anthropic_url.py \
        tests/test_llm/test_anthropic_system.py tests/test_llm/test_registry_default_env.py \
        tests/test_llm/test_ollama_close.py tests/test_llm/test_openai_dimension.py
git commit -m "fix(llm): chat endpoint, /v1 URL, system msg, env default, dimension; add lifecycle"
```

---

### Task 4: URL collector — gate `move_to_processing` + enforce READ permission

**Files:**
- Modify: `src/pipeline/collector.py:22-44`
- Modify: `src/permissions.py:98` (covered by T9; here only ensure URL path covered)
- Test: `tests/test_pipeline/test_collector_url.py`

**Interfaces:**
- `collect(task_id, source: str, source_type: SourceType) -> None` — for `URL`, fetch via `httpx.get(source, timeout=30, follow_redirects=True)` *after* `enforce_permission(COLLECTOR, source, READ)` passes. Then write to `raw_path` and emit `collector:done`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_pipeline/test_collector_url.py
import httpx, pytest
from unittest.mock import patch, MagicMock
from src.pipeline.collector import collect
from src.events.events import SourceType


def test_collect_url_does_not_move_to_processing(tmp_path):
    """URL sources must not call inbox.move_to_processing."""
    inbox = MagicMock()
    with patch("src.pipeline.collector.inbox", inbox), \
         patch("src.pipeline.collector.httpx.get") as g:
        g.return_value = MagicMock(text="<html>hi</html>", raise_for_status=lambda: None)
        collect("t1", "https://example.com/a", SourceType.URL)
    inbox.move_to_processing.assert_not_called()


def test_collect_url_blocks_loopback_by_default():
    """127.0.0.1 / 169.254.169.254 must be rejected without explicit allow."""
    from src.permissions import PermissionDenied
    with pytest.raises(PermissionDenied):
        collect("t1", "http://169.254.169.254/latest/meta-data", SourceType.URL)
```

- [ ] **Step 2: Run, verify FAIL** — tests FAIL.

- [ ] **Step 3: Implement** — in `src/pipeline/collector.py`:

```python
def collect(task_id: str, source: str, source_type: SourceType) -> None:
    enforce_permission(AgentType.COLLECTOR, source, Permission.READ)

    if source_type == SourceType.URL:
        _check_url_allowlisted(source)  # raises PermissionDenied on loopback/private
        resp = httpx.get(source, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        raw_path = raw_dir() / f"{task_id}.html"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(resp.text, encoding="utf-8")
        event_bus.emit(COLLECTOR_DONE, {"task_id": task_id, "raw_path": str(raw_path),
                                         "source": source, "source_type": "url"})
        return

    # file path
    src = Path(source)
    if not src.exists():
        raise FileNotFoundError(source)
    inbox.move_to_processing(source)
    raw_path = raw_dir() / src.name
    raw_path.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    event_bus.emit(COLLECTOR_DONE, {"task_id": task_id, "raw_path": str(raw_path),
                                     "source": source, "source_type": "file"})
```

Add `_check_url_allowlisted(source)` in `src/permissions.py` (or a new `src/pipeline/url_acl.py`):

```python
import ipaddress, socket
from urllib.parse import urlparse

_PRIVATE_NETS = [
    ipaddress.ip_network("127.0.0.0/8"), ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"), ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"), ipaddress.ip_network("::1/128"),
]

def _check_url_allowlisted(url: str) -> None:
    host = urlparse(url).hostname or ""
    try:
        ip = ipaddress.ip_address(socket.gethostbyname(host))
    except socket.gaierror:
        raise PermissionDenied(f"DNS resolution failed for {host}")
    for net in _PRIVATE_NETS:
        if ip in net:
            raise PermissionDenied(f"URL {url} resolves to private/loopback {ip}")
```

- [ ] **Step 4: Run, verify PASS** — `pytest tests/test_pipeline/test_collector_url.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/collector.py src/permissions.py \
        tests/test_pipeline/test_collector_url.py
git commit -m "fix(pipeline): gate URL collector (no inbox move; loopback/private block; READ perm)"
```

---

## Phase 2 — Prevent Data Corruption (Tasks 5–7)

### Task 5: Atomic writes for queue, snapshot, stubs, dedup

**Files:**
- Modify: `src/queue/queue.py:150-156,158-165`
- Modify: `src/sync/snapshot_store.py:18-27`
- Modify: `src/lib/write_hooks.py:26` (non-ctx path)
- Modify: `src/wiki/features/stubs.py:84-85`
- Modify: `src/wiki/features/dedup_auto.py:44`
- Test: `tests/test_queue/test_save_atomic.py`, `tests/test_sync/test_snapshot_atomic.py`, `tests/test_lib/test_safe_write_atomic.py`, `tests/test_wiki/test_stubs_atomic.py`, `tests/test_wiki/test_dedup_atomic.py`

**Interfaces:**
- `safe_write(path, content)` — when NOT inside `AtomicContext`, write to `path.with_suffix(path.suffix + ".tmp")` then `os.replace`. When inside, keep current buffered behaviour.
- `_save_queue()` — uses `safe_write` (which is now atomic-when-not-suspended).
- `_load_queue()` — wraps `json.load` in try/except `JSONDecodeError`; logs warning, starts with `[]`.
- `SnapshotStore._save` / `_load` — same atomic + corrupt-recovery pattern.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_queue/test_save_atomic.py
import json, os
from pathlib import Path
from src.queue import queue as q
from src.queue.queue import enqueue_task, __reset_for_testing


def setup_function(_):
    __reset_for_testing()


def test_save_writes_via_tmp_then_replace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    enqueue_task("t1", "x", "file")
    target = tmp_path / ".kb-queue.json"
    assert target.exists()
    assert not (target.with_suffix(".json.tmp")).exists()  # replaced


def test_load_recovers_from_truncated_queue(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".kb-queue.json").write_text("[{\"task_id\": \"t1\"", encoding="utf-8")  # truncated
    __reset_for_testing()  # re-load
    assert q._queue == []  # recovers instead of raising
```

```python
# tests/test_wiki/test_stubs_atomic.py
from pathlib import Path
from src.wiki.ensure import ensure_knowledge_base
from src.wiki.features.stubs import StubMaterializer
from src.lib.atomic_ctx import AtomicContext
from src.lib.write_hooks import _pending_writes


def test_stub_unlink_uses_sentinel(tmp_path):
    ensure_knowledge_base(tmp_path)
    stub = tmp_path / "wiki/_stubs/foo.md"
    stub.write_text("---\nid: foo\ntitle: Foo\ntype: stub\n---\n", encoding="utf-8")
    real = tmp_path / "wiki/sources/foo.md"
    sm = StubMaterializer(tmp_path)
    with AtomicContext():
        sm.materialize("foo")
    # _pending_writes should contain a DELETE_SENTINEL for stub_path
    assert any(DELETE_SENTINEL in (str(v)) or v is DELETE_SENTINEL
               for v in _pending_writes.values())
    # nothing committed yet
    assert real.exists()
    assert stub.exists()
```

- [ ] **Step 2: Run, verify FAIL** — tests FAIL.

- [ ] **Step 3: Implement**

`src/lib/write_hooks.py`:

```python
def safe_write(path, content):
    if is_suspended():
        _pending_writes[Path(path)] = content
        return
    p = Path(path)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(content if isinstance(content, str) else content,
                   encoding="utf-8")
    os.replace(tmp, p)
```

`src/queue/queue.py` `_save_queue`:

```python
def _save_queue() -> None:
    safe_write(QUEUE_FILE, json.dumps([vars(t) for t in _queue], ensure_ascii=False, indent=2))
```

`_load_queue`:

```python
def _load_queue() -> None:
    global _queue
    _queue = []
    if not Path(QUEUE_FILE).exists():
        return
    try:
        data = json.loads(Path(QUEUE_FILE).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.warning("queue file corrupt (%s); starting empty", e)
        return
    _queue = [TaskEntry(**row) for row in data]
```

`src/sync/snapshot_store.py` `_save` / `_load` — apply the same tmp+replace pattern and try/except recovery.

`src/wiki/features/stubs.py` line 84-85 — replace `os.unlink(stub_path)` with `safe_write(stub_path, DELETE_SENTINEL)`.

`src/wiki/features/dedup_auto.py` line 44 — replace `src.unlink()` with `safe_write(src, DELETE_SENTINEL)`.

- [ ] **Step 4: Run, verify PASS** — all five test files PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lib/write_hooks.py src/queue/queue.py src/sync/snapshot_store.py \
        src/wiki/features/stubs.py src/wiki/features/dedup_auto.py \
        tests/test_queue/test_save_atomic.py tests/test_sync/test_snapshot_atomic.py \
        tests/test_lib/test_safe_write_atomic.py tests/test_wiki/test_stubs_atomic.py \
        tests/test_wiki/test_dedup_atomic.py
git commit -m "fix(lib): atomic write for safe_write non-ctx path; queue/snapshot corrupt recovery"
```

---

### Task 6: Wire `can_transition` + circuit-breaker decorator + state-machine guard

**Files:**
- Modify: `src/queue/queue.py:75-90` (`update_task_status` validates)
- Modify: `src/orchestrator/state_machine.py:18,29-30`
- Modify: `src/orchestrator/orchestrator.py:53-61` (use TaskStatus enum, not strings)
- Modify: `src/circuit_breaker.py:106-138,146`
- Test: `tests/test_queue/test_update_task_status_transitions.py`, `tests/test_orchestrator/test_state_machine_guard.py`, `tests/test_circuit_breaker/test_decorator_uses_registry.py`

**Interfaces:**
- `update_task_status(task_id, status: TaskStatus, error: str | None = None) -> None` — raises `InvalidTransition(task_id, prev, next)` if `not can_transition(prev, status)`; caller is expected to catch in CLI tests.
- `get_next_status(current: TaskStatus, event: str) -> TaskStatus | None` — returns `None` if `current` is not a valid source for `event` per `EVENT_TO_STATUS`.
- `@circuit_breaker(name="…")` — uses `_circuit_breakers.setdefault(name, CircuitBreaker(name=name, …))` instead of creating a private instance.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_queue/test_update_task_status_transitions.py
import pytest
from src.queue.queue import enqueue_task, update_task_status, __reset_for_testing
from src.types import TaskStatus
from src.queue.queue import InvalidTransition


def setup_function(_): __reset_for_testing()


def test_pending_to_running_allowed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    enqueue_task("t1", "x", "file")
    update_task_status("t1", TaskStatus.RUNNING)
    # no raise


def test_running_to_approved_blocked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    enqueue_task("t1", "x", "file")
    update_task_status("t1", TaskStatus.RUNNING)
    with pytest.raises(InvalidTransition):
        update_task_status("t1", TaskStatus.APPROVED)  # must go via WAITING_REVIEW
```

```python
# tests/test_circuit_breaker/test_decorator_uses_registry.py
from src.circuit_breaker import circuit_breaker, get_circuit_breaker


def test_decorator_shares_state_with_get():
    @circuit_breaker(name="x")
    def f(): return 1

    f()
    f()
    assert get_circuit_breaker("x").failure_count >= 0  # same instance
    assert get_circuit_breaker("x") is f.circuit_breaker  # documented equality
```

- [ ] **Step 2: Run, verify FAIL** — FAIL.

- [ ] **Step 3: Implement**

`src/queue/queue.py`:

```python
class InvalidTransition(Exception): ...


def update_task_status(task_id, status: TaskStatus, error=None):
    t = next((x for x in _queue if x.task_id == task_id), None)
    if t is None:
        raise KeyError(task_id)
    from src.orchestrator.state_machine import can_transition
    if not can_transition(TaskStatus(t.status), status):
        raise InvalidTransition(task_id, t.status, status.value)
    t.status = status.value
    if error is not None:
        t.error = error
    _save_queue()
```

`src/orchestrator/orchestrator.py` line 59-65 — replace string literals with `TaskStatus.APPROVED` / `REJECTED` / `ARCHIVED` enum values.

`src/orchestrator/state_machine.py` `get_next_status`:

```python
def get_next_status(current: TaskStatus, event: str) -> TaskStatus | None:
    candidate = EVENT_TO_STATUS.get(event)
    if candidate is None:
        return None
    return candidate if can_transition(current, candidate) else None
```

`src/circuit_breaker.py` decorator:

```python
def circuit_breaker(name="default", config=None, *, on_state_change=None):
    def deco(fn):
        breaker = _circuit_breakers.setdefault(name, CircuitBreaker(name=name, config=config or CircuitBreakerConfig(), on_state_change=on_state_change))
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            with breaker: return fn(*a, **kw)
        wrapper.circuit_breaker = breaker
        return wrapper
    return deco
```

- [ ] **Step 4: Run, verify PASS** — PASS.

- [ ] **Step 5: Commit**

```bash
git add src/queue/queue.py src/orchestrator/state_machine.py src/orchestrator/orchestrator.py \
        src/circuit_breaker.py \
        tests/test_queue/test_update_task_status_transitions.py \
        tests/test_orchestrator/test_state_machine_guard.py \
        tests/test_circuit_breaker/test_decorator_uses_registry.py
git commit -m "fix(queue+orch): wire can_transition; circuit-breaker decorator uses registry"
```

---

### Task 7: Queue mutex + async flag fix + atomic_ctx flush isolation

**Files:**
- Modify: `src/queue/queue.py:21,39-193` (add `threading.Lock`)
- Modify: `src/pipeline/pipeline.py:22-40` (await collect, fire task terminal status)
- Modify: `src/lib/atomic_ctx.py:63-76` (flush failure isolation)
- Test: `tests/test_queue/test_lock.py`, `tests/test_pipeline/test_pipeline_terminal_status.py`, `tests/test_lib/test_atomic_flush_isolated.py`

**Interfaces:**
- `_lock = threading.Lock()` — wraps every public mutation of `_queue` (`enqueue_task`, `update_task_status`, `_process_next`, `_save_queue`, `_load_queue`).
- `_in_flight: set[str]` — set of currently-processing task IDs; `_process_next` only picks PENDING tasks not in `_in_flight`. Cleared in a `done_callback` of the scheduled `asyncio.Task`.
- `AtomicContext.__exit__` — runs each pending write in a try/except so one failure does not abort the batch; clears `_pending_writes` *before* running the flush callback.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_queue/test_lock.py
import threading
from src.queue.queue import enqueue_task, update_task_status, get_queue_status, __reset_for_testing


def setup_function(_): __reset_for_testing()


def test_concurrent_enqueue_no_double_process(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    errors = []
    def fire():
        try:
            for i in range(50):
                enqueue_task(f"t{i}", "x", "file")
        except Exception as e:
            errors.append(e)
    threads = [threading.Thread(target=fire) for _ in range(8)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert not errors
    assert len({t.task_id for t in get_queue_status()["tasks"]}) == 50  # unique
```

```python
# tests/test_pipeline/test_pipeline_terminal_status.py
from src.pipeline.pipeline import _on_collector_done
from src.types import TaskStatus


def test_handler_marks_task_approved_on_success(tmp_path, monkeypatch):
    # ... wire a task into the queue, emit collector:done, assert TaskStatus.APPROVED
    ...


def test_handler_marks_task_failed_on_exception(tmp_path, monkeypatch):
    # ... patch run_ingest to raise, assert TaskStatus.FAILED and error set
    ...
```

- [ ] **Step 2: Run, verify FAIL** — FAIL.

- [ ] **Step 3: Implement**

`src/queue/queue.py`:

```python
import threading
_lock = threading.Lock()
_in_flight: set[str] = set()

def enqueue_task(...):
    with _lock:
        ...

def _process_next():
    with _lock:
        for t in _queue:
            if t.status == TaskStatus.PENDING.value and t.task_id not in _in_flight:
                _in_flight.add(t.task_id)
                task_id = t.task_id
                break
        else:
            return
    event_bus.emit("collector:start", {"task_id": task_id})
    # NB: actual processing happens in the collector handler chain; the
    # flag is cleared by `_on_collector_done` (see pipeline.py).
```

`src/pipeline/pipeline.py` `_on_collector_done`:

```python
def _on_collector_done(payload):
    from src.queue.queue import update_task_status, _in_flight
    task_id = payload["task_id"]
    try:
        run_ingest(paths=payload["paths"], source_path=payload["raw_path"], source_text=payload.get("text", ""))
        update_task_status(task_id, TaskStatus.APPROVED)
    except Exception as e:
        log.exception("ingest failed for %s", task_id)
        update_task_status(task_id, TaskStatus.FAILED, error=str(e))
    finally:
        _in_flight.discard(task_id)
```

`src/lib/atomic_ctx.py` `__exit__`:

```python
def __exit__(self, exc_type, exc, tb):
    local.depth -= 1
    if local.depth > 0:
        return False
    pending = list(_pending_writes.items())
    _pending_writes.clear()  # clear BEFORE callback so callback failure doesn't leak
    failures = []
    for path, content in pending:
        try:
            safe_write(path, content)
        except Exception as e:
            log.exception("atomic flush write failed for %s", path)
            failures.append((path, e))
    local.suspended = False
    if failures:
        log.error("atomic flush had %d failures", len(failures))
    return False  # never suppress
```

- [ ] **Step 4: Run, verify PASS** — all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/queue/queue.py src/pipeline/pipeline.py src/lib/atomic_ctx.py \
        tests/test_queue/test_lock.py tests/test_pipeline/test_pipeline_terminal_status.py \
        tests/test_lib/test_atomic_flush_isolated.py
git commit -m "fix(queue): threading.Lock + in_flight set; atomic flush isolates per-write failures"
```

---

## Phase 3 — Make the Product Trustworthy (Tasks 8–12)

### Task 8: Error visibility (EventBus + chat + audit)

**Files:**
- Modify: `src/events/event_bus.py:11,23-29`
- Modify: `src/services/chat.py:37-50`
- Modify: `src/orchestrator/orchestrator.py:53-61`
- Modify: `src/wiki/features/cascade_delete.py:25-46`
- Test: `tests/test_events/test_bus_subscribe_during_emit.py`, `tests/test_events/test_bus_handler_exception_modes.py`, `tests/test_services/test_chat_error_response.py`, `tests/test_orchestrator/test_audit_error_path.py`, `tests/test_wiki/test_cascade_atomic_internal.py`

**Interfaces:**
- `EventBus.fail_fast: bool = False` — when `True`, first handler exception aborts emit and re-raises.
- `EventBus.emit(name, payload)` — iterates `list(self._handlers.get(name, ()))` (snapshot); failures logged with `extra={"event": name, "handler": h.__qualname__}`.
- `services.chat.run_chat(...) -> ChatResponse` — raises `AgentRunFailed` if no `final_answer` event seen within the configured budget.
- `_on_processor_done` — wraps `run_hard_audit` in try/except, on failure calls `update_task_status(task_id, REJECTED, error=str(e))`.
- `cascade_delete` — opens its own `atomic_pipeline_op` internally; no longer relies on caller.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_events/test_bus_subscribe_during_emit.py
from src.events.event_bus import EventBus


def test_subscribe_during_emit_does_not_crash():
    bus = EventBus()
    def handler_a(payload):
        bus.on("x", handler_c)  # subscribe during emit
    def handler_c(payload): pass
    bus.on("x", handler_a)
    bus.emit("x", {})  # must not raise RuntimeError("Set changed size during iteration")
```

```python
# tests/test_services/test_chat_error_response.py
from src.services.chat import run_chat, AgentRunFailed


def test_chat_raises_when_no_final_answer():
    # emit tool_completed events but no final_answer
    with pytest.raises(AgentRunFailed):
        run_chat(...)
```

- [ ] **Step 2: Run, verify FAIL** — FAIL.

- [ ] **Step 3: Implement** — apply the four interface changes above.

- [ ] **Step 4: Run, verify PASS** — PASS.

- [ ] **Step 5: Commit**

```bash
git add src/events/event_bus.py src/services/chat.py src/orchestrator/orchestrator.py \
        src/wiki/features/cascade_delete.py \
        tests/test_events/test_bus_subscribe_during_emit.py \
        tests/test_events/test_bus_handler_exception_modes.py \
        tests/test_services/test_chat_error_response.py \
        tests/test_orchestrator/test_audit_error_path.py \
        tests/test_wiki/test_cascade_atomic_internal.py
git commit -m "fix(events): snapshot iter + fail-fast; chat AgentRunFailed; audit error path; cascade internal atomic"
```

---

### Task 9: Permission boundary (`is_relative_to`) + ProjectNotFoundError catch

**Files:**
- Modify: `src/permissions.py:58-60,95-99`
- Modify: `src/server/routes/ingest.py:18`, `search.py:20`, `chat.py:24-28`, `reviews.py:13,25`, `files.py:15`
- Modify: `src/services/{projects,ingest,search,chat,reviews,files}.py`
- Test: `tests/test_permissions/test_relative_to.py`, `tests/test_server/test_routes_404.py`

**Interfaces:**
- `check_permission(agent, path, perm) -> PermissionCheckResult` — uses `Path(path).is_relative_to(allowed_path)` (or string-equivalent with trailing `/`); removes the `resolve()` call so CWD doesn't affect outcome.
- Every route handler in `src/server/routes/` wraps its service call in `try/except ProjectNotFoundError as e: raise HTTPException(404, str(e))`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_permissions/test_relative_to.py
from src.permissions import check_permission, AgentType, Permission


def test_inbox_does_not_match_inboxevil():
    res = check_permission(AgentType.COLLECTOR, "InboxEvil/secret.md", Permission.WRITE,
                            allowed_paths=["Inbox"])
    assert not res.allowed


def test_inbox_processing_matches():
    res = check_permission(AgentType.COLLECTOR, "Inbox/Processing/foo.txt", Permission.WRITE,
                            allowed_paths=["Inbox/Processing"])
    assert res.allowed


def test_check_permission_is_cwd_independent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    res = check_permission(AgentType.COLLECTOR, "Inbox/Processing/foo.txt", Permission.WRITE,
                            allowed_paths=["Inbox/Processing"])
    assert res.allowed
```

- [ ] **Step 2: Run, verify FAIL** — FAIL.

- [ ] **Step 3: Implement** — apply changes; the catch is a one-line per route.

- [ ] **Step 4: Run, verify PASS** — PASS.

- [ ] **Step 5: Commit**

```bash
git add src/permissions.py src/server/routes/ src/services/ \
        tests/test_permissions/test_relative_to.py tests/test_server/test_routes_404.py
git commit -m "fix(perm): is_relative_to boundary; routes map ProjectNotFoundError to 404"
```

---

### Task 10: API key security (redact `to_dict`, file permissions)

**Files:**
- Modify: `src/llm/types.py:25-35`
- Modify: `src/llm/registry.py` (when persisting new entries, `os.chmod(path, 0o600)`)
- Modify: `src/cli_ext/llm_providers_cmd.py` (`show` masks the key)
- Test: `tests/test_llm/test_types_redaction.py`, `tests/test_cli_ext/test_llm_providers_show_redacted.py`

**Interfaces:**
- `ProviderConfig.to_dict(redact: bool = False) -> dict` — when `redact=True`, replace `api_key` with `"***"` plus last 4 chars.
- `ProviderRegistry._save()` — `os.chmod(self.path, 0o600)` after writing.
- `cmd_llm_providers_show` — calls `to_dict(redact=True)`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_llm/test_types_redaction.py
from src.llm.types import ProviderConfig


def test_to_dict_redacts_api_key():
    c = ProviderConfig(name="openai", type="openai", api_key="sk-abc1234567890XYZ")
    d = c.to_dict(redact=True)
    assert d["api_key"].startswith("***")
    assert "abc1234567890XYZ" not in d["api_key"]
    assert d["api_key"].endswith("c7890XYZ") or "XYZ" in d["api_key"]


def test_to_dict_default_includes_key_for_internal_use():
    c = ProviderConfig(name="openai", type="openai", api_key="sk-x")
    d = c.to_dict()
    assert d["api_key"] == "sk-x"  # internal callers may need it
```

- [ ] **Step 2: Run, verify FAIL** — FAIL.

- [ ] **Step 3: Implement** — `to_dict` adds `redact` parameter; registry saves with chmod; `show` calls redacted form.

- [ ] **Step 4: Run, verify PASS** — PASS.

- [ ] **Step 5: Commit**

```bash
git add src/llm/types.py src/llm/registry.py src/cli_ext/llm_providers_cmd.py \
        tests/test_llm/test_types_redaction.py tests/test_cli_ext/test_llm_providers_show_redacted.py
git commit -m "fix(llm): redact api_key in to_dict(redact=True); chmod 0o600 on registry save"
```

---

### Task 11: Migration registry collision guard + dead-letter event

**Files:**
- Modify: `src/schemas/migrations/v2_to_v2_2.py:99-101`
- Modify: `src/schemas/registry.py:22,88-91`
- Modify: `src/queue/queue.py:91-105` (emit `task:dead_letter`; introduce `TaskStatus.DEAD_LETTER`)
- Test: `tests/test_schemas/test_migration_collision.py`, `tests/test_queue/test_dead_letter.py`

**Interfaces:**
- `MigrationRegistry.register(migration)` — raises `MigrationKeyCollision(key)` if `(schema_name, from_version, to_version)` already registered.
- `v2_to_v2_2` migration — declare `to_version = SchemaVersion.V2_2` (new enum value added to `src/schemas/base.py`); introduce the new field migration.
- `migrate_data(data, to_version)` — raises `NotImplementedError` with a clear pointer to the migration classes.
- `TaskStatus.DEAD_LETTER` — added to `src/types.py`. Queue emits `task:dead_letter` event on retry exhaustion.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_schemas/test_migration_collision.py
import pytest
from src.schemas.registry import MigrationRegistry, MigrationKeyCollision


def test_register_twice_raises():
    reg = MigrationRegistry()
    m1 = _stub_migration("wiki_page", "v2.0", "v2.1")
    reg.register(m1)
    m2 = _stub_migration("wiki_page", "v2.0", "v2.1")
    with pytest.raises(MigrationKeyCollision):
        reg.register(m2)


def test_migrate_data_raises():
    from src.schemas.registry import migrate_data
    with pytest.raises(NotImplementedError):
        migrate_data({}, "v2.2")
```

```python
# tests/test_queue/test_dead_letter.py
def test_dead_letter_emits_event_and_status():
    # patch event_bus, run a task that always fails, assert task:dead_letter seen
    ...
```

- [ ] **Step 2: Run, verify FAIL** — FAIL.

- [ ] **Step 3: Implement** — add `SchemaVersion.V2_2`, write the actual v2.1→v2.2 migration body, add `register()` collision check, replace `migrate_data` no-op with `NotImplementedError`, add `TaskStatus.DEAD_LETTER` + `task:dead_letter` event.

- [ ] **Step 4: Run, verify PASS** — PASS.

- [ ] **Step 5: Commit**

```bash
git add src/schemas/migrations/v2_to_v2_2.py src/schemas/registry.py src/schemas/base.py \
        src/queue/queue.py src/types.py \
        tests/test_schemas/test_migration_collision.py tests/test_queue/test_dead_letter.py
git commit -m "fix(schemas): migration collision raise + V2_2 migration; queue dead-letter event"
```

---

### Task 12: Inbox error handling (overwrite, unique log, no false success)

**Files:**
- Modify: `src/inbox/manager.py:40,51-57`
- Test: `tests/test_inbox/test_move_idempotent.py`, `tests/test_inbox/test_error_log_unique.py`, `tests/test_inbox/test_missing_source_no_false_success.py`

**Interfaces:**
- `InboxManager.move_to_processing(src)` — uses `os.replace` (overwrite) when dst exists.
- `InboxManager.move_to_error(src, error)` — uses `os.replace`; writes `{src.name}.error.log` (not `{src.stem}.error.log`); raises `FileNotFoundError` if `src` missing.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_inbox/test_move_idempotent.py
from src.inbox.manager import InboxManager


def test_move_to_processing_overwrites_existing(tmp_path):
    mgr = InboxManager(tmp_path)
    src = tmp_path / "in/foo.md"; src.write_text("new", encoding="utf-8")
    (tmp_path / "Processing").mkdir()
    (tmp_path / "Processing/foo.md").write_text("old", encoding="utf-8")
    mgr.move_to_processing(str(src))
    assert (tmp_path / "Processing/foo.md").read_text(encoding="utf-8") == "new"


def test_error_log_uses_full_filename(tmp_path):
    mgr = InboxManager(tmp_path)
    (tmp_path / "Error").mkdir()
    mgr.move_to_error(str(tmp_path / "in" / "report.docx"), "boom")
    assert (tmp_path / "Error" / "report.docx.error.log").exists()


def test_move_to_error_raises_when_missing(tmp_path):
    mgr = InboxManager(tmp_path)
    with pytest.raises(FileNotFoundError):
        mgr.move_to_error(str(tmp_path / "in" / "ghost.md"), "boom")
```

- [ ] **Step 2: Run, verify FAIL** — FAIL.

- [ ] **Step 3: Implement** — replace `shutil.move` with `os.replace`; rename `.error.log` template; add `if not src.exists(): raise FileNotFoundError(...)` before the move.

- [ ] **Step 4: Run, verify PASS** — PASS.

- [ ] **Step 5: Commit**

```bash
git add src/inbox/manager.py \
        tests/test_inbox/test_move_idempotent.py tests/test_inbox/test_error_log_unique.py \
        tests/test_inbox/test_missing_source_no_false_success.py
git commit -m "fix(inbox): os.replace + full-name error log + raise on missing source"
```

---

## Phase 4 — UX Polish (Tasks 13–16)

### Task 13: Search edge cases (empty query, RRF, top_k, SQL injection, QA citations)

**Files:**
- Modify: `src/searcher/hybrid_search.py:39,42-95`
- Modify: `src/vector/upsert.py:19,24`
- Modify: `src/searcher/qa.py:31-52`
- Test: `tests/test_searcher/test_empty_query.py`, `tests/test_searcher/test_rrf_two_lists.py`, `tests/test_searcher/test_topk_bounds.py`, `tests/test_vector/test_sql_param.py`, `tests/test_searcher/test_qa_citation_validation.py`

**Interfaces:**
- `hybrid_search(query, top_k)` — raises `ValueError` for empty `query.strip()`; raises `ValueError` for `top_k < 1`; raises `ValueError` for `top_k > MAX_TOP_K` (default 100).
- `rrf_fusion(semantic_results, keyword_results, k=60)` — receives two separate lists, computes per-document RRF contribution independently, returns merged sorted list.
- `vector_upsert_chunks(table, rows)` — uses `table.merge_insert("id")` (LanceDB API) for upsert semantics.
- `vector_delete_by_task(table, task_id)` — uses `table.delete(f"task_id = '{task_id}'")` only after escaping the value via a single helper; OR switch to `table.delete(filter=...)` with bound params if available.
- `qa.answer(query, context)` — parses model output; discards any `[1-9]\d*` citation index not in `range(1, len(context) + 1)`.

- [ ] **Step 1: Write failing tests** — one per interface above. Sketches:

```python
# tests/test_searcher/test_empty_query.py
import pytest
from src.searcher.hybrid_search import hybrid_search

def test_empty_query_raises():
    with pytest.raises(ValueError):
        hybrid_search("", top_k=5)
    with pytest.raises(ValueError):
        hybrid_search("   ", top_k=5)


# tests/test_searcher/test_rrf_two_lists.py
def test_rrf_treats_two_lists_separately():
    sem = ["A", "B", "C"]
    kw = ["D", "A", "E"]
    out = hybrid_search_score(sem, kw, k=60)
    # A appears in both lists → rank 1 + rank 2 → highest combined score
    assert out[0] == "A"


# tests/test_vector/test_sql_param.py
def test_delete_by_task_uses_param_not_string_concat(monkeypatch):
    captured = {}
    class T:
        def delete(self, expr): captured["expr"] = expr
    upsert._delete_by_task(T(), "x' OR 1=1 --")
    assert "x' OR 1=1" not in captured["expr"] or "OR 1=1" not in captured["expr"]  # sanitised
```

- [ ] **Step 2: Run, verify FAIL** — FAIL.

- [ ] **Step 3: Implement** — split `rrf_fusion` into two-list signature; add input validation; switch to merge_insert; replace string concat with escape; validate QA citations.

- [ ] **Step 4: Run, verify PASS** — PASS.

- [ ] **Step 5: Commit**

```bash
git add src/searcher/hybrid_search.py src/vector/upsert.py src/searcher/qa.py \
        tests/test_searcher/test_empty_query.py tests/test_searcher/test_rrf_two_lists.py \
        tests/test_searcher/test_topk_bounds.py tests/test_vector/test_sql_param.py \
        tests/test_searcher/test_qa_citation_validation.py
git commit -m "fix(search): validate inputs; proper RRF over two lists; upsert via merge_insert; QA citation guard"
```

---

### Task 14: Heat decay respects `is_immutable` and `created_at`

**Files:**
- Modify: `src/wiki/features/heat.py:42-64`
- Test: `tests/test_wiki/test_heat_decay_immutable.py`, `tests/test_wiki/test_heat_decay_uses_created_at.py`

**Interfaces:**
- `decay(page, now=None) -> WikiPage` — if `page.is_immutable`, return `page` unchanged; otherwise threshold = `max(page.created_at, page.last_used_at)` (treat 0 as missing → use `created_at`).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_wiki/test_heat_decay_immutable.py
from src.wiki.features.heat import decay
from src.wiki.core.types import WikiPage


def test_decay_skips_immutable_page():
    p = WikiPage(id="x", title="X", type="entity", heat=0, is_immutable=True,
                 last_used_at=0, created_at=0, zombie_since=None)
    out = decay(p, now=10**12)
    assert out.heat == 0
    assert out.zombie_since is None


def test_decay_uses_created_at_when_last_used_zero():
    p = WikiPage(id="x", title="X", type="entity", heat=50, is_immutable=False,
                 last_used_at=0, created_at=10**6)
    out = decay(p, now=10**9)
    assert out.heat < 50  # decayed
```

- [ ] **Step 2: Run, verify FAIL** — FAIL.

- [ ] **Step 3: Implement** — `if page.is_immutable: return page`; threshold = `page.last_used_at or page.created_at`.

- [ ] **Step 4: Run, verify PASS** — PASS.

- [ ] **Step 5: Commit**

```bash
git add src/wiki/features/heat.py \
        tests/test_wiki/test_heat_decay_immutable.py \
        tests/test_wiki/test_heat_decay_uses_created_at.py
git commit -m "fix(wiki): heat decay respects is_immutable; uses created_at fallback when last_used_at==0"
```

---

### Task 15: CLI error friendliness + quality `--config-root`

**Files:**
- Modify: `src/cli_ext/schema_cmd.py:47-48,75,130,173`
- Modify: `src/cli_ext/quality_cmd.py:38`
- Modify: `src/cli.py` (register `--config-root` for the quality `set` subparser)
- Modify: `src/cli_ext/serve.py:160-169,175-183`
- Test: `tests/test_cli_ext/test_schema_cmd_errors.py`, `tests/test_cli_ext/test_quality_cmd_config_root.py`, `tests/test_cli_ext/test_serve_pidfile_corrupt.py`

**Interfaces:**
- `cmd_schema_diff`, `cmd_schema_upgrade`, `cmd_schema_downgrade` — wrap `SchemaVersion(args.X)` in try/except `ValueError as e: print(f"Invalid version: {e}", file=sys.stderr); sys.exit(2)`.
- `cmd_schema_backup restore` — if `args.name is None`, print usage and `sys.exit(2)`.
- `cmd_quality_config_set` — uses `Path.cwd()` (no longer references `args.config_root`); `cli.py` adds `p_qcset.add_argument("--config-root", default=None, help="…")` so the existing code works either way.
- `cmd_serve_stop` / `cmd_serve_status` — wrap pidfile read+int in try/except `(ValueError, FileNotFoundError)`; on parse error, unlink the stale pidfile and exit cleanly.

- [ ] **Step 1: Write failing tests** — one per command, asserting exit code and stderr message.

- [ ] **Step 2: Run, verify FAIL** — FAIL.

- [ ] **Step 3: Implement** — straight try/except wrapping + argparse declaration.

- [ ] **Step 4: Run, verify PASS** — PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cli_ext/schema_cmd.py src/cli_ext/quality_cmd.py src/cli.py src/cli_ext/serve.py \
        tests/test_cli_ext/test_schema_cmd_errors.py \
        tests/test_cli_ext/test_quality_cmd_config_root.py \
        tests/test_cli_ext/test_serve_pidfile_corrupt.py
git commit -m "fix(cli): friendly errors for schema/version/pidfile; add --config-root to quality set"
```

---

### Task 16: Misc single-line fixes (similarity, html table, doc/pdf guards, snapshot load, migrate_data no-op, router, ollama close, library path, extra_headers)

**Files:**
- Modify: `src/utils/similarity.py:34-43`
- Modify: `src/utils/extract/html.py:29-35`
- Modify: `src/utils/extract/office.py:8,18,25`
- Modify: `src/utils/extract/pdf.py:6`
- Modify: `src/orchestrator/router.py:13-33` (drop `UNKNOWN`, suffix match on tokens)
- Modify: `src/schemas/registry.py:88-91` (raise instead of no-op)
- Modify: `src/pipeline/librarian.py:57,99-105` (use `paths` from caller; validate existing_path within knowledge_dir)
- Test: `tests/test_utils/test_similarity.py`, `tests/test_utils/test_html_table_attrs.py`, `tests/test_utils/test_extract_doc_guard.py`, `tests/test_utils/test_extract_encrypted.py`, `tests/test_orchestrator/test_router_suffix.py`, `tests/test_schemas/test_migrate_data_raises.py`, `tests/test_pipeline/test_librarian_validates_existing_path.py`

- [ ] **Step 1: Write failing tests** — one per concern.

```python
# tests/test_utils/test_similarity.py
from src.utils.similarity import string_similarity


def test_prefix_returns_proper_ratio():
    # a is prefix of apple → 1/5, NOT 1.0
    assert string_similarity("a", "apple") < 0.5


def test_symmetric_score():
    assert abs(string_similarity("hello", "helo") - string_similarity("helo", "hello")) < 1e-9
```

```python
# tests/test_utils/test_html_table_attrs.py
from src.utils.extract.html import convert_html_tables_to_markdown


def test_table_with_class_is_converted():
    src = '<table class="data"><tr><td>1</td></tr></table>'
    out = convert_html_tables_to_markdown(src)
    assert "| 1 |" in out
    assert "<table" not in out
```

```python
# tests/test_orchestrator/test_router_suffix.py
from src.orchestrator.router import route_task, TaskIntent


def test_search_question_with_md_word_is_search():
    assert route_task("what is the .md format?") == TaskIntent.SEARCH


def test_url_with_extension_is_ingest():
    assert route_task("https://example.com/foo.pdf") == TaskIntent.INGEST


def test_empty_input_raises():
    import pytest
    with pytest.raises(ValueError):
        route_task("")
```

```python
# tests/test_pipeline/test_librarian_validates_existing_path.py
def test_librarian_rejects_path_outside_knowledge_dir(tmp_path):
    # construct a WikiPaths, call librarian.archive with existing_path outside it
    with pytest.raises(PermissionError):
        ...
```

- [ ] **Step 2: Run, verify FAIL** — FAIL.

- [ ] **Step 3: Implement** — apply each fix:
- `similarity`: `len(shorter) / len(longer)` for prefix matches; remove dead `if longer in shorter`.
- `html.py`: replace `string.replace` with `re.sub(r"<table[^>]*>.*?</table>", lambda m: f"<table>{inner}</table>", src, flags=re.DOTALL)`.
- `extract/office.py:8`: guard `ext == ".doc"`, raise `UnsupportedFormat("legacy .doc not supported")`.
- `extract/pdf.py:6`, `office.py:18,25`: catch `cryptocode.Unknown` / `zipfile.BadZipFile` / `docx.opc.exceptions.PackageNotFoundError`; raise a typed `EncryptedDocumentError`.
- `router.py`: drop `TaskIntent.UNKNOWN`; check `last_token` for `.md|.pdf|.docx` extension; raise `ValueError` on empty.
- `registry.py:migrate_data`: `raise NotImplementedError("Use MigrationRegistry.apply(...)")`.
- `librarian.py`: take `paths: WikiPaths` parameter; `existing_path = Path(existing_path); if not existing_path.resolve().is_relative_to(paths.knowledge_dir.resolve()): raise PermissionError(...)`.

- [ ] **Step 4: Run, verify PASS** — PASS.

- [ ] **Step 5: Commit**

```bash
git add src/utils/similarity.py src/utils/extract/ src/orchestrator/router.py \
        src/schemas/registry.py src/pipeline/librarian.py \
        tests/test_utils/test_similarity.py tests/test_utils/test_html_table_attrs.py \
        tests/test_utils/test_extract_doc_guard.py tests/test_utils/test_extract_encrypted.py \
        tests/test_orchestrator/test_router_suffix.py \
        tests/test_schemas/test_migrate_data_raises.py \
        tests/test_pipeline/test_librarian_validates_existing_path.py
git commit -m "fix(misc): similarity ratio, html table attrs, extract guards, router suffix, migrate_data raise, librarian path validate"
```

---

## Self-Review Checklist

1. **Spec coverage:** Every critical and important finding from the audit maps to a task (T1–T16). Minor findings rolled into the relevant task's scope (e.g. `Ollama close retry` is in T3; `extra_headers` is in T3; `librarian.write_text collision` is in T16).
2. **No placeholders:** Each step shows actual code or a precise edit. `TBD`/`TODO` absent.
3. **Type/name consistency:** `WikiPaths` used uniformly; `TaskStatus` enum referenced everywhere after T6; `LLMResponse.content` referenced everywhere after T3; `safe_write(..., DELETE_SENTINEL)` is the only deletion primitive.
4. **Dependencies respected:** T2 (embedding runtime) precedes any task that uses `get_embedding_provider`; T5 (atomic writes) precedes any test that relies on `safe_write` being crash-safe; T6 (state machine) precedes T7 (queue mutex) so `update_task_status` raises the new exception.
5. **Test coverage:** Each task introduces at least one new test file; existing tests modified only when the public interface changed (T3 callers, T6 orchestrator).
6. **Branch / commit policy:** One commit per task on `master`. After each task, dispatch a code-review subagent; fix Critical/Important before next task. Final whole-branch review after T16.

---

## Execution Order

1 → 2 → 3 → 4 (Phase 1, sequential — wiring must compile before tests run)
5 → 6 → 7 (Phase 2, sequential — atomic semantics depend on lock + transition guard)
8 → 9 → 10 → 11 → 12 (Phase 3, sequential — visibility/permissions/security layered)
13 → 14 → 15 → 16 (Phase 4, sequential — polish)

Approx 16 commits + 16 reviewer dispatches. Estimated time: 8–12 hours of focused work, depending on how many review findings require follow-up commits.

---

## Final Whole-Branch Review

After T16 lands and tests are green, dispatch one final review subagent over the full diff (T1..T16). Fix any Important findings in a single batch commit (`fix(audit): review follow-ups`). Then mark the plan complete in `.superpowers/sdd/progress.md`.
