"""Tests for src.services.chat — agent run dispatch."""
import asyncio
from types import SimpleNamespace

from src.services import chat as chat_service


def test_run_chat_extracts_final_answer(monkeypatch, tmp_path):
    """run_chat invokes the agent and returns final_answer + references."""
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
        def __init__(self, ctx, config):
            self.ctx = ctx
            self.config = config
        async def run(self, message):
            return [
                SimpleNamespace(type="tool_started", payload={}),
                SimpleNamespace(type="tool_completed", payload={
                    "tool": "wiki.search",
                    "result": {"results": [{"path": "wiki/a.md"}]},
                }),
                SimpleNamespace(type="final_answer", payload={"answer": "the answer"}),
            ]

    monkeypatch.setattr(chat_service, "AgentRuntime", FakeRuntime)

    result = asyncio.run(chat_service.run_chat("u", "hello", session_id="s1"))
    assert result["sessionId"] == "s1"
    assert result["projectId"] == "u"
    assert result["message"]["content"] == "the answer"
    assert len(result["references"]) == 1
    assert result["references"][0]["path"] == "wiki/a.md"
    assert result["usage"]["iterations"] == 2  # 1 tool_started + 1 final_answer
    assert result["usage"]["toolCalls"] == 1


def test_run_chat_no_final_answer(monkeypatch, tmp_path):
    """If the agent never produces a final_answer, the message is empty."""
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
            return []

    monkeypatch.setattr(chat_service, "AgentRuntime", FakeRuntime)

    result = asyncio.run(chat_service.run_chat("u", "hello"))
    assert result["message"]["content"] == ""
    assert result["references"] == []


def _fake_resolve(project_dir):
    from src.project.context import ProjectContext
    from src.wiki.paths import WikiPaths
    identity = type("I", (), {"id": "u"})()
    ctx = ProjectContext(identity=identity, path=project_dir, name="p", schema_version="v2.0")
    return ctx, WikiPaths(project_dir)
