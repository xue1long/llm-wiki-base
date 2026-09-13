# Task 4 report — compiler quality and publish gates

## Changes

- Added compiler-local `_body_llm_status()` mapping:
  - no polished chapter map: `disabled`
  - every chapter body complete: `passed`
  - any failed or incomplete chapter: `failed`
- Passed that status into the existing quality gate instead of hard-coding `disabled`/`unavailable`.
- Added `llm_status=unavailable` to provider-unavailable compiler returns.
- Formal `apply` now fails closed unless the staged artifact contains complete LLM-generated chapter bodies.
- `publish_book(..., apply=True)` repeats the rule-only/partial defense so callers cannot bypass the compiler gate.
- Failed paths return before changing `CURRENT.json`.

## Tests

Command attempted:

```text
$env:UV_CACHE_DIR=(Join-Path (Get-Location) '.uv-cache-task4'); $env:PYTHONPATH='.'; uv run --offline python -m pytest tests/test_kc/test_book_wiki_compiler_gate_task4.py --import-mode=importlib -q
```

Result: **blocked by environment**. `uv` could not query the configured Python interpreter and returned `拒绝访问 (os error 5)` before pytest started.

Static check:

```text
git diff --check -- src/kc/views/book/wiki/compiler.py tests/test_kc/test_book_wiki_compiler_gate_task4.py
```

Result: passed with no whitespace errors.

## Concerns

- Existing dirty tests still contain legacy expectations that a rule-only `apply` can seed or replace a release. They were not edited per the task brief; those tests will need the next integration task to be reconciled with the new fail-closed contract.
- The configured Python/uv launcher permission problem prevents runtime confirmation in this environment.
- No CLI, preflight, rules loader, polish prompt, or commit was changed.

## Minimal rules integration

- `build_from_wiki` now loads `src.kc.views.book.wiki.rules.load_book_rules` once at build start.
- Missing, empty, unreadable, or invalid-UTF-8 `book.rules.md` returns `blocked` with `E_BOOK_RULES_UNAVAILABLE` before provider use; this applies to plan and to polished preview/apply.
- The frozen rules text is passed to every `generate_chapter_body(..., project_rules=...)` call.
- `rules_hash` and the complete `rules_snapshot` are stored in the existing manifest and release-acceptance metadata.
- Added compiler-focused coverage for fail-closed rule loading and manifest rule metadata.

## Integration verification

Runtime tests were intentionally not rerun after the user requested stopping test execution. The known environment issue remains: the configured Python/uv launcher is denied access (`os error 5`).
