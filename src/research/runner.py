"""Deep Research runner — LLM-driven topic + parallel web search + synthesis."""
import asyncio
import json
import time
import os

from ..llm.provider_factory import create_llm_provider
from ..llm.registry import ProviderRegistry
from .providers.tavily import TavilyProvider

DEFAULT_QUERY_COUNT = 3
DEFAULT_TOP_N_INGEST = 5

# Wiki logger/indexer are implemented as wiki-v2 Tasks 5/6.
# Defer (skip silently) when unavailable so the research runner can ship independently.
try:
    from ..wiki.logger import log_event  # wiki-v2 T6
except ImportError:
    log_event = None

try:
    from ..wiki.indexer import append_to_index  # wiki-v2 T5
except ImportError:
    append_to_index = None


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
        queries_prompt = (
            f"Generate {max_queries} distinct web search queries for the topic: {topic}. "
            f'Output strict JSON: {{"queries": ["q1", "q2", ...]}}'
        )
        response = await llm.complete(
            prompt=queries_prompt,
            response_format={
                "type": "object",
                "properties": {"queries": {"type": "array", "items": {"type": "string"}}},
                "maxItems": max_queries,
                "minItems": 1,
            },
            required=["queries"],
        )
        # Accept either dict or LLMResponse-shaped object
        if hasattr(response, "content"):
            try:
                response = json.loads(response.content)
            except (TypeError, ValueError):
                response = {}
        if not isinstance(response, dict):
            response = {}
        queries = list(response.get("queries", [topic]))[:max_queries]

    # Step 2: Web search (Tavily only in MVP)
    api_key = os.environ.get("TAVILY_API_KEY", "")
    provider = TavilyProvider(api_key)
    all_results: list[dict] = []
    try:
        if provider.api_key:
            tasks = [provider.search(q, top_k=top_k) for q in queries]
            results_per_query = await asyncio.gather(*tasks)
            for r in results_per_query:
                all_results.extend(r)
    finally:
        await provider.close()

    # Dedupe by URL
    seen_urls = set()
    sources = []
    for r in all_results:
        if r["url"] not in seen_urls:
            seen_urls.add(r["url"])
            sources.append(r)

    # Step 3: Synthesize
    sources_block = "\n".join(
        f"[{i+1}] {s['title']} - {s['url']}\n  {s['snippet']}"
        for i, s in enumerate(sources)
    )
    synthesis_prompt = (
        f"Synthesize research findings for: {topic}\n\n"
        f"Sources ({len(sources)}):\n{sources_block}\n\n"
        "Write a comprehensive research summary with citations [N]. Use markdown."
    )
    synthesis_response = await llm.complete(prompt=synthesis_prompt)
    if hasattr(synthesis_response, "content"):
        synthesis_text = synthesis_response.content
    else:
        synthesis_text = str(synthesis_response)

    # Step 4: Write synthesis page
    from ..wiki.types import PageType
    from ..lib.write_hooks import safe_write

    slug = topic.lower().replace(" ", "-")[:50] or "research"
    date = time.strftime("%Y-%m-%d")
    synth_filename = f"research-{slug}-{date}.md"
    task_id = synth_filename.removesuffix(".md")
    fm_yaml = (
        f"---\n"
        f"id: {task_id}\n"
        f"title: Research: {topic}\n"
        f"type: synthesis\n"
        f"sources: {[s['url'] for s in sources[:5]]}\n"
        f"created_at: {int(time.time()*1000)}\n"
        f"updated_at: {int(time.time()*1000)}\n"
        f"research_task_id: {task_id}\n"
        f"---\n"
    )
    synth_path = ctx.paths.wiki_synthesis / synth_filename
    safe_write(synth_path, fm_yaml + f"# Research: {topic}\n\n" + synthesis_text + "\n")

    if log_event is not None:
        log_event(ctx.paths, event="research", task_id=task_id, detail=f"synthesized {topic}")
    if append_to_index is not None:
        append_to_index(
            ctx.paths,
            [(task_id, PageType.SYNTHESIS, f"Research: {topic}")],
        )

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
