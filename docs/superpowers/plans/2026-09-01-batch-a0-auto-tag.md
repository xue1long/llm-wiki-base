# Plan A0 Auto-Tag Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the duplicated UGC auto-tagging helper into one canonical module while preserving behavior and compatibility.

**Architecture:** `src/orchestrator/auto_tag.py` owns `auto_tag_ugc`. `src/orchestrator/batch_runner.py` remains a `.py` facade and keeps `_auto_tag_ugc` as a module-level alias. `scripts/phase4_batch.py` calls the canonical helper. `_is_ugc_carrier` remains a function-local import.

**Tech Stack:** Python 3.11+, pytest, standard-library AST checks, existing wiki lint helper.

**Spec:** `docs/superpowers/plans/2026-09-01-batch-runner-decompose.md` §2.5, plus the safety corrections below.

## Global Constraints

- Keep `src/orchestrator/batch_runner.py` as a `.py` file and preserve its import path.
- Keep `BatchRunner`, `DefaultBatchRunner`, `run_batch`, and `_auto_tag_ugc` importable from `src.orchestrator.batch_runner`.
- Keep the `run_batch` call routed through `_auto_tag_ugc(...)` so runtime monkeypatching still works.
- Keep `_is_ugc_carrier` lazy; do not move it to module import time.
- Preserve source detection, stub exemption, in-place mutation, tag order, duplicate avoidance, return count, exceptions, and crash-hook behavior.
- Do not touch `src/services/batch_state.py`, unrelated refactors, or untracked handoff/audit artifacts.
- Do not add dependencies or use `git add .`.

## File Map

- Create: `src/orchestrator/auto_tag.py` — canonical helper.
- Modify: `src/orchestrator/batch_runner.py:330-364,782` — alias and preserved call site.
- Modify: `scripts/phase4_batch.py:299-335,854` — duplicate removal and canonical call.
- Create: `tests/test_orchestrator/test_auto_tag.py` — focused behavior and alias tests.

## Baseline

Before writing code, run:

```powershell
$env:PYTHONPATH='.'
& 'C:\Users\HP\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_orchestrator/test_state_machine_guard.py tests/test_scripts/test_batch_executor.py -q --basetemp=.pytest-tmp-a0-baseline
```

Record known unrelated blockers separately. Current evidence includes `src/pipeline/ingest.py:843` syntax failure during broad CLI collection and default pytest temp-directory permission failures.

## Tasks

### Task 1: Freeze parity and consumers

**Files:** read the two existing helper bodies and their call sites.

- [ ] Compare the two function ASTs after removing only each docstring. Expected result: executable bodies are equal; otherwise stop and resolve the difference before extraction.
- [ ] Run `rg '_auto_tag_ugc|from src\.orchestrator\.batch_runner' src scripts tests --glob '*.py'` and record all compatibility consumers.

### Task 2: Add failing focused tests

**Files:** create `tests/test_orchestrator/test_auto_tag.py`.

- [ ] Test a carrier page is mutated in place to `existing, 素材/ugc, 可信度/ugc` and returns `1`.
- [ ] Test stub pages, non-carrier pages, existing tags, empty headers, and `None` headers.
- [ ] Test `batch_runner._auto_tag_ugc is auto_tag_ugc`.

Use only standard-library page doubles:

```python
from types import SimpleNamespace

from src.orchestrator import batch_runner
from src.orchestrator.auto_tag import auto_tag_ugc


def page(sources, tags=None, processing_depth="concept"):
    return SimpleNamespace(sources=sources, tags=tags, processing_depth=processing_depth)


def test_carrier_tags_are_in_place_and_ordered():
    item = page(["raw/ugc.md"], ["existing"])
    assert auto_tag_ugc([item], {"raw/ugc.md": "公众号整理"}) == 1
    assert item.tags == ["existing", "素材/ugc", "可信度/ugc"]


def test_stub_plain_and_duplicate_cases():
    stub = page(["raw/ugc.md"], [], "stub")
    tagged = page(["raw/ugc.md"], ["素材/ugc"])
    plain = page(["raw/plain.md"], [])
    assert auto_tag_ugc([stub, tagged, plain], {"raw/ugc.md": "公众号整理"}) == 1
    assert stub.tags == []
    assert tagged.tags == ["素材/ugc", "可信度/ugc"]
    assert plain.tags == []


def test_empty_headers_are_noop():
    item = page(["raw/ugc.md"], [])
    assert auto_tag_ugc([item], None) == 0
    assert item.tags == []


def test_facade_alias_is_preserved():
    assert batch_runner._auto_tag_ugc is auto_tag_ugc
```

- [ ] Run `pytest tests/test_orchestrator/test_auto_tag.py -q --basetemp=.pytest-tmp-a0-red`; expected failure is missing `src.orchestrator.auto_tag` before implementation.

### Task 3: Add the canonical implementation

**Files:** create `src/orchestrator/auto_tag.py`.

- [ ] Copy the verified executable body, preserving behavior. Keep the import lazy:

```python
from __future__ import annotations

_UGC_TAGS = ("素材/ugc", "可信度/ugc")


def auto_tag_ugc(pages: list, raw_headers: dict[str, str]) -> int:
    from src.wiki.features.lint import _is_ugc_carrier
    carrier_raws = {raw for raw, header in (raw_headers or {}).items()
                    if _is_ugc_carrier(header)}
    if not carrier_raws:
        return 0
    tagged = 0
    for page in pages:
        if getattr(page, "processing_depth", "") == "stub":
            continue
        if not (set(page.sources or []) & carrier_raws):
            continue
        tags = list(page.tags or [])
        changed = False
        for tag in _UGC_TAGS:
            if tag not in tags:
                tags.append(tag)
                changed = True
        if changed:
            page.tags = tags
            tagged += 1
    return tagged
```

### Task 4: Wire callers without changing the facade

**Files:** modify only the locations in the file map.

- [ ] In `batch_runner.py`, import `auto_tag_ugc`, set `_auto_tag_ugc = auto_tag_ugc`, delete only the old definition, and leave `_auto_tagged = _auto_tag_ugc(all_pages, raw_headers)` unchanged.
- [ ] In `phase4_batch.py`, remove only the duplicate definition, import `auto_tag_ugc` without eagerly importing `_is_ugc_carrier`, and change the call to `auto_tag_ugc(result.pages, gen["raw_headers"])`.
- [ ] Confirm `rg "def _auto_tag_ugc|def auto_tag_ugc" src scripts tests --glob '*.py'` finds exactly one executable definition: `auto_tag_ugc` in `auto_tag.py`.

### Task 5: Verify the slice

- [ ] Run `pytest tests/test_orchestrator/test_auto_tag.py tests/test_orchestrator/test_state_machine_guard.py tests/test_scripts/test_batch_executor.py -q --basetemp=.pytest-tmp-a0-final`.
- [ ] Re-run the AST parity check, now comparing the canonical body with the saved pre-extraction body and ignoring only the docstring and literal extraction.
- [ ] Verify facade imports and crash-hook names with `rg 'from src\.orchestrator\.batch_runner|BATCH_EXECUTOR_CRASH_AT' src scripts tests --glob '*.py'`.
- [ ] Inspect `git diff --stat` and ensure only the four A0 files changed; do not stage handoff/audit artifacts.

### Task 6: Review and commit

- [ ] Run the task-scoped review required by `superpowers:subagent-driven-development`.
- [ ] Stage only `src/orchestrator/auto_tag.py`, `src/orchestrator/batch_runner.py`, `scripts/phase4_batch.py`, and `tests/test_orchestrator/test_auto_tag.py`.
- [ ] Commit with `refactor(orchestrator): extract UGC auto-tag helper`.
- [ ] Do not push without explicit confirmation.

## Audit

- Round 1: completed — caught eager import timing, facade monkeypatch, behavior parity, dirty-worktree, and baseline-blocker risks.
- Round 2: completed — pressure-tested empty/malformed headers, stubs, duplicate tags, script imports, crash hooks, rollback, and partial test collection.
- Human review: required before coding.
- Stop if executable bodies differ, import timing changes materially, monkeypatching breaks, crash hooks move, or any non-A0 file must change.
- Rollback: revert only the A0 commit; never reset or clean unrelated untracked files.

## Completion Evidence

- Final commit: pending.
- Tests and static checks: pending.
- Progress ledger: update after implementation review.
