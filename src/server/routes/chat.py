# src/server/routes/chat.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal
from ...project.context import ProjectContext, ProjectNotFoundError
from ...agent.runtime import AgentRuntime
from ...agent.types import AgentConfig

router = APIRouter(prefix="/api/v1", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    sessionId: str | None = None
    mode: Literal["fast", "standard", "deep"] = "standard"
    topK: int = 10
    includeContent: bool = False
    wiki: bool = True
    web: bool = False
    anytxt: bool = False


@router.post("/projects/{project_id}/chat")
async def chat(project_id: str, body: ChatRequest):
    """Non-streaming agent chat (MVP)."""
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


def _resolve_ctx(project_id: str) -> ProjectContext:
    try:
        return ProjectContext.resolve(project_id, by_id_only=True)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))