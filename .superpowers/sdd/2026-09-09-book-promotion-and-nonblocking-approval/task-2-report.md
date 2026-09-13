# Task 2 report — Promote a validated preview without another LLM call

Status: complete.

Implemented `--apply-from` through the compiler and CLI. Promotion validates the
candidate under `.index/book-wiki/versions/<release_id>`, checks current Wiki
snapshot freshness, acquires the existing Book lock, copies the immutable
candidate into `.releases/`, atomically updates `CURRENT.json`, and reports
`source_release_id` plus `llm_calls_used: 0`.

The promotion path bypasses provider creation and preflight. Ordinary publish
and promotion share `publish_validated_candidate`; failed pointer replacement
removes only the new release and leaves the prior pointer intact.

Verification:

- `tests/test_kc/test_book_promotion.py`: 2 passed.
- protocol, acceptance, compiler, and CLI regression set: 44 passed.
- `tests/test_cli_ext/test_book_build_from_wiki_modes.py`: 12 passed.
- No real provider call was made.
