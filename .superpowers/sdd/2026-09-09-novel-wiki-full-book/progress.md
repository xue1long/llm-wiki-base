# SDD ledger — plan: docs/superpowers/plans/2026-09-09-novel-wiki-full-book.md

## Setup

- Base: `589a10c24448dff1a75d00a07d2351668b1c8a03`
- Branch: `codex/book-series-target`
- Ruling: subagent-driven-development launcher is not executable on this Windows host; execute the same task/review gates in the controller session, preserving one logical commit per task.

## Pre-flight task/interface scan

| Task | Shared files/interface | Producer → consumer | Finding / ruling |
|---|---|---|---|
| 1 ↔ 2 | `compiler.py`, `scope_mode`, manifest | Task 1 scope report → Task 2 deterministic outline | Scope must be resolved before partitioning; Task 2 consumes only the explicit scope page set. |
| 1 ↔ 3 | CLI args, manifest | Task 1 scope counts → Task 3 budget plan | Budget must include the resolved chapter count; no provider call before scope and budget are persisted. |
| 1 ↔ 4 | `compiler.py`, chapter generation | Task 1 full page map → Task 4 body generation | Full scope bypasses pilot curation only; provenance and sensitivity gates remain active. |
| 1 ↔ 5 | output dir, CURRENT | Task 1 manifest scope → Task 5 WebUI badge/version | Full release stays on `book-wiki`; pilot remains readable through release selector. |
| 2 ↔ 3 | outline/chunk IDs | Task 2 chunk plan → Task 3 batch state | Chunk IDs must be deterministic and stable across resume. |
| 2 ↔ 4 | section plan/page IDs | Task 2 ownership → Task 4 compiler-owned provenance | LLM cannot alter page assignment. |
| 3 ↔ 6 | batch state/release | Task 3 completed batches → Task 6 one candidate release | Batch artifacts never become CURRENT individually. |
| 4 ↔ 5 | acceptance/report | Task 4 complete chapters → Task 5 WebUI | WebUI must read only integrity-verified release files. |

| Task | Internal consistency | Finding / ruling |
|---|---|---|
| 1 | CLI scope, compiler scope, manifest counts | Consistent after adding one explicit `scope_mode` parameter. |
| 2 | partition, outline, appendix | Consistent; source appendix is separate from正文 page coverage. |
| 3 | batch resume, budget, release | Consistent only if final promotion remains atomic; enforced by acceptance. |
| 4 | generated body, validation, fallback | Consistent only when partial cannot pass apply; retained as hard gate. |
| 5 | API/UI/output paths | Existing `book-wiki` reader is the seam; legacy `/kc/book/build` remains separate. |
| 6 | preview/apply-from/vector | Consistent; no vector mutation in publish path. |

## Tasks

- Task 1: complete — `scope_mode` CLI/compiler seam; 30 affected tests passed; manual diff review clean
- Task 2: complete — deterministic indexes/coverage/source appendix; 18 tests passed; real plan gate 1255/179/463 passed
- Task 3: complete — resumable batch state and pre-call budget gate; 34 related tests passed
- Task 4: complete — full-scope provenance/coverage acceptance gate; 36 related tests passed
- Task 5: pending
- Task 6: pending

## Decisions

- Full scope means all 1255 eligible knowledge pages; 463 source files are appendix/provenance.
- Full run hard cap is 358 chapter calls (179 first calls + one retry each); no volume-summary calls in this plan.

## Task 1 review

- Findings: none.
- Verification: `uv run --offline pytest tests/test_kc/test_book_wiki_compiler.py tests/test_cli_ext/test_book_build_from_wiki_modes.py -q` → 30 passed.
- Scope default remains `pilot`; `full_knowledge` bypasses persisted pilot curation and records the mode in the release manifest.

## Task 2 review

- Findings: none.
- Verification: `uv run --offline pytest tests/test_kc/test_book_wiki_compiler.py tests/test_kc/test_book_wiki_outline_llm.py -q` → 18 passed.
- Real full plan gate: `page_count=1255`, `chapter_count=179`, `source_appendix_count=463`, `coverage_ratio=1.0`, `release_status=planned`.

## Task 3 review

- Findings: none.
- Verification: `uv run --offline pytest tests/test_kc/test_book_wiki_batch_state.py tests/test_kc/test_book_wiki_compiler.py tests/test_cli_ext/test_book_build_from_wiki_modes.py -q` → 34 passed.
- Full scope skips outline LLM calls; the approved 358 cap therefore covers 179 chapter calls plus one retry each.
- Budget insufficiency is blocked before provider invocation; completed chapters are reused from atomic JSON state on resume.

## Task 4 review

- Findings: one regression found and fixed: the pre-call full-scope budget check was initially applied to pilot outline retries; it is now scoped to full scope or persisted editorial builds.
- Verification: `uv run --offline pytest tests/test_kc/test_book_acceptance_report.py tests/test_kc/test_book_chapter_body.py tests/test_kc/test_book_wiki_staged_failure.py -q` → 36 passed.
- Full-scope acceptance now requires complete page coverage, source appendix evidence, and one provenance map per chapter; human review remains advisory.
