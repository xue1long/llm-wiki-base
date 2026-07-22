# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

ruflo-kb — a Python 3.11+ multi-agent knowledge-base platform. Ingest URLs / files (PDF, DOCX, XLSX, HTML, MD, TXT), process them through a Collector → Processor → Librarian pipeline, archive structured Markdown notes plus 1536-dim LanceDB vectors, and serve hybrid (semantic + keyword / RRF) search. Codebase is being incrementally migrated from `Novel-Knowledge-Base`; the active migration plan lives at `docs/superpowers/plans/2026-07-21-nkb-to-ruflo-migration.md` and follows a TDD-per-task workflow with one commit per task.

## Commands

Setup (from repo root):

```
pip install -e ".[dev]"
pip install watchdog        # required only by src/sync/file_watcher.py
```

Run all tests:

```
pytest -v
```

Run a single test file or test node:

```
pytest tests/test_file_watcher.py -v
pytest tests/test_file_watcher.py::test_scan_once_detects_new_file -v
pytest tests/test_vector/ -v                  # one test package
pytest -k idempotency -v                       # by keyword
```

CLI (entry is `src/cli.py`, run from the repo root — paths like `Inbox/`, `Notes/`, `Knowledge/` are resolved relative to CWD):

```
python -m src.cli init [--path DIR]            # create the KB directory tree
python -m src.cli status                       # queue + circuit breaker snapshot
python -m src.cli pause | resume               # gate the queue
python -m src.cli ingest <url-or-file>         # enqueue a Collector task
python -m src.cli search <query>               # dispatch a SEARCHER_QUERY event
python -m src.cli configure --provider openai|anthropic [--openai-key KEY]
```

There is no linter, formatter, type checker, or build target configured (no `Makefile`, `tox.ini`, `ruff.toml`, `mypy.ini`). `pyproject.toml` declares only the package metadata and `setuptools` as build backend.

## Architecture

### Process flow

`src/cli.py` parses subcommands and delegates to the `Orchestrator` (`src/orchestrator/orchestrator.py`), which routes input via `Router.route_task` (`src/orchestrator/router.py`):

- Strings starting with `?`, `search:`, or `find:` → `_handle_search` emits `SEARCHER_QUERY`.
- Anything starting with `http` or containing `.md`/`.pdf`/`.doc` → `_handle_ingest` calls `enqueue_task`, then `_process_next` emits `collector:start`.
- Default is INGEST (so unknown inputs are silently treated as ingest).

The pipeline in `src/pipeline/pipeline.py` wires event handlers at import time — that module's side effects wire `collector:start` → `Collector.collect` → `COLLECTOR_DONE` → `Processor.process` → `PROCESSOR_DONE` → `Librarian.archive` → `LIBRARIAN_DONE`. `Orchestrator` listens separately to `PROCESSOR_DONE` (calls `audit_hard.run_hard_audit`, sets `APPROVED`/`REJECTED`) and `LIBRARIAN_DONE` (sets `ARCHIVED`). Wiring happens **at import** — importing `src.pipeline.pipeline` registers handlers on the global `event_bus`.

EventBus (`src/events/event_bus.py`) is a single in-process singleton: `event_bus.on(name, handler)` returns an unsubscribe callable; `event_bus.emit(name, payload)` swallows handler exceptions per handler so one failure doesn't break the chain. Event names and typed payload dataclasses live in `src/events/events.py`.

### Pipeline stages

- **Collector** (`src/pipeline/collector.py`) — fetches URLs with `httpx`, reads local files via `utils/extract/{pdf,office}.py`, writes raw content to `Inbox/Processing/<task_id><ext>`. `enforce_permission` gates every read/write against the agent's allow-list.
- **Processor** (`src/pipeline/processor.py`) — `trim_text` → 200-char summary → top-5 keyword tags → `calculate_quality_metrics` (ad-ratio + text-density + fluency). Writes a YAML-frontmatter Markdown file to `Notes/<task_id>.md`.
- **Librarian** (`src/pipeline/librarian.py`) — **pre-write hook**: chunks the note, embeds the first chunk, searches LanceDB; if any result has score > `SIMILARITY_THRESHOLD = 0.95`, it appends a `**合并来源**` block to the existing note and emits `LIBRARIAN_MERGED` instead of writing a new file. Otherwise it copies the note to `Knowledge/`, chunks + embeds every chunk, and `vector_upsert_chunks` writes them to LanceDB. When no embedding provider is set it writes zero vectors of length 1536 — `archive` does **not** fail.

Embedding is opt-in: call `pipeline.librarian.set_embedding_provider(...)` (or `searcher.hybrid_search.set_embedding_provider(...)`) at startup. Without it, archive uses placeholder vectors and search falls back to keyword-only.

### Cross-cutting concerns

- **Permissions** (`src/permissions.py`) — `AgentType` × `Permission` allow-list over directory prefixes (`Inbox/Pending`, `Inbox/Processing`, `Notes`, `Knowledge`, `.index`). `Orchestrator` always passes; the other four agents are restricted. `enforce_permission` raises `PermissionError` on denial.
- **Circuit breaker** (`src/circuit_breaker.py`) — global registry `get_circuit_breaker(name)`; the queue uses name `task_queue`. `record_failure` from `update_task_status(FAILED)` and `record_success` from `ARCHIVED`. OPEN after 3 failures, auto-HALF_OPEN after 60 s, recovers after 2 successes.
- **Timeout** (`src/timeout.py`) — `@with_timeout(seconds, task_id=...)` decorator and `run_with_timeout` wrapper around `asyncio.wait_for`. Pipeline stages don't currently apply it; it's a building block.
- **Queue** (`src/queue/queue.py`) — module-level `_queue` list, JSON-persisted to `.kb-queue.json` (only non-`APPROVED` tasks survive restarts; `_load_queue` runs at import). `MAX_RETRIES = 3`, then dead-letter. `_process_next` is single-flight and respects `_paused`.
- **Idempotency** (`src/utils/idempotency.py`) — `md5(source_type:value:content_prefix)` keyed by task_hash, in-memory TTL of 7 days. `check_and_mark` is **not atomic** with `enqueue_task`'s list append — two rapid calls could both pass the check; for stronger dedup use content prefixes.
- **State machine** (`src/orchestrator/state_machine.py`) — `VALID_TRANSITIONS` set plus `EVENT_TO_STATUS` map. `Orchestrator` currently drives transitions directly via `update_task_status` rather than calling `can_transition`/`get_next_status`, so the table is documentation until extended.
- **Schema registry** (`src/schemas/registry.py`) — `CURRENT_VERSION = "v1.0"`, `register_migration(from, to, up, down)` populates the module-level `MIGRATIONS` dict; `migrate_data(data, target)` looks up the edge directly (no path composition). Add migration edges when bumping `CURRENT_VERSION`.
- **Sync** (`src/sync/`) — `SnapshotStore` is a JSON file mapping `filename → md5`, persisting on every `set`. `FileSyncWatcher.scan_once` globs `*.md` under `root`, computes md5, diffs against the snapshot, fires the `on_change` callback, then updates the snapshot. `start_watch` uses watchdog's `Observer` and calls `scan_once` on `.md` modifications. **Note:** the snapshot key is `file_path.name` (not the relative path), so two files with the same name in different subdirectories will collide — keep notes in flat directories or extend the key.
- **Vector store** (`src/vector/`) — `LanceDB` singleton in `store.py`, schema fixed at 1536-dim float32. `init_vector_store(db_path)` must be called before any upsert/search; `get_table()` raises `RuntimeError("Vector store not initialized")` otherwise. `vector_search_chunks` converts `_distance` to a similarity score via `1 - distance` and assumes the embedding model exposes comparable distances.

### Directory layout created by `python -m src.cli init`

```
<base>/                  # cwd by default, or --path
├── Inbox/{Pending,Processing,Error}/
├── Notes/
├── Knowledge/{Archive}/
├── .index/               # LanceDB lives here
└── Templates/
```

`Inbox/Pending/` and `Knowledge/Archive/` are writeable staging areas; current pipeline writes to `Inbox/Processing/` (Collector) and `Knowledge/` (Librarian). `Knowledge/Archive` is provisioned but unused.

## Things to know before editing

- **Two import styles coexist.** Modules under `src/` generally use relative imports (`from .types import ...`, `from ..events.event_bus import event_bus`). `src/sync/file_watcher.py` is the exception: it uses absolute `from src.sync.snapshot_store import SnapshotStore` and `RuntimeError("watchdog not installed; pip install watchdog")` if watchdog is missing. New code should match the relative style of the package it lives in.
- **Event handlers register on import.** `src/pipeline/pipeline.py` and `src/orchestrator/orchestrator.py` attach handlers at module load. Adding a new pipeline stage means (a) emit a new event, (b) add a handler in `pipeline.py`, (c) optionally add a payload dataclass in `events/events.py`.
- **Embedding provider is a process-global singleton.** `pipeline.librarian._embedding_provider` and `searcher.hybrid_search._embedding_provider` are independent globals — set both if you switch providers, otherwise archive and search will disagree.
- **CLI is CWD-sensitive.** `Path("Inbox")`, `Path("Notes")`, `Path("Knowledge")`, and `KnowledgeBasePaths.default()` resolve relative to the current working directory. Run from the repo root (or pass `--path`).
- **TDD per migration plan.** When extending per `docs/superpowers/plans/...`, follow the write-test-fail-implement-pass-commit rhythm from that plan; one commit per task.
- **Tests mirror `src/` layout one level deep.** `tests/test_<module>.py` for top-level modules; `tests/test_<package>/test_<file>.py` for sub-packages (e.g. `tests/test_vector/test_store.py`). New tests follow that mapping.
- **All commit messages on `master` use `feat:` / conventional prefixes** and are scoped to a single concern (see `git log` for style).