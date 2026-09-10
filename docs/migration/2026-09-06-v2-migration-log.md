# v2 → ruflo-kb migration log

## Scope

- Source: `D:/5- 项目/000-Nico/LLM_Knowledge_base_v2`
- Target: `knowledge/video-notes-wiki`
- Target project UUID: `e3a0472c-06af-41e4-8d06-083146f195f7`
- Source was read-only throughout the migration.

## Execution

The implementation was split across parallel packages for schema compatibility, manifest and state, Wiki conversion, raw/pending conversion, vector rebuild, and final integration.

The content apply run used `migration-20260910`. The final audit dry-run used the same source and target with run id `audit-final-20260910`.

| Item | Count |
|---|---:|
| Manifest items | 5,138 |
| Raw files | 3,056 |
| Wiki files | 2,082 |
| Archived files | 637 |
| Pending files | 155 |
| Metadata-only files | 5 |
| Quarantined files | 1 |
| Skipped files | 16 |
| Support artifacts | 2 |

## Evidence

- Manifest: `knowledge/video-notes-wiki/.index/staging/audit-final-20260910/migration-manifest.json`
- Per-item report: `knowledge/video-notes-wiki/.index/staging/audit-final-20260910/migration_report.csv`
- Warnings: `knowledge/video-notes-wiki/.index/staging/audit-final-20260910/migration_warnings.csv`
- Pending decisions: `knowledge/video-notes-wiki/.index/staging/audit-final-20260910/pending_decisions.csv`
- Raw SHA-256 comparison: 0 missing, 0 mismatches.

## Current state

Content migration and native Wiki health checks are complete. The revised migration implementation has durable resume/rollback records, but the historical apply run predates that revision; its manifest is preserved while its promotion record still needs to be backfilled or the run repeated. Vector rebuild remains pending because no embedding provider is configured and the disk preflight reports 3.61 GB available versus 8.75 GB required.
