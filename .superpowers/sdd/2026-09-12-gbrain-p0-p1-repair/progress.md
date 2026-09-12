# SDD ledger — plan: docs/superpowers/plans/2026-09-12-gbrain-p0-p1-repair.md

## Preflight

| Slice | Write set | Relationship | Result |
|---|---|---|---|
| A | `worker.py`, worker tests | Real GBrain coverage JSON → ready gate | Independent of B/C |
| B | `api.py`, `sync.py`, project/sync tests | Snapshot/import file set and source registration | Independent of A/C |
| C | `runtime.py`, `setup.py`, runtime/setup tests | Runtime discovery/install trust boundary | Independent of A/B |
| D | worker lifecycle/event/route files, sync tests | Consumes A/B contracts and wires incremental sync | After A/B |

Ruling: A/B/C run in parallel because their production write sets are disjoint; D waits for them because it consumes worker and sync contracts.

Ruling: Existing unrelated dirty files are preserved; agents may stage only their assigned files.

## Tasks

- Task A: complete — commit `2d659514`, real `embed_coverage_pct` contract and fail-closed parsing
- Task B: complete — commit `0792b063`, filtered import staging and source ownership/idempotency
- Task C: complete — commit `0792b063`, managed ref validation, install lock, repair promotion
- Task D: complete — commit `e0812c0a`, pre-search incremental reconcile and MCP mutation
- Task E: complete — 57 focused tests passed; compileall and WebUI syntax checks passed; external GBrain initialize/tools/status contracts verified. Real import and write mutations were intentionally not run.
