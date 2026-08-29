# Workspace Ownership Ledger — 2026-08-28

## Scope

本台账只记录本次执行启动时的工作区状态，不代表对既有改动的归属作默认判断。

## Baseline

| Metric | Count |
|---|---:|
| Git status entries | 4,737 |
| Tracked modified | 1,288 |
| Deleted | 21 |
| Untracked | 3,428 |
| `.git/index.lock` | absent at inspection |

## Group classification

| Category | Observed scope | Decision | Evidence / next action |
|---|---|---|---|
| KC | `src/kc/` and related tests | unresolved | Compare against KC commits, progress ledger and tests before inclusion |
| Collector | `src/collector/` and related tests | unresolved | Confirm migration ownership and test evidence |
| Pipeline/service/server | `src/pipeline/`, `src/services/`, `src/server/`, `src/queue/` | unresolved | Trace every ingest caller before any edit |
| Wiki artifacts | `knowledge/novel-wiki/wiki/`, `.index/`, schema/taxonomy | exclude from KC commit | Treat as generated/user data; separate artifact decision required |
| Raw source | `knowledge/novel-wiki/raw/sources/` | unresolved / protected | 21 deletions observed; do not restore or delete further until owner confirms |
| WebUI | `web/` | exclude from KC commit | Separate task and documentation review |
| Docs/scripts | `docs/`, `scripts/`, root guidance files | unresolved | Assign per feature, never by directory-wide staging |
| Test/temp output | `.pytest-kc-*`, caches, reports | unresolved | Confirm reproducibility and user-data status before cleanup |
| Plan/report files | current execution plans and this report | include as execution records only | Do not mix with product/code commit without explicit approval |

## Decision rule

Each path must be assigned `include`, `exclude`, or `unresolved` together with owner/evidence, approval time, and rollback boundary. Only `include` paths may be staged. The 21 raw-source deletions remain protected and unresolved.

## Current gate

**STOP:** ownership confirmation is required before any source edit, `git add`, commit, restore, deletion, or cleanup.

