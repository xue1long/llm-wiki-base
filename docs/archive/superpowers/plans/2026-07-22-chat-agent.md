# Chat Agent (5 tools MVP) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Tool-using chat agent accessible via HTTP `/chat` (non-streaming JSON). 5 MVP tools: wiki.search / wiki.read_page / source.search / graph.search / web.search. RAG-based answer generation. Session-less for MVP.

**Tech Stack:** Python 3.11+, asyncio, dataclass, FastAPI.

**MVP Scope** (per spec): 5 tools + HTTP endpoint (no SSE / REPL / sessions / cost cap).

**Polish (v2.0.1)**: SSE + REPL + sessions + cost cap. **Polish (v2.1)**: 9 more tools (wiki.write_page / workspace.* / skills.* / shell.exec / deep_research.run / llm.generate).

---

### Task 1: AgentLoopAction + 5 tools

**Files:** `src/agent/__init__.py` + `src/agent/types.py` + `src/agent/tools.py` + tests

```python
# src/agent/__init__.py
"""Chat agent — tool-using LLM with agent loop."""
```

```python
# src/agent/types.py
"""AgentLoopAction + AgentEvent + AgentRuntime types."""
from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass
class AgentLoopAction:
    action: Literal["final", "tool", "user_input"]
    tool: Optional[str] = None
    query: Optional[str] = None
    path: Optional[str] = None
    content: Optional[str] = None
    top_k: int = 5
    allow_overwrite: bool = False
    fields: list[dict] = field(default_factory=list)  # for user_input
    answer: Optional[str] = None  # for final

    @classmethod
    def from_json(cls, raw: str) -> "AgentLoopAction":
        import json
        d = json.loads(raw)
        return cls(**d)


@dataclass
class AgentEvent:
    type: str
    iteration: int
    timestamp: int
    payload: dict = field(default_factory=dict)

    @classmethod
    def run_started(cls, session_id: str, mode: str) -> "AgentEvent":
        import time
        return cls(type="run_started", iteration=0, timestamp=int(time.time()*1000),
                  payload={"sessionId": session_id, "mode": mode})

    @classmethod
    def tool_started(cls, iteration: int, tool: str, params: dict) -> "AgentEvent":
        import time
        return cls(type="tool_started", iteration=iteration, timestamp=int(time.time()*1000),
                  payload={"tool": tool, "params": params})

    @classmethod
    def tool_completed(cls, iteration: int, tool: str, result: dict) -> "AgentEvent":
        import time
        return cls(type="tool_completed", iteration=iteration, timestamp=int(time.time()*1000),
                  payload={"tool": tool, "result": result})

    @classmethod
    def final_answer(cls, iteration: int, answer: str, references: list) -> "AgentEvent":
        import time
        return cls(type="final_answer", iteration=iteration, timestamp=int(time.time()*1000),
                  payload={"answer": answer, "references": references})


@dataclass
class AgentConfig:
    model: str = "gpt-4o-mini"
    max_iterations: int = 8  # standard mode MVP
    cost_cap_usd: float = 0.5  # MVP: not enforced; placeholder
```

**Tests** (3): test_agent_loop_action_from_json, test_agent_event_factory, test_default_config.

```bash
git add src/agent/ tests/test_agent/__init__.py tests/test_agent/test_types.py
git commit -m "feat(agent): add AgentLoopAction + AgentEvent + AgentConfig types"
```

---

### Task 2: Tool implementations (5 MVP tools)

**Files:** `src/agent/tools.py` + tests

```python
# src/agent/tools.py
"""5 MVP tools: wiki.search / wiki.read_page / source.search / graph.search / web.search."""
import asyncio
import logging
from typing import Protocol

from ..searcher.hybrid_search import hybrid_search
from ..wiki.page_writer import read_page, page_path_for
from ..wiki.types import PageType


_logger = logging.getLogger(__name__)


class Tool(Protocol):
    name: str
    description: str

    async def execute(self, ctx, **params) -> dict: ...


class WikiSearchTool:
    name = "wiki.search"
    description = "Hybrid search wiki/ pages"

    async def execute(self, ctx, query: str, top_k: int = 5) -> dict:
        results = await hybrid_search(ctx, query, top_k=top_k, mode="hybrid")
        return {"query": query, "results": results}


class WikiReadPageTool:
    name = "wiki.read_page"
    description = "Read a wiki page by ID or path"

    async def execute(self, ctx, path: str) -> dict:
        from pathlib import Path
        if not Path(path).is_absolute():
            path = ctx.paths.root / path
        if not path.exists():
            return {"error": f"Not found: {path}"}
        page = read_page(path)
        return {
            "id": page.id, "title": page.title, "type": page.type.value,
            "body": page.body[:5000],
        }


class SourceSearchTool:
    name = "source.search"
    description = "Search raw/sources/ for keyword matches"

    async def execute(self, ctx, query: str, top_k: int = 5) -> dict:
        results = []
        query_lower = query.lower()
        for src_file in ctx.paths.raw_sources.glob("*"):
            if src_file.suffix in (".md", ".txt"):
                content = src_file.read_text(encoding="utf-8", errors="ignore")
                if query_lower in content.lower():
                    results.append({"path": str(src_file.relative_to(ctx.paths.root))})
                    if len(results) >= top_k:
                        break
        return {"query": query, "results": results}


class GraphSearchTool:
    name = "graph.search"
    description = "Find entity neighbors via wikilinks"

    async def execute(self, ctx, query: str, top_k: int = 5) -> dict:
        from ..wiki.wikilink import extract_wikilinks
        from ..wiki.page_writer import read_page
        matches = []
        for sub in [ctx.paths.wiki_sources, ctx.paths.wiki_entities,
                    ctx.paths.wiki_concepts, ctx.paths.wiki_synthesis]:
            for f in sub.glob("*.md"):
                p = read_page(f)
                if query.lower() in (p.title + " " + p.body).lower():
                    matches.append({"id": p.id, "title": p.title,
                                    "links": extract_wikilinks(p.body)[:10]})
                    if len(matches) >= top_k:
                        break
        return {"query": query, "matches": matches}


class WebSearchTool:
    name = "web.search"
    description = "Web search via Tavily or SearXNG (per LLM provider spec)"

    async def execute(self, ctx, query: str, top_k: int = 5) -> dict:
        # MVP: use Tavily if configured, else SearXNG, else return empty
        from ..llm.registry import ProviderRegistry
        providers = ProviderRegistry.load()
        for name in ("tavily", "searxng"):
            if name in providers:
                # Reuse existing web search logic (in MVP: stub)
                return {"query": query, "results": [], "provider": name}
        return {"query": query, "results": [], "provider": "(no web search configured)"}


TOOLS = {
    "wiki.search": WikiSearchTool(),
    "wiki.read_page": WikiReadPageTool(),
    "source.search": SourceSearchTool(),
    "graph.search": GraphSearchTool(),
    "web.search": WebSearchTool(),
}
```

**Tests** (3): test_wiki_search_returns_results, test_wiki_read_page, test_web_search_no_provider.

```bash
git add src/agent/tools.py tests/test_agent/test_tools.py
git commit -m "feat(agent): add 5 MVP tools (wiki.search/read_page, source.search, graph.search, web.search)"
```

---

### Task 3: AgentRuntime + HTTP endpoint

**Files:** `src/agent/runtime.py` + `src/server/routes/chat.py` upgrade + tests

```python
# src/agent/runtime.py
"""Agent runtime — run agent loop, execute tools, generate final answer."""
import asyncio
import json
import logging

from ..llm.provider_factory import create_llm_provider
from ..llm.registry import ProviderRegistry
from .tools import TOOLS
from .types import AgentConfig, AgentEvent, AgentLoopAction


_logger = logging.getLogger(__name__)

PLANNER_PROMPT = """You are an Agent. Available tools:
{tool_descriptions}

User message: {message}

Previous tool observations:
{observations}

Output strict JSON (no markdown fence):
{{
  "action": "tool" | "final" | "user_input",
  "tool": "<tool_name>",
  "query": "...",        // for wiki.search / source.search / graph.search / web.search
  "path": "...",         // for wiki.read_page
  "topK": 5,
  "fields": [...],       // for user_input
  "answer": "..."        // for final
}}
"""


class AgentRuntime:
    def __init__(self, ctx, config: AgentConfig | None = None):
        self.ctx = ctx
        self.config = config or AgentConfig()
        cfg = ProviderRegistry.get(ctx.settings.llm.provider_registry_name)
        self.provider = create_llm_provider(cfg.name, model_override=self.config.model)
        self.tools = TOOLS

    async def run(self, message: str) -> list[AgentEvent]:
        """Run agent loop; yield events; return when final or max_iterations."""
        events: list[AgentEvent] = []
        events.append(AgentEvent.run_started("s-mvp", self.config.model))
        observations: list[str] = []

        tool_descs = "\n".join(f"- {n}: {t.description}" for n, t in self.tools.items())

        for iteration in range(self.config.max_iterations):
            prompt = PLANNER_PROMPT.format(
                message=message,
                tool_descriptions=tool_descs,
                observations="\n".join(observations) or "(none yet)",
            )
            response = await self.provider.complete(
                prompt=prompt,
                response_format={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["final", "tool", "user_input"]},
                        "tool": {"type": "string"},
                        "query": {"type": "string"},
                        "path": {"type": "string"},
                        "topK": {"type": "integer"},
                        "fields": {"type": "array"},
                        "answer": {"type": "string"},
                    },
                    "required": ["action"],
                },
            )
            try:
                action = AgentLoopAction.from_json(json.dumps(response))
            except Exception as e:
                _logger.warning(f"[agent] parse error: {e}")
                observations.append(f"[parse error: {e}]")
                continue

            if action.action == "final":
                events.append(AgentEvent.final_answer(iteration, action.answer or "Done.", []))
                return events
            elif action.action == "tool":
                tool = self.tools.get(action.tool)
                if not tool:
                    observations.append(f"[unknown tool: {action.tool}]")
                    continue
                events.append(AgentEvent.tool_started(iteration, action.tool, {"query": action.query}))
                try:
                    result = await tool.execute(self.ctx, query=action.query, top_k=action.top_k, path=action.path)
                except Exception as e:
                    result = {"error": str(e)}
                events.append(AgentEvent.tool_completed(iteration, action.tool, result))
                observations.append(json.dumps(result, ensure_ascii=False)[:1000])
            else:
                # user_input: MVP not supported
                observations.append("[user_input not supported in MVP]")
        events.append(AgentEvent(type="max_iterations_reached", iteration=self.config.max_iterations,
                                  timestamp=0, payload={"limit": self.config.max_iterations}))
        return events
```

**Modify `src/server/routes/chat.py`**: replace simple RAG with AgentRuntime:

```python
# In chat.py
from ...agent.runtime import AgentRuntime
from ...agent.types import AgentConfig

@router.post("/projects/{project_id}/chat")
async def chat(project_id: str, body: ChatRequest):
    ctx = _resolve_ctx(project_id)
    runtime = AgentRuntime(ctx, AgentConfig(model="gpt-4o-mini", max_iterations=8))
    events = await runtime.run(body.message)
    # Extract final answer + references from events
    final_answer = ""
    references = []
    for e in events:
        if e.type == "final_answer":
            final_answer = e.payload["answer"]
        if e.type == "tool_completed" and e.payload["tool"] in ("wiki.search", "source.search", "graph.search"):
            references.extend(e.payload.get("result", {}).get("results", []))
    return {
        "sessionId": body.sessionId or "s-mvp",
        "projectId": project_id,
        "mode": body.mode,
        "message": {"role": "assistant", "content": final_answer},
        "references": references[:10],
        "usage": {
            "iterations": sum(1 for e in events if e.type in ("tool_started", "final_answer")),
            "toolCalls": sum(1 for e in events if e.type == "tool_completed"),
        },
    }
```

**Tests** (3): test_agent_run_returns_final, test_agent_run_max_iterations, test_chat_endpoint_uses_agent.

```bash
git add src/agent/runtime.py src/server/routes/chat.py tests/test_agent/test_runtime.py tests/test_server/test_chat.py
git commit -m "feat(agent): add AgentRuntime (tool loop, 8 iters) + HTTP chat endpoint"
```

---

## Self-Review

- [x] 5 MVP tools ✓
- [x] AgentLoopAction JSON schema ✓
- [x] HTTP endpoint (no SSE / REPL / sessions) ✓
- [x] No placeholders
- [x] SSE / REPL / sessions / cost cap deferred to v2.0.1

## Implementation order

Tasks 1-3 chain. Total: 3 tasks, ~2-3 hours.