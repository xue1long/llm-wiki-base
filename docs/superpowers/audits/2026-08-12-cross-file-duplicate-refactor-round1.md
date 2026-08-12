# Plan Audit Round 1 — Comprehensive Leak Audit

**Scope:** `docs/superpowers/plans/2026-08-12-cross-file-duplicate-refactor.md`

**Result:** PASS WITH REQUIRED GUARDS. No critical blocker remains after the controls below are added to execution.

## Findings and controls

1. **Important — hidden imports and re-exports.** Graph call edges may miss direct imports, `__all__`, monkeypatch targets, and package re-exports. Before removing any helper, use `rg` for the symbol and module path, inspect `__init__.py` exports, then re-index and query imports.
2. **Important — cosine edge semantics.** The private dedup implementation has an empty-vector branch not identical to the public helper. Add explicit tests for empty, unequal, zero-norm, and normal vectors; retain a wrapper until those tests and graph evidence agree.
3. **Important — hash contract drift.** A shared helper must preserve binary mode, 64 KiB chunking, lowercase SHA-256 output, and exception behavior. Test empty files and a boundary larger than one chunk.
4. **Important — extractor exception taxonomy.** PDF and Office adapters have different special cases. The shared classifier may only own the common heuristic; keep `PackageNotFoundError`, `BadZipFile`, and PDF warning handling local, with tests for each branch.
5. **Important — CLI return-shape drift.** Some commands need `(ctx, paths)` while others need only `ctx`. The resolver must make this explicit and preserve the existing stderr plus exit-2 behavior for missing projects.
6. **Important — script import mode.** `scripts/` files may be executed directly rather than imported as a package. The shared logging module must be importable in the existing execution mode; run direct `--help`/import smoke checks.
7. **Important — logging side effects.** `_log` currently owns timestamp formatting, flushing, and report append behavior. Test exact formatting, Unicode, report path, and append order before replacing both bodies.
8. **Important — test-only dependencies.** Tests directly call private helpers and may monkeypatch local names. Keep compatibility wrappers until focused tests and the graph classify these as test-only or migrated.
9. **Important — stale index evidence.** The pre-change graph cannot prove post-change safety. Re-index after every production migration batch and use the refreshed graph for deletion decisions.
10. **Important — circular imports.** New utilities must depend only on stdlib or lower-level existing modules. Import smoke tests for `src.utils.extract`, `src.lib.project`, CLI extensions, and scripts are required.
11. **Optimization — over-broad utility module.** Do not create a mega-utils file. Keep hashing, similarity, extraction classification, project resolution, and script logging in their existing layers.
12. **Optimization — unrelated worktree state.** Stage named files only. Preserve `.codebase-memory/` and the unrelated existing plan file.

## Required plan amendments

- Each task must include direct-import/`rg` checks in addition to graph queries.
- Task 3 must explicitly test format-specific exception branches.
- Task 4 must retain wrappers while direct imports remain.
- Task 5 must verify direct script execution.
- Task 6 must be the only place where deletion is considered, and only after re-indexing.

## Gate

The plan may proceed to pressure testing because all identified risks have a concrete verification or compatibility control. No high-risk code is approved for direct deletion.
