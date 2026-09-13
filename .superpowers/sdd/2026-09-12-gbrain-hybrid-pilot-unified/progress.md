# SDD ledger — plan: docs/superpowers/plans/2026-09-12-gbrain-hybrid-pilot-unified.md

## Pre-flight plan scan

No separate spec is linked by the plan; the plan text is the current authority.

| Item | Shared file/interface | Scan result | Ruling |
|---|---|---|---|
| Task 0 → Task 1 | reviewed ref, runtime readiness | Task 1 consumes the frozen runtime contract; no conflict found | Keep runtime fail-closed |
| Task 1 → Task 2 | `src/integrations/gbrain/` public surface | Task 2 needs project state but must not bypass runtime resolver | Add project state behind the same package facade |
| Task 2 → Task 3 | search config/state, source ownership, job records | Task 3 consumes durable records and must preserve config epoch | Define stable defaults and monotonic job IDs |
| Task 2 → Task 4 | readiness state and source ID | Task 4 must only use an owned source marked ready | Keep `enabled` separate from `ready` |
| Task 2 → Task 5 | status/job payloads | HTTP/UI can expose only non-sensitive state | Do not persist query text, page body, keys, or env vars |
| Task 2 self-check | config/state/job files and lock | One writer per JSON file; all writes atomic; duplicate jobs are idempotent | Use stdlib JSON + atomic replace + per-project lock |
| Task 0 | fixture and embedding evidence | Already completed in the P0 report; no new real-data import | Use temporary non-sensitive fixtures only |
| Task 1 | runtime resolver/setup | Already completed and verified | Do not re-dispatch or rewrite |

## Rulings

- Ruling: implement only Task 2 in this slice — the next tasks depend on its persisted contracts, while importing real `knowledge/` would exceed the current verified safety boundary.
- Ruling: use a stable source ID derived from the on-disk project UUID and keep `enabled` false by default — this prevents accidental remote indexing and survives filesystem moves.
- Ruling: job deduplication is keyed by `(project_id, kind, config_epoch)` — this prevents duplicate enable/rebuild work without inventing a queue replacement.

## Task status

- Task 1: complete (prior commit `504c903a`)
- Task 2: complete
- Task 3: in progress (snapshot/manifest slice complete)
- Task 4: complete (P0 slice)
- Task 5: complete (P0 slice)
- Task 6: in progress (automated resolver/runtime checks complete; real project cross-machine acceptance pending)

## Task 2 completion (2026-09-12)

- Added public project contracts in `src/integrations/gbrain/api.py` and `types.py`.
- Search config defaults to `enabled=false`, stores only relative `source_path`, and derives a stable source ID from the project UUID.
- Search state and job records use atomic JSON replacement under a per-project cross-process lock.
- Enable/rebuild jobs deduplicate while queued/running for the same config epoch; completed jobs do not suppress a new request.
- RED: new project tests failed at collection because the API did not exist. GREEN: `16 passed` across the GBrain runtime/setup/project/CLI tests; `py_compile` passed.
- Review: no query text, page body, API key, or full environment is persisted; no real `knowledge/` data was touched.

## Task 3 sync slice (2026-09-12)

- Added deterministic Wiki snapshot scanning with SHA-256 content hashes, canonical relative paths, slug mapping, and singular page types.
- Excludes catalog/log files, `_archive`, and `_stubs` from the searchable snapshot.
- Added atomic manifest persistence and added/updated/deleted reconciliation.
- RED: snapshot test exposed plural `sources` leaking as `page_type`; GREEN: `2 passed` after centralized directory-to-page-type mapping.
- Added fixed `sources add`/`import` argv builders, MCP intent builders for upsert/delete/restore, and a subprocess seam for initial import.
- Added retryable reconcile execution; the manifest is committed only after every intent succeeds.
- Verification: the full GBrain targeted set is `21 passed`; no real import or MCP write was triggered by these tests.

## HTTP lifecycle slice (2026-09-12)

- Added project-scoped GET/status, enable, disable, rebuild, and job endpoints.
- Enable/rebuild require explicit `confirm`; enable returns `202` with a durable job ID, while disable immediately sets backend to local and increments `config_epoch`.
- Repeated enable on an already-ready project is idempotent and does not enqueue a new job.
- Added route/service tests. Verification: `27 passed` across all current GBrain integration, CLI, service, and server tests.

## Task 4 adapter slice (2026-09-12)

- Added strict GBrain MCP result validation, source-scope enforcement, safe manifest path mapping, and per-page chunk deduplication.
- Added source-scoped stdio search request/transport with `GBRAIN_SOURCE`; user arguments contain only query and limit.
- Integrated hybrid search routing so a ready GBrain backend is checked before local vector readiness; malformed/empty/failed remote results fall back to local.
- Verification: `36 passed` across the full current GBrain, adapter, and search-service set.

## Worker/lifecycle execution slice (2026-09-12)

- Added durable job execution: runtime preflight, fixed CLI source registration/import, snapshot/manifest commit, embedding/path coverage gates, epoch recheck, and failure classification.
- HTTP enable/rebuild now schedules the worker only for queued jobs; an already-ready enable remains idempotent without scheduling an empty job.
- Verification: `39 passed` across the full current GBrain, worker, adapter, CLI, service, and server set.

## WebUI search control slice (2026-09-12)

- Added the search-page GBrain MCP toggle, explicit privacy/cost confirmation, status badge, queued/syncing polling, failure display, and immediate local fallback on disable.
- The UI displays `GBrain hybrid` only when the API reports `ready=true` and `backend=gbrain`; it never treats a queued job as ready.
- Updated `docs/webui-buttons.md` as required by the project UI change rule.
- Verification: `node --check web/js/views/search.js` passed; no real project data was imported.

## P0 readiness closure (2026-09-12)

- Worker now persists runtime `ready`/`failed` state after preflight; search also rejects a persisted ready state whose runtime path no longer exists.
- Added and verified the global `RUFLO_SEARCH_BACKEND=local` kill switch.
- Verification: `42 passed`, `node --check web/js/views/search.js`, and app OpenAPI smoke passed.
- `graphify update .` was attempted but the installed launcher could not create its bundled Python process; no graph refresh was claimed.

## Runtime bootstrap HTTP slice (2026-09-12)

- Added read-only runtime validation at `GET /gbrain` and an explicit-confirmation setup job at `POST /gbrain/setup`.
- Setup uses the existing reviewed-ref/isolated-install guard and persists `installing`/result state; ordinary search still cannot start installation.
- Added the WebUI “安装/修复 GBrain” entry and documented the new controls in `docs/webui-buttons.md`.
- Verification: `45 passed`, `node --check web/js/views/search.js`, and app OpenAPI smoke passed.
