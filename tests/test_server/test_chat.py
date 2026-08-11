"""Tests for src/server/routes/chat.py — HTTP chat endpoint uses AgentRuntime."""

from fastapi.testclient import TestClient

from src.server.app import create_app
from src.agent.types import AgentEvent


app = create_app()
client = TestClient(app)


def test_chat_endpoint_uses_agent(monkeypatch, tmp_path):
    """POST /api/v1/projects/{id}/chat delegates to the chat_service
    and shapes the response from events. The route is now a thin
    adapter, so we patch the service rather than internals."""
    from src.services import chat as chat_service_module

    # Build scripted AgentEvent sequence
    scripted_events = [
        AgentEvent.run_started("s-test", "gpt-4o-mini"),
        AgentEvent.tool_started(0, "wiki.search", {"query": "hi"}),
        AgentEvent.tool_completed(0, "wiki.search", {"query": "hi", "results": [{"path": "a.md"}]}),
        AgentEvent.final_answer(1, "Hello!", []),
    ]

    async def fake_run_chat(project_id, message, session_id=None, model="gpt-4o-mini", max_iterations=8):
        # Run the same event-extraction logic the real service does
        # (this asserts the route + service contract, not service internals).
        final_answer = ""
        references = []
        for e in scripted_events:
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
                "iterations": sum(1 for e in scripted_events if e.type in ("tool_started", "final_answer")),
                "toolCalls": sum(1 for e in scripted_events if e.type == "tool_completed"),
            },
        }

    monkeypatch.setattr(chat_service_module, "run_chat", fake_run_chat)

    r = client.post("/api/v1/projects/proj-1/chat", json={"message": "hi"})

    assert r.status_code == 200
    body = r.json()
    assert body["projectId"] == "proj-1"
    assert body["message"]["role"] == "assistant"
    assert body["message"]["content"] == "Hello!"
    # references should include the wiki.search result
    assert body["references"] == [{"path": "a.md"}]
    # usage should count iterations + tool calls
    assert body["usage"]["toolCalls"] == 1
    assert body["usage"]["iterations"] == 2  # 1 tool_started + 1 final_answer
