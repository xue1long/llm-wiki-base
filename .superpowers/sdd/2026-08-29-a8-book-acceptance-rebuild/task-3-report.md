# Task 3 Report

## Status

- `DONE`

## Summary

- Added `src/kc/views/book/rebuild.py` with `BookRebuildReport` and `rebuild_book()`.
- Reused existing `compile_chapter()` and `render_chapter()` APIs.
- Implemented staging-first `.md` + `.json` writes with rollback on commit failure.
- Normalized compiled block ids before rendering so repeated rebuilds keep stable `rendered_hashes`.
- Exported the API from `src/kc/views/book/__init__.py`.
- Added `tests/test_kc/test_book_rebuild.py` covering empty book, full success, target subset, publication parity, compile/integrity/render/write failures, dry-run, and repeated hash equality.

## Tests

- Red:
  - `$env:PYTHONPATH='.'; & 'C:\Users\HP\AppData\Local\Python\pythoncore-3.14-64\python.exe' -m pytest tests/test_kc/test_book_rebuild.py --import-mode=importlib -q`
  - Result: `10 failed` before implementation.
- Green:
  - `$env:PYTHONPATH='.'; & 'C:\Users\HP\AppData\Local\Python\pythoncore-3.14-64\python.exe' -m pytest tests/test_kc/test_book_rebuild.py --import-mode=importlib -q`
  - Result: `10 passed`.
- Required regression:
  - `$env:PYTHONPATH='.'; & 'C:\Users\HP\AppData\Local\Python\pythoncore-3.14-64\python.exe' -m pytest tests/test_kc/test_book_rebuild.py tests/test_kc/test_book_markdown.py tests/test_kc/test_book_compiler.py --import-mode=importlib -q`
  - Result: `52 passed`.

## Commit

- Planned message: `feat(kc-views): add atomic Book rebuild API`

## Concerns

- `graphify` maintenance command is currently broken on this host with `uv trampoline failed to canonicalize script path`, so I could not refresh the graph after the code change.
- `rendered_hashes` are now deterministic inside rebuild because the compiler currently mints random knowledge-block ids; the rebuild layer normalizes them before rendering instead of changing compiler behavior in Task 3.

## Fix round 1

- Rejected requested chapter IDs that are not in `book.chapter_ids`, before any compilation or write.
- Passed a fixed publication-version snapshot to every `compile_chapter()` call, so report, Markdown, and metadata share one Core version.
- Added rollback coverage for an `os.replace` failure after the first target chapter has already been replaced.

### TDD evidence

- Red: `tests/test_kc/test_book_rebuild.py` → `2 failed, 11 passed` (foreign chapter was committed; changing Core was read 4 times).
- Green: `tests/test_kc/test_book_rebuild.py` → `13 passed`.
- Required regression: `tests/test_kc/test_book_rebuild.py tests/test_kc/test_book_markdown.py tests/test_kc/test_book_compiler.py` → `55 passed`.
