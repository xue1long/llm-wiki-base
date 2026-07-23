# src/server/routes/chat.py
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal
from ...services import chat as chat_service

router = APIRouter(prefix="/api/v1", tags=["chat"])

_logger = logging.getLogger(__name__)


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
    try:
        return await chat_service.run_chat(
            project_id=project_id,
            message=body.message,
            session_id=body.sessionId,
        )
    except chat_service.AgentRunFailed as e:
        # The agent loop exhausted its budget without producing a final
        # answer (C-15). Surface this as a 502 Bad Gateway so the client
        # can distinguish "agent failed to converge" from "agent succeeded
        # with empty answer".
        _logger.warning(
            "[chat] agent run failed for project=%s: %s",
            project_id, e,
        )
        raise HTTPException(
            status_code=502,
            detail={
                "error": "agent_run_failed",
                "message": str(e),
                "lastEvent": e.last_event,
                "budget": e.budget,
            },
        )