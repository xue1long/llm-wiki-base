# v2 → ruflo-kb validation report

## Result

Content migration: **PASS**. Full migration objective: **PENDING** until vector rebuild and service smoke test are completed.

| Gate | Result | Evidence |
|---|---|---|
| Manifest closure | PASS | 5,138 manifest rows; every item has a disposition |
| Raw integrity | PASS | 0 missing and 0 SHA-256 mismatches |
| V6 / legacy field persistence | PASS | Focused Wiki tests |
| Resume and rollback implementation | PASS | Injected interruption, exact run rollback, and collision tests in an isolated fixture |
| Target collision protection | PASS | Pre-promotion collision abort leaves live target unchanged |
| H1 / H2 / H4 / H5 | PASS | 0 issues; target status HEALTHY |
| Migration reports | PASS | 5,138 report rows, 811 warning rows, 155 pending rows |
| Embedding provider precheck | PENDING | No embedding provider is configured |
| Vector rebuild | PENDING | Dry-run: 1,924 pages / 6,136 chunks; no live LanceDB yet |
| Service and vector search smoke test | PENDING | Depends on vector rebuild |

The live content apply run (`migration-20260910`) was executed before durable promotion records were added. A non-destructive backfill created its authenticated run record; rollback dry-run identified 5,301 paths for that project/run and did not remove anything.

## Test evidence

The final focused run passed **124 tests** across migration, maintenance health checks, Wiki types, page writing, and tag compatibility.

## Resource gate

The migration disk gate requires approximately 8.75 GB free, including the 5 GB safety reserve. The current D: volume has approximately 3.61 GB free, so a new apply or vector build must refuse to start until space is available.

## Required final action

Configure an embedding provider that returns vectors compatible with the target search stack, release the required disk space, then run the vector rebuild and service smoke test. No source data needs to be re-migrated.
