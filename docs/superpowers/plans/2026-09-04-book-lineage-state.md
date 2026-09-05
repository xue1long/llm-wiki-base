# Book Lineage State and Incremental Compilation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every raw source, Wiki artifact, KC artifact, and Book chapter traceable through one project-local state store, and make Book compilation fail before publication when any source is missing, invalid, stale, or unclassified.

**Architecture:** Keep Markdown/JSON/KC files as content artifacts, and add a project-local SQLite lineage store at `<project>/.index/lineage/state.db` for identities, hashes, transitions, build runs, tombstones, and durable outbox events. The store records write intent before artifact writes and has a reconciler for crashes between file and database steps; existing in-process `EventBus` remains an accelerator only. Book compilation freezes a manifest, compiles into staging, compares the compiled source set with the frozen set, then atomically publishes the Book and its manifest.

**Tech Stack:** Python 3.11+, stdlib `sqlite3`, existing atomic file writer, existing EventBus, existing KC/Wiki/Book APIs, pytest.

**Spec:** `docs/superpowers/plans/2026-09-04-book-lineage-state.md`

## Global Constraints

- Do not store source or Wiki body text in SQLite; store IDs, paths, hashes, statuses, relations, and audit metadata only.
- Preserve existing `wiki/`, KC bundle, and Book file formats; lineage is additive and must be rebuildable from existing artifacts.
- Use stable `source_id` and `wiki_page_id`; do not use mutable filenames as the only identity.
- Raw `source_id` is assigned once from the project-relative canonical path and persisted; renames require an explicit alias/tombstone operation, while content hashes are used for change detection and rename matching only.
- Wiki-to-source relations are many-to-many because synthesis pages may cite several sources.
- Raw additions, modifications, deletions, unsupported content, no-content sources, provider failures, and unknown states must be explicit registry states; none may be silently omitted.
- A failed or incomplete run must not delete or overwrite the last committed Book.
- Use SQLite transactions for registry/outbox updates and atomic temp-file replacement for artifact writes.
- Keep `batch_build.py`, `batch_commit.py`, and `aggregate_synthesis.py` as compatibility entry points while routing their production writes through the shared lineage API.
- Follow the repository test command: `PYTHONPATH=. python -m pytest --import-mode=importlib`.
- Do not change the protected `knowledge/novel-wiki` data during tests; use temporary project roots or an approved staging copy.

## Investigation Findings

- `src/cli.py` registers `book show` and `book build`; `src/cli_ext/book_cmd.py` is the project-scoped adapter and defaults output to `<project_root>/book/` only with `--apply`.
- `src/kc/views/book/materialize.py` reads `.index/kc/bundles/` and publication state; it does not scan `wiki/` as the Book input of record.
- `src/kc/views/book/rebuild.py` performs chapter compilation and staged output behavior; it is the correct place for the frozen manifest/closure gate.
- `src/services/batch_state.py` centralizes the existing `.index/batch_build_state.json` file; `scripts/phase4_batch.py`, `scripts/phase3_accept.py`, `scripts/phase5_accept.py`, `src/services/files.py`, and batch tests still depend on that legacy batch state.
- `src/cli_ext/batch_cmd.py` exposes `batch build` and `batch commit`; `scripts/batch_build.py` is the batch ingest/archive entry point and `scripts/batch_commit.py` is the serialized generate-cache commit entry point.
- `src/cli_ext/scripts_cmd.py` exposes `aggregate-synthesis`; `scripts/aggregate_synthesis.py` is optional rather than part of the HTTP ingest path, but it writes synthesis Wiki pages and therefore must register lineage when it writes.
- `src/sync/snapshot_store.py` already detects file MD5 changes and should be reused as a detector, not promoted to the cross-stage state authority.
- Existing `wiki/index.md`, `wiki/log.md`, KC manifests, and Book sidecars remain useful projections/audit artifacts but do not currently provide one complete source-to-Book relation.
- `src/services/batch_state.py` remains a compatibility projection during migration; lineage becomes authoritative only after all production writers dual-write and the migration gate passes.

### Task 0: Freeze the lineage contract and inventory existing artifacts

**Files:**
- Create: `docs/superpowers/specs/2026-09-04-book-lineage-state.md`
- Create: `scripts/kc_lineage_inventory.py`
- Inspect/modify as needed: `scripts/batch_build.py`, `scripts/batch_commit.py`, `scripts/phase4_batch.py`, `scripts/batch_generate.py`, `scripts/accept_batch.py`, `scripts/aggregate_synthesis.py`, `scripts/ingest_novel_wiki_manual.py`
- Test: `tests/test_scripts/test_kc_lineage_inventory.py`

**Interfaces:**
- Produces an inventory record for every raw source, Wiki page, KC bundle, and Book sidecar with `source_id`, path, hash, and an explicit `legacy_unverified` or resolved state.

- [ ] **Step 1: Write failing inventory tests** covering raw-only, Wiki-only, KC-only, Book-only, linked artifacts, duplicate IDs, and missing files.
- [ ] **Step 2: Run the inventory tests and verify they fail because the inventory API does not exist.**
- [ ] **Step 3: Implement the smallest read-only inventory script using existing `WikiPage` parsing, KC manifest parsing, and Book JSON parsing.** It must never write project content.
- [ ] **Step 4: Run the inventory tests and verify they pass.** The inventory must require a complete scan marker before producing raw deletion tombstones; partial or permission-failed scans produce `scan_incomplete` and preserve prior artifacts.
- [ ] **Step 5: Run the script on an approved temporary/staging project and record unresolved mappings as `legacy_unverified`; do not claim historical completeness.
- [ ] **Step 6: Commit the contract and inventory only.**

### Task 1: Add the project-local SQLite lineage store

**Files:**
- Create: `src/lineage/__init__.py`
- Create: `src/lineage/types.py`
- Create: `src/lineage/api.py`
- Create: `src/lineage/sqlite_store.py`
- Create: `src/lineage/reconcile.py`
- Create: `tests/test_lineage/test_store.py`
- Create: `tests/test_lineage/test_transitions.py`

**Interfaces:**
- `LineageStore.open(project_root: Path) -> LineageStore`
- `LineageStore.register_source(source_id: str, source_path: str, source_hash: str, status: SourceStatus) -> None`
- `LineageStore.transition_source(source_id: str, expected: SourceStatus, new: SourceStatus, reason_codes: tuple[str, ...] = ()) -> None`
- `LineageStore.link_artifact(source_id: str, artifact_kind: ArtifactKind, artifact_id: str, path: str, content_hash: str, status: ArtifactStatus) -> None`
- `LineageStore.link_artifact(artifact_kind: ArtifactKind, artifact_id: str, source_ids: tuple[str, ...], path: str, content_hash: str, status: ArtifactStatus) -> None`
- `LineageStore.create_build_run(expected_source_ids: tuple[str, ...], input_snapshot: str) -> str`
- `LineageStore.record_build_member(run_id: str, source_id: str, chapter_id: str, status: str) -> None`
- `LineageStore.health() -> LineageHealth`
- `reconcile_pending_operations(project_root: Path) -> ReconcileSummary`

- [ ] **Step 1: Write failing tests for schema creation, idempotent registration, legal/illegal transitions, foreign-key enforcement, tombstones, build runs, and SQLite `integrity_check`.**
- [ ] **Step 2: Run the tests and verify RED.**
- [ ] **Step 3: Implement SQLite schema and transactions with `PRAGMA foreign_keys=ON`, busy timeout, schema version, and an outbox table.** Do not add a generic ORM.
- [ ] **Step 4: Implement typed transition validation so illegal state regressions fail closed.**
- [ ] **Step 5: Run the tests and verify GREEN.**
- [ ] **Step 6: Add database health checks for orphan rows, duplicate source IDs, invalid states, pending outbox events, and artifact path/hash mismatches.**
- [ ] **Step 7: Commit the lineage store and contract tests.**

### Task 2: Register raw discovery, assessment, ingestion, modification, and deletion

**Files:**
- Modify: `src/sync/snapshot_store.py`
- Modify: `src/services/ingest.py`
- Modify: `src/pipeline/ingest.py`
- Modify: `src/server/routes/ingest.py` only for source identity/status propagation
- Modify: the existing readiness assessment module that emits `skip_no_content`, `unsupported`, and `quarantine_degraded`
- Modify: `scripts/kc_novel_wiki_inventory.py`
- Test: `tests/test_lineage/test_raw_lifecycle.py`
- Test: `tests/test_pipeline/test_ingest_generate_commit_split.py`

**Interfaces:**
- `discover_raw_sources(project_root: Path) -> tuple[RawSourceChange, ...]`
- `record_raw_assessment(source_id: str, decision: str, reason_codes: tuple[str, ...]) -> None`
- `record_raw_tombstone(source_id: str, source_path: str, observed_hash: str | None) -> None`

- [ ] **Step 1: Write failing tests for new raw, unchanged raw, changed raw, deleted raw, unreadable raw, unsupported raw, no-content raw, and scan failure.**
- [ ] **Step 2: Run the tests and verify RED.**
- [ ] **Step 3: Register every discovered raw before enqueueing ingestion, using `source_id` plus content hash.**
- [ ] **Step 4: Mark changed sources stale and enqueue re-ingestion; do not reuse old KC/Wiki/Book artifacts as current.**
- [ ] **Step 5: Record explicit tombstones for confirmed deletion; a failed scan must not imply deletion.** Preserve old artifacts as orphaned until an explicit deletion policy is applied.
- [ ] **Step 6: Persist readiness decisions and prevent `raw_rejected`, `raw_no_content`, `raw_unsupported`, and `provider_error` from silently entering Book.**
- [ ] **Step 7: Run focused pipeline and lifecycle tests and verify GREEN.**
- [ ] **Step 8: Commit raw lifecycle integration.**

### Task 3: Register Wiki and KC artifact commits

**Files:**
- Modify: `src/wiki/storage/page_writer.py`
- Modify: `src/lib/write_hooks.py` only where atomic commit callbacks are needed
- Modify: `src/kc/publish/batch.py`
- Modify: `src/knowledge/core/adapter.py` only to preserve stable source IDs in the existing adapter
- Modify: `src/events/event_bus.py`
- Modify: `src/events/events.py`
- Test: `tests/test_lineage/test_artifact_transitions.py`
- Test: Wiki writer and KC publish regression tests
- Conditional: `scripts/batch_build.py`, `scripts/batch_commit.py`, `scripts/phase4_batch.py`, `scripts/batch_generate.py`
- Conditional: `scripts/aggregate_synthesis.py`

**Interfaces:**
- `record_wiki_commit(wiki_page_id: str, source_ids: tuple[str, ...], path: str, content_hash: str) -> None`
- `record_kc_commit(source_id: str, bundle_id: str, object_ids: tuple[str, ...], evidence_ids: tuple[str, ...], publication_version: int) -> None`
- `enqueue_lineage_event(event_type: str, source_id: str, payload: dict[str, Any]) -> None`

- [ ] **Step 1: Write failing tests proving a failed atomic Wiki/KC write does not become committed lineage.**
- [ ] **Step 2: Trace each script's actual write call and route only successful writes through the lineage API.** `batch_build.py` and `batch_commit.py` remain real batch write entry points; `aggregate_synthesis.py` is included only for its synthesis-page writes.
- [ ] **Step 3: Implement pending → atomic artifact write → committed transition with durable outbox insertion in the same state transaction boundary available to each writer.**
- [ ] **Step 4: Use EventBus to wake incremental Book work only after the durable transition; recovery must replay the outbox.
- [ ] **Step 5: Run focused writer, KC publish, batch, and synthesis tests.**
- [ ] **Step 6: Commit artifact lineage integration.**

### Task 4: Add frozen Book manifests and strict staging compilation

**Files:**
- Modify: `src/kc/views/book/materialize.py`
- Modify: `src/kc/views/book/rebuild.py`
- Modify: `src/kc/views/book/contract.py`
- Modify: `src/cli_ext/book_cmd.py`
- Modify: `src/cli.py`
- Create: `tests/test_lineage/test_book_manifest.py`
- Modify: `tests/test_kc/test_book_materialize.py`
- Modify: `tests/test_kc/test_book_rebuild.py`
- Modify: `tests/test_kc/test_book_rebuild_cli.py`
- Modify: `tests/test_kc/test_book_cmd.py`

**Interfaces:**
- `materialize_book_manifest(project_root: Path, *, title: str | None = None, strict: bool = True) -> BookBuildManifest`
- `rebuild_book(..., manifest: BookBuildManifest, run_id: str, output_dir: Path | None, apply: bool) -> BookRebuildReport`
- `BookBuildManifest.expected_source_ids: tuple[str, ...]`
- `BookBuildManifest.expected_wiki_page_ids: tuple[str, ...]`
- `BookBuildManifest.excluded_sources: tuple[ExcludedSource, ...]`

- [ ] **Step 1: Write failing tests for missing raw, missing KC, missing Wiki, missing evidence, duplicate source, unknown status, stale hash, and exact source-set equality.**
- [ ] **Step 2: Run the tests and verify RED.**
- [ ] **Step 3: Make materialization consume the registry's frozen source set and preserve stable source IDs through chapter mapping.**
- [ ] **Step 4: Make rebuild compile only to staging and record every source/chapter membership.**
- [ ] **Step 5: Add the pre-publication closure gate: `expected_source_ids == compiled_source_ids`, with all blockers empty.**
- [ ] **Step 6: Atomically publish `book/manifest.json` and chapter files, then mark Book artifacts committed.**
- [ ] **Step 7: Add `--strict` and JSON reporting to `book build`; keep dry-run as the default.**
- [ ] **Step 8: Run all Book/KC tests and commit.**

### Task 5: Add incremental Book updates and recovery

**Files:**
- Modify: `src/cli_ext/book_cmd.py`
- Modify: `src/cli.py`
- Modify: `src/lineage/api.py`
- Modify: `src/lineage/sqlite_store.py`
- Create: `tests/test_lineage/test_incremental_book.py`
- Create: `tests/test_lineage/test_outbox_recovery.py`

**Interfaces:**
- `plan_incremental_build(project_root: Path) -> BookBuildPlan`
- `replay_lineage_outbox(project_root: Path) -> ReplaySummary`
- `mark_deleted_source(source_id: str, *, explicit: bool) -> None`

- [ ] **Step 1: Write failing tests for new, modified, deleted, orphaned, and unchanged sources; interrupted build; repeated build; and replayed outbox events.**
- [ ] **Step 2: Run the tests and verify RED.**
- [ ] **Step 3: Build the delta from source hashes and prior committed manifest; reuse unchanged chapters and recompile only affected chapters.**
- [ ] **Step 4: Require explicit tombstones for chapter removal; preserve old Book on failed deletion/update runs.**
- [ ] **Step 5: Make stale snapshots fail with a retryable status instead of publishing against changed input.**
- [ ] **Step 6: Add `book plan`, `book build --strict`, and lineage outbox replay commands.**
- [ ] **Step 7: Run focused incremental/recovery tests and commit.**

### Task 6: Health checks, migration, and operational documentation

**Files:**
- Modify: `src/cli.py`
- Modify: `src/cli_ext/` command registration
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/conventions/directory.md`
- Create: `docs/guides/book-lineage.md`
- Create: `tests/test_lineage/test_health.py`
- Create: `scripts/kc_lineage_migrate.py`

**Interfaces:**
- `python -m src.cli lineage health --project <id> --json`
- `python -m src.cli lineage show --project <id> --json`
- `python scripts/kc_lineage_migrate.py --project <path> --dry-run`
- `python scripts/kc_lineage_migrate.py --project <path> --apply`

- [ ] **Step 1: Write failing tests for healthy DB, corrupt DB, orphan artifacts, pending outbox, stale Book, unresolved legacy records, and protected-project dry-run behavior.**
- [ ] **Step 2: Implement the read-only health command and migration dry-run.**
- [ ] **Step 3: Implement migration apply only for deterministic links; mark ambiguous records `legacy_unverified`.**
- [ ] **Step 4: Document raw add/change/delete semantics, strict Book build, incremental updates, and recovery.**
- [ ] **Step 5: Run health/migration tests and a temporary-project smoke test.**
- [ ] **Step 6: Commit operational support.**

## Design Amendments Required by Four-Lens Audit

- The completeness unit is Wiki-artifact based, not source-only. `BookBuildManifest` must carry `expected_wiki_page_ids` and each compiled chapter must carry the complete set of included `wiki_page_ids`; a source may map to many Wiki pages and a synthesis page may map to many sources.
- Book scope must be explicit: the project policy selects eligible Wiki page types/statuses, and every discovered page is included, explicitly excluded with a reason, or blocking. `expected_source_ids == compiled_source_ids` alone is insufficient.
- A multi-file Book cannot be called atomically published by replacing files one at a time. Publish an immutable versioned release directory under `book/.releases/<run_id>/`, then atomically replace `book/manifest.json` as the active pointer. Readers use the manifest; old releases remain recoverable until retention cleanup.
- Raw identity must be specified as a persisted registry key with explicit rename handling. The scanner may suggest a hash match, but only a recorded rename operation changes the source path; a partial scan never emits deletions.
- File/DB reconciliation must use an `operation_id`, expected hash, and release/run ID. A path existing is not proof of a successful write when another run may have replaced it.
- Legacy batch state must have a cutover gate: dual-write and compare for one complete staging run, then make lineage authoritative; before that, Book strict mode must fail if the two projections disagree.
- SQLite needs an explicit backup/migration protocol and a single-writer/build lease rule for every production writer, including legacy scripts; `EventBus` alone is not a synchronization mechanism.
- `legacy_unverified`, `raw_rejected`, `raw_no_content`, `raw_unsupported`, and `provider_error` must appear in the build plan as excluded or blocking entries according to an explicit project policy; no default path may silently drop them.

## Acceptance Gate

- A full inventory gives every raw source exactly one state: included, excluded, blocked, failed, or deleted.
- A strict Book plan fails before compilation when any included source lacks valid ingestion, KC, Wiki, evidence, or a stable mapping.
- A successful build has exact equality between frozen expected source IDs and committed chapter source IDs, and separately exact equality between frozen expected Wiki page IDs and committed chapter Wiki page IDs.
- A new raw source becomes Book-pending only after KC/Wiki commit and is included in the next incremental plan.
- A raw modification invalidates downstream hashes and recompiles affected chapters only.
- A raw deletion requires a tombstone and never deletes the last committed Book on a failed run.
- Unsupported/no-content/provider-failed sources remain visible with reason codes and cannot be silently published.
- Replaying the outbox after a crash converges to the same state without duplicate artifacts.
- `lineage health` detects SQLite corruption, orphan links, stale hashes, illegal transitions, and pending events.
- The active Book is selected by an atomically replaced manifest pointing to one immutable release directory; no failed run can expose a partially replaced chapter set.
- Existing Book, Wiki, KC, batch, synthesis, server, and full-suite tests remain green.

## Rollback

- Disable lineage writes with a project-local feature flag while retaining existing artifact writers.
- Revert Book strict-manifest integration independently from the SQLite store.
- Never delete `state.db`, previous `book/manifest.json`, or prior Book chapters during rollback; quarantine failed run staging under `.index/lineage/runs/`.

## Plan Audit Record

### Round 1: Comprehensive vulnerability audit

1. **Major:** SQLite/file writes are not one transaction; a crash can leave pending state with a committed artifact or vice versa. **Fix:** write intents, atomic artifact replacement, durable outbox, and a hash-based reconciler with `needs_repair` instead of guessing.
2. **Major:** A raw path-based ID breaks on rename. **Fix:** persist the first `source_id`, require explicit rename aliases/tombstones, and use hashes only for matching.
3. **Major:** A single `source_id` on Wiki artifacts cannot model synthesis pages with multiple sources. **Fix:** use many-to-many artifact links.
4. **Major:** Existing batch state has several readers/writers and could diverge from the new DB. **Fix:** retain it as a compatibility projection, dual-write all real writers, and switch authority only after migration acceptance.
5. **Major:** Direct scripts can bypass HTTP/EventBus. **Fix:** audit and route `batch_build.py`, `batch_commit.py`, `phase4_batch.py`, `batch_generate.py`, `accept_batch.py`, `aggregate_synthesis.py`, and the manual ingest script through one API or explicitly classify them as non-production.
6. **Major:** A partial raw scan could turn missing files into false deletions. **Fix:** require a complete scan marker and preserve artifacts on scan failure.
7. **Major:** Concurrent full and incremental builds can publish out of order. **Fix:** project-local build lease plus frozen input version and stale-snapshot rejection.
8. **Major:** Hashing generated Markdown with `generated_at` creates false changes. **Fix:** separate canonical input hash, semantic render hash, and audit timestamp.
9. **Major:** Outbox replay can duplicate transitions or chapters. **Fix:** unique event keys and idempotent upserts.
10. **Optimization:** Historical artifacts have ambiguous mappings and large scans may be expensive. **Fix:** mark ambiguity `legacy_unverified`, require a migration report, index source/hash columns, and use incremental scan snapshots.

### Round 2: Failure pressure test

| Scenario | Required result | Hardening |
|---|---|---|
| Crash before raw registration | Next scan registers the same source once | Unique source key + idempotent registration |
| Crash after Wiki replace, before DB commit | Reconciler completes or marks repair | Pending intent + reconciler |
| Crash after Book publish, before DB commit | New run reconciles publication marker; old manifest remains recoverable | Atomic Book manifest + publication marker |
| Raw directory permission failure | No deletion inferred | Complete-scan marker |
| Raw rename | No duplicate source or silent loss | Explicit alias/tombstone |
| New raw during build | Included in next run, never half-included | Frozen input snapshot |
| Synthesis cites multiple sources | All source edges retained | Many-to-many relation table |
| HTTP and batch run together | No lost update | SQLite transaction + write lease |
| Provider truncation/missing evidence | Source blocked; old Book survives | Fail-closed staging build |
| Corrupt/locked state DB | Stop without touching artifacts | Health check, backup, fail-closed open |

Round 2 found no new design-level gap after these hardenings. Before coding, the script-entry inventory and migration dry-run must confirm the actual production writers and complete raw scan.

### Round 1 re-review after remediation

- Fatal defects: none remaining.
- Major risks: each has an explicit task, interface, failure state, test, or rollback rule; the former file/DB transaction gap is covered by pending intents, reconciliation, and atomic publication markers.
- Scope gate: the plan covers raw lifecycle, all identified production/compatibility writers, Wiki/KC lineage, Book full and incremental builds, health checks, migration, documentation, and rollback.
- Coding gate: passed for plan quality only; implementation has not started.
