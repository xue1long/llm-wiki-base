# SDD ledger — plan: docs/superpowers/plans/2026-09-11-novel-wiki-writing-kb-remediation.md

## Setup

- Branch: codex/book-series-target
- Base commit: 09884d271e6bf5333266950dd4e1a78977ac9e1d
- Scope: v3 must-only remediation; raw read-only; no full ingestion; no push.
- External collaboration gate: browser auto-review rejected opening ChatGPT as unrelated to local plan work; execution continues from local evidence.

## Preflight task/interface scan

| Task | Inputs/outputs | Shared files/interfaces | Finding and ruling |
|---|---|---|---|
| Task 0 | writer/schema evidence -> baseline report | WikiPage serialization, page_writer | Must precede all tasks; resolve contract drift before implementation. |
| Task 1 | human usage contract -> review/migration | tags, review persistence, writer | Task 2/3 consume 用途/可执行; use one tag and existing review storage. |
| Task 2 | evidence-based generation -> pages/review queue | generator, analyzer, ingest, KnowledgeCandidate | Reuse knowledge_mode; no new candidate axis. |
| Task 3 | pending/hash/model -> ready/search response | pending ledger, search service, hybrid_search | Task 4 consumes ready state; keyword remains explicit fallback. |
| Task 4 | 15+5 cases and author tasks -> evaluation report | search mode and actionable filter | Uses Task 1/3 outputs; no full benchmark. |
| Task 5 | canary/failure drill -> final go/no-go | writer, rollback, batch executor, pending | Runs after Tasks 0–4; no automatic scale-up. |

## Task self-consistency scan

| Task | Self-consistency |
|---|---|
| Task 0 | Inspect/modify only on confirmed mismatch; one report and focused regression. Consistent. |
| Task 1 | One tag, human review, dry-run/apply/rollback. Consistent. |
| Task 2 | Removes quantity floor and candidate_use; reuses existing knowledge_mode. Consistent. |
| Task 3 | Minimal ready fields and search behavior match acceptance. Consistent. |
| Task 4 | Small benchmark and author tasks match thresholds. Consistent. |
| Task 5 | Canary and failure drill use existing safety mechanisms; no full rollout. Consistent. |

## Status

- Task 0: complete
- Task 1: complete
- Task 2: complete
- Task 3: complete
- Task 4: complete for the actionable writing index; 15/15 positive hits, 5/5 negative abstains, and 4/4 author tasks accepted within one query. The all-page vector state remains pending=1206 and is explicitly out of scope for the writing index.
- Task 5: complete — 3 real raw canaries passed in an isolated copy; injected write failure produced partial_commit, raw stayed unchanged, and --resume returned committed/done. Final decision is restricted canary go; no expansion to 20/100/full rollout.

- Task 0: complete — V6 write / V4-V5 read-compatible contract aligned; baseline report and focused regression created; commit 3b31d558; validation frontmatter regression + py_compile + strict validator P0=0. V6 ADR remains proposed by design.
- Task 1: complete — `用途/可执行` is human-review gated; user approved 15 pages, dry-run/apply migrated 15 pages with raw unchanged and page-only diffs; migration now preserves unrelated frontmatter; commits ee09e19d and 8dc27e23; direct regressions + py_compile PASS.
- Task 2: complete — fixed page-count/entity floors removed; empty evidence returns without retry; generator strips actionable tags; commit 6adfced2; static regression + py_compile PASS.
- Task 3: complete — pending ledger records page/vector hashes, model and failed state; ready is conservative; search mode is propagated and semantic search fails closed; commit 3f4a1077; ready/search regressions + py_compile PASS.
- Task 4: resolved — initial full-scope run was blocked by pending vectors; after narrowing the explicitly approved actionable scope, the final evidence passed with 15/15, 5/5 and 4/4 results.
- Task 5: complete — final report: `docs/reports/2026-09-11-novel-wiki-remediation-final.md`; Task 5 fixes cover empty-vector deletion, failed-batch status, and relative-path lineage cleanup. No automatic scale-up.

## Production rollout (user-authorized 2026-09-11)

- Scope expanded by explicit user authorization to full rollout. This supersedes the earlier Task 5 boundary of restricted canary only.
- Provider authorization: `minimax` / `MiniMax-M3`; fake generation remains disabled.
- Vector rebuild run `prod-vector-20260911` is running from checkpoint with local `thenlper/gte-small-zh` 512-dim embeddings; raw batch runner waits for its completion.
- User clarification: raw has already been ingested; re-ingestion is unnecessary. The raw batch watcher was stopped before batch 0, so no raw content was sent to MiniMax. Vector rebuild/reconciliation is complete: 1718/1718 main pages, 3829/3829 rows, pending=0, actionable readiness=true. The 22 `wiki/_stubs/` pages remain intentionally unpublished. See `docs/reports/2026-09-11-novel-wiki-production-rollout.md`.
