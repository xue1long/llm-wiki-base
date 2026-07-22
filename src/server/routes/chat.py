# src/server/routes/chat.py
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Literal
from ...services import chat as chat_service

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
    return await chat_service.run_chat(
        project_id=project_id,
        message=body.message,
        session_id=body.sessionId,
    )