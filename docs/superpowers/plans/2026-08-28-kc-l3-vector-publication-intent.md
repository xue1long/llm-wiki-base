# L3 Vector Publication Intent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing Wiki-to-vector publication window crash-recoverable and observable without changing source-level evidence semantics.

**Architecture:** Add a small durable publication-intent record around the existing `vector_pending` ledger. The intent is created before the Wiki commit, remains present until vector indexing succeeds, and is reconciled idempotently from the existing Wiki source of truth. Do not add claim truth evaluation, claim-to-page mapping, a second page writer, or a global publication waterline in this slice.

**Tech Stack:** Python 3.11+, existing `AtomicContext`, `safe_write`, `WikiPaths`, `vector.pending`, pytest.

**Spec:** `docs/superpowers/plans/2026-08-28-kc-mainline-three-levels.md` — L3 “全局发布一致性与完整 Evidence 生命周期”.

## Global Constraints

- `structurally_verified` remains source-level structural evidence only; this plan does not create or infer `entailed`.
- Wiki pages remain the source of truth; vectors remain derived state.
- Reuse `vector_pending.py`, `AtomicContext`, `safe_write`, and `commit_ingest()`; do not add a second writer.
- A failed or interrupted reconciliation must be retryable and idempotent.
- Existing legacy `workflow_state="verified"` behavior is unchanged in this slice.
- No migration or rewrite of existing Wiki pages is required.
- Do not touch unrelated dirty workspace files; implementation stays in the isolated worktree.

## Confirmed Failure Scenario

`src/pipeline/ingest.py::commit_ingest()` exits `AtomicContext` after writing Wiki pages, index, and log, then calls `vector.pending.mark_pending()` as a non-fatal best-effort operation. A process failure or ledger write error between those operations can leave committed Wiki content without a durable vector-reconciliation intent. Startup scanning can eventually discover some missing vectors, but there is no immediate publication record or explicit failure state.

## L3 Scope and Non-goals

In scope:

- durable pre-commit publication intent for the pages in one ingest;
- recovery of intents when the process stops before or after Wiki commit;
- explicit health/reconcile result showing pending, recovered, failed, and orphaned intents;
- regression tests for crash-window ordering, ledger-write failure, retry, and idempotency.

Out of scope:

- semantic claim truth or `entailed` evaluation;
- claim-to-page mapping;
- URL identity redesign;
- vector transactionality or LanceDB schema changes;
- staging pages, multi-version waterlines, or distributed locking;
- automatic historical `verified` migration.

## Data Contract

The existing `.index/vector_pending.json` remains the only durable ledger. Each page entry gains these fields while retaining existing `hash`, `ts`, and `title`:

```json
{
  "page-id": {
    "hash": "body-hash",
    "ts": 1720000000,
    "title": "Page title",
    "publication_state": "intent"
  }
}
```

Allowed values are:

- `intent`: page is scheduled for Wiki commit and vector indexing;
- `pending`: Wiki commit is known to exist, vector indexing is not complete;
- absent: vector indexing completed, or an orphaned pre-commit intent was safely discarded because its page is absent.

Old entries without `publication_state` read as `pending` for compatibility and are written back only when touched.

### Task 1: Make publication intent durable around commit ordering

**Files:**
- Modify: `src/vector/pending.py`
- Modify: `src/pipeline/ingest.py:1330-1450`
- Test: `tests/test_vector/test_pending.py`
- Test: `tests/test_pipeline/test_ingest_vector_publication.py`

**Interfaces:**
- Add `mark_intent(paths, pages) -> int` in `src/vector/pending.py`.
- Add `promote_intent(paths, page_ids) -> int` in `src/vector/pending.py`.
- Keep `mark_pending()` as a compatibility wrapper that creates `pending` entries.
- `commit_ingest()` calls `mark_intent()` before writing Wiki pages; if that call fails, it aborts before the first Wiki write. It promotes surviving entries to `pending` after the Wiki commit and never deletes the record merely because vector upsert has not run.

- [ ] **Step 1: Write failing tests**

```python
def test_mark_intent_persists_intent(tmp_path):
    paths = _paths(tmp_path)
    page = _page("alpha")
    assert pending_mod.mark_intent(paths, [page]) == 1
    assert pending_mod.list_pending(paths)["alpha"]["publication_state"] == "intent"

def test_promote_intent_marks_committed_page_pending(tmp_path):
    paths = _paths(tmp_path)
    page = _page("alpha")
    pending_mod.mark_intent(paths, [page])
    assert pending_mod.promote_intent(paths, ["alpha"]) == 1
    assert pending_mod.list_pending(paths)["alpha"]["publication_state"] == "pending"
```

The pipeline test uses the existing `commit_ingest()` fixture pattern and monkeypatches `write_page()` to read the ledger during the first page write; it must observe `intent`. A second test injects an exception in the post-commit promotion call and asserts the Wiki page remains present and `list_pending()` still contains the `intent` record for the next reconciliation run.

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `PYTHONPATH=. python -m pytest --import-mode=importlib tests/test_vector/test_pending.py tests/test_pipeline/test_ingest_vector_publication.py -q`

Expected: FAIL because intent entries and the pre-commit ordering do not exist.

- [ ] **Step 3: Implement the smallest ordering change**

Use the existing pending ledger functions. Write intent entries before the first `write_page()` call, promote them to `pending` only after the `AtomicContext` completes, and preserve old-entry compatibility in `_load()`/`reconcile_pending()`.

- [ ] **Step 4: Run focused tests**

Run: `PYTHONPATH=. python -m pytest --import-mode=importlib tests/test_vector/test_pending.py tests/test_pipeline/test_ingest_vector_publication.py -q`

Expected: PASS, including the case where the Wiki commit succeeds but the ledger promotion fails; that case must remain detectable rather than silently reported as healthy.

- [ ] **Step 5: Commit**

```bash
git add src/vector/pending.py src/pipeline/ingest.py tests/test_vector/test_pending.py tests/test_pipeline/test_ingest_vector_publication.py
git commit -m "feat(vector): persist publication intent before wiki commit"
```

### Task 2: Add idempotent recovery and explicit observability

**Files:**
- Modify: `src/vector/pending.py`
- Modify: `src/cli_ext/vector_cmd.py:17-84` to expose the extended reconcile result
- Modify: `src/server/app.py:178-187` to report outstanding intent/pending counts during startup health reconciliation
- Test: `tests/test_vector/test_pending.py`
- Test: the existing health/reconcile test module for that caller

**Interfaces:**
- Extend `reconcile_pending()` result with `intent`, `pending`, `recovered`, `failed`, and `orphaned` counts while preserving existing keys.
- `scan_wiki_vector_diff()` treats `intent` and `pending` as outstanding records and never duplicates them.
- A missing page removes only an `intent` record and increments `orphaned`; a missing page with `pending` keeps the existing deletion/reconciliation behavior and increments `failed`.

- [ ] **Step 1: Write failing tests**

```python
def test_reconcile_intent_after_restart_is_idempotent(tmp_path):
    paths = _paths(tmp_path)
    page = _page("page-1")
    _write_page(paths, page)
    pending_mod.mark_intent(paths, [page])
    calls = []
    def upsert(page, paths, table=None):
        calls.append(page.id)
        return True
    result1 = pending_mod.reconcile_pending(paths, upsert)
    result2 = pending_mod.reconcile_pending(paths, upsert)
    assert result1["recovered"] == 1
    assert result2["attempted"] == 0
    assert calls == ["page-1"]

def test_scan_does_not_duplicate_intent_or_pending_entries(tmp_path):
    paths = _paths(tmp_path)
    page = _page("page-1")
    _write_page(paths, page)
    pending_mod.mark_intent(paths, [page])
    assert pending_mod.scan_wiki_vector_diff(paths, None, []) == 0
    assert list(pending_mod.list_pending(paths)) == ["page-1"]
```

- [ ] **Step 2: Run focused tests and verify they fail**

Run: `PYTHONPATH=. python -m pytest --import-mode=importlib tests/test_vector/test_pending.py -q`

Expected: FAIL because the result has no explicit intent/recovery accounting.

- [ ] **Step 3: Implement recovery accounting using the existing ledger**

Do not add a new database or background worker. Classify the existing entries, re-use `_find_page_file()`, and keep successful upserts idempotent through the existing `clear_pending()` path.

- [ ] **Step 4: Run focused and queue-adjacent tests**

Run: `PYTHONPATH=. python -m pytest --import-mode=importlib tests/test_vector/test_pending.py tests/test_queue/test_queue_retry_liveness.py -q`

Expected: PASS with no duplicate pages, index rows, or vector work items. Existing `reconcile_pending()` keys remain compatible; new counters are additive.

- [ ] **Step 5: Commit**

```bash
git add src/vector/pending.py tests/test_vector/test_pending.py
git commit -m "feat(vector): expose publication recovery state"
```

### Task 3: Final boundary verification

**Files:**
- Create: `docs/adr/2026-08-28-vector-publication-intent.md` recording the ordering decision and compatibility behavior
- Test: existing L1/L2 regression set and the new L3 tests

- [ ] **Step 1: Run the L3 focused suite**

Run: `PYTHONPATH=. python -m pytest --import-mode=importlib tests/test_vector/test_pending.py tests/test_pipeline/test_ingest_vector_publication.py -q`

Expected: all tests pass.

- [ ] **Step 2: Run the L1/L2 regression suite**

Run the existing L1/L2 command from `2026-08-28-kc-mainline-three-levels.md`. Expected: no regression in structural evidence, source path, page provenance, Generator blocking, or commit idempotency.

- [ ] **Step 3: Verify failure boundaries**

Manually or with tests confirm:

- a structural evidence failure still blocks Generator before any publication intent is created;
- a Wiki commit failure does not leave a `pending` record that claims a committed page;
- a vector failure leaves a recoverable `pending` record;
- a process interruption at each ordering boundary can be reconciled safely;
- repeated reconciliation is idempotent.

- [ ] **Step 4: Commit**

```bash
git add tests/test_vector/test_pending.py tests/test_pipeline/test_ingest_vector_publication.py docs/adr/2026-08-28-vector-publication-intent.md
git commit -m "test(vector): verify publication intent boundaries"
```

The ADR must state: Wiki is authoritative; the intent record precedes the first Wiki write; promotion to `pending` follows a successful Wiki commit; vector failure is retryable; orphaned pre-commit intents are removable; old ledger entries default to `pending`; and this decision does not redefine `structurally_verified` or `workflow_state="verified"`.

## Acceptance Criteria

- Every ingest that reaches its first Wiki write has a durable vector publication record; a ledger failure aborts before any Wiki write.
- Every vector failure remains discoverable and retryable.
- Restart/reconcile recovers interrupted intents without duplicate Wiki/index/vector effects.
- Existing L1/L2 behavior and `structurally_verified` meaning are unchanged.
- No new page system, claim truth gate, waterline, distributed lock, or historical data migration is introduced.
- The new L3 slice has focused tests with deterministic failure injection and explicit rollback behavior: remove only orphaned pre-commit intents; retain committed-page pending records.

## Stop Conditions

Stop before implementation if any of these is observed:

- `AtomicContext` cannot safely buffer the intent write with existing Wiki writes;
- the current vector pending ledger cannot distinguish an orphaned pre-commit intent from a committed page;
- a required health/reconcile caller cannot be identified without broad routing changes;
- the fix requires changing `workflow_state="verified"` semantics;
- the test harness cannot run deterministic failure injection independently of the known nested-pytest hang.

## Rollback

Rollback is limited to reverting the L3 commits. Old ledger entries remain readable because missing `publication_state` defaults to `pending`. No Wiki page or vector data migration is performed.

## Readiness Decision

This plan is ready for L3 implementation only after the two-round `plan-audit` finds no fatal or major defect, and after the nested-pytest harness issue is recorded as an environment limitation rather than used as evidence of a production queue failure.
