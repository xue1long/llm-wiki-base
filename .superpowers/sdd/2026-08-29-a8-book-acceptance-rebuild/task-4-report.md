# Task 4 Report

Date: 2026-08-30

Scope:
- Added `scripts/kc_book_rebuild.py` as the real Book rebuild CLI.
- Added `tests/test_kc/test_book_rebuild_cli.py` and `tests/fixtures/book_rebuild_fixture.json`.
- Kept all work inside the shared workspace and out of `knowledge/novel-wiki`.

Implementation notes:
- The CLI only adapts the fixed snapshot shape into `Book`, `Chapter`, `KnowledgeUnit`, `Evidence`, `SimpleKnowledgeCoreView`, and `IntegrityGate`, then calls `rebuild_book`.
- Output is structured JSON for both success and snapshot-validation failure paths.
- Apply mode writes to `<project-root>/book`; dry-run mode does not write.

TDD evidence:
- Red: `C:\Users\HP\AppData\Local\Python\pythoncore-3.14-64\python.exe -m pytest tests/test_kc/test_book_rebuild_cli.py --import-mode=importlib -q`
  - Failed because `scripts/kc_book_rebuild.py` did not exist yet.
- Green: same command after implementation
  - Result: `5 passed in 6.45s`
- Regression: `C:\Users\HP\AppData\Local\Python\pythoncore-3.14-64\python.exe -m pytest tests/test_kc/test_book_rebuild_cli.py tests/test_kc/test_book_rebuild.py --import-mode=importlib -q`
  - Result: `18 passed in 6.05s`

Concerns:
- Snapshot validation is intentionally strict at the top-level shape and constructor boundary; duplicate KU or Evidence ids currently follow the last value in the JSON object/list rather than raising a dedicated duplicate-id error.
