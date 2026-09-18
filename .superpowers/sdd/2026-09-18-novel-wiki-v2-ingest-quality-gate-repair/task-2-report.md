# Task 2 report — resolved templates and fail-closed slots

## Outcome

Candidate ingest now validates required slots before rendering can conceal
missing content.  Empty and placeholder values are withheld from the formal
ingest/write path; the deterministic source page remains eligible and the task
returns `NEEDS_HUMAN_REVIEW` with the withheld page IDs and reasons.

Candidate parse rejection, missing source identity, invalid evidence,
review rejection, and promotion failure are quarantined as failures rather than
being converted to source-only output.

## Files changed

- `src/pipeline/generator.py`
  - adds slot verdicts (`FILLED`, `DECLARATIVE_ABSENCE`, `EMPTY`,
    `PLACEHOLDER`) and a list-compatible generated-page result with withheld
    page reasons;
  - enforces these verdicts only when the formal ingest boundary opts in, so
    direct legacy generator callers preserve their established behaviour;
  - withholds title decorations of the candidate title as ambiguous variants.
- `src/pipeline/ingest.py`
  - enables formal slot enforcement and returns source-only review metadata;
  - restores fail-closed quarantine for rejected/empty/mismatched candidates,
    invalid evidence, reviewer rejection, and promoter failure.
- `src/pipeline/quality_gate.py`
  - rejects a rendered body containing only template headings as
    `missing_required_content`.

The quality-gate change is the minimal necessary companion to Task 1's direct
red regression test: that test calls `check_pages()` directly, so generator or
ingest changes alone cannot satisfy it.

## Verification

```powershell
$env:PYTHONPATH='.'
python -m pytest --import-mode=importlib tests/test_wiki/test_templates_renderer.py tests/test_pipeline/test_generator.py tests/test_pipeline/test_ingest_generate_commit_split.py tests/test_pipeline/test_quality_gate.py -q
# 119 passed, 11 warnings

python -m pytest --import-mode=importlib tests/test_pipeline/test_generate_from_candidate.py tests/test_pipeline/test_provenance.py tests/test_pipeline/test_ingest_kc_mainline.py -q
# 18 passed
```

The 11 warnings are the existing `unified_generate` deprecation warnings from
legacy-path coverage; no test failures remain. `graphify update .` was also
run after the code changes.

## Scope note

No Task 1 test or fixture was changed. The working tree already contains Task
1 and unrelated user changes; the Task 2 commit therefore stages only its
production files and report. The new memory note is intentionally local
because `.memory/` is gitignored.
