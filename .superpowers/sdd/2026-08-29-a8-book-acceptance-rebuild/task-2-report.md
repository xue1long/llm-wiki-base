# Task 2 Report — Book Diff and Affected Chapter Analysis

Status: BLOCKED on full pytest verification in the local runtime.

Implemented:
- `src/kc/views/book/diff.py`
- `src/kc/views/book/__init__.py`
- `tests/test_kc/test_book_diff.py`

Behavior added:
- `BookDiff` frozen dataclass with added/removed/changed chapter ids and changed KU ids.
- `compute_book_diff(...)` compares ordered chapter ids plus explicit chapter fields and tracks source KU deltas.
- `affected_chapters(...)` dedupes incoming KU ids and returns matching chapters in input order.

Verification:
- `python -m compileall src/kc/views/book/diff.py src/kc/views/book/__init__.py tests/test_kc/test_book_diff.py` succeeded under the local Python 3.14.3 venv.
- The brief's pytest command could not complete in this workspace because the local 3.14 venv does not have `pytest` installed, and importing `src.kc` in that env also fails without `yaml` available.

Notes:
- Unrelated dirty files under `knowledge/novel-wiki/` were left untouched.
- No knowledge/novel-wiki changes were made for Task 2.

Fix round 1:
- Adjusted `compute_book_diff()` so `changed_chapter_ids` follow new Book order, while `changed_knowledge_unit_ids` preserve deterministic old-chapter then new-chapter/Book order.
- Verified with the brief test command in the local 3.14 venv:
  - `PYTHONPATH=. python -m pytest tests/test_kc/test_book_diff.py tests/test_kc/test_book_mapper.py --import-mode=importlib -q`
  - Result: `61 passed, 1 warning`

Fix round 2:
- Changed `compute_book_diff()` to compare `old.chapter_ids` vs `new.chapter_ids` even when `old_chapters` / `new_chapters` are omitted.
- Added regression coverage for pure Book-level order changes and `knowledge_block_ids` changes.
- Re-ran the exact brief test command in the local 3.14 venv:
  - `PYTHONPATH=. python -m pytest tests/test_kc/test_book_diff.py tests/test_kc/test_book_mapper.py --import-mode=importlib -q`
  - Result: `63 passed, 1 warning`
