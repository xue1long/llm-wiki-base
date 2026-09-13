"""Chat service — runs the agent and shapes the response.

Extracted from src/server/routes/chat.py. Validates the project,
instantiates the AgentRuntime, runs the agent, and extracts the
final answer + references from the event stream.

C-15 fix (T8): if the agent exhausts its budget without emitting a
`final_answer` event, raise `AgentRunFailed` instead of silently
returning an empty assistant message. The HTTP layer converts this
into a 502/504 so the caller learns the agent failed to converge.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from ..agent.claude_host import ClaudeHostError, run_gbrain_claude
from ..agent.runtime import AgentRuntime
from ..agent.types import AgentConfig
from ..integrations.gbrain.api import load_search_config
from ..lib.project import resolve_project


class AgentRunFailed(Exception):
    """Raised when the agent loop never produces a `final_answer` event
    within the configured iteration budget.

    The exception message includes the last seen event type (if any) so
    callers / logs can show "agent failed after tool_completed" etc.
    """

    def __init__(self, last_event: str | None, budget: int):
        self.last_event = last_event
        self.budget = budget
        if last_event:
            super().__init__(
                f"Agent did not produce a final_answer within {budget} "
                f"iterations; last event: {last_event}"
            )
        else:
            super().__init__(
                f"Agent produced no events within {budget} iterations"
            )


class GBrainAgentFailed(Exception):
    """Raised when explicit GBrain Agent mode cannot complete."""

    def __init__(self, error: ClaudeHostError):
        self.error_code = error.code
        super().__init__(str(error))


async def run_chat(
    project_id: str,
    message: str,
    session_id: str | None = None,
    model: str = "",
    max_iterations: int = 8,
    agent_backend: str = "local",
) -> dict:
    """Run a non-streaming agent chat on the project's wiki tree.

    Returns a dict ready for the HTTP route:
        {
            "sessionId": str,
            "projectId": str,
            "message": {"role": "assistant", "content": str},
            "references": list[dict],
            "usage": {"iterations": int, "toolCalls": int},
        }

    Raises:
        AgentRunFailed: if the agent loop exhausts `max_iterations` without
            emitting a `final_answer` event. The HTTP layer translates this
            into a non-200 response so the caller learns the agent failed.
    """
    ctx, paths = resolve_project(project_id, by_id_only=True)
    if agent_backend not in {"local", "auto", "gbrain"}:
        raise ValueError(f"unsupported agent backend: {agent_backend}")

    degraded = False
    degrade_reason = ""
    if agent_backend in {"auto", "gbrain"}:
        conversation_id = session_id or f"chat-{uuid.uuid4().hex[:12]}"
        try:
            hosted = await run_gbrain_claude(
                paths.root, message, conversation_id=conversation_id
            )
            expected_source = load_search_config(paths.root).source_id
            if hosted.get("source_id") != expected_source:
                raise ClaudeHostError("gbrain_source_mismatch")
            references = _validate_gbrain_references(
                paths.root, expected_source, hosted.get("references", [])
            )
            turns = int(hosted.get("num_turns") or 1)
            return {
                "sessionId": conversation_id,
                "projectId": project_id,
                "message": {"role": "assistant", "content": hosted.get("answer", "")},
                "references": references[:10],
                "backend": "gbrain",
                "degraded": False,
                "degrade_reason": "",
                "usage": {"iterations": turns, "toolCalls": max(0, turns - 1)},
            }
        except ClaudeHostError as exc:
            if agent_backend == "gbrain":
                raise GBrainAgentFailed(exc) from exc
            degraded = True
            degrade_reason = exc.code

    runtime = AgentRuntime(ctx, AgentConfig(model=model, max_iterations=max_iterations))
    events = await runtime.run(message)

    # Extract final answer + references from events
    final_answer = ""
    references = []
    last_event_type: str | None = None
    final_answer_seen = False
    for e in events:
        last_event_type = e.type
        if e.type == "final_answer":
            # Track whether a `final_answer` event was seen, independently
            # of whether its answer content is empty. A valid `final_answer`
            # event with empty content (legitimately empty response) must
            # NOT be misinterpreted as "no final_answer seen".
            final_answer_seen = True
            final_answer = e.payload["answer"]
        if e.type == "tool_completed" and e.payload.get("tool") in (
            "wiki.search", "source.search", "graph.search",
        ):
            references.extend(e.payload.get("result", {}).get("results", []))

    if not final_answer_seen:
        # The agent ran but never produced a final_answer event — surface
        # the failure instead of returning a 200 with empty content (C-15).
        raise AgentRunFailed(last_event=last_event_type, budget=max_iterations)

    return {
        "sessionId": session_id or "s-mvp",
        "projectId": project_id,
        "message": {"role": "assistant", "content": final_answer},
        "references": references[:10],
        "backend": "local",
        "degraded": degraded,
        "degrade_reason": degrade_reason,
        "usage": {
            "iterations": sum(1 for e in events if e.type in ("tool_started", "final_answer")),
            "toolCalls": sum(1 for e in events if e.type == "tool_completed"),
        },
    }


def _validate_gbrain_references(root: Path, source_id: str, raw: object) -> list[dict]:
    """Keep only source-scoped references that map back into this Wiki."""
    if not isinstance(raw, list):
        return []
    wiki_root = (Path(root) / "wiki").resolve()
    references: list[dict] = []
    for item in raw:
        if not isinstance(item, dict) or item.get("source_id") != source_id:
            continue
        slug = str(item.get("slug") or "").replace("\\", "/").lstrip("/")
        if slug.startswith("wiki/"):
            slug = slug[5:]
        relative = Path(slug + ("" if slug.endswith(".md") else ".md"))
        if relative.is_absolute() or ".." in relative.parts:
            continue
        candidate = (wiki_root / relative).resolve()
        try:
            candidate.relative_to(wiki_root)
        except ValueError:
            continue
        if not candidate.is_file():
            continue
        references.append({
            "title": item.get("title", ""),
            "slug": slug.removesuffix(".md"),
            "source_id": source_id,
            "path": "wiki/" + relative.as_posix(),
            "snippet": item.get("snippet", ""),
        })
    return references
