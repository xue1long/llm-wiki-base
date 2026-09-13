# Task 3–4 report — budget preflight and vector separation

Status: complete.

Task 3 extracts `estimate_outline_call_sites` from the same prompt payload
builder used by `plan_outline`. Fresh-outline builds now reject an insufficient
cap before provider construction/calls, and new call-site metadata uses
`requested` rather than `pending`. Existing persisted-outline behavior remains
backward-compatible.

Task 4 adds `vector_index: not_updated` and a stable `vector status` /
`vector reconcile` hint to Book results. Book publication does not touch
LanceDB. The novel-wiki local policy now contains only non-secret governance
fields (`approver`, `budget_cap`); it is ignored by Git in this checkout and
was not force-added.

Verification:

- `tests/test_kc/test_book_chapter_body.py`: 22 passed.
- `tests/test_cli_ext/test_book_build_from_wiki_modes.py`: 13 passed.
- `tests/test_cli_ext/test_vector_cmd.py`: 2 passed.
- Combined focused run: 37 passed.
