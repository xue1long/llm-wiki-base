# Task 4 report — unified target and page-depth rules

## Outcome

- H2, reconciliation, and batch gate now recognize the same target classes;
  valid taxonomy is a virtual target, while an undeclared taxonomy remains an
  explicit unresolved error.
- `taxonomy/<name>` normalizes to the persisted `taxonomy-<slug>` form.
- Duplicate-title diagnostics are grouped by page type and normalized title.
- A shared page-type/depth predicate accepts LLM depths only in valid pairs and
  permits `source`/`stub` only for deterministic system pages. Legacy pages
  remain readable without being rewritten.
- Wiki specification documents now define bare/path wikilinks and taxonomy
  input versus persisted forms.

## Verification

```powershell
$env:PYTHONPATH='.'
python -m pytest --import-mode=importlib `
  tests/test_maintenance/test_h2_break_links.py `
  tests/test_wiki/test_ndg_lint_consistency.py `
  tests/test_wiki/test_taxonomy_registry.py `
  tests/test_pipeline/test_quality_gate.py `
  tests/test_cli_ext/test_cmd_quality.py -q
# 67 passed
```

No fuzzy target merge or new dependency was introduced.
