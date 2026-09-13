# Task 0 report

- Status: complete
- Changed: `src/kc/views/book/wiki/compiler.py`, `tests/test_kc/test_book_release_protocol.py`
- Added: typed `ValidatedCandidate`, canonical manifest identity validation, closed-world file checks, project/book identity checks, lifecycle sidecar read/write, and rejection of invalid/rejected/expired/superseded candidates.
- Verification: `uv run --offline pytest tests/test_kc/test_book_release_protocol.py -q` → 10 passed.
- Real provider calls: none.
- Concern for next task: promotion must use `validate_candidate_release()` and must not bypass the candidate source path under `<project_root>/.index/book-wiki/versions`.
