"""Test that src/research/runner.py uses WikiPaths(ctx.path) correctly (not ctx.paths)."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_run_deep_research_uses_wiki_paths(tmp_path, monkeypatch):
    """Verify runner constructs WikiPaths(ctx.path) and uses it (not ctx.paths)."""
    from src.research import runner

    # Create wiki directories
    wiki_synthesis = tmp_path / "wiki" / "synthesis"
    wiki_synthesis.mkdir(parents=True)

    # Mock ctx with ONLY .path attribute (no .paths, no .settings.llm)
    class FakeCtx:
        def __init__(self, path):
            self.path = path

    ctx = FakeCtx(tmp_path)

    # Mock LLM
    llm = MagicMock()
    llm.complete = AsyncMock(side_effect=[
        {"queries": ["q1", "q2", "q3"]},
        SimpleNamespace(content="Synthesis content"),
    ])
    monkeypatch.setattr(runner.ProviderRegistry, "get_default", lambda: SimpleNamespace(name="default"))
    monkeypatch.setattr(runner, "create_llm_provider", lambda name: llm)

    # Mock Tavily
    monkeypatch.setattr(runner.TavilyProvider, "search", AsyncMock(return_value=[]))
    monkeypatch.setattr(runner.TavilyProvider, "close", AsyncMock())
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setattr(runner, "log_event", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(runner, "append_to_index", lambda *args, **kwargs: None, raising=False)

    # Should NOT raise AttributeError
    result = await runner.run_deep_research(ctx, "Test Topic")

    assert result["task_id"]
    assert Path(result["synthesis_path"]).stem == result["task_id"]


def test_run_deep_research_does_not_access_ctx_paths(tmp_path, monkeypatch):
    """Regression: ctx.paths must NOT be accessed (it doesn't exist)."""
    from src.research import runner

    wiki_synthesis = tmp_path / "wiki" / "synthesis"
    wiki_synthesis.mkdir(parents=True)

    class ExplodingCtx:
        def __init__(self, path):
            self.path = path

        @property
        def paths(self):
            raise AssertionError("ctx.paths must not be accessed")

        @property
        def settings(self):
            raise AssertionError("ctx.settings must not be accessed in runner")

    ctx = ExplodingCtx(tmp_path)

    # Mock LLM
    llm = MagicMock()
    llm.complete = AsyncMock(side_effect=[
        {"queries": ["q1"]},
        SimpleNamespace(content="Synthesis"),
    ])
    monkeypatch.setattr(runner.ProviderRegistry, "get_default", lambda: SimpleNamespace(name="default"))
    monkeypatch.setattr(runner, "create_llm_provider", lambda name: llm)
    monkeypatch.setattr(runner.TavilyProvider, "search", AsyncMock(return_value=[]))
    monkeypatch.setattr(runner.TavilyProvider, "close", AsyncMock())
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setattr(runner, "log_event", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(runner, "append_to_index", lambda *args, **kwargs: None, raising=False)

    # Should not raise AssertionError on .paths
    result = asyncio.run(runner.run_deep_research(ctx, "Test"))
    assert result["task_id"]