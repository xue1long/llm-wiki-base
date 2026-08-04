"""Deep Research service — automated multi-query research with auto-ingest.

Phase 2.4 of the Nash absorption plan.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..llm.provider import LLMProvider
    from ..wiki.core.paths import WikiPaths


class ResearchStatus(str, Enum):
    """Research task status."""

    PENDING = "pending"
    GENERATING_QUERIES = "generating_queries"
    SEARCHING = "searching"
    INGESTING = "ingesting"
    SYNTHESIZING = "synthesizing"
    DONE = "done"
    FAILED = "failed"


@dataclass
class ResearchTask:
    """A deep research task."""

    id: str
    topic: str
    queries: list[str] = field(default_factory=list)
    status: ResearchStatus = ResearchStatus.PENDING
    results: list[dict] = field(default_factory=list)  # url, title, snippet
    synthesis: str = ""
    created_at: str = ""
    updated_at: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "topic": self.topic,
            "queries": self.queries,
            "status": self.status.value,
            "results": self.results,
            "synthesis": self.synthesis,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ResearchTask":
        return cls(
            id=data.get("id", ""),
            topic=data.get("topic", ""),
            queries=data.get("queries", []),
            status=ResearchStatus(data.get("status", "pending")),
            results=data.get("results", []),
            synthesis=data.get("synthesis", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            error=data.get("error", ""),
        )


class DeepResearchService:
    """Automated deep research with LLM query generation and web search."""

    def __init__(
        self,
        paths: "WikiPaths",
        llm: "LLMProvider",
        search_provider: str = "tavily",
    ):
        self.paths = paths
        self.llm = llm
        self.search_provider = search_provider
        self._tasks_dir = paths.index / "research_tasks"
        self._tasks_dir.mkdir(parents=True, exist_ok=True)

    def _now(self) -> str:
        return datetime.now().isoformat()

    def _generate_id(self) -> str:
        return f"research-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"

    def _task_path(self, task_id: str) -> Path:
        return self._tasks_dir / f"{task_id}.json"

    def _save_task(self, task: ResearchTask) -> None:
        task.updated_at = self._now()
        path = self._task_path(task.id)
        path.write_text(json.dumps(task.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_task(self, task_id: str) -> ResearchTask | None:
        path = self._task_path(task_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return ResearchTask.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            return None

    async def create_task(self, topic: str, queries: list[str] | None = None) -> ResearchTask:
        """Create a new research task.

        Args:
            topic: Research topic
            queries: Optional pre-defined queries (LLM generates if None)

        Returns:
            ResearchTask with PENDING status
        """
        task = ResearchTask(
            id=self._generate_id(),
            topic=topic,
            queries=queries or [],
            created_at=self._now(),
            updated_at=self._now(),
        )
        self._save_task(task)
        return task

    async def generate_queries(self, task: ResearchTask) -> list[str]:
        """Use LLM to generate search queries for the topic.

        Args:
            task: ResearchTask to generate queries for

        Returns:
            List of search queries
        """
        task.status = ResearchStatus.GENERATING_QUERIES
        self._save_task(task)

        prompt = f"""Generate 3-5 web search queries to research the topic: "{task.topic}"

The queries should be specific and designed to find authoritative sources.
Return ONLY a JSON array of query strings, nothing else.

Example output:
["query 1", "query 2", "query 3"]"""

        try:
            response = await self.llm.complete(prompt)
            # Parse JSON array from response
            text = response.strip()
            if text.startswith("```"):
                # Strip markdown code block
                lines = text.split("\n")
                text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

            queries = json.loads(text)
            if isinstance(queries, list):
                return [str(q) for q in queries if q]
            return []
        except Exception as e:
            task.status = ResearchStatus.FAILED
            task.error = f"Query generation failed: {e}"
            self._save_task(task)
            raise

    async def execute_search(self, task: ResearchTask) -> list[dict]:
        """Execute web searches for all queries.

        Args:
            task: ResearchTask with queries

        Returns:
            List of search results (deduplicated)
        """
        from ..searcher.web_search import web_search

        task.status = ResearchStatus.SEARCHING
        self._save_task(task)

        all_results: dict[str, dict] = {}  # url -> result

        for query in task.queries:
            try:
                results = await web_search(query, provider=self.search_provider, max_results=10)
                for r in results:
                    if r.url not in all_results:
                        all_results[r.url] = r.to_dict()
            except Exception as e:
                # Log but continue with other queries
                print(f"Search failed for query '{query}': {e}")

        return list(all_results.values())

    async def process_task(self, task_id: str) -> ResearchTask:
        """Execute the full research pipeline for a task.

        Args:
            task_id: Task ID to process

        Returns:
            Completed ResearchTask
        """
        task = self._load_task(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        try:
            # Step 1: Generate queries if not provided
            if not task.queries:
                task.queries = await self.generate_queries(task)

            # Step 2: Execute searches
            task.results = await self.execute_search(task)

            # Step 3: Ingest top results
            task.status = ResearchStatus.INGESTING
            self._save_task(task)

            from ..services.ingest import enqueue_source
            ingested_urls = []
            for result in task.results[:20]:  # Top 20 results
                url = result.get("url", "")
                if url:
                    try:
                        await enqueue_source(url, str(self.paths.root))
                        ingested_urls.append(url)
                    except Exception:
                        pass  # Skip failed ingestions

            # Step 4: Generate synthesis
            task.status = ResearchStatus.SYNTHESIZING
            self._save_task(task)

            results_text = "\n".join([
                f"- {r.get('title', '')}: {r.get('snippet', '')}"
                for r in task.results[:10]
            ])

            synthesis_prompt = f"""Based on the following search results, provide a brief synthesis of findings on "{task.topic}":

{results_text}

Provide a 2-3 paragraph summary of key findings."""

            task.synthesis = await self.llm.complete(synthesis_prompt)

            task.status = ResearchStatus.DONE
            self._save_task(task)

            return task

        except Exception as e:
            task.status = ResearchStatus.FAILED
            task.error = str(e)
            self._save_task(task)
            raise