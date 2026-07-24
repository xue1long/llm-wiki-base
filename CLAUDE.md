# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

ruflo-kb — a Python 3.11+ multi-agent knowledge-base platform. Ingest URLs / files (PDF, DOCX, XLSX, HTML, MD, TXT), process them through Collector → Analyzer → Generator, archive structured Markdown notes plus 1536-dim LanceDB vectors, and serve hybrid (semantic + keyword / RRF) search. Codebase is being incrementally migrated from `Novel-Knowledge-Base`; the active migration plan lives at `docs/superpowers/plans/2026-07-21-nkb-to-ruflo-migration.md` and follows a TDD-per-task workflow with one commit per task.

**Session memory:** `.memory/` — persisted learnings, project facts, user preferences, and runbooks. Read it when starting a new session or picking up after compaction.

## Commands

> **Full environment setup story (Python 3.14 wheels, proxy workarounds, the
> sibling-conftest cascade that affects new test directories) lives in
> [`docs/environment/SETUP.md`](docs/environment/SETUP.md). Read that first if
> any test is failing unexpectedly — it covers the four pitfalls that are
> not obvious from reading the code alone.**

Setup (from repo root):

```
# Quick online install (fast path; on this host, bypass the 127.0.0.1:7897
# proxy which times out on large wheels — see SETUP.md §2):
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  pip install -e ".[dev]"
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  pip install watchdog tavily-python pypdf

# Offline install for the two heavy native packages (pyarrow + lancedb):
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  pip install docs/environment/wheels/pyarrow-25.0.0-cp314-cp314-win_amd64.whl \
                docs/environment/wheels/lancedb-0.27.1-cp39-abi3-win_amd64.whl
```

Run all tests:

```
# The two flags matter; without them you get collection errors:
#   PYTHONPATH=.        so `from src.xxx import ...` resolves
#   --import-mode=importlib   so same-named test files (test_paths.py,
#                             test_types.py, test_registry.py) in
#                             different test_X/ directories don't collide
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest --import-mode=importlib
# → 719 passed in ~30s on Python 3.14 / Windows

# Touched areas only:
PYTHONPATH=. pytest tests/test_wiki/ tests/test_cli_ext/ tests/test_pipeline/ tests/test_server/ tests/test_agent/ -v
```

Run a single test file or test node:

```
pytest tests/test_file_watcher.py -v
pytest tests/test_file_watcher.py::test_scan_once_detects_new_file -v
pytest tests/test_vector/ -v                  # one test package
pytest -k idempotency -v                       # by keyword
```

CLI (entry is `src/cli.py`, run from the repo root — paths like `Inbox/`, `Notes/`, `Knowledge/`, `wiki/` are resolved relative to CWD or `--path`):

```
python -m src.cli project init <path>          # multi-project layout (current)
python -m src.cli project list | current | info | select | import | forget
# Ingestion is via the HTTP API (see "Ingesting raw documents" below)
python -m src.cli llm-providers add <name> <type>          # <type>=openai|anthropic|ollama
python -m src.cli llm-providers set-default <name>
python -m src.cli relations {list|backlinks|neighbors|path|types|add-type}
python -m src.cli fields validate <page> --project <id>
python -m src.cli tags validate [--all] --project <id>
python -m src.cli heat {show|top|cold|decay|zombies|restore|archive}
python -m src.cli stubs {list|promote} --project <id>
python -m src.cli dedup auto [--threshold high] --project <id>
python -m src.cli lint [--cache-ttl N] [--no-cache] --project <id>
python -m src.cli lint-cache-clear --project <id>
python -m src.cli schema {list|diff|upgrade|downgrade|backup}
python -m src.cli serve [--host H] [--port P] [--daemon]
python -m src.cli mcp                          # stdio MCP server (8 tools)
```

There is no linter, formatter, type checker, or build target configured (no `Makefile`, `tox.ini`, `ruff.toml`, `mypy.ini`). `pyproject.toml` declares only the package metadata and `setuptools` as build backend.

### Ingesting raw documents

There is **no** top-level `python -m src.cli ingest` command — it was removed in the 2026-07-22 cleanup. The current ingestion path is the HTTP API (the `Inbox/` watcher and `python -m src.cli project import` only register/import an existing KB; they do **not** parse raw files).

```bash
# 1. Initialize a project (one-time; creates wiki/, .llm-wiki/, .index/)
python -m src.cli project init <project_path>

# 2. Configure an LLM provider (Anthropic / OpenAI / Ollama)
python -m src.cli llm-providers add --provider openai --api-key $OPENAI_API_KEY --default
# Ollama (local):  --provider ollama --base-url http://127.0.0.1:11434

# 3. Start the server
python -m src.cli serve --host 127.0.0.1 --port 8765

# 4. Find the project_id
python -m src.cli project list

# 5. Enqueue ingestion (URL, single file, or whole folder)
PROJECT=<id from step 4>
curl -X POST http://127.0.0.1:8765/api/v1/projects/$PROJECT/ingest \
  -H "Content-Type: application/json" \
  -d '{"source": "https://example.com/paper.pdf"}'                # URL

curl -X POST http://127.0.0.1:8765/api/v1/projects/$PROJECT/ingest \
  -H "Content-Type: application/json" \
  -d '{"source": "/abs/path/to/notes.docx"}'                       # file

curl -X POST http://127.0.0.1:8765/api/v1/projects/$PROJECT/ingest \
  -H "Content-Type: application/json" \
  -d '{"source": {"folder": "/abs/path/to/stuff"}, "folderContext": "papers"}'
```

The route handler (`src/server/routes/ingest.py`) calls `services.ingest.enqueue_source`, which validates the project exists and pushes a task onto `src/queue/queue.py`. Processing is async — `enqueue_task` returns `{status, taskId}` immediately; the Collector → Analyzer → Generator pipeline runs in the background. Idempotency is by md5(source + folder_context) with a 7-day TTL (`src/utils/idempotency.py`).

Supported source formats (extracted by `src/utils/extract/`): PDF (pypdf), DOCX (python-docx), XLSX (openpyxl), HTML, MD, TXT. Vector embeddings are 1536-dim float32 in LanceDB (`src/vector/`); upsert requires `init_vector_store_for_paths(WikiPaths)` to have been called for the project (the server's lifespan does this automatically).

Alternative ingestion paths:
- **MCP** (`python -m src.cli mcp`) — stdio server exposes `ingest` as an MCP tool for Claude Desktop
- **Programmatic** — `from src.pipeline.pipeline import run_ingest` runs Collector → Analyzer → Generator → atomic write synchronously (no queue); `from src.wiki.features.folder_ingest import collect_files` enumerates files in a folder for batch processing

Verify results:
```bash
ls <project_path>/wiki/{sources,entities,concepts,synthesis}/     # generated pages
cat <project_path>/wiki/index.md                                    # catalog (id, type, title)
cat <project_path>/wiki/log.md                                       # audit trail
python -m src.cli health --project <project_id>                     # H1/H2/H4 checks
```

## Architecture (Wiki v2 — current)

The wiki is the **primary data model**. Legacy `Notes/<task_id>.md` output is preserved by some agent paths but the wiki pipeline supersedes it.

### Wiki data model (`src/wiki/`)

`WikiPage` is the core dataclass. Frontmatter (YAML) carries:

| Field | Type | Default | Purpose |
|---|---|---|---|
| `id` | str | required | Slug or `card_<13hex_millis>_<8hex_rand>_<slug>` (v2.2+) |
| `title` | str | required | Display title |
| `type` | PageType | required | `source` \| `entity` \| `concept` \| `synthesis` |
| `sources` | list[str] | [] | Raw source paths |
| `created_at` / `updated_at` | int | 0 | Unix ms |
| `body` | str | "" | Markdown body (may contain `[[wikilinks]]`) |
| `relations` | list[Relation] | [] | Typed relations (16 built-in + `x-*` user) |
| `grade` | str | "B" | v2.2: A \| B \| C |
| `processing_depth` | str | "concept" | v2.2: concept \| memory |
| `is_immutable` | bool | False | v2.2: zombie-resist flag |
| `heat` | int | 50 | Heat decay tracker (0-100) |
| `last_used_at` | int | 0 | Heat: last AI retrieval timestamp |
| `zombie_since` | int\|None | None | Heat: 0-heat timestamp |

**Wiki 规范（含命名/Frontmatter/Body 规则）：** [`docs/guides/wiki-spec.md`](docs/guides/wiki-spec.md)

Layout (created by `python -m src.cli project init <path>`):

```
<project>/
├── wiki/
│   ├── sources/   entities/   concepts/   synthesis/   _stubs/
│   ├── _archive/                      # heat CLI archive target
│   ├── index.md                      # catalog (id, type, title)
│   └── log.md                        # audit trail
├── raw/sources/
├── .llm-wiki/   project.json   settings.json   chats/   analysis_cache/
└── .index/   heat_events.log   lint_cache/   staging/   dedup_history/
```

### Pipeline (Analyzer → Generator → Writer)

`src/pipeline/pipeline.py` registers event handlers at import time. The flow is:

```
collector:start → Collector → collector:done
  → Analyzer (LLM extracts AnalysisResult)
  → Generator (LLM renders WikiPage list)
  → atomic: write_page + append_to_index + log_event
```

`run_ingest(paths, source_path, source_text, provider, ...)` is the new pure function entry point. EventBus (`src/events/event_bus.py`) is a singleton; handlers register via `event_bus.on(name, handler)`. `AtomicContext` batches writes via `safe_write` (which buffers to `_pending_writes` and flushes on context exit). For deletions use the `DELETE_SENTINEL` mechanism in `src/lib/write_hooks.py` so cascade operations are atomic.

### Critical gotcha: `ProjectContext.path` vs `WikiPaths`

`ProjectContext` (in `src/project/context.py`) exposes `path: Path`, **NOT** `paths: WikiPaths`. The clean way to operate on the wiki is via the service layer or the `src/lib/project.py` helpers:

```python
# Preferred: use the central helpers in src/lib/project.py
from src.lib.project import resolve_project, resolve_ctx_only

ctx, paths = resolve_project(proj_arg, by_id_only=True)
# Use paths.wiki_sources, paths.wiki_entities, paths.index, etc.

# Or, for a CLI handler that needs the same pattern:
from src.lib.project import resolve_project

def _resolve_ctx(proj_arg):
    return resolve_project(proj_arg, by_id_only=True)
```

4 of the 9 historical `_resolve_ctx` copies have been migrated to the helpers (`heat_cmd`, `wiki_polish_cmd`, `fields_cmd`, `relations_cmd`); the other 5 are eliminated by routing through the service layer. **Do not** access `ctx.paths.X` — that attribute does not exist.

### Test infrastructure

`pytest` collection fails on heavy deps (platformdirs, lancedb, pyarrow, pypdf, docx, openpyxl, mcp, tavily) when not installed. Per-directory `conftest.py` files stub them so that tests can be collected even when those packages are missing:

- `tests/test_pipeline/conftest.py`
- `tests/test_server/conftest.py`
- `tests/test_cli_ext/conftest.py`
- `tests/test_wiki/conftest.py`
- `tests/test_llm/conftest.py`
- `tests/test_lib/conftest.py`

`sys.modules.setdefault` is global to the pytest session, so an alphabetically-later conftest can re-stub a module after an earlier conftest has restored it. The four conftests under `tests/test_{project,vector,searcher,mcp_server}/` work around this; the full pattern is documented in [`docs/environment/SETUP.md`](docs/environment/SETUP.md) §4. When adding a new test directory that imports from `src/`, copy an existing `conftest.py` and, if the new directory actually needs the real heavy module, also copy the "restore real module" pattern.

## Cross-cutting concerns

- **Permissions** (`src/permissions.py`) — `AgentType` × `Permission` allow-list. `Orchestrator` always passes; the other agents are restricted.
- **Circuit breaker** (`src/circuit_breaker.py`) — global registry `get_circuit_breaker(name)`. OPEN after 3 failures, auto-HALF_OPEN after 60s, recovers after 2 successes.
- **Queue** (`src/queue/queue.py`) — module-level `_queue`, JSON-persisted to `.kb-queue.json`. `MAX_RETRIES = 3`, then dead-letter.
- **Idempotency** (`src/utils/idempotency.py`) — md5-keyed dedup, in-memory TTL 7 days.
- **Schemas** (`src/schemas/`) — Migration framework. `Migration` ABC with `up`/`down`/`preview`. MigrationRegistry indexes by `(schema_name, from_version, to_version)`.
- **Sync** (`src/sync/`) — `SnapshotStore` JSON, `FileSyncWatcher` watchdog observer. `start_watch` / `stop` are **deprecated** (no current callers; remove in 1.0).
- **Vector store** (`src/vector/`) — `LanceDB` singleton, 1536-dim float32. `init_vector_store_for_paths(WikiPaths)` must be called before any upsert/search; the legacy `init_vector_store(db_path)` parent-walking heuristic was removed (use `WikiPaths(root)` to construct the canonical path object).
- **Service layer** (`src/services/`) — business logic between HTTP routes and core domain. Routes are thin adapters; services are unit-testable without HTTP. 7 modules: `files`, `projects`, `schema`, `reviews`, `ingest`, `search`, `chat`.
- **Project resolution** (`src/lib/project.py`) — single entry point. `resolve_project(arg, by_id_only) -> (ProjectContext, WikiPaths)`; `resolve_ctx_only(...)` for the no-paths case. Replaces 9 hand-rolled `_resolve_ctx` copies.
- **LLM providers** (`src/llm/registry.py`) — `ProviderRegistry` loads from `~/.config/ruflo-kb/llm-providers.json`. `OllamaProvider.__init__` auto-registers in `_loaded_providers`; `ProviderRegistry.aclose_all()` is called from FastAPI lifespan shutdown to release `httpx.AsyncClient` resources.

## Implementation workflow

For multi-step work (especially the plans in `docs/superpowers/plans/`), use `superpowers:subagent-driven-development`:

1. **Read the plan** — `docs/superpowers/plans/<name>.md` lists tasks with `Files`, `Tests`, `Implementation guidance`.
2. **TDD per task** — write test first (run, fail), implement (run, pass), commit (`feat: ...` or `fix: ...`).
3. **Per-task review** — dispatch reviewer subagent after each task; fix Critical/Important findings before next task.
4. **Final whole-branch review** — when plan is complete, dispatch one final review; fix any Important findings in one batch.
5. **Durable progress** — update `.superpowers/sdd/progress.md` ledger after each task. The ledger is the recovery map after compaction.

Commit prefixes on `feat/continue-implementation`: `feat(scope):` for new features, `fix(scope):` for fixes, `chore:` for project docs/infra, `refactor:` for restructuring. Scoped to a single concern.

## Automatic Memory Capture

After each significant event, capture learnings to `.memory/` so future sessions can fast-start.

**Trigger conditions — capture to `.memory/` when:**
- Discovering a bug, workaround, or regression → write a `feedback-*.md` entry
- Completing a multi-step task (especially via subagent-driven-development) → write a `feedback-*.md` entry
- Learning a non-obvious constraint, configuration detail, or path structure → write a `feedback-*.md` or `arch-*.md` entry
- Starting a new project type or initializing a new knowledge base → write a `quickstart-*.md` entry
- Completing a plan → update `.superpowers/sdd/progress.md` ledger

**File naming convention:**
- `feedback-<short-name>.md` — bug workarounds, regression findings, non-obvious gotchas
- `arch-<topic>.md` — architecture constraints, directory conventions, config loading
- `quickstart-<topic>.md` — step-by-step runbook for recurring setup tasks
- `project-<name>.md` — project-specific facts (IDs, commands, known issues)
- `user-preferences.md` — collaboration style, user habits

**Format:**
```markdown
---
name: <short-kebab-case-slug>
description: <one-line summary for future relevance check>
metadata:
  type: <user|feedback|project|reference>
---

# Title

**When:** [what triggered this learning]
**Why:** [the root cause or design reason]
**How to apply:** [what to do in future sessions]
```

**Index:** All entries are listed in `.memory/MEMORY.md`.

## Things to know before editing

- **Two import styles coexist.** Modules under `src/` generally use relative imports (`from .types import ...`, `from ..events.event_bus import event_bus`). `src/sync/file_watcher.py` is the exception: it uses absolute `from src.sync.snapshot_store import SnapshotStore`.
- **Event handlers register on import.** `src/pipeline/pipeline.py` and `src/orchestrator/orchestrator.py` attach handlers at module load. Adding a new pipeline stage means (a) emit a new event, (b) add a handler in `pipeline.py`, (c) optionally add a payload dataclass in `events/events.py`.
- **Embedding provider is a process-global singleton.** `pipeline.librarian._embedding_provider` and `searcher.hybrid_search._embedding_provider` are independent globals — set both if you switch providers.
- **CLI is CWD-sensitive.** `Path("Inbox")`, `Path("Notes")`, `Path("Knowledge")`, and `WikiPaths.root` resolve relative to the current working directory. Run from the repo root or pass `--path`/`--project`.
- **Tests mirror `src/` layout one level deep.** `tests/test_<module>.py` for top-level modules; `tests/test_<package>/test_<file>.py` for sub-packages (e.g. `tests/test_vector/test_store.py`).
- **WikiPage frontmatter must round-trip cleanly.** When adding a field to `WikiPage`, update BOTH `to_frontmatter_dict()` and `from_dict()` (use `.get(key, default)` for backwards compat with older pages).
- **`safe_write` buffers; `os.unlink` does not.** Multi-step atomic operations (cascade_delete, export/import) must defer deletions through the `DELETE_SENTINEL` mechanism in `safe_write` or the atomic guarantee is broken.
- **Server runtime is not covered by tests.** No test imports `src.server.app` or `src.cli serve`. Import-time crashes in the lifespan hook (e.g. the `from ..wiki.ensure import …` regression that broke `python -m src.cli serve` after the wiki split) only surface when the server is actually started. After any refactor that touches `src/server/`, `src/cli.py`, or top-level imports of `src/wiki/`, run `python -m src.cli serve --port <free>` and curl `/health` to confirm the lifespan completes.

## Plans (in `docs/superpowers/plans/`)

Plans are completed in dependency order. Check `.superpowers/sdd/progress.md` for current status. When picking up a plan, read it once for global constraints, then dispatch one implementer subagent per task with `superpowers:subagent-driven-development`.

Known finished plans: wiki-v2, wiki-relations, wiki-fields-v22, wiki-heat-5pool, wiki-v21-polish, http-api-mcp, web-search-deep-research, chat-agent, schemas-v3, atomic-ctx+budgeted-llm, multi-provider-llm, project-multi-instancing, plus the 2026-07-23 cleanup trio (`full-audit-fix`, `followup-carryovers`, `cleanup-final-minors`).

## Recent architectural changes (cleanup series, 2026-07-22 → 2026-07-23)

In a single cleanup pass, the following changes landed on `feat/continue-implementation`:

**Dead code removal**:
- `src/timeout.py` deleted (131 lines) — `with_timeout`, `run_with_timeout`, `TimeoutTracker`, `TaskTimeoutError`, `TaskTimeoutConfig` had zero callers
- `src/knowledge_base.py` deleted (107 lines) — old `Inbox/Notes/Knowledge` layout; superseded by `src/wiki/storage/ensure.py`
- `InboxManager.clear_processing`, `IdempotencyCache.remove`, `EntityMention.to_dict` + `from_dict` removed
- `src/schemas/__init__.py: CURRENT_VERSION / MIGRATIONS` back-compat shims removed
- `FileSyncWatcher.start_watch / .stop` marked `DeprecationWarning` (no current callers; remove in 1.0)

**Bug fixes surfaced by the audit**:
- `OllamaProvider.close()` was not called by any business code → `httpx.AsyncClient` leak. Fixed via `ProviderRegistry._loaded_providers` + `aclose_all()` + FastAPI lifespan shutdown hook.
- Test isolation bug: `test_cmd_schema_upgrade` failed when run with `test_schemas/` due to `MigrationRegistry` not being cleared after tests.

**2026-07-23 follow-up audits** extended the cleanup: `atomic_ctx` exception rollback (atomic guarantee was previously broken on handler errors); `LLM.complete(messages)` call-site fixes; `health_check` response shape normalization; vector store project-isolation (no cross-project bleed); `pipeline` provider selection now respects project config; `safe_write` enforcement at remaining call sites; `schema` 404 returns proper status; `hybrid_search` exception classification (logs class + reason, no longer silent swallow); `Registry.save` uses `safe_write` for atomic write-hook compliance; env-sourced LLM providers persist with empty `api_key` (not stored).

**Service layer (P0)** — `src/services/`:
- 7 new modules: `files.py`, `projects.py`, `schema.py`, `reviews.py`, `ingest.py`, `search.py`, `chat.py`
- Each service has a corresponding test file under `tests/test_server/test_service_*.py`
- HTTP routes in `src/server/routes/` are now thin adapters (Pydantic validation + service call + HTTP status mapping)
- CLI handlers in `src/cli_ext/` can call services directly without HTTP machinery

**`src/lib/project.py`**: central `resolve_project` / `resolve_ctx_only` helpers. 4 of 9 `_resolve_ctx` copies migrated; the other 5 are eliminated by routing through the service layer.

**`src/wiki/` split** (commit `4645664`):
- `core/` — types, paths, page model, id generator
- `storage/` — page_writer, ensure, atomic_ctx_helpers
- `features/` — relations, heat, review, lint, dedup, stubs, zombie, tag_namespace, import, export, cascade_delete, indexer, wikilink, folder_ingest, schema_routing, logger
- `src/wiki/__init__.py` re-exports the most commonly used *symbols* (functions/classes) for convenience (`from src.wiki import WikiPage, WikiPaths, ensure_knowledge_base, ...`).
- **Old module paths are NOT aliased.** `from src.wiki.ensure import X` is broken — there is no `sys.modules` shim for `src.wiki.<old_module>`. All production code must use the layered paths (`src.wiki.core.paths`, `src.wiki.storage.ensure`, `src.wiki.features.relations`, ...). A grep for `from (\.\.|src\.)wiki\.(ensure|page_writer|types|paths|...)` should return zero matches outside `tests/` and `docs/superpowers/{specs,plans}/`.

**`src/cli.py` slimmed** (511 → 407 lines): 7 legacy `cmd_*` deleted (`init`/`status`/`pause`/`resume`/`ingest`/`search`/`configure`), each superseded by `src/cli_ext/*` modules.