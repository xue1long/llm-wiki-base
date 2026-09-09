# Task 4 review

## Result

Clean after one compatibility fix. Full-scope acceptance fails closed when coverage, source appendix, or chapter provenance is incomplete. Chapter failures remain partial and cannot pass apply; human readability/content review remains advisory.

## Verification

`uv run --offline pytest tests/test_kc/test_book_acceptance_report.py tests/test_kc/test_book_chapter_body.py tests/test_kc/test_book_wiki_staged_failure.py -q` → 36 passed.
