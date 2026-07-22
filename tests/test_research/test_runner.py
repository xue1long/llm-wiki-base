from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_run_deep_research_generates_queries_and_writes_synthesis(tmp_path, monkeypatch):
    from src.research import runner

    paths = SimpleNamespace(
        root=tmp_path,
        wiki=tmp_path / "wiki",
        wiki_synthesis=tmp_path / "wiki" / "synthesis",
    )
    paths.wiki_synthesis.mkdir(parents=True)
    ctx = MagicMock()
    ctx.paths = paths
    ctx.settings.llm.provider_registry_name = "test-provider"

    llm = MagicMock()
    llm.complete = AsyncMock(side_effect=[
        {"queries": ["query one", "query two", "query three"]},
        SimpleNamespace(content="Synthesized findings [1]."),
    ])
    monkeypatch.setattr(runner.ProviderRegistry, "get", lambda name: SimpleNamespace(name=name))
    monkeypatch.setattr(runner, "create_llm_provider", lambda name: llm)

    search = AsyncMock(return_value=[
        {"title": "Result", "url": "https://example.com", "snippet": "Evidence"}
    ])
    monkeypatch.setattr(runner.TavilyProvider, "search", search)
    monkeypatch.setattr(runner.TavilyProvider, "close", AsyncMock())
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setattr(runner, "log_event", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(runner, "append_to_index", lambda *args, **kwargs: None, raising=False)

    result = await runner.run_deep_research(ctx, "Test Topic")

    assert result["queries"] == ["query one", "query two", "query three"]
    assert result["sources"] == [
        {"title": "Result", "url": "https://example.com", "snippet": "Evidence"}
    ]
    synthesis = tmp_path / result["synthesis_path"]
    assert synthesis.exists()
    assert "Synthesized findings [1]." in synthesis.read_text(encoding="utf-8")
    assert search.await_count == 3
