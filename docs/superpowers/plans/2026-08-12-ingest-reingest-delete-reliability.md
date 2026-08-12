# Ingest Reliability Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent destructive re-ingest races, preserve ingest task history across restarts, and lock the four ingest UI flows with regression tests.

**Architecture:** Keep the existing service and tracker boundaries. Add a small preflight guard in `src/services/ingest.py`, persist tracker records under the project `.index`, and leave the explicit `.kb-queue-paused` runtime sentinel unchanged.

**Tech Stack:** Python 3.11+, FastAPI, pytest, JSON files.

## Global Constraints

- Do not auto-delete or override `.kb-queue-paused`.
- Preserve existing HTTP paths and request/response shapes unless a test requires an error response.
- Use project-local `.index` operational storage; wiki pages remain source of truth.

### Task 1: Re-ingest race guard

**Files:**
- Modify: `src/services/ingest.py`
- Test: `tests/test_server/test_service_ingest.py`

- [x] Add a failing test proving re-ingest refuses a source with an active matching task before cascade deletion.
- [x] Run the focused test and confirm the expected failure.
- [x] Add the smallest active-task lookup/guard before `cascade_delete`.
- [x] Run the focused test and confirm it passes.

### Task 2: Persistent task history

**Files:**
- Modify: `src/server/ingest_tracker.py`
- Modify: `src/server/routes/ingest.py`
- Test: `tests/test_server/test_ingest_tracker.py`

- [x] Add a failing test that records a task, recreates the tracker state, and still lists the task for the same project.
- [x] Run the focused test and confirm the expected failure.
- [x] Persist only the tracker records needed by `list_tasks` under the project `.index` directory.
- [x] Run the focused test and confirm it passes.

### Task 3: Positive delete/re-ingest coverage and stale path contract

**Files:**
- Modify: `tests/test_server/test_service_ingest.py`
- Modify: `tests/test_pipeline/test_pipeline.py` only if the shared re-ingest fixture needs the current cache API.

- [x] Add the active re-ingest 409 response test and correct the explicit outside-project absolute-path 400 test contract.
- [x] Run the focused ingest/server suite with a repository-local pytest temp directory.
- [x] Fix only implementation defects exposed by those tests.

### Task 4: Verification

- [x] Run the focused ingest/server/pipeline tests with `--basetemp .tmp-pytest-ingest-check`.
- [x] Run route import and router-mount smoke tests.
- [x] Confirm `.kb-queue-paused` remains present and report that queue resume is still an explicit operational action.
