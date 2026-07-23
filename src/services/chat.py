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

from ..agent.runtime import AgentRuntime
from ..agent.types import AgentConfig
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

    Raises:
        AgentRunFailed: if the agent loop exhausts `max_iterations` without
            emitting a `final_answer` event. The HTTP layer translates this
            into a non-200 response so the caller learns the agent failed.
    """
    ctx, _paths = resolve_project(project_id, by_id_only=True)
    runtime = AgentRuntime(ctx, AgentConfig(model=model, max_iterations=max_iterations))
    events = await runtime.run(message)

    # Extract final answer + references from events
    final_answer = ""
    references = []
    last_event_type: str | None = None
    for e in events:
        last_event_type = e.type
        if e.type == "final_answer":
            final_answer = e.payload["answer"]
        if e.type == "tool_completed" and e.payload.get("tool") in (
            "wiki.search", "source.search", "graph.search",
        ):
            references.extend(e.payload.get("result", {}).get("results", []))

    if not final_answer:
        # The agent ran but never produced a final_answer — surface the
        # failure instead of returning a 200 with empty content (C-15).
        raise AgentRunFailed(last_event=last_event_type, budget=max_iterations)

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
