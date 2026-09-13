# Task 1 — Instance Book rules

Implement only the instance-owned `book.rules.md` loader and its tests.

Write set: `src/kc/views/book/wiki/rules.py`, `tests/test_kc/test_book_wiki_rules.py`.

Requirements:
- Read `<project_root>/book.rules.md` once.
- Empty, missing, unreadable rules fail closed.
- Return an immutable snapshot containing canonical text and SHA-256 `rules_hash`.
- Do not add JSON schema, inheritance, include, DSL, or compiler changes.
- Preserve all unrelated dirty changes. Do not edit other production files.
- Follow TDD; run the focused tests and report exact command/result in the report file.
