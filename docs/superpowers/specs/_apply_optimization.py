#!/usr/bin/env python3
"""Batch-update all 18 ruflo-kb specs to add Input Contract + MVP/Polish/Deferred sections.

Reads docs/superpowers/specs/_input_contracts.md for the cross-spec dependency map
and inserts two new sections into each spec:
1. "## Input Contract" — after "## Non-goals"
2. "## MVP Scope / Polish / Deferred" — before "## Implementation order"
"""

import re
from pathlib import Path

SPECS_DIR = Path("docs/superpowers/specs")

# Per-spec content for Input Contract + MVP/Polish/Deferred
SPECS = {
    "2026-07-21-wiki-semantic-structure-design.md": {
        "provides": [
            "`WikiPage` (base structure; extended by Wiki Fields / Relations / Heat)",
            "`KnowledgeTask` (extended by Quality Gate / Deep Research)",
            "`EventName` base enum (extended by Quality Gate / Chat Agent / Deep Research)",
            "`ReviewItem` (extended by Quality Gate with `quality-warn` type)",
            "Pipeline: Collector → Analyzer → Generator → Librarian",
            "CascadeDelete result type",
            "DedupResult + DuplicateGroup + MergeRequest types",
        ],
        "consumes": [
            "**Project multi-instancing (REQUIRED)**: `ProjectContext`, `ProjectSettings`, `EventBus`",
            "**Schemas v3 (REQUIRED)**: `Migration` base class for v1→v2 migration",
            "**AtomicContext (REQUIRED)**: for cascade_delete atomic multi-step commits",
            "**Multi-Provider LLM (REQUIRED)**: `LLMProvider.complete()` / `complete_stream()`",
            "**src/shared/ (REQUIRED)**: `EventName`, `ReviewItem`, `KnowledgeTask` definitions",
        ],
        "phase": "Phase 2 — Core",
        "priority": "P0 — MVP",
        "mvp_scope": """- 4 page types: source / entity / concept / synthesis (query+comparison merged into source subsections)
- 2-step CoT (Analyzer → Generator)
- A1: cascade_delete
- A2: folder-aware ingest
- A3: review_items (4 basic types)
- A4: lint (5 issue types, NO semantic LLM)
- A5: schema routing validation
- A6: ZIP export/import
- A7: dedup (basic, no --auto)
- Stub pages (auto-created on broken wikilink)
- Indexer + log.md""",
        "polish": """- A4: lint semantic (LLM-driven)
- A7: dedup --auto flag
- overview.md auto-regenerate
- _archive/ directory""",
        "deferred": """- wiki/_stubs/ automatic materialization (in Wiki v2.1 polish)
- Templates/ user customization
- query / comparison as separate page types""",
    },
    "2026-07-21-project-multi-instancing-design.md": {
        "provides": [
            "`ProjectContext` (consumed by ALL other specs)",
            "`ProjectSettings` (consumed by ALL other specs)",
            "`GlobalRegistry` — global project list",
            "`EventBus` with on_project / on_global dual subscription",
            "`with_project_lock` async + `sync_with_project_lock`",
        ],
        "consumes": [
            "**src/shared/ (REQUIRED)**: `PlatformdirsPath` helper for OS-config-dir",
        ],
        "phase": "Phase 1 — Foundations (parallel)",
        "priority": "P0 — MVP",
        "mvp_scope": """- UUID identity + project.json
- registry.json + last_project.json
- 4-step resolve chain (--project → CWD → last_project → error)
- Per-project mutex (async + sync wrapper)
- Auto-discovery on first run
- CLI: `project {list,info,current,select,init,import,forget,rename,discover}`""",
        "polish": """- Per-project user permissions
- Undo/redo for project operations
- Project templates (3 bundled templates)""",
        "deferred": """- Remote registry sync
- CLI shell completion for project names (handled in CLI/UX polish)""",
    },
    "2026-07-21-http-api-mcp-design.md": {
        "provides": [
            "FastAPI server on 127.0.0.1:19828",
            "stdio MCP server (`python -m src.cli mcp`)",
            "Daemon mode with pidfile management",
        ],
        "consumes": [
            "**Project multi-instancing (REQUIRED)**: `ProjectContext`, `ProjectSettings`",
            "**Wiki v2.0 (REQUIRED)**: search / files / ingest / reviews / chat endpoints",
            "**Multi-Provider LLM (REQUIRED)**: LLM provider resolution per project",
            "**Quality Gate (REQUIRED for /quality endpoint)**: `Judgment`, scoring",
            "**AtomicContext (OPTIONAL)**: for atomic multi-step HTTP handlers",
        ],
        "phase": "Phase 2 — Core",
        "priority": "P0 — MVP",
        "mvp_scope": """- 8 core endpoints: health / projects / files / search / ingest / reviews / chat (RAG) / schema (read-only)
- 8 core MCP tools: status / projects / set_project / files / read_file / search / ingest / reviews
- Auth: localhost-only, no token
- Session CRUD: list / get / delete
- No SSE (deferred)
- Daemon mode: simple fork + pidfile""",
        "polish": """- SSE streaming for /chat
- Session cancellation endpoint
- --metrics flag for daemon
- Remaining 5 endpoints (graph / rescan / cascade-delete / lint / dedup)""",
        "deferred": """- LAN access (allow_lan flag)
- Token-based auth
- SSE for /research, /lint, /dedup""",
    },
    "2026-07-21-quality-gate-v2-design.md": {
        "provides": [
            "`JudgmentScores` (6 dimensions)",
            "`Judgment` + `BatchJudgmentResult`",
            "`QualityJudge.judge_batch`",
            "`QuarantineStore`",
        ],
        "consumes": [
            "**Wiki v2.0 (REQUIRED)**: `WikiPage` (judged object)",
            "**Multi-Provider LLM (REQUIRED)**: `LLMProvider.complete()`",
            "**AtomicContext (REQUIRED)**: for judge batch atomic commit",
            "**src/shared/**: `ReviewItem` extended with `quality-warn` type",
        ],
        "phase": "Phase 3 — Quality",
        "priority": "P0 — MVP",
        "mvp_scope": """- 6 dimensions: source_type_appropriateness / factuality / completeness / clarity / readability / searchability
- 2-tier verdict: pass / reject (warn + hard_reject deferred)
- 1 retry per page (configurable to 2)
- Basic quarantine (mark + don't write; no archive / retry / discard CLI yet)
- CLI: `quality score / quality config show / quality config set`""",
        "polish": """- 4-tier verdict (add warn + hard_reject)
- 2 retries (default)
- Quality-warn review item
- Full quarantine CLI (list/retry/discard)""",
        "deferred": """- Quarantine archive retention (30 days)
- Staging draft generation
- Cross-page consistency check""",
    },
    "2026-07-21-chat-agent-design.md": {
        "provides": [
            "`AgentRuntime` + `run_agent_loop`",
            "`AgentLoopAction` JSON schema",
            "14 builtin tools (MVP: 5)",
            "`ChatSession` persistence (deferred)",
            "SSE streaming (deferred)",
        ],
        "consumes": [
            "**Project multi-instancing (REQUIRED)**: per-project `ProjectContext`",
            "**Wiki v2.0 (REQUIRED)**: wiki.search / wiki.read_page tools",
            "**Multi-Provider LLM (REQUIRED)**: streaming + completion",
            "**AtomicContext (OPTIONAL)**: for atomic chat session commits",
            "**src/shared/**: `EventName` extended with `agent:*` events",
        ],
        "phase": "Phase 4 — Advanced",
        "priority": "P0 — MVP for HTTP endpoint only",
        "mvp_scope": """- 5 tools only: wiki.search / wiki.read_page / source.search / graph.search / web.search
- HTTP /chat endpoint (non-streaming JSON response)
- 8 iterations max (fast=4 / standard=8 / deep=12)
- No SSE, no REPL, no skills, no workspace, no shell
- No cost cap""",
        "polish": """- CLI REPL (`chat`)
- SSE streaming for HTTP
- 9 remaining tools (wiki.write_page / workspace.* / skills.* / shell.exec / deep_research.run / llm.generate)
- Session persistence to `.llm-wiki/chats/`
- Cost cap (0.5 USD/session)""",
        "deferred": """- Skills marketplace
- Voice I/O
- Sub-agent delegation
- Multi-provider per-task routing""",
    },
    "2026-07-21-multi-provider-llm-design.md": {
        "provides": [
            "`OllamaProvider`",
            "`OpenAICompatibleProvider`",
            "`ProviderRegistry` (global config)",
            "`NonStreamingToStreamingAdapter`",
            "`LLMCostTracker`",
            "`OllamaHealthChecker`",
        ],
        "consumes": [
            "**Project multi-instancing (REQUIRED)**: per-project provider override",
            "**src/shared/**: `LLMProvider` base interface",
        ],
        "phase": "Phase 2 — Core",
        "priority": "P0 — MVP",
        "mvp_scope": """- Ollama provider only
- Global registry at `~/.config/ruflo-kb/llm-providers.json`
- Per-project override via settings.llm.provider_registry_name
- Health check at startup + manual `llm-providers test`
- CLI: `llm-providers {list,add,remove,test,show,set-default}`""",
        "polish": """- OpenAI-compatible generic provider (LM Studio / vLLM)
- Model auto-check + pull hint
- Streaming adapter (use for future non-streaming providers)""",
        "deferred": """- Google Gemini / Anthropic Bedrock / Vertex AI
- Subprocess CLI providers (Claude Code CLI / Codex CLI)
- Vision / image input""",
    },
    "2026-07-21-web-search-deep-research-design.md": {
        "provides": [
            "6 web search providers (MVP: 1 Tavily)",
            "`ResearchRunner`",
            "`optimizeResearchTopic` (LLM)",
            "`synthesizeFindings` (LLM)",
            "`ResearchState` persistence (deferred)",
            "`TopicOptimizer`",
        ],
        "consumes": [
            "**Wiki v2.0 (REQUIRED)**: writes `wiki/synthesis/<slug>.md`",
            "**Multi-Provider LLM (REQUIRED)**: LLM calls for optimizer + synthesizer",
            "**Quality Gate (REQUIRED for auto-ingest)**: judges synthesized pages",
            "**src/shared/**: `ReviewItem.search_queries` consumed via `--from-review-id`",
        ],
        "phase": "Phase 4 — Advanced",
        "priority": "P0 — MVP (Tavily only)",
        "mvp_scope": """- Tavily only
- 1 concurrent task × 3 concurrent queries
- No state persistence (in-memory)
- Auto-ingest: disabled by default (`--no-ingest` default)
- CLI: `research {run,list,show}`""",
        "polish": """- SearXNG
- State persistence to `.index/research/`
- Review items integration (`--from-review-id`)
- Auto-ingest top 5 (default)
- HTTP + MCP endpoints""",
        "deferred": """- 4 more providers (Firecrawl / Brave / SerpApi / Ollama Web Search)
- Result caching
- Cross-source synthesis templates
- Scheduling / cron recurring research""",
    },
    "2026-07-21-wiki-v21-polish-design.md": {
        "provides": [
            "Stub auto-materialization worker (background)",
            "Dedup `--auto` flag (high confidence auto-merge)",
            "Lint semantic cache TTL",
            "`StubMaterializerWorker`",
            "`DedupHistoryStore` (30-day archive)",
        ],
        "consumes": [
            "**Wiki v2.0 (REQUIRED)**: stub pages + dedup foundation",
            "**Quality Gate (REQUIRED)**: lint semantic uses Judge LLM",
            "**AtomicContext (REQUIRED)**: stub materialization + dedup auto atomic commits",
        ],
        "phase": "Phase 3 — Wiki Polish",
        "priority": "P1 — v2.0.1",
        "mvp_scope": """- All 3 features bundled
- CLI: `stubs / dedup --auto / lint --cache-ttl`""",
        "polish": """- Stub materialization retry budget
- Dedup archive retention (default 30 days)
- Lint cache invalidation triggers (index_version change)""",
        "deferred": """- Stubs UI (click to materialize)
- Dedup --auto for medium confidence
- Lint cache cross-project sharing""",
    },
    "2026-07-21-quality-gate-v21-ensemble-design.md": {
        "provides": [
            "Multi-judge ensemble voting",
            "`EnsembleJudge`",
            "`JudgeVote` + `AggregatedJudgment`",
            "Per-dimension mean + veto logic",
        ],
        "consumes": [
            "**Quality Gate v2.0 (REQUIRED)**: `JudgmentScores`, `Judgment`",
            "**Multi-Provider LLM (REQUIRED)**: multiple provider registry entries",
        ],
        "phase": "Phase 4 — Advanced",
        "priority": "P2 — v2.1 experiment",
        "mvp_scope": """- Default 2 judges (primary + 1 configured)
- Mean aggregation
- Veto on factuality < 0.2""",
        "polish": """- Configurable judge count (2-3)
- Per-dimension judge specialization
- Judge A/B testing framework""",
        "deferred": """- Ensemble training via user feedback
- Model disagreement visualization UI
- Cross-project judge sharing""",
    },
    "2026-07-21-cli-ux-polish-design.md": {
        "provides": [
            "Shell completion via `argcomplete` (bash + zsh)",
            "3 project templates (research / novels / business)",
            "`TemplateLoader`",
        ],
        "consumes": [
            "**Project multi-instancing (REQUIRED)**: project list for completion",
            "**src/shared/**: completion caching",
        ],
        "phase": "Phase 4 — Polish",
        "priority": "P1 — v2.0.1",
        "mvp_scope": """- CLI completion: bash + zsh
- 1 template only (research)
- 1 hardcoded project name autocompletion""",
        "polish": """- Fish shell completion
- 2 more templates (novels / business)
- User-defined custom templates at `~/.config/ruflo-kb/templates/`""",
        "deferred": """- Template marketplace
- Per-template custom commands or hooks
- Custom completion caching""",
    },
    "2026-07-21-vision-image-input-design.md": {
        "provides": [
            "`ImageExtractor` (PDF → images)",
            "`VisionCaptioner` (LLM)",
            "`MediaPage` wiki page type",
            "Image-aware search enhancement",
        ],
        "consumes": [
            "**Wiki v2.0 (REQUIRED)**: writes `wiki/media/<id>.md` + image links in source page",
            "**Multi-Provider LLM (REQUIRED)**: vision-capable model (gpt-4o-mini / claude-haiku-4-5)",
        ],
        "phase": "Phase 3 — Media",
        "priority": "P2 — v2.1",
        "mvp_scope": """- PDF only (pdfplumber + Pillow)
- GPT-4o-mini / Claude vision models
- 20 images/task max, 5 concurrent
- `wiki/media/` storage + .md caption pages
- Image links embedded in source page""",
        "polish": """- DOCX / PPTX / EPUB extractors
- Image rerank in search results
- Per-image diff tracking""",
        "deferred": """- Video frame extraction
- OCR fallback
- Image generation
- Image embedding (CLIP)""",
    },
    "2026-07-21-wiki-relations-design.md": {
        "provides": [
            "`Relation` dataclass (target / type / weight / context)",
            "`RelationSync` (bidirectional)",
            "`RelationQuery` (list / backlinks / neighbors / path)",
            "16 built-in relation types",
            "User-defined x-* types",
        ],
        "consumes": [
            "**Wiki v2.0 (REQUIRED)**: `WikiPage` extended with `relations` field",
            "**Schemas v3 (REQUIRED)**: v2.0 → v2.1 migration for relations field",
            "**src/shared/**: bidirectional sync primitives",
        ],
        "phase": "Phase 3 — Wiki Polish",
        "priority": "P1 — v2.1",
        "mvp_scope": """- Generator emits relations per page
- Bidirectional sync via INVERSE_RELATIONS table
- 16 built-in types (is_part_of / references / causes / etc.)
- User-defined x-* types
- CLI: `relations {list,backlinks,neighbors,path,types,add-type}`""",
        "polish": """- Relation versioning
- Relation inference from prose""",
        "deferred": """- Visual graph UI
- 4-signal relevance scoring (separate spec)
- Graph algorithms (Louvain / PageRank)
- Cross-project relations""",
    },
    "2026-07-21-schemas-v3-design.md": {
        "provides": [
            "`Migration` base class (forward-compat + reversible)",
            "`SchemaRegistry` (multiple schema types)",
            "`BackupManager` (timestamped backups + latest symlink)",
            "`ForwardCompatModel` (extra='allow')",
            "v2.0 → v2.1 migration template",
        ],
        "consumes": [
            "**src/shared/**: error classes (MigrationError)",
        ],
        "phase": "Phase 1 — Foundations (parallel)",
        "priority": "P0 — MVP",
        "mvp_scope": """- Migration base class with up()/down()/preview()
- Wiki page schema registry
- Frontmatter loading with extra='allow'
- v2.0 → v2.1 migration (for Wiki Relations spec)
- CLI: `schema {list,diff,upgrade,downgrade,backup}`""",
        "polish": """- Multi-schema transactional migrations
- Auto-upgrade on read
- Per-schema version registry""",
        "deferred": """- Lazy migration on read
- Remote schema registry
- Custom migration hooks""",
    },
    "2026-07-21-wiki-heat-5pool-design.md": {
        "provides": [
            "`Pool` enum (pool_1..4 / ccd / drift)",
            "`HeatTracker` (increment / decay)",
            "`PoolRouter` (priority * similarity)",
            "`ZombieDetector`",
            "`WikiPage` extended with `pool` + `heat` + `last_used_at`",
        ],
        "consumes": [
            "**Wiki v2.0 (REQUIRED)**: `WikiPage` base structure",
            "**Multi-Provider LLM (OPTIONAL)**: zombie staging draft generation",
        ],
        "phase": "Phase 3 — Wiki Polish",
        "priority": "P1 — v2.1",
        "mvp_scope": """- `heat` field (0-100) + decay (-10 per 30 days) + increment (+5 per AI retrieval)
- Zombie detection at heat=0 for 30 days
- CLI: `heat {show,top,cold,decay,zombies,restore,archive}`""",
        "polish": """- 5-Pool routing (priority * similarity scoring)
- Staging draft generation for zombies
- Heat propagation via relations""",
        "deferred": """- Pool inheritance
- Custom decay policies
- Heat-based page pinning""",
    },
    "2026-07-21-metrics-endpoint-design.md": {
        "provides": [
            "`Counter` + `Gauge` + `Histogram` metric classes",
            "`MetricsRegistry`",
            "`LLMCostTracker` (per-model USD)",
            "`MetricsStore` (SQLite 24h rolling window)",
            "Prometheus text format 0.0.4 serializer",
            "`GET /metrics` endpoint",
        ],
        "consumes": [
            "**src/shared/**: event hooks for instrumentation",
        ],
        "phase": "Phase 4 — Polish",
        "priority": "P1 — v2.0.1",
        "mvp_scope": """- 5 core metrics: ingest_total / chat_total / llm_cost_usd_total / active_tasks / uptime_seconds
- SQLite persistence with 24h rolling window
- `GET /metrics` endpoint
- CLI: `metrics {show,reset,export,cost}`""",
        "polish": """- Full metrics suite (search_total / judge_total / http_requests_total / etc.)
- `--only` / `--skip` filtering""",
        "deferred": """- OpenTelemetry / OTLP export
- Per-project metrics namespace
- Long-term retention (30 days)
- Alerting rules engine""",
    },
    "2026-07-21-atomic-ctx-budgeted-llm-design.md": {
        "provides": [
            "`AtomicContext` context manager (atomic multi-step commits)",
            "`BudgetedLLM` context manager (token budget chunking)",
            "`safe_write()` hook (respects AtomicContext)",
            "0.5 token/char conservative estimator",
        ],
        "consumes": [
            "**src/shared/**: error classes",
        ],
        "phase": "Phase 1 — Foundations (parallel)",
        "priority": "P0 — MVP",
        "mvp_scope": """- AtomicContext with nested semantics
- `safe_write` hook + `flush_pending_writes`
- BudgetedLLM with paragraph chunking
- 0.5 token/char conservative estimator
- CLI: `atomic status / budget estimate / budget check`""",
        "polish": """- Per-thread / per-async-task suspension
- Streaming output aggregation across chunks""",
        "deferred": """- tiktoken / model-specific tokenizers
- Multi-process coordination
- Persistent suspension state across crashes""",
    },
    "2026-07-21-wiki-fields-design.md": {
        "provides": [
            "L0-L3 layered field validation",
            "`FieldsValidator`",
            "`TagNamespace` validator (8 prefixes)",
            "`GradeRouter` (grade A/B/C → processing_depth concept/memory)",
            "UUID v7 page IDs (`card_<13hex>_<8hex>_<slug>`)",
            "`WikiPage` extended with 8 new fields",
        ],
        "consumes": [
            "**Wiki v2.0 (REQUIRED)**: `WikiPage` base structure",
            "**Schemas v3 (REQUIRED)**: v2.0 → v2.2 migration",
            "**Health Check (REQUIRED)**: H4 ID format uses `ID_PATTERN`",
        ],
        "phase": "Phase 3 — Wiki Polish",
        "priority": "P1 — v2.0.1",
        "mvp_scope": """- 4 fields: id (UUID v7) / grade / processing_depth / is_immutable
- Tag namespace validation (8 prefixes)
- Migration v2.0 → v2.2
- CLI: `fields validate / tags validate`""",
        "polish": """- Remaining 4 fields: use_context / maturity / workflow_state
- L3 per-type conditional fields
- Tag audit CLI""",
        "deferred": """- Auto-promote memory → concept
- Tag auto-suggestion
- Per-namespace tag color/icon""",
    },
    "2026-07-21-health-check-design.md": {
        "provides": [
            "`HealthCheckRunner` + `Check` base class",
            "5 checks: H1 / H2 / H3 / H4 / H5",
            "`HealthReport` JSON",
            "`CheckResult` + `CheckIssue`",
        ],
        "consumes": [
            "**Wiki v2.0 (REQUIRED)**: frontmatter loaders",
            "**Wiki Fields (REQUIRED)**: H4 ID format uses `ID_PATTERN`",
            "**src/shared/**: shared check base class",
        ],
        "phase": "Phase 1 — Foundations (parallel)",
        "priority": "P1 — small enough to land in MVP",
        "mvp_scope": """- 3 of 5 checks: H1 (file existence), H2 (break-links), H4 (ID format)
- Text + JSON output
- --strict / --only / --skip flags
- CLI: `health [--only H1,H3] [--skip H5] [--strict] [--json]`""",
        "polish": """- H3 (density) + H5 (tag namespace)
- --fix flag for H5 (auto-suggest tag prefixes)""",
        "deferred": """- H6-H11 (DB / done ratio / use_context / workflow_state / verified overdue / violation guard)
- Custom check plugins
- Per-check timeout
- Integration with CI / pre-commit""",
    },
}


def insert_input_contract(spec_path: Path, content: dict) -> bool:
    """Insert '## Input Contract' section after '## Non-goals' section."""
    text = spec_path.read_text(encoding="utf-8")

    if "## Input Contract" in text:
        return False  # already present

    # Find Non-goals section end
    non_goals_pattern = re.compile(r"## Non-goals\s*\n(.*?)(?=\n## |\Z)", re.DOTALL)
    match = non_goals_pattern.search(text)
    if not match:
        print(f"  WARN: no Non-goals section in {spec_path.name}")
        return False

    non_goals_end = match.end()

    provides_list = "\n".join(f"- {p}" for p in content["provides"])
    consumes_list = "\n".join(f"- {p}" for p in content["consumes"])

    contract_section = f"""

## Input Contract

> Reference: [`_input_contracts.md`](_input_contracts.md) for cross-spec dependency map.

**This spec provides** (consumed by other specs):

{provides_list}

**This spec requires from other specs**:

{consumes_list}

**Phase**: {content['phase']}
**Priority**: {content['priority']}
"""

    new_text = text[:non_goals_end] + contract_section + text[non_goals_end:]
    spec_path.write_text(new_text, encoding="utf-8")
    return True


def insert_mvp_polish_deferred(spec_path: Path, content: dict) -> bool:
    """Insert MVP / Polish / Deferred section before '## Implementation order'."""
    text = spec_path.read_text(encoding="utf-8")

    if "## MVP Scope" in text:
        return False  # already present

    impl_pattern = re.compile(r"## Implementation order")
    match = impl_pattern.search(text)
    if not match:
        print(f"  WARN: no Implementation order in {spec_path.name}")
        return False

    mvp_section = f"""
## MVP Scope / Polish / Deferred

> This section partitions the spec's features into delivery tiers. See [`_input_contracts.md`](_input_contracts.md) for cross-spec context.

### MVP Scope ({content['priority'].split(' — ')[0]})

{content['mvp_scope']}

### Polish (v2.0.1 or later)

{content['polish']}

### Deferred (v2.1+)

{content['deferred']}

"""

    new_text = text[:match.start()] + mvp_section + text[match.start():]
    spec_path.write_text(new_text, encoding="utf-8")
    return True


def main():
    SPECS_DIR.mkdir(exist_ok=True)
    updated = 0
    for fname, content in SPECS.items():
        path = SPECS_DIR / fname
        if not path.exists():
            print(f"  MISSING: {fname}")
            continue
        ic_done = insert_input_contract(path, content)
        mvp_done = insert_mvp_polish_deferred(path, content)
        status = []
        if ic_done: status.append("IC")
        if mvp_done: status.append("MVP")
        if not ic_done and not mvp_done:
            status.append("(already done)")
        print(f"  {fname}: {'+'.join(status)}")
        updated += 1 if (ic_done or mvp_done) else 0
    print(f"\nUpdated {updated} specs")


if __name__ == "__main__":
    main()