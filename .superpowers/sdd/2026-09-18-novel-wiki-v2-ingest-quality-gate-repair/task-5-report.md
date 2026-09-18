# Task 5 report — KC/Wiki/Vector/Book publication boundary

## Outcome

Book materialization now fails closed on bundle status: only manifests marked
`published` contribute claims and evidence. Staged, quarantined, missing, or
unknown-status bundles remain recovery inputs and cannot appear in a Book.
The existing finalization path already records actual post-gate page ids and
keeps vector failures staged; tests were updated to make published fixture
status explicit.

## Verification

```powershell
$env:PYTHONPATH='.'
python -m pytest --import-mode=importlib `
  tests/test_pipeline/test_ingest_generate_commit_split.py `
  tests/test_kc/test_mainline_publication.py `
  tests/test_kc/test_book_materialize.py `
  tests/test_kc/test_book_lineage_manifest.py `
  tests/test_cli_ext/test_book_cmd.py -q
# 72 passed, 11 existing deprecation warnings
```
