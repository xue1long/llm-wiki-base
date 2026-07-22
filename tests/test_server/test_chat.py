"""Tests for src/server/routes/chat.py — HTTP chat endpoint uses AgentRuntime."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.server.app import create_app
from src.agent.types import AgentEvent


app = create_app()
client = TestClient(app)


def test_chat_endpoint_uses_agent(monkeypatch, tmp_path):
    """POST /api/v1/projects/{id}/chat delegates to AgentRuntime and shapes response from events."""
    from src.server.routes import chat as chat_route

    # Stub ProjectContext resolution to avoid filesystem lookups
    fake_ctx = MagicMock()
    fake_ctx.settings = MagicMock()
    fake_ctx.settings.llm = MagicMock()
    fake_ctx.settings.llm.provider_registry_name = "openai"
    monkeypatch.setattr(chat_route, "_resolve_ctx", lambda pid: fake_ctx)

    # Build scripted AgentEvent sequence: run_started + final_answer
    scripted_events = [
        AgentEvent.run_started("s-test", "gpt-4o-mini"),
        AgentEvent.tool_started(0, "wiki.search", {"query": "hi"}),
        AgentEvent.tool_completed(0, "wiki.search", {"query": "hi", "results": [{"path": "a.md"}]}),
        AgentEvent.final_answer(1, "Hello!", []),
    ]

    fake_runtime = MagicMock()
    fake_runtime.run = AsyncMock(return_value=scripted_events)
    with patch.object(chat_route, "AgentRuntime", return_value=fake_runtime):
        r = client.post("/api/v1/projects/proj-1/chat", json={"message": "hi"})

    assert r.status_code == 200
    body = r.json()
    assert body["projectId"] == "proj-1"
    assert body["mode"] == "standard"
    assert body["message"]["role"] == "assistant"
    assert body["message"]["content"] == "Hello!"
    # references should include the wiki.search result
    assert body["references"] == [{"path": "a.md"}]
    # usage should count iterations + tool calls
    assert body["usage"]["toolCalls"] == 1
    assert body["usage"]["iterations"] == 2  # 1 tool_started + 1 final_answer