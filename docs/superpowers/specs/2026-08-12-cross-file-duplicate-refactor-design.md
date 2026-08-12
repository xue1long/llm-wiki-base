# Cross-File Duplicate Logic Refactor — Design Spec

**Date:** 2026-08-12  
**Status:** Approved design; implementation pending plan audit  
**Scope:** Production duplicates identified by codebase-memory-MCP

## Goal

Consolidate repeated, cross-file logic behind small stable interfaces while preserving current CLI, ingestion, deduplication, hashing, logging, and test behavior. No high-risk implementation is deleted before all production callers are migrated and compatibility tests pass.

## Non-goals

- Do not refactor `_parse_llm_response`; both copies already delegate to `src.pipeline._pipeline_common.parse_llm_json`.
- Do not change hash algorithm, chunk size, cosine edge-case results, exception classes, CLI exit code, report format, or log timestamp format.
- Do not mix production refactoring with test-only `_fake_resolve` cleanup until production compatibility is verified.

## Findings and invariants

1. `sha256_file` is duplicated byte-for-byte in `scripts/batch_build.py` and `scripts/migrate_vector_paths.py`; both have live production callers.
2. `src/wiki/features/dedup.py:_cosine_similarity` is used by `find_near_duplicates` and the `dedup_auto` service path. The public utility is currently test-only according to the call graph.
3. PDF and Office encryption handlers share token-based detection but have format-specific exceptions (`BadZipFile`, `PackageNotFoundError`, PDF crypto warnings).
4. CLI resolver wrappers preserve two distinct return contracts: `(ctx, paths)` and `ctx`; all convert missing projects to stderr plus exit code 2.
5. The two script `_log` implementations share behavior but write to module-specific `REPORT` paths.
6. The graph confirms direct production callers for every high-risk function; static imports and compatibility names must be checked before final deletion.

## Architecture

### Public utility seam

- Add `src/utils/hashing.py::sha256_file(path: str | Path, chunk_size: int = 1 << 16) -> str`.
- Keep `src/utils/similarity.py::cosine_similarity` as the canonical implementation.
- Replace private deduplication math with a compatibility wrapper first, then migrate its caller.

### Extraction error seam

Add `src/utils/extract/errors.py::looks_like_encryption_error(exc) -> bool` for shared message/type heuristics. PDF and Office modules retain thin `_raise_if_encrypted` adapters so format-specific exception mapping remains local.

### CLI project seam

Add `src/cli_ext/project_resolve.py::resolve_cli_project(project_arg, *, with_paths=True, by_id_only=True)`. The CLI adapter owns stderr and `SystemExit(2)` handling; `src/lib/project.py` remains a pure project-resolution module exposing `resolve_project` and `resolve_ctx_only`. Existing module-local `_resolve*` functions remain as wrappers until all call sites and tests are migrated.

### Script logging seam

Add `scripts/_common.py::log_message(message, report)`. It accepts the report path explicitly, preserving each script's independent output file. Existing `_log` functions remain adapters during migration.

## Compatibility contracts

| Area | Contract that must not change |
|---|---|
| Hashing | SHA-256, binary reads, 64 KiB chunks, lowercase hexadecimal digest |
| Similarity | Mismatched/empty/zero-norm vectors return `0.0`; equal vectors retain current result |
| Extraction | Raise `EncryptedDocumentError` with the current format-specific message class |
| CLI | Return shape unchanged; missing project prints to stderr and exits with status 2 |
| Logging | `[HH:MM:SS] message`, flush stdout, append one newline to report |
| Pipeline parsing | Existing private names stay importable and continue delegating to `parse_llm_json` |

## Migration flow

```text
new canonical function
  → focused contract tests
  → old implementation becomes compatibility wrapper
  → production callers migrate
  → import/call graph re-check
  → full relevant tests
  → remove wrapper only in a later cleanup task
```

## Verification

- Focused tests for each new seam and all preserved edge cases.
- Existing tests for deduplication, extraction, CLI commands, scripts, and pipeline.
- `PYTHONPATH=. python -m pytest --import-mode=importlib` for the full suite.
- CLI import and missing-project smoke checks.
- Re-index with codebase-memory-MCP and confirm no production caller points to deleted symbols before cleanup.

## Rollback

Each subdomain is a separate commit. Roll back the latest subdomain commit if its focused or integration tests fail; compatibility wrappers ensure intermediate commits remain runnable.
