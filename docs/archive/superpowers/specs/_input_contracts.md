# ruflo-kb Spec Input Contract Map

This file maps inter-spec dependencies and MVP/Deferred partitioning. Each spec should embed its Input Contract + MVP/Polish/Deferred section referencing this map.

## Phase 0 — Shared Infrastructure (NEW)

All specs reference `src/shared/` (extracted during implementation, not a separate spec):

- `src/shared/types.py` — ReviewItem, EventName, KnowledgeTask, WikiPage, ProjectSettings, Judgment, ResearchState (single source of truth)
- `src/shared/errors.py` — ProjectError, WikiError, LLMError + subclasses
- `src/shared/test_helpers.py` — ScriptedLLMProvider, temp_project fixture, temp_config_dir fixture
- `src/shared/event_bus_dual.py` — on_project / on_global / emit(project_id=...)
- `src/shared/conventions.py` — naming + dataclass conventions
- `src/shared/file_utils.py` — safe_write / atomic_write / path_within_project

## Phase 1 — Foundations (parallel, 4 specs)

### 1.1 Project multi-instancing (P0 — MVP)

**Provides:**
- `ProjectContext` (all other specs)
- `ProjectSettings` (all other specs)
- `GlobalRegistry` (registry.py) — global project list
- `EventBus` with on_project / on_global dual subscription

**Consumes:** `src/shared/`

**MVP scope:**
- UUID identity + project.json
- registry.json + last_project.json
- 4-step resolve chain (--project → CWD → last_project → error)
- Per-project mutex (async + sync wrapper)
- Auto-discovery on first run
- CLI: `project {list,info,current,select,init,import,forget,rename,discover}`

**Polish (v2.0.1):**
- Per-project user permissions
- Undo/redo for project operations
- Project templates

**Deferred:**
- Remote registry sync
- CLI shell completion for project names (handled in CLI/UX polish)

### 1.2 Schemas v3 (P0 — MVP)

**Provides:**
- `Migration` base class (forward-compat + reversible)
- `SchemaRegistry` (multiple schema types)
- `BackupManager` (timestamped backups)
- `ForwardCompatModel` (extra="allow")

**Consumes:** `src/shared/`

**MVP scope:**
- Migration base class with up()/down()/preview()
- Wiki page schema registry
- Frontmatter loading with extra="allow"
- v2.0 → v2.1 migration (for Wiki Relations spec)
- CLI: `schema {list,diff,upgrade,downgrade,backup}`

**Polish (v2.0.1):**
- Multi-schema transactional migrations
- Auto-upgrade on read

**Deferred:**
- Lazy migration on read
- Remote schema registry

### 1.3 AtomicContext + BudgetedLLM (P0 — MVP)

**Provides:**
- `AtomicContext` context manager (atomic multi-step commits)
- `BudgetedLLM` context manager (token budget chunking)
- `safe_write()` hook (respects AtomicContext)

**Consumes:** `src/shared/`

**MVP scope:**
- AtomicContext with nested semantics
- safe_write hook + flush_pending_writes
- BudgetedLLM with paragraph chunking
- 0.5 token/char conservative estimator
- CLI: `atomic status / budget estimate / budget check`

**Polish (v2.0.1):**
- Per-thread / per-async-task suspension
- Streaming output aggregation across chunks

**Deferred:**
- tiktoken / model-specific tokenizers
- Multi-process coordination

### 1.4 Health Check (P1 — polish but small enough for MVP)

**Provides:**
- `HealthCheckRunner` + `Check` base class
- 5 checks: H1 file existence / H2 break-links / H3 density / H4 ID format / H5 tag namespace
- `HealthReport` JSON

**Consumes:** Wiki v2.0 (frontmatter loaders), Wiki Fields (ID format)

**MVP scope:**
- 3 of 5 checks: H1 (file existence), H2 (break-links), H4 (ID format)
- Text + JSON output
- --strict / --only / --skip flags
- CLI: `health [--only H1,H3] [--skip H5] [--strict] [--json]`

**Polish (v2.0.1):**
- H3 (density) + H5 (tag namespace)
- --fix flag for H5

**Deferred:**
- H6-H11 (DB / done ratio / use_context / workflow_state / verified overdue / violation guard)
- Custom check plugins

## Phase 2 — Core (depends on Phase 1)

### 2.1 Wiki v2.0 (P0 — MVP)

**Provides:**
- `WikiPage` (base structure, extended by Wiki Fields / Relations / Heat)
- `KnowledgeTask` (extended by Quality Gate / Deep Research)
- `EventName` base enum
- `ReviewItem` (extended by Quality Gate with `quality-warn` type)
- Pipeline: Collector → Analyzer → Generator → Librarian

**Consumes:** Project, Schemas v3, AtomicContext, Multi-Provider, src/shared/

**MVP scope:**
- 4 page types: source / entity / concept / synthesis (merge query+comparison into source sections)
- 2-step CoT (Analyzer → Generator)
- A1: cascade_delete
- A2: folder-aware ingest
- A3: review_items (basic 4 types)
- A4: lint (5 issue types, NO semantic LLM)
- A5: schema routing validation
- A6: ZIP export/import
- A7: dedup (basic, no --auto)
- Stub pages (auto-created on broken wikilink)
- Indexer + log.md

**Polish (v2.0.1):**
- A4: lint semantic (LLM-driven)
- A7: dedup --auto flag
- overview.md auto-regenerate
- _archive/ directory

**Deferred:**
- wiki/_stubs/ automatic materialization (covered in Wiki v2.1 polish)
- Templates/ user customization
- query / comparison as separate page types

### 2.2 Multi-Provider LLM (P0 — MVP)

**Provides:**
- `OllamaProvider` + `OpenAICompatibleProvider`
- `ProviderRegistry` (global config)
- `NonStreamingToStreamingAdapter`
- `LLMCostTracker`

**Consumes:** Project, src/shared/

**MVP scope:**
- Ollama provider only (single new provider)
- Global registry at `~/.config/ruflo-kb/llm-providers.json`
- Per-project override via settings.llm.provider_registry_name
- Health check at startup + manual `llm-providers test`
- CLI: `llm-providers {list,add,remove,test,show,set-default}`

**Polish (v2.0.1):**
- OpenAI-compatible generic provider (LM Studio / vLLM)
- Model auto-check + pull hint

**Deferred:**
- Google Gemini / Anthropic Bedrock
- Subprocess CLI providers (Claude Code CLI / Codex CLI)

### 2.3 HTTP API + MCP (P0 — MVP)

**Provides:**
- FastAPI server on 127.0.0.1:19828
- stdio MCP server
- 13 HTTP endpoints + 15 MCP tools (basic set)

**Consumes:** Project, Wiki v2.0, Multi-Provider, Quality Gate, AtomicContext

**MVP scope:**
- 8 core endpoints: health / projects / files / search / ingest / reviews (list+resolve) / chat (RAG only) / schema (read-only)
- 8 core MCP tools: ruflo_kb_status / projects / set_project / files / read_file / search / ingest / reviews
- Auth: localhost-only, no token
- Session CRUD: list / get / delete
- Streaming: NO SSE (v2.0.1)
- Daemon mode: simple fork + pidfile

**Polish (v2.0.1):**
- SSE streaming for /chat
- Session cancellation endpoint
- --metrics flag for daemon

**Deferred:**
- LAN access (allow_lan flag)
- Token-based auth
- SSE for /research, /lint, /dedup

## Phase 3 — Quality + Wiki Enhancements (depends on Phase 2)

### 3.1 Quality Gate v2.0 (P0 — MVP)

**Provides:**
- `JudgmentScores` (6 dimensions) + `Judgment` + `BatchJudgmentResult`
- `QualityJudge.judge_batch`
- `QuarantineStore`

**Consumes:** Wiki v2.0, Multi-Provider, AtomicContext, src/shared/

**MVP scope:**
- 6 dimensions: source_type_appropriateness / factuality / completeness / clarity / readability / searchability
- 2-tier verdict: pass / reject (skip warn + hard_reject)
- 1 retry per page (downgrade from spec's 2)
- Basic quarantine (mark + don't write; no archive / retry / discard CLI yet)
- CLI: `quality score / quality config show / quality config set`

**Polish (v2.0.1):**
- 4-tier verdict (add warn + hard_reject)
- 2 retries (configurable)
- Quality-warn review item
- Full quarantine CLI (list/retry/discard)

**Deferred:**
- Quarantine archive retention (30 days)
- Staging draft generation

### 3.2 Wiki Fields v2.2 (P1 — v2.0.1, not MVP)

**Provides:**
- L0-L3 layered field validation
- `FieldsValidator`
- `TagNamespace` validator
- `GradeRouter` (grade A/B/C → processing_depth concept/memory)
- UUID v7 page IDs

**Consumes:** Wiki v2.0, src/shared/

**MVP scope (v2.0.1):**
- 4 fields: id (UUID v7) / grade / processing_depth / is_immutable
- Tag namespace validation (8 prefixes)
- Migration v2.0 → v2.2

**Polish (v2.1):**
- Remaining 4 fields: use_context / maturity / workflow_state
- L3 per-type conditional fields
- Tag audit CLI

**Deferred:**
- Auto-promote memory → concept
- Tag auto-suggestion

### 3.3 Wiki Relations v2.1 (P1 — polish)

**Provides:**
- `Relation` dataclass
- `RelationSync` (bidirectional sync)
- `RelationQuery` (list / backlinks / neighbors / path)
- 16 built-in relation types + user-defined (x- prefix)

**Consumes:** Wiki v2.0, Schemas v3, src/shared/

**MVP scope:**
- Generator emits relations per page
- Bidirectional sync via INVERSE_RELATIONS table
- 16 built-in types (is_part_of / references / causes / etc.)
- User-defined x-* types
- CLI: `relations {list,backlinks,neighbors,path,types,add-type}`

**Polish (v2.2):**
- Relation versioning
- Relation inference from prose

**Deferred:**
- Visual graph UI
- 4-signal relevance scoring (separate spec)

### 3.4 Wiki Heat 5-Pool v2.1 (P1 — polish)

**Provides:**
- `Pool` enum (pool_1..4 / ccd / drift)
- `HeatTracker` (increment / decay)
- `PoolRouter`
- `ZombieDetector`

**Consumes:** Wiki v2.0, Multi-Provider

**MVP scope:**
- heat field (0-100) + decay (-10 per 30 days) + increment (+5 per AI retrieval)
- Zombie detection at heat=0 for 30 days
- CLI: `heat {show,top,cold,decay,zombies,restore,archive}`

**Polish (v2.2):**
- 5-Pool routing (priority * similarity scoring)
- Staging draft generation for zombies
- Heat propagation via relations

**Deferred:**
- Pool inheritance
- Custom decay policies

### 3.5 Wiki v2.1 polish (P1 — split into v2.0.1)

**Provides:**
- Stub auto-materialization worker
- Dedup --auto flag
- Lint semantic cache

**Consumes:** Wiki v2.0, Quality Gate

**MVP scope:**
- All 3 features bundled
- CLI: `stubs / dedup --auto / lint --cache-ttl`

**Polish (v2.0.2):**
- Stub materialization retry budget
- Dedup archive retention
- Lint cache invalidation triggers

**Deferred:**
- Stubs UI

### 3.6 Vision / Image Input (P2 — v2.1)

**Provides:**
- Image extractor (PDF → images)
- Vision captioner (LLM)
- `MediaPage` wiki page type
- Image-aware search

**Consumes:** Wiki v2.0, Multi-Provider

**MVP scope:**
- PDF only (pdfplumber + Pillow)
- GPT-4o-mini / Claude vision models
- 20 images/task max, 5 concurrent
- `wiki/media/` storage + .md caption pages
- Image links embedded in source page

**Polish (v2.1):**
- DOCX / PPTX / EPUB extractors
- Image rerank in search results

**Deferred:**
- Video frame extraction
- OCR fallback
- Image generation

## Phase 4 — Advanced (depends on Phase 3)

### 4.1 Chat Agent (P0 — MVP for HTTP, polish for full)

**Provides:**
- `AgentRuntime` + `run_agent_loop`
- 14 builtin tools (MVP: 5)
- CLI REPL (MVP)
- SSE streaming (polish)

**Consumes:** Wiki v2.0, Project, Multi-Provider, AtomicContext

**MVP scope (HTTP-only):**
- 5 tools only: wiki.search / wiki.read_page / source.search / graph.search / web.search
- HTTP /chat endpoint (non-streaming JSON response)
- 8 iterations max
- No SSE, no REPL, no skills, no workspace, no shell
- cost cap deferred

**Polish (v2.0.1):**
- CLI REPL (`chat`)
- SSE streaming
- 9 remaining tools (wiki.write_page / workspace.* / skills.*)
- Session persistence

**Polish (v2.1):**
- shell.exec with approval
- deep_research.run + llm.generate
- Session persistence to `.llm-wiki/chats/`
- Cost cap (0.5 USD/session)

**Deferred:**
- Skills marketplace
- Voice I/O
- Sub-agent delegation

### 4.2 Web Search + Deep Research (P0 — MVP for Tavily only)

**Provides:**
- 6 web search providers (MVP: 1)
- `ResearchRunner`
- `optimizeResearchTopic` (LLM)
- `synthesizeFindings` (LLM)
- `ResearchState` persistence

**Consumes:** Wiki v2.0, Multi-Provider, Quality Gate (for auto-ingest)

**MVP scope:**
- Tavily only
- 1 concurrent task × 3 concurrent queries
- No state persistence (in-memory)
- Auto-ingest: disabled by default (`--no-ingest` is default; `--ingest` flag opts in)
- CLI: `research {run,list,show}`

**Polish (v2.0.1):**
- SearXNG
- State persistence to `.index/research/`
- Review items integration (`--from-review-id`)
- Auto-ingest top 5 (default)

**Polish (v2.1):**
- 4 more providers (Firecrawl / Brave / SerpApi / Ollama Web Search)
- 3 × 5 concurrency
- Cancellation

**Deferred:**
- Result caching
- Cross-source synthesis templates

### 4.3 Quality Gate v2.1 Ensemble (P2 — v2.1 experiment)

**Provides:**
- Multi-judge ensemble voting
- Per-dimension mean + veto logic

**Consumes:** Quality Gate v2.0, Multi-Provider

**MVP scope:**
- Default 2 judges (primary + 1 configured)
- Mean aggregation
- Veto on factuality < 0.2

**Polish (v2.1):**
- Configurable judge count (2-3)
- Per-dimension judge specialization

**Deferred:**
- Ensemble training via user feedback
- Model disagreement visualization

### 4.4 Metrics + CLI/UX polish (P1 — v2.0.1)

**Provides:**
- Prometheus `/metrics` endpoint
- Shell completion via argcomplete
- 3 project templates (research / novels / business)

**Consumes:** Project, all CLI specs

**MVP scope (v2.0.1):**
- Metrics: 5 core metrics (ingest_total / chat_total / llm_cost_usd_total / active_tasks / uptime_seconds)
- CLI completion: bash + zsh
- 1 template only (research)

**Polish (v2.1):**
- Full metrics suite
- Fish shell completion
- 2 more templates (novels / business)

**Deferred:**
- OpenTelemetry / OTLP
- Template marketplace
- Custom completion caching

---

## MVP Cutoff Summary (Week 6)

**MVP = Phase 0 + Phase 1 + Phase 2 + Phase 3 partial** = 11 specs:

1. src/shared/ (infrastructure)
2. Project multi-instancing
3. Schemas v3
4. AtomicContext + BudgetedLLM
5. Wiki v2.0 (4 page types, basic features)
6. Multi-Provider LLM (Ollama only)
7. HTTP API + MCP (8 endpoints, no SSE)
8. Quality Gate v2.0 (2-tier verdict, 1 retry, basic quarantine)
9. Health Check (3 of 5 checks)
10. Chat Agent (5 tools, HTTP-only)
11. Web Search DR (Tavily only)

**Polish Cutoff (Week 12)** = adds:
- Wiki v2.1 polish (3 features)
- Wiki Fields v2.2 (4 of 8 fields)
- Metrics (5 core metrics)
- CLI completion (bash + zsh)
- 1 project template
- Remaining Health Checks (H3 + H5)
- Quality Gate v2.0.1 (4-tier verdict, 2 retries)

**v2.1 Cutoff (Week 20)** = adds:
- Wiki Relations v2.1
- Wiki Heat 5-Pool
- Vision (PDF)
- Quality Gate v2.1 Ensemble
- Chat Agent: SSE + REPL + 9 more tools + sessions + cost cap
- Web Search DR: 5 more providers + state persistence + auto-ingest + review integration
- Multi-Provider: OpenAI-compatible
- Metrics: full suite
- 2 more templates

**v2.2+ Cutoff (Week 30)** = experiments:
- Cascade soft-delete
- Skill marketplace
- 4-signal relevance scoring
- Graph relevance + Louvain
- Auth + multi-user
- Cross-project search