"""Chat service — runs the agent and shapes the response.

Extracted from src/server/routes/chat.py. Validates the project,
instantiates the AgentRuntime, runs the agent, and extracts the
final answer + references from the event stream.
"""
from __future__ import annotations

from ..agent.runtime import AgentRuntime
from ..agent.types import AgentConfig
from ..lib.project import resolve_project


async def run_chat(
    project_id: str,
    message: str,
    session_id: str | None = None,
    model: str = "gpt-4o-mini",
    max_iterations: int = 8,
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
    """
    ctx, _paths = resolve_project(project_id, by_id_only=True)
    runtime = AgentRuntime(ctx, AgentConfig(model=model, max_iterations=max_iterations))
    events = await runtime.run(message)

    # Extract final answer + references from events
    final_answer = ""
    references = []
    for e in events:
        if e.type == "final_answer":
            final_answer = e.payload["answer"]
        if e.type == "tool_completed" and e.payload.get("tool") in (
            "wiki.search", "source.search", "graph.search",
        ):
            references.extend(e.payload.get("result", {}).get("results", []))

    return {
        "sessionId": session_id or "s-mvp",
        "projectId": project_id,
        "message": {"role": "assistant", "content": final_answer},
        "references": references[:10],
        "usage": {
            "iterations": sum(1 for e in events if e.type in ("tool_started", "final_answer")),
            "toolCalls": sum(1 for e in events if e.type == "tool_completed"),
        },
    }
