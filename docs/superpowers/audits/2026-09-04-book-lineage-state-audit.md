# Book Lineage State Plan Audit Report

Date: 2026-09-04

Audited plan: `docs/superpowers/plans/2026-09-04-book-lineage-state.md`

## Executive verdict

**Conditional pass at the design level; not yet implementation-ready without the amendments recorded in the plan.** The original proposal was directionally correct but could not prove the stated goal because it measured completeness primarily by raw `source_id`, while the user goal is that every eligible Wiki artifact is represented in Book. It also called a multi-file directory publication atomic without defining a directory-level publication mechanism.

After remediation, the plan can achieve the original goal if and only if implementation preserves the following invariants:

```text
every discovered raw has an explicit terminal/build decision
every included Wiki page is represented in the frozen Book plan
compiled Wiki page IDs equal planned Wiki page IDs
the active Book points to one immutable release
raw changes are persisted before incremental compilation is scheduled
```

No implementation evidence exists yet. This is a plan audit, not a product acceptance result.

## Goal measurement

| Original goal | Design result | Proof required during implementation |
|---|---|---|
| No raw/Wiki omission during compilation | Achievable after page-level closure gate | `expected_wiki_page_ids == compiled_wiki_page_ids`; zero unknown states |
| Raw add/change/delete causes correct Book update | Achievable with complete-scan marker, hashes, tombstones, and outbox | New/changed/deleted fixtures and crash replay |
| Raw quality failures are not silently omitted | Achievable with explicit excluded/blocking policy | Every rejected source appears in plan/manifest with reason |
| Wiki/KC/Book state stays synchronized | Achievable after all writers dual-write and cut over | Batch, HTTP, synthesis, manual, and restart paths converge |
| Failed builds never damage the last Book | Achievable with immutable releases and atomic active manifest | Crash at every publish boundary leaves old release readable |
| Historical project can be migrated safely | Achievable, but ambiguous links remain unverified | Migration dry-run has zero unexplained deterministic mismatches |

## Four-angle review

### 1. First-principles review

The irreducible problem is not “store more statuses”; it is preserving identity and causal transitions across independently persisted artifacts. A status database alone is insufficient if it cannot answer which exact raw hash produced which exact Wiki page and Book chapter.

The revised plan correctly adds stable IDs, hashes, artifact relations, write intents, build snapshots, and publication manifests. The important correction is changing the closure check from source-only to both source-level and Wiki-artifact-level. Without that, one source could generate three Wiki pages while Book contains one page and the build would still report success.

First-principles result: **sound after amendment**.

### 2. Critical-thinking review

The following counterexamples were applied:

1. A raw file is readable during discovery but disappears before ingest. Required result: `blocked`/`failed`, never silent omission.
2. A scan loses directory permission. Required result: no deletion tombstones.
3. A file is renamed. Required result: no duplicate source and no silent new source.
4. A synthesis page cites several sources. Required result: many-to-many lineage.
5. A Wiki write succeeds but the process dies before the DB update. Required result: reconciliation by operation ID and hash.
6. A Book chapter file is replaced and the process dies before the next chapter. Required result: readers still see the previous immutable release.
7. HTTP ingest and legacy batch scripts run concurrently. Required result: serialized transitions and no lost projection update.
8. An old Book sidecar exists without a reliable source mapping. Required result: `legacy_unverified`, not false success.
9. A provider returns truncated output. Required result: blocked source and unchanged last Book.
10. A new raw arrives after the build snapshot. Required result: next build, never partial inclusion in the current build.

The original plan missed the page-level version of case 4 and the directory-level version of case 6. Both are now explicit amendments.

Critical-thinking result: **no unresolved fatal counterexample; two major findings were fixed**.

### 3. End-state / terminal review

The final user-visible outcome must be provable from a committed Book manifest, not from logs or a successful process exit. The revised end state is:

```text
state.db
  → build_run manifest
  → immutable book/.releases/<run_id>/
  → atomic book/manifest.json active pointer
```

The manifest must expose included, excluded, blocked, and deleted Wiki/source entries. A user should be able to select any raw or Wiki ID and find its current Book result or an explicit reason why it is not in Book.

Terminal review result: **achievable, provided the active-manifest/release contract is implemented exactly**.

### 4. Systems-thinking review

The system has several writers and feedback loops: HTTP ingest, batch build/commit, manual ingestion, synthesis aggregation, Wiki writer, KC publisher, Book builder, and recovery. In-process EventBus is not durable, and the existing `batch_build_state.json` is still a live compatibility projection. The revised plan correctly treats SQLite/outbox as the durable coordination layer and requires a measured cutover.

The main systemic failure mode is dual authority during migration. If a legacy script changes `batch_build_state.json` without writing lineage, the Book plan can be incomplete while all local components individually appear healthy. Therefore the implementation must make disagreement between projections a strict build blocker before lineage becomes authoritative.

Systems review result: **achievable, but migration/cutover is a release gate, not a cleanup detail**.

## Remaining implementation gates

These are not design failures, but they must be explicit before coding is considered complete:

1. Define the SQLite schema, migrations, backup, and recovery behavior in the spec file.
2. Define the exact raw source identity and rename command/API; do not leave rename detection heuristic-only.
3. Audit every write path of the seven identified scripts and classify each as production, compatibility, or test-only.
4. Implement the immutable release directory plus atomic active manifest; per-file replacement is insufficient.
5. Define the policy for excluded raw/Wiki items and whether strict mode blocks on any exclusion or only on unclassified/failed items.
6. Add a complete-scan marker and prove that partial scans cannot emit deletions.
7. Add the legacy projection cutover test: old batch state and lineage must agree over one complete staging run.
8. Add crash-injection tests around raw, Wiki, KC, outbox, and Book publication boundaries.

## Final recommendation

**Approve the amended plan for implementation planning, not for claiming the feature complete.** The plan is capable of reaching the original goal, but only after the acceptance gate is based on both `source_id` and `wiki_page_id`, and the Book is published as an immutable release selected by an atomic manifest.

Implementation should start with the inventory/spec task and stop before production cutover if any writer remains outside the lineage API.
