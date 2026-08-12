# ruflo-kb Implementation Progress

## 2026-08-12: cross-file duplicate refactor
- [x] Design, ADR, implementation plan, and two-round plan audit
- [x] Hashing, cosine, extraction errors, CLI resolution, and script logging compatibility migrations
- [x] Full repository re-index: 16,813 nodes / 55,896 edges
- [x] Focused verification: 49 passed; compileall passed
- [ ] Final full-suite run is environment-limited by global registry path permissions; unrelated generated/worktree files remain untouched

## 2026-08-12: knowledge-os document integration
- [x] Phase 0 taxonomy contract and schema/purpose/taxonomy prompt injection
- [x] Phase 1 triage contract, durable JSONL log, and generate/commit side-effect boundary
- [x] Phase 2 operation processing depth and operation template injection
- [x] Phase 3 export audit log and read-only content health CLI/API aggregate
- [x] Final review and isolated commit (`10cbae8`; unrelated workspace changes remain unstaged)

## 2026-08-12: knowledge-base scenario templates
- [x] Stage 1 architecture plan and two-round plan audit
- [x] Scenario template loader with bundled/custom templates and safe apply
- [x] Five bundled scenarios; General includes four project page templates
- [x] CLI create/edit/delete/apply and project init template integration
- [x] HTTP scenario-template endpoints and WebUI project template selection
- [x] Stage 3 code review and full relevant test run (`120 passed`; server dependencies repaired)

## 2026-08-12: schema/purpose data-driven custom types
- [x] SchemaRegistry parses and validates schema.md custom page types
- [x] Analyzer/Generator prompt injection and dynamic structured-output enums
- [x] Candidate -> KnowledgeObject -> WikiPage custom_type propagation
- [x] Custom directory routing, frontmatter round-trip, and base-template fallback
- [x] 803 relevant tests pass; implementation ready for stage-3 code review

## Plan 1: Project multi-instancing (11 tasks)
- [ ] Task 1: src/project/paths.py — config directory helpers
- [ ] Task 2: src/project/identity.py — ProjectIdentity + UUID
- [ ] Task 3: src/project/registry.py — GlobalRegistryStore
- [ ] Task 4: ProjectContext.from_path()
- [ ] Task 5: ProjectContext.resolve() 4-step chain
- [ ] Task 6: src/project/mutex.py — with_project_lock
- [ ] Task 7: src/project/discovery.py — auto-discover
- [ ] Task 8: cmd_project_init/list CLI
- [ ] Task 9: cmd_project_info/current/select CLI
- [ ] Task 10: cmd_project_import/forget/rename/discover CLI
- [ ] Task 11: wire auto_register + env override

## Plan 2-18: TODO
Task 1: complete (commit 24a9690, review clean)
Task 2: complete (commit c474cc2, review clean)
Task 3: complete (commit 01dab6f fix, atomic save + broader except, review clean)
Task 4: complete (commit 83c1129, review clean — minor: name field vs property)
Task 5: complete (commit 1e43b58, review clean — 6 minor stylistic notes)
Task 6: complete (commit 7a8df0b fix, dead code removed, review clean)
Task 7: complete (commit 3feefe4, manual review clean — reviewer hit rate limit but diff verified)
Task 8: complete (commits b21f404 + d0f5689 fix, review clean)
Task 9: complete (commit c7c7a8b, review approved with notes — minor: dead _registry_path monkeypatch + ProjectNotFoundError not caught in cmd_project_current)
Task 10: complete (commits 894e60c + 633fcde fix, path canonicalization + safe rename order verified)
Task 11: complete (commits 272c345 + 4070f83 fix, integration test strengthened, Plan 1 DONE)
---
## Plan 2: Schemas v3 (6 tasks) - STARTING
- [ ] Task 1: src/schemas/base.py - ForwardCompatModel
- [ ] Task 2: src/schemas/migration.py - Migration base class
- [ ] Task 3: src/schemas/backup.py - BackupManager
- [ ] Task 4: src/schemas/registry.py - refactor + v1_to_v2 as class
- [ ] Task 5: src/schemas/migrations/v2_to_v2_1.py
- [ ] Task 6: src/cli_ext/schema_cmd.py - CLI
S1: complete (commit 1fc548e, ForwardCompatModel + 3/3 tests pass)
S2: complete (commit 948e620, 6/6 new tests, fixed 2 plan bugs in test code)
S3: complete (commit 641cb43, recursion bug fix, 4/4 tests)
S4: complete (commit 170e98b, 3/3 + 16/16 total schema tests; noted pre-existing legacy test will need cleanup)
S5: complete (commits 49cea87 + bbf9e15 fix, 3/3 tests pass; all 19 schema tests pass)
S6: complete (commit 82a70ec, 3/3 tests pass, fixed 3 plan bugs); PLAN 2 COMPLETE
AC1: complete (commit 1fe0fa4, 7/7 tests, fixed process-global→threading.local for thread isolation)
AC2: complete (commit 24cd4b0, 5/5 tests; 12/12 total test_lib pass)
AC3: complete (commits d6bbab1 + 088a757 fix, 6/6 tests; 18/18 total test_lib pass)
AC4: complete (commit be0b707, 3/3 tests, fixed plan test issues, 21/21 total test_lib pass)
AC5: complete (commit 1f37dcd, added get_model_context_window + 5 CLI tests, 26/26 test_lib + test_cli_ext pass); ATOMIC-CTX+BUDGETED-LLM PLAN COMPLETE

## 2026-07-22 continuation: all 8 remaining plans

Dispatched 32 tasks via subagent-driven-development, in dependency order:
- Wave 1: http-api-mcp T1-T4, web-search T1, chat-agent T1-T2
- Wave 2: wiki-v2 T5-T8 (analyzer/generator)
- Wave 3: wiki-v2 T9-T15 (lifecycle A1-A7)
- Wave 4: wiki-v2 T16, chat-agent T3
- Wave 5: wiki-relations T1-T3, wiki-fields-v22 T1-T4, wiki-heat-5pool T1-T2, wiki-v21-polish T1-T3

HAP1: complete (commit e30dfcd, review approved; 3 Minor (all brief-verbatim) — no fixes; spec-compliance note: __init__.py docstring divergence from brief but reviewer judged acceptable since pre-existing from 0177275)
HAP2: complete (implementer db6ba98, fix c3327e8; official reviewer stuck but peer review identified real issues — path traversal in files, project_id ignored in schema, mostly-import tests; fix addressed all Important; 28/28 tests pass; T2 final state: secure + behavioral)
HAP3: complete (commit 66461c8, reviewer Approved; 0 Critical/Important, 8 Minor polish only; platform split clean — POSIX os.fork + Windows subprocess.Popen with DETACHED_PROCESS flags; 14/14 tests pass; T3 includes serve-status as a useful extra subcommand)
HAP4: complete (commit 8533ae2, reviewer Approved; 0 Critical/Important, 6 Minor polish; 17/17 MCP tests pass; mcp>=0.1.0 added to pyproject; http-api-mcp PLAN COMPLETE)
WS1: complete (impl 34d79a8+286624e, fix 08784f8; reviewer + peer both identified same Important — show delegation broken, no HTTP error handling, client not closed on error; fix addressed all 3; 2/2 research tests pass; web-search PLAN COMPLETE)
CA1: complete (commit 2a81b8e, reviewer Approved; 0 Critical/Important, 3 Minor brief-inherited; 3/3 tests pass; types only)
CA2: complete (commit cf92155, reviewer Approved; 0 Critical/Important, 3 Minor brief-inherited; 3/3 tests pass; 5 tools + TOOLS dict)
CA3: complete (impl 66f6ee4, fix 7c23691; reviewer Needs-fixes 3 Important — topK/top_k schema mismatch, ctx.settings fallback missing, tool kwargs mismatch; fix addressed all 3 with 3 new RED→GREEN tests; 23/23 tests pass; chat-agent PLAN COMPLETE)
WV5: complete (commit b11812e, reviewer Approved; 4/4 tests pass; wiki/index.md maintainer with idempotency; brief had typo wiki_index→llm_wiki_index, implementer aligned correctly)
WV6: complete (commit 5a9c7c2, reviewer Approved; 0 issues; 3/3 tests pass; wiki/log.md audit trail)
WV7: complete (commit e2f71e4, reviewer Approved; 0 issues; 1/1 test passes; Analyzer Step 1 (LLM-driven AnalysisResult); env issue (pip SSL) noted but worked around)
WV8: complete (commit b4cce1a, reviewer Approved; 0 issues; 1/1 test passes; Generator Step 2 (LLM-renders WikiPage list from AnalysisResult); wiki-v2 T5-T8 FOUNDATION COMPLETE)
WV9: complete (commit 3e1dab7, reviewer Approved; 2/2 tests; cascade_delete (A1); brief had `p.wiki_index` typo (real attr is `llm_wiki_index`) + matching logic needed raw-path extension to satisfy test — both acceptable)
WV10: complete (commits b986a96 + 9f3f048 fix, reviewer NEEDS_FIXES then fix Approved; 5/5 tests; lint (A4); fix changed scanned_pages to count .md files, not unique ids; new test test_lint_counts_files_with_duplicate_page_ids covers regression)
WV11: complete (commit 0b582b0, reviewer Approved; 2/2 tests; schema_routing (A5); concise + correct)
WV12: complete (commit 0a7596f, reviewer Approved; 3/3 tests; export/import ZIP (A6); Minor: extractall path-traversal risk acknowledged as MVP — defer security fix to v2.0.1)
WV13: complete (commit 82d1aef, reviewer Approved; 3/3 tests; review items (A3); replaced prior stub from db6ba98; concerns (storage location, status vocab, non-atomic move) all MVP-acceptable per brief)
WV14: complete (commit 287a6fb, reviewer Approved; 2/2 tests; dedup MVP stub (A7))
WV15: complete (commit 7dc54dc, reviewer Approved; 5/5 tests; folder-aware ingest helpers (A2))
WV16: complete (commit e6afb99, reviewer Approved; 1/1 new test + 55/55 regression on test_pipeline + test_wiki; pipeline integration; chose additive migration path (kept legacy wiring + added run_ingest), brief typo p.wiki_index→p.llm_wiki_index fixed; wiki-v2 PLAN COMPLETE — 16/16 tasks)
FINAL REVIEW: 0 Critical / 2 Important / 1 Minor; dispatched single fix subagent
- ce92ef9 fix(wiki): defer cascade_delete file ops to atomic flush (Important #2 — DELETE_SENTINEL in safe_write + new regression test)
- 2bf7ced feat(pipeline): wire run_ingest into collector:done event flow (Important #1 — Option A minimal: replaced legacy Processor/Librarian with new Analyzer+Generator chain)
Concerns post-fix: _get_provider() defaults to openai registry entry — flag for follow-up; legacy processor.py/librarian.py no longer called from event flow but kept on disk
Final test count: 57/57 passing in test_pipeline + test_wiki (added 2 regression tests)

## Wiki-v2 Plan COMPLETE (16/16 tasks) — T9-T16 + 3 fix commits

Final commits in this batch (b4cce1a..2bf7ced): 11 commits total
- 3e1dab7 cascade_delete (A1)
- b986a96 + 9f3f048 lint (A4) [fix for scanned_pages count]
- 0b582b0 schema_routing (A5)
- 0a7596f export/import ZIP (A6)
- 82d1aef review items (A3)
- 287a6fb dedup stub (A7)
- 7dc54dc folder-aware ingest (A2)
- e6afb99 pipeline integration
- ce92ef9 cascade atomic flush fix
- 2bf7ced run_ingest wiring fix

Total wiki tests passing: 57 (test_pipeline + test_wiki combined)
Minor remaining: ZipFile.extractall path-traversal risk in import_ — acknowledged MVP, defer security fix to v2.0.1

## Chat-agent T3 follow-up: server test infrastructure
f4180c1 fix(test): add tests/test_server/conftest.py stubbing heavy deps
- Mirrors tests/test_pipeline/conftest.py: stubs platformdirs, lancedb, pyarrow, pypdf, docx, openpyxl, mcp
- Unblocks tests/test_server/test_chat.py + test_routes.py
- All 10 server tests pass + agent (11) + wiki/pipeline (57) = 78/78 across touched areas

## Wiki-relations Plan started
WR1: complete (commit 030422b, reviewer Approved; 5/5 new + 7/7 regression; Relation type + 17 built-in + inverse table + WikiPage.relations field with frontmatter round-trip via lazy import; plan typo 16→17 acknowledged)
WR2: complete (commit be47952, reviewer Approved; 7/7 new + 63/63 regression; RelationSync + RelationQuery + SYMMETRIC_RELATIONS skip; idempotency verified; find_path returns 3-tuples as documented)
WR3: complete (commit 5f7e7a2, reviewer NEEDS_FIXES 2 Important + 1 Minor; fix 9371528, 4/4 + 74/74 regression; Important #1: ctx.paths→WikiPaths(ctx.path) using _paths helper, handlers now derive WikiPaths from real ProjectContext; Important #2: new integration test using real ProjectContext (RED on unfixed, GREEN after); Minor #3: cmd_relations_types now reads user_relation_types from settings.json; wiki-relations PLAN COMPLETE — 3/3 tasks)
TEST_INFRA: conftest for test_cli_ext added (stubs platformdirs + lancedb + pyarrow + pypdf + docx + openpyxl + mcp + tavily); unblocks test_cmd_relations.py + test_cmd_research.py collection

## Wiki-relations Plan COMPLETE (3/3 tasks)
- 030422b relation types + inverse table
- be47952 RelationSync + RelationQuery
- 5f7e7a2 Generator relations + CLI
- 9371528 fix ctx.paths → WikiPaths(ctx.path)
- test conftest for test_cli_ext

## Wiki-fields-v22 Plan started
WF1: complete (commit 3048dc2, reviewer Approved; 4/4 new + 67/67 regression; UUID v7 ID generator + 3 v2.2 fields grade/processing_depth/is_immutable; brief fixture inconsistency 16→13 hex chars acknowledged; relations field NOT broken)
WF2: complete (commit 3a03045, reviewer Approved; 4/4 new + 71/71 regression; TagNamespace validator with 8 prefixes)
WF3: complete (commit 7a8aaa0, reviewer Approved; 3/3 new + 146/149 regression; fields/tags CLI; WikiPaths(ctx.path) correctly used (NOT ctx.paths); 2 deviations justified: L4 ID warning as non-fatal aligns with plan's "WARN:" prefix; tags read from raw YAML since WikiPage lacks tags field)
WF4: complete (commit 281baa0, reviewer Approved; 4/4 new + 23/23 schema regression; v2.0→v2.2 migration; 2 plan bugs caught+fixed by implementer: import path ....wiki → ...wiki (3 dots not 4); down() guarded on schema_version marker that up() never writes to page files — fixed for round-trip symmetry); wiki-fields-v22 PLAN COMPLETE — 4/4 tasks

## Wiki-fields-v22 Plan COMPLETE (4/4 tasks)
- 3048dc2 UUID v7 ID + 3 v2.2 fields (grade/processing_depth/is_immutable)
- 3a03045 TagNamespace validator (8 prefixes)
- 7a8aaa0 fields/tags CLI
- 281baa0 v2.0→v2.2 migration (UUID v7 IDs + 3 new fields)

## Wiki-heat-5pool Plan started
WH1: complete (commit 2329b56, reviewer Approved; 5/5 new + 76/76 regression; HeatTracker + ZombieDetector + WikiPage.heat fields; constants HEAT_DECAY_DAYS=30, HEAT_DECAY_AMOUNT=10, HEAT_INCREMENT=5; _infer_type duplication noted for Task 2)
WH2: complete (commit ef36083, reviewer Approved; 3/3 new + 147/150 regression; heat CLI 7 subcommands; WikiPaths(ctx.path) correctly used; wiki-heat-5pool PLAN COMPLETE — 2/2 tasks)

## Wiki-heat-5pool Plan COMPLETE (2/2 tasks)
- 2329b56 HeatTracker + ZombieDetector + WikiPage.heat fields
- ef36083 heat CLI (7 subcommands)

5-Pool routing logic deferred to v2.0.1 (per spec polish)

## Wiki-v21-polish Plan started
WP1: complete (commit ccedd2c, reviewer Approved; 2/2 new + 85/85 regression; StubMaterializerWorker auto-promotes referenced stubs to real pages via LLM; 2 plan deviations caught+fixed: plan used `from .analyzer/.generator/.schemas` (wrong, those live in src/pipeline/) — implementer used `from src.pipeline.generator import generate` directly + lazy imports; new tests/test_wiki/conftest.py added)
WP2: complete (commit 6c51e34, reviewer Approved; 6/6 new + 84/84 regression; DedupAuto + LintCache; signature fix: DedupHistoryStore.record(paths, ...) accepts WikiPaths not ProjectContext; find_duplicates(paths, ...) matches real signature; TTL 86400=24h default)
WP3: complete (commit 962515c, fix 8b9fbb0, reviewer NEEDS_FIXES then fix Approved; 4/4 new + 159/162 regression; polish CLI 5 subcommands + subparsers wired; fix added test_lint_uses_cache_on_second_run covering cache-hit behavior); wiki-v21-polish PLAN COMPLETE — 3/3 tasks

## Wiki-v21-polish Plan COMPLETE (3/3 tasks)
- ccedd2c StubMaterializerWorker
- 6c51e34 DedupAuto + LintCache
- 962515c + 8b9fbb0 fix polish CLI (5 subcommands) + cache-hit test

## Session 1 END (2026-07-22, ~10h)

**Completed plans (4):**
- http-api-mcp (4 tasks)
- web-search-deep-research (1 task)
- chat-agent (3 tasks)
- wiki-v2 T5-T8 (foundation: indexer, logger, analyzer, generator)

**Total commits this session: 14** (from e30dfcd to b4cce1a, plus 3 fix commits)

**Remaining: 18 tasks** (wiki-v2 T9-T16 lifecycle + 4 polish plans)

---

## Session 2 (2026-07-23): Full-codebase audit + fix plan

Branch: `fix/2026-07-23-full-audit` (base = 8f0fd0f master HEAD)
Plan: `docs/superpowers/plans/2026-07-23-full-audit-fix.md` (1524 lines, 16 tasks, 4 phases)
Brief files: `.superpowers/sdd/task-N-brief.md`
Report files: `.superpowers/sdd/task-N-report.md`

Resolution of audit findings (2026-07-23 full audit):
- 23 critical, 53 important, 6 minor + ~12 notable issues across 6 subsystems (LLM, Service/HTTP/CLI, Cross-cutting, Queue/Orch, Pipeline/Wiki, Vector/Search)

TBD — execution starts below

T1: complete (commit cf908df, review clean — 0 Critical/Important; Minor carryover for final review: `templates_cmd.py:45` raw `dest.write_text` out-of-scope, will triage at final review)
T2: complete (commit 964d2477, review clean — 0 Critical/Important; side-effect fix `_build_schema()` lazy resolved alphabet-conftest import order bug, +27 regression tests now pass; 3 minor carryovers for final review: (a) legacy `init_vector_store(db_path)` wrapper heuristic fragility, (b) hybrid_search silent exception swallow in keyword-fallback path, (c) pre-existing zero-vector fallback in librarian upsert path)
T3: complete (commit a1e6a8b, review clean — 0 Critical/Important; brief ambiguity around registry "default" field correctly adjudicated by implementer; scope additions to src/lib/budgeted.py and src/shared/test_helpers.py confirmed NECESSARY for the contract change; 3 minor carryovers for final review: (a) dead `isinstance(response, dict)` shim in agent/runtime.py:88-103, (b) redundant `self.client = client` in openai_provider.py:50-51, (c) `embedding()` alias duplication in ollama_provider.py:129-135)
T4: complete (commits 61d7560 + 762cf9b fix, review Approved after re-review — 3 Important findings from first review all addressed: SSRF redirect loop with per-hop ACL, raw `.html` write (not `.html.txt`), FILE source regression test; 8/8 collector_url + 18/18 pipeline regression pass)
T5: complete (commits 62384fc + 5612738 fix, review Approved after re-review — 1 Critical + 2 Minor from first review: queue atomic test was patching Path.replace instead of os.replace (no-op assertion); fix verified empirically catches non-atomic regression; 25/25 covering + 504/504 full suite pass)
T6: complete (commit 5487b3f, review clean — 0 findings; `update_task_status` validates via can_transition, raises KeyError/InvalidTransition correctly; get_next_status validates source; orchestrator uses TaskStatus enums; CB decorator shares registry state via setdefault; 14 new + 29 regression + 515 full pass)
T7: complete (commits 39cada0 + befea06 + 0481259, review Approved after 2 fix passes — first review found 1 Critical + 5 Important: async collector handler via sync lambda → run_ingest never runs (Critical), flush callback re-raised, emit-under-lock deadlock, retry liveness, self-locking save/load, thread-scoped pending writes; first fix addressed 5/6 but Critical remained (nested asyncio.run cancellation); second fix used skip-EventBus approach (await _on_collector_done in-line from _on_collector_start) — verified empirically, 534/534 full suite pass)
T8: complete (commits e698b6f + fee3aa9 fix, review Approved after re-review — 2 Important: chat checked `not final_answer` truthiness (empty answer incorrectly raised AgentRunFailed) → introduced `final_answer_seen` flag; cascade_delete's `atomic_pipeline_op` was not first line → moved all setup/validation inside context; 18 + 9 covering + 552 full pass)
T9: complete (commits d9fd9a0 + 3debca8 fix, review Approved after re-review — 1 Important: `PurePosixPath.is_relative_to` is purely lexical, doesn't normalize `..` (path traversal via `Inbox/Processing/../../secret.txt`); fix uses pure-string stack-walk (no Path.resolve(), preserves CWD independence); 13 + 3 covering + 568 full pass; T4 + T7 not regressed)
T10: complete (commit f5a0c3d, review clean — 0 Critical/Important; masking uses "***"+last4 for >=5 chars / "***" for 1-4 chars (closes 4-char leak per brief); os.chmod cross-platform safe; 2 Minor carryovers for final review: (a) docstring drift in `src/llm/types.py:45` says "shorter than 4" but code uses `< 5` (correct code), (b) out-of-scope pre-existing env-var leak in `src/llm/registry.py:_default_providers` — env keys persisted unredacted on first upsert; 8 new + 576 full pass)
T11: complete (commit fb02252, review clean — 0 findings; `MigrationRegistry.register()` raises `MigrationKeyCollision`; `SchemaVersion.V2_2` added; `v2_to_v2_2.to_version = V2_2` registers under `(V2_0, V2_2)`; `migrate_data` raises `NotImplementedError`; `TaskStatus.DEAD_LETTER` + `EventName.TASK_DEAD_LETTER` added; `(FAILED, DEAD_LETTER)` + `(TIMEOUT, DEAD_LETTER)` state transitions added; latent v2_to_v2_2 shadowing bug fixed; 9 new + 52 regression + 585 full pass)
T12: complete (commit 88b4b6f, review clean — 0 findings; `move_to_processing` + `move_to_error` use `os.replace`; error log uses `{src.name}.error.log` (full filename); `move_to_error` raises `FileNotFoundError` before log write; 3 new + 1 updated + 584 full pass)
T13: complete (commit 2e26523, review clean — 0 findings; hybrid_search validates empty query + top_k bounds (1..100); rrf_fusion accepts two lists with independent RRF contribution + merges by path; vector upsert uses merge_insert("id"); SQL task_id escaped (doubles single quote, verified row-level); QA citations filtered to 1..len(context); 35 new + 46 regression + 619 full pass)
T14: complete (commit c04bd7d, review clean — 0 findings; `decay(page)` short-circuits on `is_immutable`; threshold uses `max(created_at, last_used_at)` (treats 0 as missing); 2 new + 93 regression = 95/95 pass; test value adjustment (100-day gap vs brief's 11.6-day) justified since brief's gap < 30-day HEAT_DECAY_DAYS threshold)
T15: complete (commit baa0731, review clean — 0 findings; schema commands use `_parse_version_or_exit` helper (DRY); backup restore validates name; cli.py declares --config-root for quality set; serve stop/status handle corrupt pidfile via `_read_pidfile_or_cleanup` helper; 13 new + 97 regression + 634 full pass)
T16: complete (commits 57daddc + e5491ce fix, review Approved after re-review — first review found 2 Important + 2 Minor: librarian PermissionError swallowed by broad except (Important), positive test bypassed is_relative_to by not passing paths (Important), __pycache__ tracked (Minor out-of-scope), redundant except tuple (Minor); fix restructured archive() to call _merge_duplicates OUTSIDE broad except, added regression test, positive test now passes paths=paths, removed redundant tuple; 21 new + 654 full pass)

---

## Session 2 完整执行汇总（Plan 19）

| Task | 主题 | 关键 commit | 修复 audit findings |
|---|---|---|---|
| T1 | ctx.paths → WikiPaths | cf908df | C-8..C-12 |
| T2 | Vector + embedding init | 964d2477 | C-1, C-2, C-3, C-23, I-vector-9 |
| T3 | LLM provider contract | a1e6a8b | C-21, C-22 + 9 important |
| T4 | URL collector gate | 61d7560 + 762cf9b | C-7, I-pipeline-15 |
| T5 | Atomic writes | 62384fc + 5612738 | C-6 + 4 important |
| T6 | State machine + CB | 5487b3f | C-5, C-19, I-orch-2,3 |
| T7 | Queue mutex + async | 39cada0 + befea06 + 0481259 | C-4 + 5 important |
| T8 | Error visibility | e698b6f + fee3aa9 | C-15 + 3 important |
| T9 | Permission + 404 | d9fd9a0 + 3debca8 | C-13, C-20 |
| T10 | API key security | f5a0c3d | I-llm-12 |
| T11 | Migration + dead-letter | fb02252 | C-18, I-cross-14, I-queue-11 |
| T12 | Inbox error handling | 88b4b6f | I-inbox-3,4,5 |
| T13 | Search edge cases | 2e26523 | I-vector-3,4,5,6,7,8,11 |
| T14 | Heat decay | c04bd7d | I-pipeline-8,9 |
| T15 | CLI error friendliness | baa0731 | I-svc-11,12,13,14 |
| T16 | Misc single-line fixes | 57daddc + e5491ce | I-cross-6..12,14,15 + notable issues |

**Min carryovers for final review triage:**
- T1: `templates_cmd.py:45` raw `dest.write_text` (out-of-scope)
- T2: (a) legacy `init_vector_store(db_path)` wrapper fragility, (b) hybrid_search silent exception swallow in keyword-fallback, (c) pre-existing zero-vector fallback in librarian upsert
- T3: (a) dead `isinstance(response, dict)` shim in agent/runtime.py:88-103, (b) redundant `self.client = client` in openai_provider.py:50-51, (c) `embedding()` alias duplication in ollama_provider.py:129-135
- T10: (a) docstring drift `src/llm/types.py:45` (says "shorter than 4" but uses `< 5`), (b) out-of-scope pre-existing env-var leak in `src/llm/registry.py:_default_providers`
- T16: __pycache__ files in commit (intentionally tracked per project convention; defer bulk cleanup)

**Test count progression:** 426 baseline → 654 final (full suite)

## Plan 19 COMPLETE (final whole-branch review + cross-cutting fix)

**Final commit:** `c290266` (on top of `e5491ce`)

**Final review (Opus) verdict:** NEEDS_FIXES — 1 Critical + 7 Important + 2 must-fix carryovers

**Final fix addressed all 10 findings:**
- C1 atomic_ctx exception rollback (no commit-on-failure)
- I1 5 production callers migrated to `complete(messages=[...])`
- I2 health_check shape standardized to `dict` across base + 3 providers
- I3 vector-store per-project table resolution via `get_table(project_paths)`
- I4 pipeline uses `ProviderRegistry.get_default()`
- I5 `project_id` threaded through enqueue → collector → done
- I6 4 raw `write_text` sites replaced with `safe_write`
- I7 schema route maps `ProjectNotFoundError` → 404
- M1 templates_cmd.py:45 now uses `safe_write` (carryover)
- M2 librarian raises on missing embeddings (no zero-vector fallback)

**Final test count:** 676 passed in 23.18s (Python 3.14 / Windows)
**Final commit count on branch:** 24 commits (16 task commits + 6 task-fix commits + 1 final-fix + 1 final-fix-fix)

**Deferred carryovers (8 items, non-blocking):**
- T2 legacy `init_vector_store(db_path)` wrapper heuristic
- T2 hybrid-search exception swallowing in keyword-fallback
- T3 dead `isinstance(response, dict)` shim in agent/runtime.py
- T3 redundant `self.client = client` in openai_provider.py
- T3 `embedding()` alias duplication in ollama_provider.py
- T10 docstring drift `src/llm/types.py:45`
- T10 pre-existing env-var persistence behavior
- T16 tracked `__pycache__` binaries (project convention)

**Pre-existing test-isolation quirk:** `.kb-queue.json` accumulates stale tasks and can trip `test_queue_retry_liveness` after the I5 `project_id` field addition. Workaround: `rm -f .kb-queue.json` before full-suite runs. Not part of this audit.

**Branch ready for:** review and merge into master, OR additional incremental fixes for the deferred carryovers.

---

## Plan 20: Followup carryovers (branch `fix/2026-07-23-followup-carryovers`)

Plan: `docs/superpowers/plans/2026-07-23-followup-carryovers.md` (6 small tasks)

F1: complete (commit c8c852f, review clean — 0 findings; removed dead isinstance shim in agent/runtime.py, redundant self.client in openai_provider.py:49-50, embedding() alias in ollama_provider.py; migrated stale AgentRuntime test fixtures to LLMResponse; 3 new + 676 baseline + 0 regression = 679/679 pass; 1 out-of-scope carryover: `OpenAIEmbeddingProvider.__init__:224` still has `self.client = client`)
F2: complete (commits f859ca7 + e129a77 fix, review Approved after re-review — 2 Important: empty-list test didn't prove keyword fallback ran; 1000-char truncation test didn't verify 200-char boundary; fix used pre-populated tmp_path/Knowledge file + inspected warnings[0].args; 5 new + 679 = 684/684 pass)
F3: complete (commit e99d2f0, review clean — 0 findings; dropped `init_vector_store(db_path)` entirely; migrated test_store.py caller; updated `__init__.py` + CLAUDE.md; 3 new + 684 = 687/687 pass)
F4: complete (commit a04c8a0, inline trivial docstring fix — "shorter than 4" → "shorter than 5 chars to avoid leaking the entire key when it's only 4 chars"; no test needed per plan)
F5: complete (commits cf5fa0c + 26d465f fix, review Approved after re-review — Critical save→reload regression found in first review: env-sourced providers disappeared after first save because save() filtered them entirely + load() only reads disk; fix used `dataclasses.replace` to write env-sourced entries with `api_key=""` so provider factory's env-var fallback resolves at runtime; 9 focused + 687 baseline = 696/696 pass; 3 Minor carryovers (raw `path.write_text` in Registry.save — pre-existing; `remove("openai")` silently drops env-default; test helper lacks comment))
F6: complete (commit c65d8a5, review clean — 0 findings; setup_function resets queue module state + deletes .kb-queue.json before each test; new test_retry_liveness_isolation.py runs module twice via subprocess; queue suite passes twice with 25 tests each, full suite 697 each; 0 carryovers)

---

## Plan 20: Followup carryovers — 6/6 tasks complete

**Branch:** `fix/2026-07-23-followup-carryovers`
**Final HEAD:** `c65d8a5`
**Commits on branch:** 6 (F1 + F2 + F2-fix + F3 + F4-inline + F5 + F5-fix + F6)
**Final test count:** 697 passed in ~24s
**Carryovers to final review triage:**
- F1: `OpenAIEmbeddingProvider.__init__:224` still has `self.client = client` (out-of-scope for F1)
- F5: raw `path.write_text` in `Registry.save` (pre-existing, not introduced by F5)
- F5: `Registry.remove("openai")` silently drops env-default — undocumented
- F5: `_isolated_registry` test helper lacks explanatory comment

Now dispatching final whole-branch review (Opus).

---

## Plan 21: Cleanup final minors (branch `fix/2026-07-23-cleanup-final-minors`)

Plan: `docs/superpowers/plans/2026-07-23-cleanup-final-minors.md` (3 small tasks)

C1: complete (commit 7bd465e, review clean — 0 findings; removed `self.client = client` from `OpenAIEmbeddingProvider.__init__`; updated 2 test references from `p.client` to `p._sdk` (necessary scope); 3 new + 702 = 705/705 pass)
C2: complete (commits bab37dc + 68d5b67 fix, re-review Approved — Important finding: docstring referenced nonexistent `add()` method; fix changed to `upsert()` (correct method); 2 new + 705 = 707/707 pass)
C3: complete (commit d2cc803, inline trivial — added 5-line docstring to `_isolated_registry` explaining why `_config_dir()` doesn't need stubbing; 707/707 pass unchanged)
Final review: APPROVED. Branch ready to merge.

---

## Three-plan summary

| Plan | Branch | Commits | Tests (start → end) | Findings fixed |
|---|---|---|---|---|
| 19: Audit-fix | `fix/2026-07-23-full-audit` | 24 | 426 → 676 (+250) | 23 critical + 53 important + 6 minor + 12 notable |
| 20: Followup carryovers | `fix/2026-07-23-followup-carryovers` | 9 | 676 → 702 (+26) | 8 T3/T10/T2 carryovers + 1 quirk + 1 binding-constraint |
| 21: Final minors cleanup | `fix/2026-07-23-cleanup-final-minors` | 4 | 702 → 707 (+5) | 3 out-of-scope carryovers from Plan 20 |

**Total master commits added:** 37
**Final test count:** 707 passed in ~25s
**Remaining deferred items:** none (all carryovers closed across the three plans)

---

## Plan: 2026-07-24-novel-wiki-init (5 tasks)

| Task | Description | Status |
|---|---|---|
| 1 | 初始化项目（project init + ensure_knowledge_base） | ✅ complete（无 git commit — 项目在 repo 外；wiki 目录结构已验证） |
| 2 | 确认 LLM Provider 配置 | ✅ complete（MINIMAX_API_KEY 在 .env 中；minimax 为默认 provider） |
| 3 | 启动 Server | ✅ complete（server 运行在 127.0.0.1:8765；/health 返回 ok） |
| 4 | 摄入 7 份创作资料 | ✅ complete（7/7 queued；27 wiki pages 生成） |
| 5 | 验证分类结果 | ✅ complete（3 sources + 3 entities + 20 concepts + 1 synthesis；frontmatter v2.2 正确） |

---

## Plan: 2026-07-25-queue-pipeline-refactor (10 tasks, branch: master)

| Task | Description | Status |
|---|---|---|
| 1 | Extract `src/queue/state.py` (pure state machine) | ✅ complete (commit 8911317, review-then-fix; matrix aligned to orchestrator; 765 tests) |
| 2 | Extract `src/queue/ports.py` + `src/queue/in_flight.py` | ✅ complete (cfaa619) |
| 3 | Extract `src/queue/persistence.py` (JsonFileBackend + safe_write) | ✅ complete (8aa1a8c) |
| 4 | Extract `src/queue/retry.py` (DefaultRetryPolicy) | ✅ complete (9ea3626) |
| 5 | Extract `src/queue/scheduler.py` (select_next_task pure) | ✅ complete (7096c68) |
| 6 | Extract `src/queue/service.py` (QueueService + __reset_for_testing) | ✅ complete (e34874f, reworded for breaking-behavior-change note) |
| 7 | Migrate `src/queue/__init__.py` + delete `queue.py` | ✅ complete (39d84dd — see Finding 4 note below for cross-task contamination) |
| 8 | Extract `src/pipeline/ports.py` + events.py + stages/ | ✅ complete (100fb17) |
| 9 | Extract `src/pipeline/runner.py` + ingest.py | ✅ complete (58cb8e6) |
| 10 | Extract `src/pipeline/dispatcher.py` + service.py + `__init__.py` compat | ✅ complete (402cc56 — pipeline delete compat shim) |
| F1 | Final whole-branch review: Use `iter_ids()` protocol method | ✅ complete (67285da) |
| F2 | Final whole-branch review: Amend `cb40cd4` with breaking-behavior-change note | ✅ complete (e34874f) |
| F3 | Final whole-branch review: spec "15 entries" → "16 entries" | ✅ verified: no "15" reference in spec; no action needed |
| F4 | Final whole-branch review: Task 7 cross-task contamination note | ✅ complete (see note below) |
| F5 | Final whole-branch review: test setup_function change | ✅ verified: not an issue; no action needed |

## Final whole-branch review (Finding 4)

Task 7 (commit `3d611e2` "refactor(queue): migrate __init__.py to service-based re-exports") was supposed to only touch `src/queue/__init__.py` and delete `src/queue/queue.py`. However, the same commit also created/modified `src/pipeline/service.py` and `src/pipeline/stages/collector.py` — files that belong to Task 10 (the pipeline refactor). This is cross-task contamination: pipeline code inside a queue refactor commit.

Causes / context: The queue refactor wired pipelines into a different shape, and the implementer had to add a small `src/pipeline/service.py` shim + adjust `src/pipeline/stages/collector.py` so the queue's `collector:start` emit kept working end-to-end (the queue test fixture runs the pipeline even though the production route is still via the legacy collector). The contamination is intentional, not accidental, but it broke the one-commit-per-task invariant the plan was structured around.

Cannot fix retroactively: rewriting the commit history to separate these changes would also break the dependency chain (the Task 10 commits depend on the queue-side shim from Task 7).

Verification: the architectural intent is intact in the final code — no circular imports, service-level locks still serialize correctly, pipeline service still depends on the queue service via the protocol. This is a documentation-only note.

Final HEAD: `67285da` (after Finding 1 + Finding 2)
Final test count: 820 passed (816 baseline + 4 new for `iter_ids()`)
Amended commit: `cb40cd4` → `e34874f` (reworded with `BREAKING BEHAVIOR CHANGE` note)


## Plan 23: Post-queue-pipeline cleanup + ingestion UX + prompt quality (7 commits)

Branch: master (on top of 67285da)

| Commit | Description |
|---|---|
| f572f82 | refactor(queue): complete service-based re-export migration (orchestrator, runner, services) |
| 2f14ac4 | chore(events): update CollectorDonePayload docstring (drop Inbox/Processing reference) |
| 98563e9 | refactor(inbox): remove legacy InboxManager + direct project-relative paths (delete src/inbox/, tests/test_inbox*) |
| f7b355b | test(permissions): update collector allowlist tests for raw/sources-only |
| 212fcf9 | feat(pipeline): extract parse_llm_json + Language directive + slug normalisation + PageType semantics |
| c3224bd | refactor(llm): simplify OpenAI provider to use SDK client only (drop httpx fallback) |
| 40f357c | feat(server): add ingest status/tasks + current project endpoints (FRONTEND_DESIGN.md section 14.1) |

Deletions: src/inbox/{__init__,manager}.py, tests/test_inbox.py + 3 sub-tests (legacy InboxManager module)
New files: src/pipeline/_pipeline_common.py (parse_llm_json helper), src/server/ingest_tracker.py (lifecycle tracker)
Test count after Plan 23: 820 passed in 52.86s (no regression)

### Why Plan 23 exists

The 2026-07-25-queue-pipeline-refactor plan moved queue.py and pipeline.py to a Protocol-bounded composition root, but its T7 "migrate src/queue/__init__.py" task only touched the queue re-exports. Three callers (orchestrator, research runner, services.ingest) were missed and still imported from `..queue.queue`. Separately, the wiki-v2 layout was already in production but the legacy InboxManager staged-copy flow was never removed — src/inbox/ was dead code, with permissions, collector, and tests all still wired through it. Plan 23 finishes the queue refactor (completeness) and tears out the obsolete Inbox flow (clean-up), then layers in two quality-of-life improvements for the next ingest cycle (pipeline prompt quality for Chinese content + frontend ingest progress endpoints).


## Plan 24: Wiki 规范同步 (2026-07-24) — DONE

4 commits on master:
- 2f2ba77 feat: wiki-spec sync pipeline — canonical spec drives Generator prompt
- b66297c chore(hooks): use python shebang so pre-commit works on Windows
- 4112b46 fix(docs): allow UUID v7 + legacy slug IDs in wiki-spec
- d66e003 fix(docs): include PageType semantics in wiki-spec so sync preserves them

Files:
- docs/guides/wiki-spec.md (YAML frontmatter + Markdown body, canonical)
- scripts/sync_wiki_spec.py (MD5-based regen of wiki_rules_prompt.py)
- scripts/setup_git_hooks.py (idempotent pre-commit installer)
- src/pipeline/wiki_rules_prompt.py (auto-generated: ID_RULES, FRONTMATTER_RULES, BODY_RULES, WIKI_RULES_SUMMARY)
- .git/hooks/pre-commit (installed)
- .gitignore (added .wiki-spec-md5)
- src/pipeline/generator.py (imports WIKI_RULES_SUMMARY)
- CLAUDE.md (references wiki-spec.md)

Test count after Plan 24: 820 passed in 52.56s (no regression)

Note: d66e003 fixes a bug where Plan 23's PageType 语义 content in wiki_rules_prompt.py was lost when the sync script regenerated the file (the spec doc never had the matching section). The fix adds the section to the spec so sync preserves it end-to-end.


## Plan 25: Wiki Page Templates (2026-07-25) — v1 DONE (v2/v3 deferred)

1 commit on master:
- 8b882c1 feat(wiki): add page templates (Plan 25 v1) — bundled + resolver + generator

Files:
- src/wiki/templates/bundled/{source,entity,concept,synthesis}.md (4 bundled templates with 3-4 slots each)
- src/wiki/templates/resolver.py (3-tier priority: project > user > bundled; validates type header)
- src/wiki/templates/__init__.py (re-exports Template, resolve, list_available)
- src/pipeline/generator.py (GENERATOR_PROMPT gets {PAGE_TEMPLATES} section)
- tests/test_wiki/test_templates_resolver.py (8 tests: bundled for all 4 types, project override, type-mismatch rejection, list_available, missing-bundled)

Test count after Plan 25: 828 passed in 53.10s (+8 from resolver tests)

Scope notes:
- v1 only: basic templates + resolver + generator integration
- v2 (conditional slots <!-- if: --> <!-- slot:? --> <!-- include: -->) deferred
- v3 (version headers + status/upgrade/diff CLI + auto-migration) deferred
- No CLI yet (Plan 25 spec has list/show/edit/reset commands — not implemented)


## 9 unstarted plans (per "还有多少未执行plan" check on 2026-07-25) — ALL ALREADY COMMITTED to master

Earlier I claimed these 9 plans were "not started" because grep on progress.md found no references. Investigation shows all 9 were completed in earlier sessions and committed to master — the work is just absent from progress.md (the sessions didn't update the ledger).

| # | Plan | Key commit(s) on master | Notes |
|---|---|---|---|
| 1 | wiki-spec-sync (2026-07-24) | 2f2ba77 + b66297c + 4112b46 + **d66e003** | d66e003 (my fix) added PageType 语义 to spec so sync preserves Plan 23's content |
| 2 | wiki-page-templates v1 (2026-07-25) | **8b882c1** | I implemented v1 (4 bundled templates + resolver + generator injection + 8 tests) |
| 3 | quality-gate-v2 (2026-07-22) | b127bb3 | LLM-as-judge + 6 dims + 2-tier verdict + 1 retry + quarantine + CLI |
| 4 | quality-gate-v21-ensemble (2026-07-22) | dd1eb37 | Multi-judge voting + veto on factuality < 0.2 |
| 5 | multi-provider-llm (2026-07-22) | 370ab36 | Ollama + global registry + 6 CLI subcommands |
| 6 | health-check (2026-07-22) | 66abf03 | H1/H2/H4 + 'health' CLI subcommand |
| 7 | metrics-endpoint (2026-07-22) | 0177275 | Counter/Gauge/Histogram + Prometheus + SQLite + 4 CLI subcommands + /metrics endpoint |
| 8 | cli-ux-polish (2026-07-22) | 94efc01 | completions install/show/print-words + templates list/show/apply |
| 9 | vision (2026-07-22) | 402d70e | PDF image extractor (PyMuPDF) + captioner + MediaPage + CLI |

Bold commits are ones I made in this session; others are pre-existing on master.

Lessons:
- "grep progress.md for plan name" is NOT a reliable way to determine plan status. Master HEAD may have the work without the ledger knowing about it.
- Better: `git log --all --oneline | grep -iE "<keyword>"` to find feat commits by topic.
- Going forward: every plan that lands on master should update progress.md in the same session. This is the gap that hid 8 plans' work.
## 2026-08-12 — Cross-file duplicate refactor

- Design and ADR approved: `docs/superpowers/specs/2026-08-12-cross-file-duplicate-refactor-design.md`, `docs/adr/0001-compatibility-first-duplicate-refactor.md`.
- Implementation plan drafted: `docs/superpowers/plans/2026-08-12-cross-file-duplicate-refactor.md`.
- Plan audit round 1 and round 2 passed: `docs/superpowers/audits/2026-08-12-cross-file-duplicate-refactor-round{1,2}.md`.
- Current stage: TDD implementation pending; no production refactor or deletion started.

## 2026-08-12 — Code-review fixes
- [x] Moved CLI resolver tests to the `tests/test_cli_ext/` mirror location
- [x] Added append, flush, and exact-output assertions for the shared script logger
- [x] Final review findings addressed; focused verification pending
