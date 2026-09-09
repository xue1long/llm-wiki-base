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
- Task 2: pending
- Task 3: pending
- Task 4: pending
- Task 5: pending
- Task 6: pending

## Decisions

- Full scope means all 1255 eligible knowledge pages; 463 source files are appendix/provenance.
- Full run hard cap is 358 chapter calls (179 first calls + one retry each); no volume-summary calls in this plan.

## Task 1 review

- Findings: none.
- Verification: `uv run --offline pytest tests/test_kc/test_book_wiki_compiler.py tests/test_cli_ext/test_book_build_from_wiki_modes.py -q` → 30 passed.
- Scope default remains `pilot`; `full_knowledge` bypasses persisted pilot curation and records the mode in the release manifest.
