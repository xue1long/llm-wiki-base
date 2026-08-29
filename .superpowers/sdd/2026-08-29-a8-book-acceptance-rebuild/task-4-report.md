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
- Snapshot validation is intentionally strict at the top-level and nested record boundaries. Duplicate chapter, KU, and Evidence IDs now fail with structured snapshot schema errors.

## Fix Round 1

Addressed review findings:
- Reject duplicate IDs for chapters, knowledge units, and evidences during snapshot load.
- Validate required Book scalar/list fields, nested chapter/KU/Evidence record shape and ID/type fields, list field types, and integer publication/order fields before construction.
- Serialize `failed_object_ids` for normal rebuild failures from the failed chapter IDs, as well as for snapshot-load failures.

Added tests for duplicate IDs, malformed nested fields, and rebuild failure serialization.

Verification:
- `C:\Users\HP\AppData\Local\Python\pythoncore-3.14-64\python.exe -m pytest tests/test_kc/test_book_rebuild_cli.py --import-mode=importlib -q` — `8 passed in 7.85s`
- `C:\Users\HP\AppData\Local\Python\pythoncore-3.14-64\python.exe -m pytest tests/test_kc/test_book_rebuild_cli.py tests/test_kc/test_book_rebuild.py --import-mode=importlib -q` — `21 passed in 7.60s`

Final rerun after the duplicate-ID test was expanded to cover each record collection:
- CLI tests — `8 passed in 7.96s`
- CLI/API regression — `21 passed in 8.53s`
