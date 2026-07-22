# src/server/routes/chat.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal
from ...project.context import ProjectContext, ProjectNotFoundError

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
    """Non-streaming RAG chat (MVP)."""
    ctx = _resolve_ctx(project_id)
    # Use hybrid search for context (RAG)
    from ...searcher.hybrid_search import hybrid_search
    refs = await hybrid_search(ctx, body.message, top_k=body.topK, mode="hybrid")
    # Build prompt + LLM call
    from ...llm.provider_factory import create_llm_provider
    from ...llm.registry import ProviderRegistry
    config = ProviderRegistry.get("default") if "default" in ProviderRegistry.load() else None
    if not config:
        from ...project.settings import ProjectSettings
        config_name = ctx.settings.llm.provider_registry_name
        config = ProviderRegistry.get(config_name)
    provider = create_llm_provider(config.name)
    system = f"You are a helpful assistant with access to a wiki. Cite sources by [N]."
    context = "\n".join(f"[{i+1}] {r.get('title','')}: {r.get('snippet','')[:200]}" for i, r in enumerate(refs))
    prompt = f"Context:\n{context}\n\nUser: {body.message}"
    response = await provider.complete(prompt=prompt, system=system)
    return {
        "sessionId": body.sessionId or "s-default",
        "projectId": project_id,
        "mode": body.mode,
        "message": {"role": "assistant", "content": response.content},
        "references": [
            {"path": r.get("path", ""), "title": r.get("title", ""),
             "kind": "wiki", "score": r.get("score"), "snippet": r.get("snippet")}
            for r in refs
        ],
        "usage": {
            "promptChars": len(prompt), "completionChars": len(response.content),
            "referenceCount": len(refs),
        },
    }


def _resolve_ctx(project_id: str) -> ProjectContext:
    try:
        return ProjectContext.resolve(project_id, by_id_only=True)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))
