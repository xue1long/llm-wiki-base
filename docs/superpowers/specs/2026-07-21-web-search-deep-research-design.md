# Web Search + Deep Research Design Spec

**Date:** 2026-07-21
**Status:** Approved (pending user sign-off)
**Target codebase:** ruflo-kb (Python 3.11+, master @ b253c83, post-multi-provider spec)
**Inspired by:** llm_wiki-main `web-search.ts` + `deep-research.ts` + `optimize-research-topic.ts`

## Goal

Add a dedicated Web Search + Deep Research subsystem to ruflo-kb that closes the wiki-generation loop:

1. **Web Search providers** (6 total): Tavily + SearXNG (already in chat-agent spec) + Firecrawl + Brave + SerpApi + Ollama Web Search. Each provider has independent API key / base URL configuration.
2. **Deep Research command** (`python -m src.cli research [TOPIC]`): refines the topic via LLM, runs 5 parallel web searches, synthesizes findings, writes `wiki/synthesis/research-<topic>-<date>.md`, and optionally auto-ingests top 5 sources back to the KB.
3. **Review Items integration**: deep research accepts `review_item_id` (a `needs-research` type from wiki v2.0's review system) and consumes its pre-generated `search_queries`.
4. **Persistent task state**: research tasks tracked in `.index/research/<task_id>.json` (pending → running → completed/failed); resumable across process restarts.

This spec completes the wiki v2.0 loop: `Analyzer` flags uncertain facts as review items → `Deep Research` investigates them → `Auto-Ingest` adds new wiki pages → `Quality Gate` validates them. End-to-end self-improvement.

## Non-goals

- No image / video search (Firecrawl v2 supports it; deferred).
- No full-text PDF extraction inside web results (deferred).
- No agent-loop integration (chat-agent already has `web.search` tool; this spec is the dedicated subsystem).
- No scheduling / cron-based recurring research (deferred).
- No collaboration (multi-user research session merging; deferred).
- No result caching beyond task-level persistence (each run re-queries).


## Input Contract

> Reference: [`_input_contracts.md`](_input_contracts.md) for cross-spec dependency map.

**This spec provides** (consumed by other specs):

- 6 web search providers (MVP: 1 Tavily)
- `ResearchRunner`
- `optimizeResearchTopic` (LLM)
- `synthesizeFindings` (LLM)
- `ResearchState` persistence (deferred)
- `TopicOptimizer`

**This spec requires from other specs**:

- **Wiki v2.0 (REQUIRED)**: writes `wiki/synthesis/<slug>.md`
- **Multi-Provider LLM (REQUIRED)**: LLM calls for optimizer + synthesizer
- **Quality Gate (REQUIRED for auto-ingest)**: judges synthesized pages
- **src/shared/**: `ReviewItem.search_queries` consumed via `--from-review-id`

**Phase**: Phase 4 — Advanced
**Priority**: P0 — MVP (Tavily only)

## Architecture

### Pipeline

```
CLI: python -m src.cli research "<topic>" [--from-review-id RID] [--no-ingest] [--max-sources N] [--provider tavily]

        │
        ▼
ResearchRunner.run(ctx, topic, opts)
        │
        ├── 1. optimizeResearchTopic(topic, ctx.purpose, ctx.overview, review_item?)
        │      LLM refines topic + generates 3 search queries
        │
        ├── 2. (in parallel, max 5) web_search_provider.search(query)
        │      Firecrawl / Tavily / Brave / SerpApi / SearXNG / Ollama Web Search
        │      Up to 20 sources total (deduped by URL)
        │
        ├── 3. (if --source local) source_search(query) for each query
        │      Searches raw/sources/ via keyword match (existing utils/extract)
        │
        ├── 4. synthesizeFindings(topic, sources) — LLM writes synthesis
        │
        ├── 5. write wiki/synthesis/research-<slug>-<date>.md
        │      Frontmatter: type=synthesis, sources=[], research_task_id=<uuid>
        │
        ├── 6. (if not --no-ingest) auto_ingest_top_n(sources, n=5)
        │      enqueue_task(source_url, source_type=URL) for top 5 sources
        │      Pipeline: Collector → Analyzer → Generator → Quality Judge → Librarian
        │
        └── 7. save task state → .index/research/<task_id>.json
               Mark review_item status = "resolved" if --from-review-id provided

Concurrency: max 3 research tasks in flight; each task runs max 5 web searches in parallel.
```

### Configuration

```
.llm-wiki/settings.json (per-project, additions):
{
  "research": {
    "providers": {
      "tavily":     {"api_key_env": "TAVILY_API_KEY", "max_results": 10},
      "searxng":    {"base_url": "http://localhost:8888", "categories": ["general", "science"]},
      "firecrawl":  {"api_key_env": "FIRECRAWL_API_KEY", "base_url": "https://api.firecrawl.dev"},
      "brave":      {"api_key_env": "BRAVE_API_KEY"},
      "serpapi":    {"api_key_env": "SERPAPI_API_KEY", "engine": "google"},
      "ollama":     {"base_url": "https://ollama.com", "api_key_env": "OLLAMA_API_KEY"}
    },
    "default_provider": "tavily",
    "auto_ingest_top_n": 5,
    "max_concurrent_tasks": 3,
    "max_concurrent_queries_per_task": 5
  }
}
```

`.index/research/<task_id>.json`:

```json
{
  "id": "uuid",
  "projectId": "uuid",
  "topic": "backpropagation",
  "refinedTopic": "How does backpropagation work in deep neural networks?",
  "searchQueries": ["backpropagation algorithm", "gradient descent neural networks", "..."],
  "fromReviewItemId": "uuid-or-null",
  "createdAt": 1721558400000,
  "updatedAt": 1721558500000,
  "status": "completed",
  "provider": "tavily",
  "sourcesFound": 23,
  "sourcesIngested": 5,
  "synthesisPath": "wiki/synthesis/research-backpropagation-2026-07-21.md",
  "ingestTaskIds": ["kb-...", "kb-..."],
  "errors": [],
  "events": [
    {"at": ..., "type": "started", "data": {}},
    {"at": ..., "type": "optimized_topic", "data": {"refinedTopic": "..."}},
    {"at": ..., "type": "collected_sources", "data": {"count": 23}},
    {"at": ..., "type": "synthesized", "data": {"path": "..."}},
    {"at": ..., "type": "ingested", "data": {"taskIds": [...]}},
    {"at": ..., "type": "completed", "data": {}}
  ]
}
```

## Components

### New modules

```
src/research/
├── __init__.py
├── runner.py              # ResearchRunner.run()
├── topic_optimizer.py     # optimizeResearchTopic()
├── synthesizer.py         # synthesizeFindings()
├── state.py               # ResearchState persistence
├── sources.py             # SourceCollection (dedup by URL)
└── auto_ingest.py         # auto_ingest_top_n()

src/research/providers/
├── __init__.py
├── base.py                # WebSearchProvider protocol
├── tavily.py
├── searxng.py
├── firecrawl.py
├── brave.py
├── serpapi.py
└── ollama.py

src/pipeline/prompts/
├── research_optimizer.py
└── research_synthesizer.py

src/cli_ext/
├── research_cmd.py        # cmd_research run/list/show/cancel/delete

src/server/research.py    # HTTP endpoints
src/mcp_server/tools.py    # (extend) ruflo_kb_research_run/list/cancel

tests/test_research/
├── test_runner.py
├── test_topic_optimizer.py
├── test_synthesizer.py
├── test_state.py
├── test_sources.py
├── test_auto_ingest.py
└── test_providers/
    ├── test_tavily.py
    ├── test_searxng.py
    ├── test_firecrawl.py
    ├── test_brave.py
    ├── test_serpapi.py
    └── test_ollama.py

tests/test_cli_ext/test_cmd_research.py
tests/test_integration/test_deep_research_e2e.py
```

### Modified modules

| Path | Change |
|---|---|
| `src/project/settings.py` | `ProjectSettings` adds `research: ResearchSettings` block |
| `src/llm/registry.py` (from multi-provider spec) | Reuse for LLM calls |
| `src/wiki/review.py` | `ReviewManager.mark_resolved(item_id, action="deep-research", task_id=<research_id>)` |
| `src/cli.py` | `research` subcommand dispatch |

## Data structures

```python
# src/research/types.py
@dataclass
class OptimizedTopic:
    topic: str                              # user-provided
    refined_topic: str                      # LLM-refined
    search_queries: list[str]               # 3 queries
    rationale: str                          # LLM's reasoning

@dataclass
class ResearchSource:
    title: str
    url: str                                # unique key
    snippet: str
    source_provider: str                    # "tavily" | "firecrawl" | etc.
    score: float | None = None

@dataclass
class ResearchEvent:
    at: int
    type: str                               # "started" | "optimized_topic" | "collected_sources" | "synthesized" | "ingested" | "completed" | "failed"
    data: dict

class ResearchStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass
class ResearchState:
    id: str
    project_id: str
    topic: str
    refined_topic: str | None = None
    search_queries: list[str] = field(default_factory=list)
    from_review_item_id: str | None = None
    created_at: int
    updated_at: int
    status: ResearchStatus = ResearchStatus.PENDING
    provider: str | None = None
    sources_found: int = 0
    sources_ingested: int = 0
    synthesis_path: str | None = None
    ingest_task_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    events: list[ResearchEvent] = field(default_factory=list)
    
    STATE_DIR = ".index/research"
    
    @classmethod
    def load(cls, ctx: ProjectContext, task_id: str) -> "ResearchState": ...
    def save(self) -> None: ...
    def delete(self) -> None: ...
    @classmethod
    def list_for_project(cls, ctx: ProjectContext) -> list["ResearchStateMetadata"]: ...

@dataclass
class ResearchStateMetadata:
    id: str
    topic: str
    status: str
    created_at: int
    updated_at: int
    sources_found: int

@dataclass
class ResearchSettings:
    providers: dict[str, dict] = field(default_factory=lambda: {
        "tavily":    {"api_key_env": "TAVILY_API_KEY", "max_results": 10},
        "searxng":   {"base_url": "", "categories": ["general"]},
        "firecrawl": {"api_key_env": "FIRECRAWL_API_KEY", "base_url": "https://api.firecrawl.dev"},
        "brave":     {"api_key_env": "BRAVE_API_KEY"},
        "serpapi":   {"api_key_env": "SERPAPI_API_KEY", "engine": "google"},
        "ollama":    {"base_url": "https://ollama.com", "api_key_env": "OLLAMA_API_KEY"},
    })
    default_provider: str = "tavily"
    auto_ingest_top_n: int = 5
    max_concurrent_tasks: int = 3
    max_concurrent_queries_per_task: int = 5
    synthesis_max_tokens: int = 4096
    refine_topic_enabled: bool = True
```

```python
# src/research/providers/base.py
class WebSearchProvider(Protocol):
    name: str                                # "tavily" | etc.
    
    async def search(self, query: str, max_results: int = 10) -> list[ResearchSource]: ...
    async def close(self) -> None: ...

def get_provider(name: str, settings: ResearchSettings) -> WebSearchProvider:
    cfg = settings.providers[name]
    if name == "tavily":
        return TavilyProvider(api_key=os.environ.get(cfg["api_key_env"], ""))
    elif name == "searxng":
        return SearXNGProvider(base_url=cfg["base_url"], categories=cfg["categories"])
    elif name == "firecrawl":
        return FirecrawlProvider(api_key=os.environ.get(cfg["api_key_env"], ""), base_url=cfg["base_url"])
    elif name == "brave":
        return BraveProvider(api_key=os.environ.get(cfg["api_key_env"], ""))
    elif name == "serpapi":
        return SerpApiProvider(api_key=os.environ.get(cfg["api_key_env"], ""), engine=cfg["engine"])
    elif name == "ollama":
        return OllamaWebSearchProvider(api_key=os.environ.get(cfg["api_key_env"], ""), base_url=cfg["base_url"])
    raise ValueError(f"Unknown provider: {name}")
```

## Pipeline

```python
# src/research/runner.py
class ResearchRunner:
    def __init__(self, ctx: ProjectContext, llm: LLMProvider):
        self.ctx = ctx
        self.llm = llm
        self.settings = ctx.settings.research
        self.sem_task = asyncio.Semaphore(self.settings.max_concurrent_tasks)
        self.sem_query = asyncio.Semaphore(self.settings.max_concurrent_queries_per_task)
        self.provider = get_provider(self.settings.default_provider, self.settings)
    
    async def run(
        self,
        topic: str,
        from_review_item_id: str | None = None,
        no_ingest: bool = False,
        max_sources: int | None = None,
    ) -> ResearchState:
        async with self.sem_task:
            state = ResearchState(
                id=str(uuid.uuid4()),
                project_id=self.ctx.id,
                topic=topic,
                from_review_item_id=from_review_item_id,
                created_at=int(time.time() * 1000),
                status=ResearchStatus.RUNNING,
                provider=self.provider.name,
            )
            state.save()
            state.events.append(ResearchEvent(at=state.created_at, type="started", data={}))
            
            try:
                # Step 1: Refine topic (if enabled)
                if self.settings.refine_topic_enabled:
                    optimized = await topic_optimizer.optimize(
                        self.llm, topic, self.ctx.purpose, self.ctx.overview, from_review_item_id
                    )
                    state.refined_topic = optimized.refined_topic
                    state.search_queries = optimized.search_queries
                    state.events.append(ResearchEvent(at=..., type="optimized_topic", data={...}))
                else:
                    state.search_queries = [topic]
                
                # Step 2: Parallel web searches
                async def search_one(query: str) -> list[ResearchSource]:
                    async with self.sem_query:
                        try:
                            return await self.provider.search(query, max_results=self.settings.providers[self.provider.name].get("max_results", 10))
                        except Exception as e:
                            state.errors.append(f"Search '{query}' failed: {e}")
                            return []
                
                all_results = await asyncio.gather(*[search_one(q) for q in state.search_queries])
                sources = self._dedup_sources([s for batch in all_results for s in batch])
                state.sources_found = len(sources)
                state.events.append(ResearchEvent(at=..., type="collected_sources", data={"count": len(sources)}))
                
                # Step 3: Synthesize
                synthesis_md = await synthesizer.synthesize(
                    self.llm, state.refined_topic, sources, max_tokens=self.settings.synthesis_max_tokens
                )
                state.synthesis_path = self._write_synthesis(state, synthesis_md)
                state.events.append(ResearchEvent(at=..., type="synthesized", data={"path": state.synthesis_path}))
                
                # Step 4: Auto-ingest top N
                if not no_ingest and sources:
                    top_n = max_sources or self.settings.auto_ingest_top_n
                    ingest_task_ids = await auto_ingest.ingest_top_n(self.ctx, sources[:top_n])
                    state.sources_ingested = len(ingest_task_ids)
                    state.ingest_task_ids = ingest_task_ids
                    state.events.append(ResearchEvent(at=..., type="ingested", data={"taskIds": ingest_task_ids}))
                
                # Step 5: Mark review item resolved
                if from_review_item_id:
                    review_manager.mark_resolved(from_review_item_id, action="deep-research", task_id=state.id)
                
                state.status = ResearchStatus.COMPLETED
                state.events.append(ResearchEvent(at=..., type="completed", data={}))
                state.save()
                return state
            
            except Exception as e:
                state.status = ResearchStatus.FAILED
                state.errors.append(str(e))
                state.events.append(ResearchEvent(at=..., type="failed", data={"error": str(e)}))
                state.save()
                raise
            finally:
                await self.provider.close()
    
    def _dedup_sources(self, sources: list[ResearchSource]) -> list[ResearchSource]:
        seen = {}
        for s in sources:
            if s.url not in seen:
                seen[s.url] = s
            else:
                # Keep higher score
                if s.score and (seen[s.url].score is None or s.score > seen[s.url].score):
                    seen[s.url] = s
        return list(seen.values())
    
    def _write_synthesis(self, state: ResearchState, markdown: str) -> str:
        slug = slugify(state.refined_topic or state.topic)
        date = datetime.fromtimestamp(state.created_at / 1000).strftime("%Y-%m-%d")
        path = self.ctx.paths.wiki_synthesis / f"research-{slug}-{date}.md"
        path.write_text(markdown, encoding="utf-8")
        return str(path.relative_to(self.ctx.path))
```

```python
# src/research/topic_optimizer.py
async def optimize(
    llm: LLMProvider,
    topic: str,
    purpose: str | None,
    overview: str | None,
    review_item_id: str | None = None,
) -> OptimizedTopic:
    """LLM refines user topic + generates 3 search queries.
    
    If review_item_id provided, fetch review item to enrich context.
    """
    review_item = None
    if review_item_id:
        review_item = review_manager.get(review_item_id)  # type: ignore
    
    prompt = build_optimizer_prompt(
        topic=topic,
        purpose=purpose,
        overview=overview,
        review_item=review_item,
    )
    
    response = await llm.complete(
        prompt=prompt,
        response_format={
            "type": "object",
            "properties": {
                "refined_topic": {"type": "string"},
                "search_queries": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 5},
                "rationale": {"type": "string"},
            },
            "required": ["refined_topic", "search_queries"],
        },
        system="You are a research assistant. Generate precise search queries.",
    )
    
    return OptimizedTopic(
        topic=topic,
        refined_topic=response["refined_topic"],
        search_queries=response["search_queries"][:5],
        rationale=response.get("rationale", ""),
    )
```

```python
# src/research/synthesizer.py
async def synthesize(
    llm: LLMProvider,
    topic: str,
    sources: list[ResearchSource],
    max_tokens: int = 4096,
) -> str:
    """LLM synthesizes findings into a Markdown research page."""
    
    # Build source context (numbered)
    source_blocks = []
    for i, s in enumerate(sources[:20], 1):
        snippet = (s.snippet or "")[:500]
        source_blocks.append(f"[{i}] {s.title}\nURL: {s.url}\n{snippet}\n")
    
    sources_text = "\n".join(source_blocks)
    
    prompt = SYNTHESIS_PROMPT_TEMPLATE.format(
        topic=topic,
        source_count=len(sources),
        sources=sources_text,
    )
    
    response = await llm.complete(
        prompt=prompt,
        system="You are a research synthesizer. Cite sources by [N].",
        max_tokens=max_tokens,
    )
    
    # Response is already Markdown; wrap with frontmatter
    frontmatter = {
        "title": topic,
        "type": "synthesis",
        "sources": [s.url for s in sources[:20]],
        "created_at": int(time.time() * 1000),
    }
    fm_yaml = yaml.dump(frontmatter, allow_unicode=True, sort_keys=False)
    return f"---\n{fm_yaml}---\n\n# {topic}\n\n{response}"
```

```python
# src/research/auto_ingest.py
async def ingest_top_n(ctx: ProjectContext, sources: list[ResearchSource]) -> list[str]:
    """Enqueue top N sources for ingest via the standard pipeline."""
    task_ids = []
    for source in sources:
        task_hash = generate_task_hash(SourceType.URL, source.url)
        task_id = enqueue_task(source.url, SourceType.URL, task_hash)
        if task_id:
            task_ids.append(task_id)
    return task_ids
```

## Web search providers

```python
# src/research/providers/tavily.py (new in this spec; reuse existing chat-agent tavily)
class TavilyProvider:
    name = "tavily"
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=30)
    
    async def search(self, query: str, max_results: int = 10) -> list[ResearchSource]:
        if not self.api_key:
            return []
        resp = await self.client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": self.api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "advanced",
                "include_answer": False,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            ResearchSource(
                title=r["title"],
                url=r["url"],
                snippet=r.get("content", ""),
                source_provider="tavily",
                score=r.get("score"),
            )
            for r in data.get("results", [])
        ]
    
    async def close(self) -> None:
        await self.client.aclose()

# Other providers (searxng, firecrawl, brave, serpapi, ollama) similar pattern
# Each returns list[ResearchSource]; missing api_key → empty list (degraded gracefully)
```

## CLI surface

```
python -m src.cli research "<topic>" [--from-review-id RID] [--provider tavily|searxng|firecrawl|brave|serpapi|ollama] [--no-ingest] [--max-sources N] [--no-refine]
    # Run deep research on topic; optional review item context

python -m src.cli research list [--status pending|running|completed|failed|cancelled]
    # List research tasks

python -m src.cli research show <task_id>
    # Show full task JSON + events

python -m src.cli research cancel <task_id>
    # Cancel a running research task

python -m src.cli research delete <task_id>
    # Delete research task (state + synthesis page if exists)

python -m src.cli research from-review <review_item_id> [--no-ingest]
    # Convenience: shortcut for `research "" --from-review-id <id>`

python -m src.cli config set research.providers.tavily.api_key_env TAVILY_KEY --project <id>
    # Set provider API key env var name

python -m src.cli config set research.default_provider brave --project <id>
    # Change default provider
```

## HTTP endpoints

```
POST /api/v1/projects/{id}/research           # Run research (returns research_id; poll for status)
GET  /api/v1/projects/{id}/research            # List tasks
GET  /api/v1/projects/{id}/research/{tid}     # Get task JSON
POST /api/v1/projects/{id}/research/{tid}/cancel
DELETE /api/v1/projects/{id}/research/{tid}
```

## MCP tools

```
ruflo_kb_research_run(project_id, topic, from_review_id?, provider?, no_ingest?, max_sources?)
    → Returns research_id; final answer waits for completion (or polls)

ruflo_kb_research_list(project_id, status?)
    → List of research tasks

ruflo_kb_research_show(project_id, task_id)
    → Full task JSON

ruflo_kb_research_cancel(project_id, task_id)
ruflo_kb_research_delete(project_id, task_id)
```

## Error handling

| Stage | Error | Strategy |
|---|---|---|
| Topic optimizer LLM | Timeout / schema fail | Use raw topic as refined_topic + 1 search query = topic itself |
| Topic optimizer | All retries fail | Use empty search_queries → search query = topic |
| Web search (all providers) | All providers fail | State fails with error; user can retry |
| Web search (one provider) | Single provider fails | Log to state.errors; continue with others |
| Source dedup | URL collision | Keep higher score |
| Synthesis LLM | Timeout | Retry 1x with shorter prompt; if still fails, write stub synthesis with raw sources |
| Synthesis write fail | Disk full / permission | State fails; partial state saved |
| Auto-ingest | enqueue_task fails (duplicate) | Skip; note in state.errors |
| Auto-ingest | Pipeline fails (per-task errors) | State still marked COMPLETED with sources_ingested = N (some ingested); errors logged |
| Review item not found | --from-review-id points to nothing | Hard error before starting |
| Concurrency | 3 tasks already running | Queue + wait for semaphore; show "queued" status |
| State persistence | .index/research/ not writable | In-memory state; warning logged |
| Cancel during synthesis | User cancels | State CANCELLED; partial synthesis saved with note |
| Provider config missing | api_key_env not set | Provider returns empty list (degraded); warning at startup |

## Backwards compatibility

- New `research` subcommand: purely additive.
- New `settings.research` block: defaults match v1 (Tavily default, auto-ingest top 5).
- Existing wiki v2.0 `review_items` with `search_queries` array: now consumable by `research --from-review-id`.
- No new required dependencies (httpx + asyncio already in use).

## Testing strategy

### Unit tests

| Module | Test focus |
|---|---|
| `src/research/topic_optimizer.py` | LLM mock; JSON schema validation; fallback to raw topic on timeout |
| `src/research/synthesizer.py` | LLM mock; source numbering; frontmatter generation |
| `src/research/sources.py` | Dedup by URL; score-based winner |
| `src/research/state.py` | create/load/save/delete/list; concurrent writes |
| `src/research/runner.py` | Full pipeline with mocked LLM + provider; concurrent task limit |
| `src/research/auto_ingest.py` | Enqueue top N; duplicate detection; failure handling |
| `src/research/providers/*.py` | httpx mock per provider; missing api_key graceful degradation |
| `src/cli_ext/research_cmd.py` | All subcommands; --provider validation |

### Integration tests

```
tests/test_integration/test_deep_research_e2e.py:
    async def test_full_pipeline_with_mock_provider():
        # Mock provider returns 5 sources
        # Mock LLM optimizer + synthesizer
        # Verify: state file created, synthesis page in wiki/, 5 ingest tasks queued

    async def test_from_review_id_consumes_search_queries():
        # Create review item with search_queries
        # Run research --from-review-id
        # Verify: optimizer uses review item's context

    async def test_concurrent_task_limit():
        # Spawn 5 research tasks simultaneously
        # Verify: only 3 run in parallel; 2 queued

    async def test_no_ingest_flag():
        # Run research --no-ingest
        # Verify: synthesis written but no ingest tasks

    async def test_provider_failure_graceful():
        # Mock provider raises exception
        # Verify: state.failed; error logged
```


## MVP Scope / Polish / Deferred

> This section partitions the spec's features into delivery tiers. See [`_input_contracts.md`](_input_contracts.md) for cross-spec context.

### MVP Scope (P0)

- Tavily only
- 1 concurrent task × 3 concurrent queries
- No state persistence (in-memory)
- Auto-ingest: disabled by default (`--no-ingest` default)
- CLI: `research {run,list,show}`

### Polish (v2.0.1 or later)

- SearXNG
- State persistence to `.index/research/`
- Review items integration (`--from-review-id`)
- Auto-ingest top 5 (default)
- HTTP + MCP endpoints

### Deferred (v2.1+)

- 4 more providers (Firecrawl / Brave / SerpApi / Ollama Web Search)
- Result caching
- Cross-source synthesis templates
- Scheduling / cron recurring research

## Implementation order

8 phases, each independently committable:

1. **Foundation** — `src/research/types.py` + `ResearchSettings` + state persistence + tests
2. **Provider implementations** — `src/research/providers/{tavily,searxng,firecrawl,brave,serpapi,ollama}.py` + tests
3. **Topic optimizer** — `src/research/topic_optimizer.py` + prompt + tests
4. **Synthesizer** — `src/research/synthesizer.py` + prompt + tests
5. **Source collection + dedup** — `src/research/sources.py` + tests
6. **Runner orchestration** — `src/research/runner.py` + concurrency control + tests
7. **Auto-ingest integration** — `src/research/auto_ingest.py` + review_items.mark_resolved + tests
8. **CLI + HTTP + MCP** — `src/cli_ext/research_cmd.py` + HTTP endpoints + MCP tools + integration tests

Each phase follows TDD per-task rhythm; one commit per task.

## Cost estimation

Per deep research task:
- Topic optimizer: 1 LLM call (~500 tokens in, ~200 out)
- Web searches: 5 queries × 1 HTTP call = 5 web API calls (~$0.01-0.05 total across providers)
- Synthesizer: 1 LLM call (~3000-8000 tokens in, ~2000 out)
- Auto-ingest: 5 sources × standard ingest pipeline = +$0.10-0.20 (per Quality Gate v2 spec)

Per deep research task: ~$0.15-0.30 (depends on provider pricing + LLM model).

## Open questions / deferred (v3.0+)

- **Image / video search** (Firecrawl v2 supports; deferred)
- **Scheduling / cron** — auto-run research on review items weekly
- **Result caching** — TTL-based cache for repeat queries
- **Multi-user research session merging** — collaborative research
- **Citation graph** — track which wiki pages cite which research syntheses
- **Quality scoring for synthesized pages** — extend Quality Gate v2 to assess synthesis quality
- **Per-provider rate limiting** — uniform 30s timeout in v1; provider-specific limits later
- **Custom synthesis templates** — per-project research synthesis style
- **Research task dependency** — chain research tasks (run B after A completes)
- **Streaming progress events** — extend chat-agent SSE pattern for real-time research progress

## Dependency graph

```
src/research/providers/base.py
       │
       ├──► tavily.py, searxng.py, firecrawl.py, brave.py, serpapi.py, ollama.py
       │
src/research/topic_optimizer.py ──► src/llm/base.py (complete)
src/research/synthesizer.py ──► src/llm/base.py (complete)
       │
src/research/sources.py (dedup)
src/research/state.py (persistence)
       │
       ▼
src/research/runner.py
       │
       ├──► src/research/auto_ingest.py ──► src/queue/queue.py (enqueue_task)
       │
src/wiki/review.py (mark_resolved)
       │
       ▼
src/cli_ext/research_cmd.py ──► src/research/runner.py
src/server/research.py ──► src/research/runner.py
src/mcp_server/tools.py ──► src/research/runner.py
```