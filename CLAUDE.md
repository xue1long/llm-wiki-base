# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

ruflo-kb — a Python 3.11+ multi-agent knowledge-base platform. Ingest URLs / files (PDF, DOCX, XLSX, HTML, MD, TXT), process them through Collector → Analyzer → Generator, archive structured Markdown notes plus 1536-dim LanceDB vectors, and serve hybrid (semantic + keyword / RRF) search. Codebase is being incrementally migrated from `Novel-Knowledge-Base`; the active migration plan lives at `docs/superpowers/plans/2026-07-21-nkb-to-ruflo-migration.md` and follows a TDD-per-task workflow with one commit per task.

## Commands

Setup (from repo root):

```
pip install -e ".[dev]"
pip install watchdog        # required only by src/sync/file_watcher.py
```

Run all tests:

```
pytest -v
PYTHONPATH=. pytest tests/test_wiki/ tests/test_cli_ext/ tests/test_pipeline/ tests/test_server/ tests/test_agent/ -v   # touched areas
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
python -m src.cli init [--path DIR]            # legacy layout
python -m src.cli project init <path>          # multi-project layout (current)
python -m src.cli project list | current | info | select | import | forget
python -m src.cli ingest <url-or-file>         # enqueue a Collector task
python -m src.cli search <query>               # dispatch a SEARCHER_QUERY event
python -m src.cli configure --provider openai|anthropic [--openai-key KEY]
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

`ProjectContext` (in `src/project/context.py`) exposes `path: Path`, **NOT** `paths: WikiPaths`. CLI handlers that operate on the wiki MUST derive `WikiPaths`:

```python
from src.wiki.paths import WikiPaths

ctx = ProjectContext.resolve(proj_arg, by_id_only=True)
paths = WikiPaths(ctx.path)        # ← THIS PATTERN

# Then use paths.wiki_sources, paths.wiki_entities, paths.index, etc.
# Using ctx.paths.X will raise AttributeError at runtime.
```

This bug has been fixed 4+ times in CLI handlers (wiki-relations, wiki-fields-v22, wiki-heat-5pool, wiki-v21-polish). When writing new CLI handlers, use `_resolve_ctx(proj_arg)` helper that returns `(ctx, WikiPaths(ctx.path))`.

### Test infrastructure

`pytest` collection fails on heavy deps (platformdirs, lancedb, pyarrow, pypdf, docx, openpyxl, mcp, tavily) when not installed. Per-directory `conftest.py` files stub them:

- `tests/test_pipeline/conftest.py`
- `tests/test_server/conftest.py`
- `tests/test_cli_ext/conftest.py`
- `tests/test_wiki/conftest.py`

When adding a new test directory that imports from `src/`, add a matching `conftest.py` (copy an existing one).

## Cross-cutting concerns

- **Permissions** (`src/permissions.py`) — `AgentType` × `Permission` allow-list. `Orchestrator` always passes; the other agents are restricted.
- **Circuit breaker** (`src/circuit_breaker.py`) — global registry `get_circuit_breaker(name)`. OPEN after 3 failures, auto-HALF_OPEN after 60s, recovers after 2 successes.
- **Timeout** (`src/timeout.py`) — `@with_timeout(seconds, task_id=...)` decorator. Pipeline stages don't currently apply it.
- **Queue** (`src/queue/queue.py`) — module-level `_queue`, JSON-persisted to `.kb-queue.json`. `MAX_RETRIES = 3`, then dead-letter.
- **Idempotency** (`src/utils/idempotency.py`) — md5-keyed dedup, in-memory TTL 7 days.
- **Schemas** (`src/schemas/`) — Migration framework. `Migration` ABC with `up`/`down`/`preview`. MigrationRegistry indexes by `(schema_name, from_version, to_version)`.
- **Sync** (`src/sync/`) — `SnapshotStore` JSON, `FileSyncWatcher` watchdog observer.
- **Vector store** (`src/vector/`) — `LanceDB` singleton, 1536-dim float32. `init_vector_store(db_path)` must be called before any upsert/search.

## Implementation workflow

For multi-step work (especially the plans in `docs/superpowers/plans/`), use `superpowers:subagent-driven-development`:

1. **Read the plan** — `docs/superpowers/plans/<name>.md` lists tasks with `Files`, `Tests`, `Implementation guidance`.
2. **TDD per task** — write test first (run, fail), implement (run, pass), commit (`feat: ...` or `fix: ...`).
3. **Per-task review** — dispatch reviewer subagent after each task; fix Critical/Important findings before next task.
4. **Final whole-branch review** — when plan is complete, dispatch one final review; fix any Important findings in one batch.
5. **Durable progress** — update `.superpowers/sdd/progress.md` ledger after each task. The ledger is the recovery map after compaction.

Commit prefixes on `feat/continue-implementation`: `feat(scope):` for new features, `fix(scope):` for fixes, `chore:` for project docs/infra, `refactor:` for restructuring. Scoped to a single concern.

## Things to know before editing

- **Two import styles coexist.** Modules under `src/` generally use relative imports (`from .types import ...`, `from ..events.event_bus import event_bus`). `src/sync/file_watcher.py` is the exception: it uses absolute `from src.sync.snapshot_store import SnapshotStore`.
- **Event handlers register on import.** `src/pipeline/pipeline.py` and `src/orchestrator/orchestrator.py` attach handlers at module load. Adding a new pipeline stage means (a) emit a new event, (b) add a handler in `pipeline.py`, (c) optionally add a payload dataclass in `events/events.py`.
- **Embedding provider is a process-global singleton.** `pipeline.librarian._embedding_provider` and `searcher.hybrid_search._embedding_provider` are independent globals — set both if you switch providers.
- **CLI is CWD-sensitive.** `Path("Inbox")`, `Path("Notes")`, `Path("Knowledge")`, and `WikiPaths.root` resolve relative to the current working directory. Run from the repo root or pass `--path`/`--project`.
- **Tests mirror `src/` layout one level deep.** `tests/test_<module>.py` for top-level modules; `tests/test_<package>/test_<file>.py` for sub-packages (e.g. `tests/test_vector/test_store.py`).
- **WikiPage frontmatter must round-trip cleanly.** When adding a field to `WikiPage`, update BOTH `to_frontmatter_dict()` and `from_dict()` (use `.get(key, default)` for backwards compat with older pages).
- **`safe_write` buffers; `os.unlink` does not.** Multi-step atomic operations (cascade_delete, export/import) must defer deletions through the `DELETE_SENTINEL` mechanism in `safe_write` or the atomic guarantee is broken.

## Active plans (in `docs/superpowers/plans/`)

Plans are completed in dependency order. Check `.superpowers/sdd/progress.md` for current status. When picking up a plan, read it once for global constraints, then dispatch one implementer subagent per task with `superpowers:subagent-driven-development`.

Known finished plans (this session): wiki-v2, wiki-relations, wiki-fields-v22, wiki-heat-5pool, wiki-v21-polish, http-api-mcp, web-search-deep-research, chat-agent, schemas-v3, atomic-ctx+budgeted-llm, multi-provider-llm, project-multi-instancing.