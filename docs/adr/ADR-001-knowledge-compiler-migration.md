# ADR-001: Incremental Knowledge Compiler migration

Status: accepted for execution

Date: 2026-08-21

## Decision

Upgrade the existing `ruflo-kb` repository in place. Add a small `src/kc/` seam, adapt the existing pipeline and Wiki implementation, and postpone broad normalization until the minimum verified compiler loop is proven.

The execution order is:

```text
A discipline → C minimum compiler → B normalization backlog
```

## Invariants

- New facts are authoritative only as `KnowledgeObject + Evidence`.
- A new published Claim must have locally verified block-level Evidence.
- Wiki output is a `WikiProjection` and cannot become a second fact source.
- Existing data and entry points remain readable during A/C.
- A failed or incomplete object is not published; it is retried or isolated.

## Rejected alternatives

- A clean-slate second repository: loses existing data, tests and operational fixes.
- Full directory rewrite before a working vertical slice: creates migration risk without user-visible proof.
- Building a general plugin/runtime platform before the compiler loop: speculative scope.

## Scope boundary

This ADR governs A/C execution only. Full-format ingestion, historical migration, Agent retrieval evaluation, production recovery and Runtime/Registry normalization remain B backlog items.
