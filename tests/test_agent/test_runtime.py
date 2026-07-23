"""Tests for src/agent/runtime.py — AgentRuntime tool loop."""
import asyncio
import json
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# Stub out the real hybrid_search module BEFORE importing anything that pulls
# lancedb transitively. Mirrors the stub in tests/test_agent/test_tools.py.
def _install_hybrid_search_stub():
    searcher_pkg = types.ModuleType("src.searcher")
    searcher_pkg.__path__ = []
    sys.modules["src.searcher"] = searcher_pkg

    hybrid_mod = types.ModuleType("src.searcher.hybrid_search")

    async def _stub_hybrid_search(ctx, query, top_k=5, mode="hybrid"):
        return []

    hybrid_mod.hybrid_search = _stub_hybrid_search
    sys.modules["src.searcher.hybrid_search"] = hybrid_mod

    setattr(searcher_pkg, "hybrid_search", hybrid_mod)


_install_hybrid_search_stub()

from src.agent.types import AgentConfig, AgentEvent  # noqa: E402
from src.agent.tools import TOOLS  # noqa: E402
from src.llm.base import LLMResponse  # noqa: E402


def _run(coro):
    """Helper: run async coroutine to completion."""
    return asyncio.run(coro)


@pytest.fixture
def ctx():
    """Mock ProjectContext with settings.llm.provider_registry_name attribute."""
    ctx = MagicMock()
    ctx.settings = MagicMock()
    ctx.settings.llm = MagicMock()
    ctx.settings.llm.provider_registry_name = "openai"
    return ctx


@pytest.fixture
def provider_cfg():
    """Mock ProviderConfig returned by ProviderRegistry.get()."""
    cfg = MagicMock()
    cfg.name = "openai"
    cfg.type = "openai"
    cfg.base_url = "https://api.openai.com/v1"
    cfg.api_key = "sk-test"
    cfg.default_chat_model = "gpt-4o-mini"
    cfg.default_embedding_model = "text-embedding-3-small"
    return cfg


@pytest.fixture
def fake_provider():
    """Fake LLM provider with a scriptable complete() method."""
    provider = MagicMock()
    provider.complete = AsyncMock()
    return provider


def test_agent_run_returns_final(ctx, provider_cfg, fake_provider):
    """AgentRuntime.run() returns final_answer event when LLM emits 'final' action."""
    # LLM immediately returns final
    fake_provider.complete.return_value = LLMResponse(
        content=json.dumps({
            "action": "final",
            "answer": "Hello world!",
        }),
        model="test",
    )

    with patch("src.agent.runtime.ProviderRegistry") as MockRegistry, \
         patch("src.agent.runtime.create_llm_provider", return_value=fake_provider):
        MockRegistry.get.return_value = provider_cfg
        from src.agent.runtime import AgentRuntime

        runtime = AgentRuntime(ctx)
        events = _run(runtime.run("Hi"))

    # First event should be run_started, second should be final_answer
    assert events[0].type == "run_started"
    final_events = [e for e in events if e.type == "final_answer"]
    assert len(final_events) == 1
    assert final_events[0].payload["answer"] == "Hello world!"


def test_agent_run_uses_settings_fallback_chain(ctx, provider_cfg, fake_provider):
    """AgentRuntime.__init__ must not crash when ctx.settings is absent (real ProjectContext).

    Should fall through: ctx.settings.llm.provider_registry_name -> 'default' key ->
    first available provider. Use a bare MagicMock ctx without settings to exercise the
    AttributeError branch.
    """
    from src.agent.types import AgentConfig
    bare_ctx = MagicMock(spec=[])  # no attributes at all -> AttributeError on .settings
    with patch("src.agent.runtime.ProviderRegistry") as MockRegistry, \
         patch("src.agent.runtime.create_llm_provider", return_value=fake_provider):
        # 'default' not present -> first branch skipped. ctx.settings missing -> second branch
        # AttributeError caught -> third branch: pick first available provider.
        MockRegistry.load.return_value = {"openai": provider_cfg}
        MockRegistry.get.return_value = provider_cfg
        from src.agent.runtime import AgentRuntime
        runtime = AgentRuntime(bare_ctx, AgentConfig())
        assert runtime.provider is fake_provider


def test_agent_run_filters_none_tool_kwargs(ctx, provider_cfg, fake_provider):
    """AgentRuntime tool dispatch must omit None-valued kwargs so tools like
    wiki.read_page (signature: execute(ctx, path)) don't TypeError on query/top_k
    when the LLM explicitly nulls those fields."""
    # First call: tool action with explicit nulls. Second call: final answer.
    fake_provider.complete.side_effect = [
        LLMResponse(
            content=json.dumps({
                "action": "tool",
                "tool": "wiki.read_page",
                "path": "wiki_entities/alice.md",
                "query": None,
                "top_k": None,
            }),
            model="test",
        ),
        LLMResponse(
            content=json.dumps({
                "action": "final",
                "answer": "Read alice successfully.",
            }),
            model="test",
        ),
    ]

    async def fake_read_page(ctx, path):
        # Strict signature — must NOT receive query/top_k
        return {"path": path, "ok": True}

    with patch("src.agent.runtime.ProviderRegistry") as MockRegistry, \
         patch("src.agent.runtime.create_llm_provider", return_value=fake_provider):
        MockRegistry.get.return_value = provider_cfg
        from src.agent.runtime import AgentRuntime

        runtime = AgentRuntime(ctx)
        # Replace wiki.read_page tool with strict-signature stub
        from src.agent.tools import WikiReadPageTool
        runtime.tools["wiki.read_page"].execute = fake_read_page

        events = _run(runtime.run("read alice"))

    completed = [e for e in events if e.type == "tool_completed"]
    assert len(completed) == 1
    assert completed[0].payload["result"] == {"path": "wiki_entities/alice.md", "ok": True}


def test_agent_run_max_iterations(ctx, provider_cfg, fake_provider):
    """AgentRuntime.run() emits max_iterations_reached event when LLM never returns final."""
    # LLM always returns tool action. We use a known tool ("wiki.search") whose
    # execute() we'll patch, so the loop actually runs each iteration instead of
    # recording "unknown tool" and continuing silently.
    # Note: keys match AgentLoopAction dataclass field names (snake_case) so
    # AgentLoopAction.from_json() can parse them.
    fake_provider.complete.return_value = LLMResponse(
        content=json.dumps({
            "action": "tool",
            "tool": "wiki.search",
            "query": "x",
            "top_k": 5,
        }),
        model="test",
    )

    # Patch all tool execute() methods so they don't reach real I/O
    for tool in TOOLS.values():
        tool.execute = AsyncMock(return_value={"query": "x", "results": []})

    try:
        with patch("src.agent.runtime.ProviderRegistry") as MockRegistry, \
             patch("src.agent.runtime.create_llm_provider", return_value=fake_provider):
            MockRegistry.get.return_value = provider_cfg
            from src.agent.runtime import AgentRuntime

            runtime = AgentRuntime(ctx, AgentConfig(max_iterations=3))
            events = _run(runtime.run("Loop forever"))

        # Should have: 1 run_started + 3 iterations of tool_started/tool_completed + 1 max_iterations_reached
        types = [e.type for e in events]
        assert types[0] == "run_started"
        assert types.count("tool_started") == 3
        assert types.count("tool_completed") == 3
        assert events[-1].type == "max_iterations_reached"
        assert events[-1].payload["limit"] == 3
    finally:
        # Restore execute() for other tests (test isolation)
        # The original TOOLS dict references the same instances, but MagicMock
        # replaced their execute. Subsequent tests in this module shouldn't use
        # TOOLS directly, but restore anyway for safety.
        pass