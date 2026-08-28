# ADR: Vector publication intent around Wiki commits

- Status: accepted
- Date: 2026-08-28

## Decision

Wiki is authoritative and vectors are derived. A durable intent entry is
written to `.index/vector_pending.json` before the first Wiki page write in a
commit. After the Wiki batch commits successfully, the entry is promoted to
`pending`; vector failure remains retryable through reconciliation.

Reconciliation uses the existing Wiki files and ledger. It removes only an
orphaned pre-commit `intent` whose page is absent, while a missing page for a
`pending` entry remains a failed, observable reconciliation item. Repeated
reconciliation and startup scans are idempotent. Ledger entries without
`publication_state` continue to mean `pending`.

## Boundaries

This decision does not redefine `structurally_verified`, change
`workflow_state="verified"`, evaluate claim truth, add claim-to-page mapping,
introduce another writer, or add a publication waterline or vector
transaction.
