# Web Search + Deep Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Tavily-only web search + Deep Research command that consumes `review_items.search_queries` + writes `wiki/synthesis/<slug>.md` + auto-ingest top 5 sources.

**Tech Stack:** Python 3.11+, asyncio, httpx, dataclass, JSON.

**MVP Scope** (per spec): Tavily only + 1 task × 3 queries + no state persistence + auto-ingest disabled by default + CLI `research {run,list,show}`.

**Polish (v2.0.1)**: SearXNG + state persistence + `--from-review-id` + auto-ingest top 5. **Deferred (v2.1)**: 4 more providers (Firecrawl / Brave / SerpApi / Ollama Web Search).

---

### Task 1: TavilyProvider + research runner + CLI

**Files:** `src/research/__init__.py` + `src/research/providers/tavily.py` + `src/research/runner.py` + `src/cli_ext/research_cmd.py` + tests

```python
# src/research/__init__.py
"""Web Search + Deep Research subsystem."""
```

```python
# src/research/providers/tavily.py
"""Tavily web search provider."""
import httpx


class TavilyProvider:
    name = "tavily"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=30)

    async def search(self, query: str, top_k: int = 10) -> list[dict]:
        if not self.api_key:
            return []
        resp = await self.client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": self.api_key,
                "query": query,
                "max_results": top_k,
                "search_depth": "advanced",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            {"title": r["title"], "url": r["url"], "snippet": r.get("content", "")}
            for r in data.get("results", [])
        ]

    async def close(self):
        await self.client.aclose()
```

```python
# src/research/runner.py
"""Deep Research runner — LLM-driven topic + parallel web search + synthesis."""
import asyncio
import json
import logging
import time

from ..llm.provider_factory import create_llm_provider
from ..llm.registry import ProviderRegistry
from .providers.tavily import TavilyProvider
import os


_logger = logging.getLogger(__name__)

DEFAULT_QUERY_COUNT = 3
DEFAULT_TOP_N_INGEST = 5


async def run_deep_research(
    ctx, topic: str, top_k: int = 10, from_review_id: str | None = None,
    no_ingest: bool = True, max_queries: int = DEFAULT_QUERY_COUNT,
) -> dict:
    """Run deep research: generate queries, parallel search, synthesize, write synthesis page.

    Returns: {"synthesis_path": str, "sources": list, "queries": list, "task_id": str}
    """
    cfg = ProviderRegistry.get(ctx.settings.llm.provider_registry_name)
    llm = create_llm_provider(cfg.name)

    # Step 1: Get queries (from review item OR generate)
    if from_review_id:
        from ..wiki.review import load_reviews
        items = load_reviews(ctx.paths)
        review = next((i for i in items if i.id == from_review_id), None)
        queries = review.search_queries if review and review.search_queries else [topic]
    else:
        # Generate 3 queries via LLM
        queries_prompt = f"Generate {max_queries} distinct web search queries for the topic: {topic}. Output strict JSON: {{\"queries\": [\"q1\", \"q2\", ...]}}"
        response = await llm.complete(
            prompt=queries_prompt,
            response_format={"type": "object", "properties": {"queries": {"type": "array", "items": {"type": "string"}}, "maxItems": max_queries, "minItems": 1}, "required": ["queries"]},
        )
        queries = response.get("queries", [topic])[:max_queries]

    # Step 2: Web search (Tavily only in MVP)
    api_key = os.environ.get("TAVILY_API_KEY", "")
    provider = TavilyProvider(api_key)
    all_results: list[dict] = []
    if provider.api_key:
        tasks = [provider.search(q, top_k=top_k) for q in queries]
        results_per_query = await asyncio.gather(*tasks)
        for r in results_per_query:
            all_results.extend(r)
    await provider.close()

    # Dedupe by URL
    seen_urls = set()
    sources = []
    for r in all_results:
        if r["url"] not in seen_urls:
            seen_urls.add(r["url"])
            sources.append(r)

    # Step 3: Synthesize
    synthesis_prompt = f"""Synthesize research findings for: {topic}

Sources ({len(sources)}):
{chr(10).join(f"[{i+1}] {s['title']} - {s['url']}\\n  {s['snippet']}" for i, s in enumerate(sources))}

Write a comprehensive research summary with citations [N]. Use markdown."""
    synthesis_text = await llm.complete(prompt=synthesis_prompt)
    synthesis_text = synthesis_text.content if hasattr(synthesis_text, "content") else str(synthesis_text)

    # Step 4: Write synthesis page
    from ..wiki.page_writer import write_page
    from ..wiki.types import PageType
    from ..wiki.logger import log_event
    from ..wiki.indexer import append_to_index
    from ..lib.write_hooks import safe_write

    task_id = f"research-{int(time.time())}"
    slug = topic.lower().replace(" ", "-")[:50] or "research"
    date = time.strftime("%Y-%m-%d")
    fm_yaml = f"""---
id: research-{slug}-{date}
title: Research: {topic}
type: synthesis
sources: {[s["url"] for s in sources[:5]]}
created_at: {int(time.time()*1000)}
updated_at: {int(time.time()*1000)}
research_task_id: {task_id}
---
"""
    synth_path = ctx.paths.wiki_synthesis / f"research-{slug}-{date}.md"
    safe_write(synth_path, fm_yaml + f"# Research: {topic}\n\n" + synthesis_text + "\n")
    log_event(ctx.paths, event="research", task_id=task_id, detail=f"synthesized {topic}")
    append_to_index(ctx.paths, [(f"research-{slug}-{date}", PageType.SYNTHESIS, f"Research: {topic}")])

    # Step 5: Auto-ingest (MVP: disabled by default)
    ingest_task_ids = []
    if not no_ingest and sources:
        from ..queue.queue import enqueue_task
        from ..types import SourceType
        for s in sources[:DEFAULT_TOP_N_INGEST]:
            task_hash = f"research-{slug}-{s['url']}"
            tid = enqueue_task(s["url"], SourceType.URL, task_hash)
            if tid:
                ingest_task_ids.append(tid)

    return {
        "task_id": task_id,
        "topic": topic,
        "queries": queries,
        "sources": sources,
        "synthesis_path": str(synth_path.relative_to(ctx.paths.root)),
        "ingest_task_ids": ingest_task_ids,
    }
```

```python
# src/cli_ext/research_cmd.py
"""Deep Research CLI subcommands."""
import argparse
import asyncio
import json
import sys

from ..research.runner import run_deep_research
from ..project.context import ProjectContext, ProjectNotFoundError


def cmd_research_run(args: argparse.Namespace) -> None:
    try:
        ctx = ProjectContext.resolve(args.project, by_id_only=True)
    except ProjectNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr); sys.exit(2)
    result = asyncio.run(run_deep_research(
        ctx, topic=args.topic, from_review_id=args.from_review_id,
        no_ingest=not args.ingest, top_k=args.top_k,
    ))
    print(f"Task: {result['task_id']}")
    print(f"Synthesis: {result['synthesis_path']}")
    print(f"Sources: {len(result['sources'])}")
    if result['ingest_task_ids']:
        print(f"Ingest tasks: {result['ingest_task_ids']}")


def cmd_research_list(args: argparse.Namespace) -> None:
    """List recent research tasks (MVP: no persistence; placeholder)."""
    print("No persistence in MVP. Run `research run` to create new tasks.")


def cmd_research_show(args: argparse.Namespace) -> None:
    """Show synthesis page (MVP: no state lookup; just read file)."""
    try:
        ctx = ProjectContext.resolve(args.project, by_id_only=True)
    except ProjectNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr); sys.exit(2)
    from ..wiki.page_writer import read_page
    path = ctx.paths.wiki_synthesis / f"{args.task_id}.md"
    if not path.exists():
        print(f"Synthesis not found: {path}", file=sys.stderr); sys.exit(2)
    p = read_page(path)
    print(p.body)
```

**Wire in cli.py**: 3 subcommands.

**Tests** (3): test_run_deep_research_generates_queries, test_run_deep_research_writes_synthesis, test_research_cli_routes.

```bash
git add src/research/ src/cli_ext/research_cmd.py src/cli.py tests/test_research/__init__.py tests/test_research/test_runner.py tests/test_cli_ext/test_cmd_research.py
git commit -m "feat(research): add Tavily web search + Deep Research runner (3 queries) + CLI (3 subcommands)"
```

---

## Self-Review

- [x] Tavily only ✓
- [x] 3 queries per run (sequential, MVP) ✓
- [x] Synthesis page written to wiki/synthesis/ ✓
- [x] CLI ✓
- [x] No state persistence (deferred to v2.0.1)
- [x] Auto-ingest off by default (--ingest flag) ✓

## Implementation order

Single task (~2 hours).