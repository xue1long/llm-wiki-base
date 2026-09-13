"""Tests for src.services.chat — agent run dispatch."""
import asyncio
from types import SimpleNamespace

import pytest

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
    (project_dir / ".llm-wiki" / "gbrain-search.json").write_text(
        '{"source_id": "ruflo-demo", "enabled": true}', encoding="utf-8"
    )

    monkeypatch.setattr(
        "src.services.chat.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    config_values = {}

    class FakeAgentConfig:
        def __init__(self, **kwargs):
            config_values.update(kwargs)
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
    assert config_values["model"] == ""


def test_run_chat_no_final_answer(monkeypatch, tmp_path):
    """If the agent never produces a final_answer, run_chat must raise
    AgentRunFailed (C-15). This replaces the pre-T8 contract which silently
    returned an empty message."""
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

    with pytest.raises(chat_service.AgentRunFailed):
        asyncio.run(chat_service.run_chat("u", "hello"))


def test_run_chat_gbrain_host_returns_validated_references(monkeypatch, tmp_path):
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )
    (project_dir / ".llm-wiki" / "gbrain-search.json").write_text(
        '{"source_id": "ruflo-demo", "enabled": true}', encoding="utf-8"
    )
    page = project_dir / "wiki" / "concepts" / "a.md"
    page.parent.mkdir(parents=True)
    page.write_text("# A", encoding="utf-8")
    monkeypatch.setattr(
        "src.services.chat.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    async def fake_host(root, message):
        return {
            "answer": "来自 GBrain",
            "source_id": "ruflo-demo",
            "references": [{"title": "A", "slug": "concepts/a", "source_id": "ruflo-demo"}],
            "num_turns": 3,
        }

    monkeypatch.setattr(chat_service, "run_gbrain_claude", fake_host)

    result = asyncio.run(chat_service.run_chat("u", "hello", agent_backend="gbrain"))

    assert result["backend"] == "gbrain"
    assert result["degraded"] is False
    assert result["message"]["content"] == "来自 GBrain"
    assert result["references"][0]["path"] == "wiki/concepts/a.md"
    assert result["references"][0]["source_id"] == "ruflo-demo"


def test_run_chat_auto_falls_back_to_local(monkeypatch, tmp_path):
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

    async def unavailable(root, message):
        raise chat_service.ClaudeHostError("gbrain_runtime_unready")

    monkeypatch.setattr(chat_service, "run_gbrain_claude", unavailable)

    class FakeRuntime:
        def __init__(self, ctx, config): pass
        async def run(self, message):
            return [SimpleNamespace(type="final_answer", payload={"answer": "本地回答"})]

    monkeypatch.setattr(chat_service, "AgentRuntime", FakeRuntime)

    result = asyncio.run(chat_service.run_chat("u", "hello", agent_backend="auto"))

    assert result["backend"] == "local"
    assert result["degraded"] is True
    assert result["degrade_reason"] == "gbrain_runtime_unready"
    assert result["message"]["content"] == "本地回答"


def _fake_resolve(project_dir):
    from src.project.context import ProjectContext
    from src.wiki.core.paths import WikiPaths
    identity = type("I", (), {"id": "u"})()
    ctx = ProjectContext(identity=identity, path=project_dir, name="p", schema_version="v2.0")
    return ctx, WikiPaths(project_dir)
