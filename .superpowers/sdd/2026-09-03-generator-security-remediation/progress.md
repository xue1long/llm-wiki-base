# SDD ledger — plan: docs/superpowers/plans/2026-09-03-generator-security-remediation.md

## Preflight

- Branch: `codex/instance-template-safe-implementation`; not main/master.
- v1 default preserved: `src/config.py` leaves `RUFLO_PIPELINE_MODE` unset as the v1-compatible default; no production selector change authorized.
- Unrelated dirty files under `knowledge/novel-wiki/` are user-owned and out of scope; do not touch or stage them.
- Referenced evidence-contract spec and ADR were read. No new dependency is authorized.

### Task/file and interface conflict scan

| Scope | Shared surface | Finding | Ruling |
|---|---|---|---|
| Task 1 ↔ Task 2 | `ingest.py`, task/version context | Task 2 consumes task identity and template version from Task 1. | Implement Task 1 first; keep RenderBundle additive. |
| Task 1 ↔ Task 5 | task lock/manifest vs publish manifest | Both persist recovery metadata but at different scopes. | Task 1 owns task/stage state; Task 5 owns bundle publication. No duplicate lock protocol. |
| Task 1 ↔ Task 6 | template/contract snapshot | Task 6 enriches the snapshot contract created in Task 1. | Preserve one immutable snapshot per task; later code reads it, never re-resolves current files. |
| Task 2 ↔ Task 3 | `RenderBundle` → `WikiBundle` | Compiler is the only conversion from untrusted draft to trusted page data. | Writer must consume only validated compiler output. |
| Task 2 ↔ Task 4 | generator retry and draft output | Task 4 changes failure classification without making evidence/link errors generator retries. | Keep generator retries limited to format/structure/provider cases explicitly allowed by the existing path. |
| Task 3 ↔ Task 5 | validator → commit | Task 5 adds staging and commit around Task 3 validation. | No Writer, index, or vector call before validation and publish marker. |
| Task 4 ↔ Task 7 | budget/retry metrics vs shadow report | Shadow must observe the same task budget and not invoke a second LLM path. | Reuse counters/context; report only, no side effects. |
| Task 5 ↔ Task 7 | quarantine/recovery vs rollback | Rollback handles incomplete v2 bundles only and never rewrites published Wiki. | Preserve published state; quarantine incomplete bundles atomically. |
| Task 6 ↔ Task 7 | contract version and migration flag | v1 remains default; v2 is explicit until release gates pass. | Add flags/reporting without changing unset behavior. |
| Task 1 | listed files/tests | Interfaces and tests agree; no incompatible existing public API is specified. | Proceed. |
| Task 2 | listed files/tests | Draft constructor examples omit some named fields, so compatibility defaults are needed. | Use keyword-friendly/defaulted optional candidate fields while preserving immutability. |
| Task 3 | listed files/tests | Compiler/validator types are new and must not leak Writer concerns. | Keep pure deterministic boundary; integrate narrowly. |
| Task 4 | listed files/tests | `RetryBudget` is introduced across stages and must not multiply queue retries. | One task-owned budget object; fail closed at any limit. |
| Task 5 | listed files/tests | Cross-file atomicity cannot be delegated to `safe_write` alone. | Use staging manifest + marker and existing atomic writer. |
| Task 6 | listed files/tests | Snapshot needs content, not only hashes, for replay. | Store bounded prompt content/snapshot reference within project root and enforce path safety. |
| Task 7 | listed files/tests | Real-provider acceptance is external and may be unavailable. | Automate local gates; record any external acceptance as unverified, never weaken code gates. |

## Rulings

- Ruling: execute in Task 1→7 dependency order — later tasks consume the prior contracts; cost is sequential work.
- Ruling: do not stage or commit unrelated dirty knowledge files — they predate this task and are outside the requested file set; cost is commits remain scoped and the worktree stays dirty.
- Ruling: use existing writer/atomic primitives where possible — avoids a second transaction model; cost is recovery logic remains explicit at bundle level.

## Task status

- Task 1: complete — `b4e5a70f` plus follow-up `dfbdbf8e`; focused tests `16 passed`, py_compile passed. Follow-up integrated task-context metadata, lock/recovery boundary, manifest serialization, safe task paths, and queued-ingest staging. Full suite not run.
- Task 2: complete — `d85b3c9c` plus `64442ff6` adds immutable `RenderDraft`/`RenderBundle`, stable page keys, deterministic bundle hash, and a legacy-compatible `generate_render_bundle()` entry; RenderBundle/Generator tests `57 passed`.
- Task 3: complete — `3a79eaf5` adds deterministic compiler/validator boundary; compile smoke check passed. Dedicated compiler tests still need expansion.
- Task 4: complete — `df17c493` adds shared `RetryClass`/`RetryBudget`; `31ac11be` enforces budget at Generator retry boundary; `consume_or_raise` now fails closed for later stages; related tests `58 passed`.
- Task 5: complete — added redacted task quarantine records and staging manifest/publish-marker commit boundary with rollback on writer failure; focused assertions pass (pytest cleanup emits a known Windows temp-permission traceback).
- Task 6: complete — `2b4961c7` normalizes legacy null list fields; existing template snapshot/path-safety coverage and focused tests pass.
- Task 7: complete — adds pure local `compare_contracts` and unpublished-task rollback quarantine; safety tests pass. Real-provider acceptance remains unverified because no external provider run was authorized or required for local completion.
