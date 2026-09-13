# Task 3 report — LLM prompt trust boundary

## Result

Implemented only the chapter prompt boundary in `src/kc/views/book/wiki/polish_llm.py` and added `tests/test_kc/test_book_wiki_prompt_boundary.py`.

- Added a fixed hard-contract system prompt through the existing `provider.complete(..., system=...)` API.
- Added a distinct `project_rules` object before `allowed_sections` and `source_pages` in the user JSON payload.
- Kept the existing structured-output request and deterministic post-generation validation.
- Preserved the returned `chapter_id` so provenance validation can reject a provider response that changes it.
- Did not edit compiler, preflight, CLI, rules loader, provider implementations, or commit.

## Tests

Passed:

```text
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib tests/test_kc/test_book_wiki_prompt_boundary.py -q
2 passed in 1.63s
```

Regression run:

```text
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib tests/test_kc/test_book_wiki_prompt_boundary.py tests/test_kc/test_book_wiki_polish.py tests/test_kc/test_book_chapter_body.py -q
21 passed, 1 failed in 6.52s
```

The failing existing test is `test_publication_llm_budget_counts_outline_and_body_requests`; it expected `status == "partial"` but received `"failed"`. It is outside this task's write set and concerns compiler publication/budget behavior.

## Concerns

The compiler caller does not yet pass the instance rules snapshot into `generate_chapter_body`; this task exposes the optional `project_rules` input but intentionally leaves caller wiring to the compiler task. No provider capability or fallback was added.
