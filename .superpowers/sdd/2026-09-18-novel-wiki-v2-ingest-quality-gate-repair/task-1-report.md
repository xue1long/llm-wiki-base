# Task 1 report — representative ingestion contract

## Files changed

- `tests/fixtures/novel_wiki_v2_outline_source.md`
- `tests/test_pipeline/test_generator.py`
- `tests/test_pipeline/test_ingest_generate_commit_split.py`
- `tests/test_pipeline/test_quality_gate.py`

## Verification

```powershell
$env:PYTHONPATH='.'
python -m pytest --import-mode=importlib tests/test_pipeline/test_ingest_generate_commit_split.py tests/test_pipeline/test_generator.py tests/test_pipeline/test_quality_gate.py -q
```

Result: **100 passed, 3 failed, 11 warnings** in 10.01s.

The three failures are the intended red regression cases for this repair plan:

1. A generated `小说大纲写作技巧` semantic variant is still retained alongside the deterministic source page instead of being quarantined with `NEEDS_HUMAN_REVIEW`.
2. A concept with missing required slots is still retained instead of producing source-only output plus a warning/review result.
3. The rule-based quality gate retains a concept whose body contains only template headings instead of dropping it while preserving the valid source page.

The pre-existing narrow-suite baseline was 99 passed; the added positive resolved-template/fact/provenance test passes.

## Review follow-up

- Removed the temp-path-dependent `280f64ec` expectation. The variant test now verifies the generated source page through `meta["source_page_id"]` and its deterministic title prefix.
- Moved the positive contract to the complete candidate ingest boundary: it now asserts exactly one source plus the two allowed concepts, and verifies that `提纲的重要性` remains content rather than an independent page.
- Bound every fake evidence item to the exact `preprocess_source()` canonical block id and content, removing unrelated CandidateReviewer warnings.

Re-ran the same narrow command: **100 passed, 3 failed, 11 warnings** in 6.82s. The remaining failures are only the three intended red regression cases listed above.

## Re-review follow-up

- Replaced the remaining path-derived quality-gate fixture id with stable test-local id `outline-source`; the test continues to verify source preservation when its paired concept has only template headings.

Verification after this change:

- `tests/test_pipeline/test_quality_gate.py -q`: **32 passed, 1 failed** (the intended missing-required-content regression).
- Required narrow suite: **100 passed, 3 failed, 11 warnings** in 5.04s; the same three intended red regressions remain.
