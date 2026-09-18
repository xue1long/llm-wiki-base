# Task 3 report — semantic constraints and variant disposition

## Files changed

- `src/pipeline/generator.py`
- `src/pipeline/wiki_rules_prompt.py`
- `tests/test_pipeline/test_generator.py`

## Outcome

- Candidate rendering now drops exact duplicate ids/titles deterministically,
  preserving the first response item.
- A title is canonicalized only through an explicit
  `SlugAliasRegistry` alias. Unregistered variants and unsupported subsection
  titles are withheld with `NEEDS_HUMAN_REVIEW` and therefore cannot be
  written by the existing ingest boundary.
- Candidate-render and shared wiki rules now forbid invented reference slugs,
  distinguish taxonomy virtual targets from ordinary pages, and keep
  subsection-level arguments inside their parent concept unless independently
  evidenced.
- Task 2 slot verdicts and `enforce_slot_verdicts=False` legacy behavior are
  unchanged.

## Verification

```powershell
$env:PYTHONPATH='.'
python -m pytest --import-mode=importlib `
  tests/test_pipeline/test_generator_constraint.py `
  tests/test_pipeline/test_generator.py `
  tests/test_pipeline/test_wiki_book_sync.py `
  tests/test_pipeline/test_generate_from_candidate.py `
  tests/test_pipeline/test_provenance.py -q
# 90 passed

python -m pytest --import-mode=importlib `
  tests/test_wiki/test_templates_renderer.py `
  tests/test_pipeline/test_ingest_generate_commit_split.py::test_outline_variant_is_not_written_and_requires_human_review `
  tests/test_pipeline/test_ingest_generate_commit_split.py::test_outline_missing_required_concept_keeps_only_source_with_warning -q
# 18 passed
```

## Compatibility boundary

The semantic review and deterministic de-duplication are enabled only for the
formal candidate ingest call (`enforce_slot_verdicts=True`). Legacy/direct
generator callers retain their established rendering behavior. No planner,
candidate-schema field, fuzzy auto-merge, or Task 4 taxonomy resolver was
added.
