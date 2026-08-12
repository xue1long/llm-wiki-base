# Cross-file Duplicate Logic Refactor — Implementation Plan

> **For execution:** follow the project TDD workflow one task at a time. Each task ends with its own focused test, review, and logical commit.

**Goal:** Consolidate proven duplicate production logic while preserving observable behavior and compatibility for existing callers.

**Design:** `docs/superpowers/specs/2026-08-12-cross-file-duplicate-refactor-design.md`

**ADR:** `docs/adr/0001-compatibility-first-duplicate-refactor.md`

**Constraints:** Do not touch WebUI code. Do not delete a wrapper until static imports, tests, and the re-indexed graph show zero callers. Preserve the existing untracked `.codebase-memory/` artifact and unrelated plan files. Use `apply_patch` for edits and stage only named files.

**Audit gates:** The two audit records in `docs/superpowers/audits/` are mandatory execution gates. Every migration task must use both `rg` symbol/import search and focused tests; the refreshed codebase-memory graph is additional evidence, never the sole deletion proof. A failed edge-case or smoke test stops that task and leaves its compatibility wrapper in place.

## Task 1: Canonicalize file hashing

**Files:**

- Add `src/utils/hashing.py`.
- Update `scripts/batch_build.py` and `scripts/migrate_vector_paths.py`.
- Extend `tests/test_scripts/test_batch_build.py` and `tests/test_scripts/test_migrate_vector_paths.py`; add `tests/test_utils/test_hashing.py` only if existing coverage cannot express the contract.

**Contract:** `sha256_file(path: str | Path, chunk_size: int = 1 << 16) -> str` returns the lowercase 64-character SHA-256 digest, reads binary data in chunks, and preserves current missing-file/error behavior.

**TDD steps:**

1. Add tests for empty input, multi-chunk input, `Path` input, and the existing script callers; run the focused tests and confirm the new import/helper path fails.
2. Implement the smallest shared helper using `hashlib.sha256` and `Path.open("rb")`.
3. Replace the two local implementations with imports; retain caller-specific flow and report behavior.
4. Run the two script test files and the hashing tests; inspect the diff for accidental behavior changes.
5. Commit only this task as `refactor(utils): 统一文件哈希实现`.

## Task 2: Route deduplication through canonical cosine similarity

**Files:**

- Update `src/wiki/features/dedup.py`.
- Update `tests/test_utils/test_similarity.py` and `tests/test_wiki/test_dedup.py` or `tests/test_wiki/test_dedup_auto.py` as needed.

**Contract:** Keep `src/utils/similarity.py::cosine_similarity` as the public implementation. Preserve results for empty vectors, unequal lengths, zero norms, and normal vectors. Keep a short private compatibility wrapper in `dedup.py` first if direct tests or imports still rely on `_cosine_similarity`; remove it only after the graph re-index proves no callers.

**TDD steps:**

1. Add regression cases for the private wrapper's empty-vector behavior and all canonical edge cases; run focused tests to establish the pre-migration baseline.
2. Make `_cosine_similarity` delegate to the canonical helper, adding only the minimal compatibility guard required by existing behavior.
3. Run dedup and similarity tests, then use `rg` to verify no second numerical implementation remains.
4. Commit as `refactor(dedup): 复用统一余弦相似度实现`.

## Task 3: Share encryption-error classification without merging format adapters

**Files:**

- Add `src/utils/extract/errors.py`.
- Update `src/utils/extract/pdf.py` and `src/utils/extract/office.py`.
- Extend `tests/test_utils/test_extract_encrypted.py` and `tests/test_utils/test_extract_doc_guard.py`.

**Contract:** `looks_like_encryption_error(exc: BaseException) -> bool` centralizes only the shared message/class heuristic. PDF-specific warning handling and Office-specific `PackageNotFoundError`/`BadZipFile` handling remain in their format adapters. Existing `EncryptedDocumentError` type and user-facing messages remain unchanged.

**TDD steps:**

1. Add tests covering known encrypted exceptions, unrelated exceptions, and each format adapter's special branches; confirm the shared helper is absent/failing.
2. Implement the small classifier in `src/utils/extract/errors.py`.
3. Replace duplicated heuristic branches while retaining adapter-specific exception handling.
4. Run extractor tests and a direct import smoke check for both modules.
5. Commit as `refactor(extract): 统一加密文档错误识别`.

## Task 4: Add one compatibility-aware CLI project resolver

**Files:**

- Update `src/lib/project.py`.
- Update `src/cli_ext/wiki_cleanup_v1_cmd.py`, `relations_cmd.py`, `migrate_source_slugs_cmd.py`, `wiki_polish_cmd.py`, `cache_cmd.py`, `heat_cmd.py`, and `fields_cmd.py`.
- Extend `tests/test_lib/test_project_resolve.py` and the affected `tests/test_cli_ext/` files; add `tests/test_lib/test_cli_project_resolve.py` for the new seam if needed.

**Contract:** Add `resolve_cli_project(project_arg, *, with_paths=True)`. With paths it returns `(ctx, paths)`; without paths it returns `ctx`. It preserves `ProjectNotFoundError` conversion to the existing stderr message and exit code 2. Existing command-local functions may remain as thin compatibility wrappers until all direct callers are migrated.

**TDD steps:**

1. Add tests for both return shapes, missing projects, project IDs/paths, and the existing command error contract; run focused tests and confirm the new seam fails.
2. Implement the resolver by delegating to the already-canonical `resolve_project` / `resolve_ctx_only`; do not duplicate resolution logic.
3. Migrate command modules one at a time, preserving aliases, output, and command-specific path usage.
4. Run all affected CLI tests and `rg` for old resolver bodies. Keep wrappers where direct imports remain.
5. Commit as `refactor(cli): 统一项目解析兼容入口`.

## Task 5: Share script timestamp logging

**Files:**

- Add `scripts/_common.py`.
- Update `scripts/phase4_batch.py` and `scripts/pilot_ingest.py`.
- Extend the corresponding script tests, especially `tests/test_scripts/test_batch_build.py` only if it covers shared script conventions; otherwise add the smallest focused test under `tests/test_scripts/`.

**Contract:** `log_message(message, report)` preserves `[HH:MM:SS] ` formatting, stdout flushing, and append-to-report behavior. The report path remains explicit at the caller, so importing the helper has no hidden global file side effect. Direct script execution must continue to work.

**TDD steps:**

1. Add tests for formatting, flush, append behavior, Unicode text, and a missing report parent if current behavior defines it; establish failure.
2. Implement the minimal helper with an explicit report path.
3. Replace both local `_log` bodies and preserve each script's report constant and invocation flow.
4. Run focused script tests and direct `python scripts/<name>.py --help` smoke checks where supported.
5. Commit as `refactor(scripts): 复用统一日志输出`.

## Task 6: Compatibility cleanup and graph verification

**Files:** Only files proven necessary by the updated graph and tests; likely affected test helpers are separate from production modules.

**TDD/verification steps:**

1. Re-index the complete repository with `codebase-memory-MCP`.
2. Query callers, imports, and traces for every old helper. Classify each remaining use as production, test-only, or zero-use.
3. Remove only zero-use production duplicates and test-only helpers that have an explicit replacement; retain low-volume compatibility wrappers and document their removal condition.
4. Run the full required suite with `PYTHONPATH=.` and `--import-mode=importlib`, plus import smoke checks for `src.cli`, extractors, scripts, and the server module if top-level imports changed.
5. Run the final code review and record risk status: no high-risk direct deletion; high-risk paths remain compatibility-first.
6. Commit cleanup and verification as `refactor: 清理重复逻辑兼容包装` only if there is an actual safe cleanup.

## Final acceptance checks

- `codebase-memory-MCP` reports updated node/edge totals and no hidden production callers for removed duplicates.
- Focused tests for all five migrated areas pass.
- Full pytest suite passes with the repository-required import mode.
- `git diff --check` passes; unrelated untracked files remain untouched.
- No new dependency, mega-utility module, WebUI change, or direct deletion of high-risk code was introduced.
- `.memory/` captures the completed multi-step refactor and `.superpowers/sdd/progress.md` records task status.
