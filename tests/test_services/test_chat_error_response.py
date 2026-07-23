"""Tests for C-15 fix: services.chat.run_chat raises AgentRunFailed when
the agent never emits a `final_answer` event within the configured budget.

Before T8, run_chat silently returned a 200 with an empty assistant message
when the agent loop ran out of iterations without producing a final_answer.
T8 introduces AgentRunFailed and a budget check on `max_iterations` so the
caller learns that the agent failed to converge.
"""
import asyncio
from types import SimpleNamespace

import pytest

from src.services import chat as chat_service


def test_chat_raises_when_no_final_answer(monkeypatch, tmp_path):
    """Agent emits only tool events; no final_answer -> AgentRunFailed."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "src.services.chat.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    class FakeAgentConfig:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    monkeypatch.setattr(chat_service, "AgentConfig", FakeAgentConfig)

    class FakeRuntime:
        def __init__(self, ctx, config): pass
        async def run(self, message):
            # Loop exhausted without producing final_answer.
            return [
                SimpleNamespace(type="tool_started", payload={}),
                SimpleNamespace(type="tool_completed", payload={
                    "tool": "wiki.search",
                    "result": {"results": [{"path": "wiki/a.md"}]},
                }),
                SimpleNamespace(type="max_iterations_reached", payload={"limit": 8}),
            ]

    monkeypatch.setattr(chat_service, "AgentRuntime", FakeRuntime)

    with pytest.raises(chat_service.AgentRunFailed):
        asyncio.run(chat_service.run_chat("u", "hello"))


def test_chat_returns_on_final_answer(monkeypatch, tmp_path):
    """Normal path with final_answer must still succeed and NOT raise."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "src.services.chat.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    class FakeAgentConfig:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
    monkeypatch.setattr(chat_service, "AgentConfig", FakeAgentConfig)

    class FakeRuntime:
        def __init__(self, ctx, config): pass
        async def run(self, message):
            return [
                SimpleNamespace(type="tool_started", payload={}),
                SimpleNamespace(type="tool_completed", payload={
                    "tool": "wiki.search",
                    "result": {"results": [{"path": "wiki/a.md"}]},
                }),
                SimpleNamespace(type="final_answer", payload={"answer": "ok"}),
            ]

    monkeypatch.setattr(chat_service, "AgentRuntime", FakeRuntime)

    result = asyncio.run(chat_service.run_chat("u", "hello", session_id="s1"))
    assert result["message"]["content"] == "ok"


def test_agent_run_failed_includes_last_event_for_diagnostics(monkeypatch, tmp_path):
    """AgentRunFailed carries the last-seen event name for diagnostics."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "src.services.chat.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    class FakeAgentConfig:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
    monkeypatch.setattr(chat_service, "AgentConfig", FakeAgentConfig)

    class FakeRuntime:
        def __init__(self, ctx, config): pass
        async def run(self, message):
            return [
                SimpleNamespace(type="tool_completed", payload={
                    "tool": "wiki.search", "result": {"results": []},
                }),
            ]

    monkeypatch.setattr(chat_service, "AgentRuntime", FakeRuntime)

    with pytest.raises(chat_service.AgentRunFailed) as exc_info:
        asyncio.run(chat_service.run_chat("u", "hello"))
    # The exception's message / payload should include the last seen event type
    # so the caller can show "agent failed after tool_completed".
    msg = str(exc_info.value)
    assert "tool_completed" in msg or "tool_completed" in repr(exc_info.value)


def _fake_resolve(project_dir):
    from src.project.context import ProjectContext
    from src.wiki.core.paths import WikiPaths
    identity = type("I", (), {"id": "u"})()
    ctx = ProjectContext(identity=identity, path=project_dir, name="p", schema_version="v2.0")
    return ctx, WikiPaths(project_dir)