# Task 1 report — instance Book rules loader

Status: VERIFIED

## Changed files

- `src/kc/views/book/wiki/rules.py`
- `tests/test_kc/test_book_wiki_rules.py`

## Implementation

- Loads `<project_root>/book.rules.md` exactly once per call.
- Decodes UTF-8, strips a leading BOM, and normalizes CRLF/CR to LF without otherwise rewriting Markdown.
- Rejects missing, unreadable, invalid UTF-8, empty, and whitespace-only rules with `BookRulesError`.
- Returns a frozen, slotted `BookRulesSnapshot` containing canonical text and SHA-256 `rules_hash`.
- Does not cache, parse, inherit, include, or touch compiler call sites.

## Verification

Command:

```text
$env:PYTHONPATH='.'; uv run --no-sync python -m pytest tests/test_kc/test_book_wiki_rules.py --import-mode=importlib -q
```

Result: `7 passed in 5.64s`

## Concerns

- The repository has extensive pre-existing dirty changes; only the two assigned production/test files and this required report were added by this task.
- `graphify query` could not start because the configured uv Python process is unavailable/blocked; direct source inspection was used.
