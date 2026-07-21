# Project Multi-Instancing Design Spec

**Date:** 2026-07-21
**Status:** Approved (pending user sign-off)
**Target codebase:** ruflo-kb (Python 3.11+, master @ 47dfe33, post-wiki-v2.0 spec)
**Inspired by:** llm_wiki-main `project-identity.ts` / `project-store.ts` / `project-mutex.ts`

## Goal

Transform ruflo-kb from a single-KB-in-process tool into a multi-project platform where:

- Each KB has a stable **UUID identity** (survives filesystem moves/renames)
- A **global registry** tracks all known projects (UUID → path) in OS-standard config dir
- Each project carries its own **`.llm-wiki/settings.json`** (LLM provider, embedding model, output language, prompt versions)
- A **per-project async mutex** serializes mutations (ingest / cascade_delete / lint --fix / dedup merge) within a project; different projects are fully independent
- **Project resolution** flows from explicit `--project` arg → CWD upward search → `last_project` → user-friendly error
- **Auto-discovery** on first run scans default paths (`~/Documents`, `~/Notes`, etc.) and registers existing KBs without user action

This spec is **prerequisite** for HTTP API + MCP server (separate spec) and lays the foundation for cascade deletion / lint / dedup mutex needs already documented in the wiki v2.0 spec.

## Non-goals

- No GUI / TUI project switcher. CLI is the only surface in this spec.
- No concurrent cross-project operations (e.g. "search across all projects"). Single project per CLI invocation; HTTP API spec may add cross-project endpoints later.
- No project migration to remote storage (e.g. S3) — local filesystem only.
- No per-project user permissions (single-user model).
- No project templates or "starter content" beyond the wiki v2.0 `ensure_knowledge_base` defaults.
- No undo/redo of project-level operations (`project forget --delete-data` is irreversible; users should back up first).

## Architecture

### Layers

```
┌─────────────────────────────────────────────────────────────┐
│ Global layer (cross-project, OS-config-dir)                │
│                                                             │
│ ~/.config/ruflo-kb/                                        │
│   ├── registry.json     ← {uuid → {path, name, last_opened}} │
│   └── last_project.json ← {id, path}                       │
└─────────────────────────────────────────────────────────────┘
                             │
                             │ CLI: python -m src.cli <cmd>
                             │ resolve chain:
                             │   1. --project <id|name>
                             │   2. CWD upward search for .llm-wiki/project.json
                             │   3. last_project.json
                             │   4. error + hint
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ Project layer (per-project state on disk)                   │
│                                                             │
│ <project>/                                                  │
│ ├── .llm-wiki/                                              │
│ │   ├── project.json    ← {id, name, created_at, schema_version} │
│ │   ├── settings.json   ← {llm, embedding, search, output_language, prompt_versions} │
│ │   ├── reviews.json    (from wiki v2.0)                    │
│ │   └── lint_history/   (from wiki v2.0)                    │
│ ├── raw/sources/         (from wiki v2.0)                   │
│ ├── wiki/                (from wiki v2.0)                   │
│ ├── .index/              (lancedb + queue.json + ...)       │
│ └── Templates/                                                 │
└─────────────────────────────────────────────────────────────┘
                             │
                             │ ProjectContext(project_id, paths, settings, schema_version)
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ Module layer (project-scoped state, no module singletons)   │
│                                                             │
│ QueueState(project)        ← replaces _queue / _processing / _paused │
│ InboxManager(project)      ← already instance-based, add factory │
│ VectorStore(project)       ← replaces _db / _table          │
│ LLMProvider(project)       ← per-project provider from settings │
│ Orchestrator(stateless)    ← no instance state, takes ctx    │
│ EventBus(global singleton, project-scoped handlers)         │
└─────────────────────────────────────────────────────────────┘
```

### EventBus dual subscription model

`event_bus.on_project(project_id, event, handler)` — default for business logic; only fires for matching `project_id`.
`event_bus.on_global(event, handler)` — for cross-cutting concerns (metrics, unified log); fires for all projects.

`emit(event, payload, project_id=...)` requires explicit `project_id`. Payload dataclasses do NOT need a `project_id` field; routing is by the explicit `emit` argument.

### Per-project mutex

`async with_project_lock(project_id, fn)` — asyncio lock per project_id; serializes mutations within a project; different projects are fully concurrent.

`sync_with_project_lock(project_id, fn)` — sync wrapper for CLI subcommands (which run sync entry points).

Use sites: `Collector.collect`, `Generator.generate`, `CascadeDeleter.run`, `LintRunner.run(fix=True)`, `DedupRunner.merge`, `WikiIndexer.full_rebuild`. Queue-driven ingest is already serial internally; mutex protects cross-entry-point races (queue ingest vs Save-to-Wiki vs cascade delete).

## Components

### New modules

| Path | Responsibility |
|---|---|
| `src/project/__init__.py` | Public API: `ProjectContext`, `resolve_project`, `GlobalRegistry`, etc. |
| `src/project/paths.py` | `config_dir()`, `registry_path()`, `last_project_path()` — uses `platformdirs.user_config_dir` |
| `src/project/identity.py` | `ensure_project_id(project_path)` — generates UUID + writes `.llm-wiki/project.json` if missing |
| `src/project/registry.py` | `GlobalRegistry` dataclass + `GlobalRegistryStore` (load/save/upsert/remove/by_id/by_name/by_path) |
| `src/project/settings.py` | `ProjectSettings` / `LLMSettings` / `EmbeddingSettings` / `SearchSettings` dataclasses + load/save `.llm-wiki/settings.json` |
| `src/project/context.py` | `ProjectContext` dataclass + `resolve_project(project_arg)` factory + `from_path(path, name)` factory |
| `src/project/mutex.py` | `with_project_lock` (async) + `sync_with_project_lock` (sync wrapper) + `__reset_for_testing` |
| `src/project/discovery.py` | `discover_existing_kbs()` + `is_kb_root(path)` + `auto_register_on_first_run()` |
| `src/project/exceptions.py` | `ProjectNotFoundError`, `ProjectMismatchError`, `RegistryCorruptError` |
| `src/cli_ext/project_cmd.py` | `cmd_project_list` / `current` / `info` / `select` / `init` / `import` / `forget` / `rename` / `discover` |
| `src/cli_ext/config_cmd.py` | `cmd_config_show` / `set` / `reset` |
| `tests/_helpers/temp_config_dir.py` | Test fixture: monkey-patches `platformdirs.user_config_dir` to a tmpdir |
| `tests/test_project/__init__.py` | |
| `tests/test_project/test_paths.py` | OS-specific paths |
| `tests/test_project/test_identity.py` | UUID generation + project.json idempotency |
| `tests/test_project/test_registry.py` | CRUD + reverse-lookup + corrupt-recovery |
| `tests/test_project/test_settings.py` | load/save + defaults + env var override |
| `tests/test_project/test_context.py` | resolve chain (4 steps) + from_path migration |
| `tests/test_project/test_mutex.py` | same-project serializes / different-project concurrent / exception releases lock |
| `tests/test_project/test_discovery.py` | default path scan + is_kb_root + auto_register |
| `tests/test_project/test_event_bus_project.py` | on_project / on_global / project_id routing |
| `tests/test_project/test_singleton_refactor.py` | QueueState / InboxManager / VectorStore per-project isolation |
| `tests/test_integration/test_multi_project_isolation.py` | End-to-end: 2 projects, verify zero cross-talk |

### Modified modules

| Path | Change |
|---|---|
| `src/queue/queue.py` | Add `QueueState` class; old module-level `_queue` becomes `default_state: QueueState | None`; backward-compat shim functions (`enqueue_task` etc.) read default_state |
| `src/inbox/manager.py` | Add `InboxManager.for_project(project_id, project_path)` classmethod factory; old `get_inbox_manager()` becomes shim reading default |
| `src/vector/store.py` | Add `VectorStore(project_path)` class; old `_db`/`_table` become `_default_stores: dict[str, VectorStore]`; `get_table()` adds `project_id` param |
| `src/vector/upsert.py` | `vector_upsert_chunks(chunks, project_id, project_path)` — new required params |
| `src/vector/search.py` | `vector_search_chunks(query_embedding, top_k, project_id, project_path)` — new required params |
| `src/events/event_bus.py` | Add `_project_handlers` dict + `on_project()` / `on_global()` / `emit(event, payload, project_id=...)` |
| `src/events/events.py` | Add `ProjectScopedMixin` helper for dataclasses that include `project_id` (optional convenience; emit() does not require payload to have project_id) |
| `src/llm/provider_factory.py` | `create_llm_provider(ctx: ProjectContext)` reads `ctx.settings.llm`; falls back to env var if no settings.json |
| `src/llm/__init__.py` | Add `set_llm_provider_for_project(project_id, provider)` / `get_llm_provider_for_project(project_id)` |
| `src/orchestrator/orchestrator.py` | `Orchestrator` is now stateless; constructor takes `ctx: ProjectContext`; `process(ctx, input_text)` |
| `src/orchestrator/router.py` | unchanged |
| `src/orchestrator/state_machine.py` | unchanged |
| `src/orchestrator/audit_hard.py` | `run_hard_audit(ctx, note_path)` — ctx for path resolution |
| `src/pipeline/*.py` | All stage functions receive `ctx` as first param; use `ctx.queue_state` / `ctx.vector_store` / `ctx.inbox_manager` instead of module singletons |
| `src/permissions.py` | All path resolution uses `ctx.paths.*` |
| `src/cli.py` | New top-level `project` / `config` subparsers dispatching to `src/cli_ext/project_cmd.py` / `src/cli_ext/config_cmd.py`; `--project <id|name>` global arg added to all existing subcommands; old `init` subcommand becomes alias to `cmd_project_init` with DeprecationWarning; first-run calls `auto_register_on_first_run()` |
| `pyproject.toml` | Add `platformdirs>=4.0` to `dependencies` |

### Deleted modules

None.

## Data structures

```python
# src/project/identity.py
@dataclass
class ProjectIdentity:
    id: str                          # UUID v4
    created_at: int                  # unix ms
    name: str                        # human-readable, unique in registry
    schema_version: str              # "v2.0"
    
    PROJECT_JSON_PATH = ".llm-wiki/project.json"
    
    @classmethod
    def load(cls, project_path: Path) -> "ProjectIdentity":
        """Read from {project}/.llm-wiki/project.json. Generate if missing."""
        ...
    
    def save(self, project_path: Path) -> None: ...
```

```python
# src/project/registry.py
@dataclass
class ProjectRegistryEntry:
    id: str
    path: str                        # normalized absolute, forward slashes
    name: str
    last_opened: int                 # unix ms
    schema_version: str

@dataclass
class GlobalRegistry:
    version: int = 1
    projects: dict[str, ProjectRegistryEntry] = field(default_factory=dict)    # uuid → entry

@dataclass
class LastProjectPointer:
    id: str
    path: str

class GlobalRegistryStore:
    REGISTRY_FILENAME = "registry.json"
    LAST_PROJECT_FILENAME = "last_project.json"
    
    @staticmethod
    def registry_path() -> Path: ...        # → <config_dir>/registry.json
    @staticmethod
    def last_project_path() -> Path: ...    # → <config_dir>/last_project.json
    
    @staticmethod
    def load() -> GlobalRegistry:
        """Load registry. Returns empty GlobalRegistry if file missing or corrupt."""
        ...
    
    @staticmethod
    def save(reg: GlobalRegistry) -> None:
        """Atomic write (write to .tmp + os.replace)."""
        ...
    
    @staticmethod
    def upsert(entry: ProjectRegistryEntry) -> None: ...
    @staticmethod
    def remove(id: str) -> None: ...
    
    @staticmethod
    def by_id(id: str) -> ProjectRegistryEntry | None: ...
    @staticmethod
    def by_name(name: str) -> ProjectRegistryEntry | None: ...
    @staticmethod
    def by_path(path: Path) -> ProjectRegistryEntry | None: ...
    
    @staticmethod
    def load_last_project() -> LastProjectPointer | None: ...
    @staticmethod
    def save_last_project(pointer: LastProjectPointer) -> None: ...
```

```python
# src/project/settings.py
@dataclass
class LLMSettings:
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    api_key_env: str = "OPENAI_API_KEY"
    timeout_seconds: int = 60
    max_retries: int = 2

@dataclass
class EmbeddingSettings:
    provider: str = "openai"
    model: str = "text-embedding-3-small"
    dimension: int = 1536
    api_key_env: str = "OPENAI_API_KEY"

@dataclass
class SearchSettings:
    default_top_k: int = 10
    similarity_threshold: float = 0.85

@dataclass
class ProjectSettings:
    llm: LLMSettings = field(default_factory=LLMSettings)
    embedding: EmbeddingSettings = field(default_factory=EmbeddingSettings)
    search: SearchSettings = field(default_factory=SearchSettings)
    output_language: str = "auto"
    prompt_versions: dict[str, str] = field(default_factory=dict)
    
    SETTINGS_PATH = ".llm-wiki/settings.json"
    
    @classmethod
    def load(cls, project_path: Path) -> "ProjectSettings":
        """Load from {project}/.llm-wiki/settings.json. Returns defaults if missing."""
        ...
    
    def save(self, project_path: Path) -> None:
        """Atomic write."""
        ...
    
    def env_overrides(self) -> "ProjectSettings":
        """Return new ProjectSettings with env var overrides applied.
        Env vars: RUFLO_LLM_MODEL, RUFLO_LLM_API_KEY, RUFLO_EMBEDDING_MODEL, etc.
        """
        ...
```

```python
# src/project/context.py
@dataclass
class ProjectContext:
    """Resolved, ready-to-use project handle. Created once per CLI invocation."""
    identity: ProjectIdentity
    path: Path
    paths: KnowledgeBasePaths        # all subdirectory paths
    settings: ProjectSettings
    schema_version: str
    
    @property
    def id(self) -> str:
        return self.identity.id
    
    @property
    def name(self) -> str:
        return self.identity.name
    
    def to_registry_entry(self, last_opened: int | None = None) -> ProjectRegistryEntry:
        ...
    
    @classmethod
    def resolve(cls, project_arg: str | None) -> "ProjectContext":
        """4-step resolution chain. Raises ProjectNotFoundError if all steps fail."""
        ...
    
    @classmethod
    def from_path(cls, project_path: Path, name: str | None = None) -> "ProjectContext":
        """Initialize or read project.json at given path. Always registers."""
        ...
    
    @classmethod
    def from_registry_entry(cls, entry: ProjectRegistryEntry) -> "ProjectContext":
        """Read project.json from entry.path. Updates last_opened in registry."""
        ...
```

```python
# src/project/exceptions.py
class ProjectError(Exception): ...
class ProjectNotFoundError(ProjectError):
    """Raised when resolution chain fails. Includes hint message."""

class ProjectMismatchError(ProjectError):
    """Raised when registry entry points to path that no longer exists."""

class RegistryCorruptError(ProjectError):
    """Raised when registry.json is unparseable. Recovery: backup + start fresh."""
```

```python
# src/project/mutex.py
import asyncio
from typing import TypeVar, Callable, Awaitable

T = TypeVar("T")

_locks: dict[str, asyncio.Lock] = {}

def _lock_for(project_id: str) -> asyncio.Lock:
    if project_id not in _locks:
        _locks[project_id] = asyncio.Lock()
    return _locks[project_id]

async def with_project_lock(project_id: str, fn: Callable[[], Awaitable[T]]) -> T:
    """Serialize mutations within a project. Different projects are independent."""
    async with _lock_for(project_id):
        return await fn()

def sync_with_project_lock(project_id: str, fn: Callable[[], T]) -> T:
    """Sync wrapper for CLI subcommands. Uses asyncio.run internally."""
    async def _wrap() -> T:
        async with _lock_for(project_id):
            return fn()
    return asyncio.run(_wrap())

def __reset_for_testing() -> None:
    _locks.clear()
```

## File formats

### `<config_dir>/registry.json`

```json
{
  "version": 1,
  "projects": {
    "550e8400-e29b-41d4-a716-446655440000": {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "path": "/home/user/research",
      "name": "research",
      "last_opened": 1721558400000,
      "schema_version": "v2.0"
    },
    "abc12345-e29b-41d4-a716-446655440000": {
      "id": "abc12345-e29b-41d4-a716-446655440000",
      "path": "/home/user/novels",
      "name": "novels",
      "last_opened": 1721558500000,
      "schema_version": "v2.0"
    }
  }
}
```

### `<config_dir>/last_project.json`

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "path": "/home/user/research"
}
```

### `<project>/.llm-wiki/project.json`

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "research",
  "created_at": 1721558400000,
  "schema_version": "v2.0"
}
```

### `<project>/.llm-wiki/settings.json` (defaults)

```json
{
  "llm": {
    "provider": "openai",
    "model": "gpt-4o-mini",
    "api_key_env": "OPENAI_API_KEY",
    "timeout_seconds": 60,
    "max_retries": 2
  },
  "embedding": {
    "provider": "openai",
    "model": "text-embedding-3-small",
    "dimension": 1536,
    "api_key_env": "OPENAI_API_KEY"
  },
  "search": {
    "default_top_k": 10,
    "similarity_threshold": 0.85
  },
  "output_language": "auto",
  "prompt_versions": {
    "analyzer": "2026-07-21-v1",
    "generator": "2026-07-21-v1",
    "lint_semantic": "2026-07-21-v1",
    "dedup_detect": "2026-07-21-v1"
  }
}
```

## CLI surface

### New top-level subcommands

```
python -m src.cli project list                              # 列出所有注册项目
python -m src.cli project current                           # 显示当前解析到的项目
python -m src.cli project info [id|name]                     # 显示项目详情
python -m src.cli project select <id|name>                  # 切换 last_project（不改其他子命令的默认）
python -m src.cli project init <path> [--name <name>]        # 创建项目：生成 project.json + settings.json + 注册
python -m src.cli project import <path> [--name <name>]     # 导入现有 KB：自动发现 + 补 project.json + 注册
python -m src.cli project forget <id|name> [--delete-data]  # 从注册表移除（可选物理删除）
python -m src.cli project rename <id|name> <new-name>       # 改名（更新 registry + project.json）
python -m src.cli project discover                          # 手动触发自动发现

python -m src.cli config show [id|name]                     # 打印 settings.json（带默认值标记）
python -m src.cli config set <key.path> <value> [--project <id|name>]
                                                             # e.g. config set llm.model gpt-4o --project research
python -m src.cli config reset [--project <id|name>]         # 还原默认值
```

### Existing subcommands: add `--project <id|name>` global arg

```
python -m src.cli [--project <id|name>] ingest <url|file>
python -m src.cli [--project <id|name>] status
python -m src.cli [--project <id|name>] search <query>
python -m src.cli [--project <id|name>] lint
... (所有其他子命令：pause / resume / cascade_delete / review / dedup / export / import / rebuild_index / etc.)
```

Resolution order per invocation:
1. `--project <id|name>` if given
2. CWD upward search for `.llm-wiki/project.json`
3. `last_project.json`
4. Raise `ProjectNotFoundError` with hint

After successful resolution, `last_project.json` is updated to the resolved project (if `--project` was used or CWD matched).

### Deprecated alias

`python -m src.cli init --path <dir>` becomes alias to `python -m src.cli project init <dir>`. Prints `DeprecationWarning` to stderr, behavior unchanged.

## Resolution chain (detail)

```
resolve_project(project_arg):
    1. project_arg given:
        registry = GlobalRegistryStore.load()
        if project_arg in registry.projects:           # by UUID
            return ProjectContext.from_registry_entry(registry.projects[project_arg])
        for entry in registry.projects.values():       # by name
            if entry.name == project_arg:
                return ProjectContext.from_registry_entry(entry)
        raise ProjectNotFoundError(f"No project with id/name: {project_arg}")
    
    2. CWD upward search:
        cwd = Path.cwd().resolve()
        for ancestor in [cwd, *cwd.parents]:
            project_json = ancestor / ".llm-wiki" / "project.json"
            if project_json.exists():
                return ProjectContext.from_path(ancestor)
    
    3. last_project.json:
        last = GlobalRegistryStore.load_last_project()
        if last:
            try:
                return ProjectContext.from_path(Path(last.path))
            except ProjectMismatchError:
                pass    # stale pointer; fall through
    
    4. raise ProjectNotFoundError("No project resolved. Run `python -m src.cli project list` to see known projects, or `project init <path>` to create one, or `cd` into a project directory.")
```

## Auto-discovery

```python
# src/project/discovery.py
DEFAULT_SEARCH_PATHS = [
    Path.home() / "Documents",
    Path.home() / "Notes",
    Path.home() / "Knowledge",
    Path.home() / "wiki",
]

def is_kb_root(path: Path) -> bool:
    if (path / ".index" / "schema_version").exists():
        return True                          # v2.0 KB
    if (path / "Notes").is_dir():
        return True                          # v1.0 KB (pre-migration)
    return False

def discover_existing_kbs() -> list[Path]:
    candidates = []
    for base in DEFAULT_SEARCH_PATHS:
        if not base.exists():
            continue
        if is_kb_root(base):
            candidates.append(base)
        try:
            for child in base.iterdir():
                if child.is_dir() and is_kb_root(child):
                    candidates.append(child)
        except PermissionError:
            continue
    return candidates

def auto_register_on_first_run() -> list[ProjectContext]:
    """Called from CLI startup. Idempotent."""
    if GlobalRegistryStore.registry_path().exists():
        return []                             # registry already exists; not first run
    kbs = discover_existing_kbs()
    contexts = []
    for kb_path in kbs:
        try:
            ctx = ProjectContext.from_path(kb_path, name=kb_path.name)
            contexts.append(ctx)
        except Exception as e:
            logger.warning(f"[discovery] Failed to register {kb_path}: {e}")
    if contexts:
        # Set last_project to most recently modified
        most_recent = max(contexts, key=lambda c: c.path.stat().st_mtime)
        GlobalRegistryStore.save_last_project(LastProjectPointer(
            id=most_recent.id, path=str(most_recent.path)
        ))
    return contexts
```

## Error handling

| Stage | Error type | Strategy |
|---|---|---|
| `resolve()` step 1 | `--project` not found in registry | Raise `ProjectNotFoundError` listing known projects |
| `resolve()` step 2-3 | CWD/last_project path doesn't exist anymore | Treat as stale, continue to next step |
| `resolve()` step 4 | All steps fail | Raise `ProjectNotFoundError` with hint listing 4 ways to provide a project |
| `init/import` | Path doesn't exist or not writable | Hard error exit, code 2 |
| `init` | Path already has `.llm-wiki/project.json` | Hard error: "Project already exists at {path}; use `project import` to re-register" |
| `init` | v1.0 KB detected (has `Notes/`) | Hard error: "Path contains v1.0 KB; run wiki v2.0 migration first" |
| `forget` | Project id/name not found | Hard error listing known projects |
| `forget --delete-data` | Partial deletion (some files succeed, some fail) | Report what was deleted and what wasn't; exit code 1 |
| `forget` (without `--delete-data`) | Path on disk still exists | Warn user but proceed (registry-only removal) |
| `with_project_lock` | `fn()` raises | Lock released; exception propagated |
| Registry write | Disk full / permission denied | Whole CLI invocation fails with friendly error; suggest checking filesystem |
| Settings write | `.llm-wiki/` not writable | Hard error |
| Discovery | Scan finds KB but `project.json` write fails | Warning logged; continue with other KBs |
| Discovery | All KBs fail to register | Warning logged; registry.json not created; user can run `project discover` manually |
| `by_path()` reverse lookup | Path has moved since last registry update | Returns None; user can `project import <new-path>` to re-register |
| EventBus `emit()` | `project_id=None` passed but handler is `on_project` registered | Handler silently skipped (no error) |
| `Orchestrator()` constructor | `ctx` is None | `TypeError` (cannot operate without context) |

## Backwards compatibility

This spec is **non-breaking** for CLI users except for one cosmetic change:

- ✅ All existing CLI subcommands keep their names and args
- ✅ `--project` is **optional**; existing scripts that don't pass it work via CWD/last_project resolution
- ✅ `python -m src.cli init --path <dir>` keeps working as deprecated alias
- ✅ Module-level functions (`enqueue_task`, `vector_search_chunks`, etc.) keep working via shim → `default_state`
- ✅ All existing tests pass without modification (they don't use multi-project yet, so resolution defaults to last_project or single-KB env)
- ⚠️ One breaking change: anyone calling `enqueue_task()` without a project context will get a warning + auto-create a `_anonymous_project` from CWD. To explicitly opt out, pass `project_id="default"` or use the new ctx-aware API.

## Testing strategy

### Unit tests (per module)

| Module | Test focus |
|---|---|
| `src/project/identity.py` | UUID generation; idempotent (calling twice returns same id); corrupt project.json recovery |
| `src/project/registry.py` | CRUD; reverse-lookup by name/path; atomic write; corrupt recovery (rename to .bak + return empty); concurrent upsert serialization |
| `src/project/settings.py` | load/save; defaults when file missing; env var override; schema migration for old settings format |
| `src/project/context.py` | resolve() 4 steps with mocked failures; from_path() creates project.json idempotently; from_path() handles v1 KB detection |
| `src/project/mutex.py` | Same project: serializes (slow fn called second waits for first); different projects: concurrent (second runs while first runs); exception releases lock; `__reset_for_testing` between tests |
| `src/project/discovery.py` | `is_kb_root` true/false cases; default paths configurable via env; `auto_register_on_first_run` idempotent |
| `src/events/event_bus.py` | `on_project` only fires for matching project_id; `on_global` fires for all; `emit(event, payload, project_id=None)` raises if any `on_project` handler exists |
| `src/queue/state.py` | QueueState per-project: A's enqueue doesn't appear in B's queue; `_load_queue` reads correct per-project file |
| `src/vector/store.py` | VectorStore per-project: A's upsert doesn't appear in B's table; closing one doesn't close the other |
| `src/inbox/manager.py` | InboxManager.for_project creates separate instances; no cross-talk |
| `src/orchestrator/orchestrator.py` | Orchestrator stateless: same input → same output regardless of call history |

### Integration tests

```
tests/test_integration/test_multi_project_isolation.py:
    def test_two_projects_no_crosstalk():
        # Create projects A and B in tmpdirs
        # Initialize both
        # Run ingest on A
        # Verify: A's queue has 1 task, B's queue empty
        #         A's vector store has chunks, B's vector store empty
        #         A's wiki/ has pages, B's wiki/ empty
        #         event handlers (on_project) for A didn't receive B's events

    def test_project_move_updates_registry():
        # Create project at path X
        # Move to path Y
        # Run ingest with --project <id>
        # Verify: registry now points to Y; works without re-init

    def test_stale_last_project_recovered():
        # Set last_project to non-existent path
        # Run any CLI command
        # Verify: gracefully falls through to next resolution step
        #         OR fails with helpful error

    def test_settings_override_env():
        # Set env var RUFLO_LLM_MODEL=gpt-4o
        # Project settings.json has model=gpt-4o-mini
        # Run command; verify env wins

    def test_discovery_idempotent():
        # Run CLI twice
        # Verify: registry not duplicated; last_project unchanged second time
```

### Test fixture: isolated config dir

```python
# tests/_helpers/temp_config_dir.py
import pytest
from pathlib import Path
from unittest.mock import patch

@pytest.fixture
def temp_config_dir(tmp_path, monkeypatch):
    """Redirect platformdirs.user_config_dir to tmp_path."""
    config_dir = tmp_path / "ruflo-kb-config"
    config_dir.mkdir()
    monkeypatch.setattr(
        "src.project.paths.config_dir",
        lambda: config_dir
    )
    yield config_dir
    # Cleanup happens automatically via tmp_path
```

## Implementation order

8 phases, each independently committable:

1. **Foundation** — `src/project/{__init__,paths,identity,registry,settings,exceptions}.py` + tests; `pyproject.toml` adds `platformdirs>=4.0`
2. **Resolution & discovery** — `src/project/{context,discovery}.py` + auto_register hook + tests
3. **Mutex** — `src/project/mutex.py` + tests
4. **EventBus refactor** — dual subscription API + tests
5. **Singleton refactor** — QueueState / InboxManager / VectorStore / LLMProvider per-project + EventBus per-project handlers in pipeline stages + integration with wiki v2.0 spec modules + tests
6. **CLI surface** — `src/cli_ext/{project_cmd,config_cmd}.py` + `--project` global arg + `init` deprecated alias + tests
7. **Orchestrator stateless** — refactor constructor to take ctx + tests
8. **Integration** — `tests/test_integration/test_multi_project_isolation.py` + end-to-end smoke test

Each phase follows TDD per-task rhythm; one commit per task.

## Cost estimation

- New dependencies: `platformdirs>=4.0` (Apache 2.0, ~10KB)
- New code: ~1500 lines (project package + CLI extensions + tests)
- New tests: ~1000 lines
- Migration: existing single-KB users get auto-discovery on first run; zero manual steps
- Backwards compat: `init --path` deprecated but works; module-level shims keep old API surface

## Open questions / deferred (v3.0+)

- **Cross-project search** — `python -m src.cli search --all-projects <query>` for unified search across all known KBs. Depends on per-project search API; deferred.
- **Project templates** — `project init --template research` to seed purpose.md / schema.md beyond wiki v2.0 defaults. Cosmetic; deferred.
- **Project export/import is CLI-level, not registry-level** — wiki v2.0 spec's `export <zip>` already covers; registry entry can be added to zip metadata in v2.1.
- **Project sharing / collaboration** — multi-user; deferred.
- **Project-level LLM cost tracking** — count tokens per project per day; deferred.
- **Remote registry sync** — sync registry across machines; deferred.
- **CLI shell completion** — `ruflo-kb project <TAB>` completes known project names; deferred.
- **Project aliases** — human-friendly nicknames (`work` → uuid); partial via `by_name` already.
- **Global settings** (UI preferences, theme, debug flag) — env vars only for now; if user demand rises, add `~/.config/ruflo-kb/config.json` in v3.

## Dependency graph (for visual reference)

```
src/project/identity.py
       │
       ▼
src/project/registry.py ◄── src/project/paths.py
       │                            │
       ▼                            ▼
src/project/context.py ────► src/project/discovery.py
       │
       ▼
src/project/settings.py ◄── src/project/exceptions.py
       │
       ▼
src/project/mutex.py

src/cli_ext/project_cmd.py ──► src/project/* (all)
src/cli_ext/config_cmd.py  ──► src/project/settings.py

src/queue/queue.py ──► src/project/context.py (for default_state init)
src/vector/store.py ──► src/project/context.py
src/inbox/manager.py ──► src/project/context.py
src/orchestrator/orchestrator.py ──► src/project/context.py (stateless)
src/llm/provider_factory.py ──► src/project/settings.py

src/events/event_bus.py (independent — only depends on stdlib)
```