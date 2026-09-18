# Task 3 report — semantic constraints and variant disposition

## Outcome

- Tightened the existing candidate render prompt with independent-concept,
  subsection, title-variant, slug-reuse, and `NEEDS_HUMAN_REVIEW` constraints.
- Added the same semantic boundary and reference-target rules to
  `WIKI_RULES_SUMMARY`.
- Extended the representative outline regression fixture with a semantic title
  variant and verified it is withheld rather than returned as a page.

## Verification

```powershell
$env:PYTHONPATH='.'
python -m pytest --import-mode=importlib tests/test_pipeline/test_generator_constraint.py tests/test_pipeline/test_generator.py -q
# 70 passed
```

## Compatibility boundary

The existing enforcement remains scoped to formal candidate ingest. No planner,
schema field, or new duplicate-resolution mechanism was added; existing
deterministic slug/title handling and fail-closed writer behavior are reused.
