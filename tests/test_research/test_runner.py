from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
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
    ctx.path = tmp_path
    ctx.paths = paths  # legacy attribute, may be removed in future
    # ctx.settings.llm.provider_registry_name is gone — runner now uses ProviderRegistry.get_default()

    llm = MagicMock()
    llm.complete = AsyncMock(side_effect=[
        {"queries": ["query one", "query two", "query three"]},
        SimpleNamespace(content="Synthesized findings [1]."),
    ])
    monkeypatch.setattr(runner.ProviderRegistry, "get_default", lambda: SimpleNamespace(name="default"))
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


@pytest.mark.asyncio
async def test_run_deep_research_survives_tavily_http_error_and_task_id_matches_synthesis_stem(
    tmp_path, monkeypatch
):
    """Regression test for task-1 fixes.

    Verifies:
    1. Tavily HTTP errors degrade gracefully (run completes, synthesis still produced).
    2. Path(returned["synthesis_path"]).stem == returned["task_id"]
       so CLI's `research show <task_id>` resolves the file.
    """
    from src.research import runner
    from src.research.providers.tavily import TavilyProvider

    paths = SimpleNamespace(
        root=tmp_path,
        wiki=tmp_path / "wiki",
        wiki_synthesis=tmp_path / "wiki" / "synthesis",
    )
    paths.wiki_synthesis.mkdir(parents=True)
    ctx = MagicMock()
    ctx.path = tmp_path
    ctx.paths = paths  # legacy attribute, may be removed in future
    # ctx.settings.llm.provider_registry_name is gone — runner now uses ProviderRegistry.get_default()

    llm = MagicMock()
    llm.complete = AsyncMock(side_effect=[
        {"queries": ["q1", "q2", "q3"]},
        SimpleNamespace(content="Synthesis despite Tavily failure."),
    ])
    monkeypatch.setattr(runner.ProviderRegistry, "get_default", lambda: SimpleNamespace(name="default"))
    monkeypatch.setattr(runner, "create_llm_provider", lambda name: llm)

    # Don't mock TavilyProvider.search itself — let the real one run so its
    # internal try/except (added in fix #3) catches the simulated HTTP failure.
    # We patch the provider's httpx client.post to raise httpx.ConnectError.
    real_provider = TavilyProvider("test-key")
    real_provider.client = MagicMock()
    real_provider.client.post = AsyncMock(
        side_effect=httpx.ConnectError("Tavily API down")
    )
    real_provider.client.aclose = AsyncMock()
    monkeypatch.setattr(runner, "TavilyProvider", lambda api_key: real_provider)

    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setattr(runner, "log_event", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(runner, "append_to_index", lambda *args, **kwargs: None, raising=False)

    # The run should NOT propagate the Tavily error; it should complete gracefully.
    result = await runner.run_deep_research(ctx, "Test Topic")

    # Synthesis was still produced.
    synthesis = tmp_path / result["synthesis_path"]
    assert synthesis.exists(), "Synthesis file should be written even when Tavily fails"
    body = synthesis.read_text(encoding="utf-8")
    assert "Synthesis despite Tavily failure." in body

    # Sources are empty since Tavily returned [] on error.
    assert result["sources"] == []

    # Fix #1: task_id matches the synthesis filename stem (CLI lookup invariant).
    assert Path(result["synthesis_path"]).stem == result["task_id"], (
        f"task_id ({result['task_id']!r}) must equal synthesis file stem "
        f"({Path(result['synthesis_path']).stem!r}) so `research show <task_id>` resolves."
    )

    # Confirm the CLI's lookup path actually finds the file using task_id.
    cli_lookup = paths.wiki_synthesis / f"{result['task_id']}.md"
    assert cli_lookup.exists(), (
        f"CLI would look for {cli_lookup}; the synthesis file must match."
    )

    # Fix #2: httpx client was closed even on the failure path.
    real_provider.client.aclose.assert_awaited_once()
