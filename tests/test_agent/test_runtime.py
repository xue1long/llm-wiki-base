"""Tests for src/agent/runtime.py — AgentRuntime tool loop."""
import asyncio
import json
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# Stub out the real hybrid_search module BEFORE importing anything that pulls
# lancedb transitively. Mirrors the stub in tests/test_agent/test_tools.py.
def _install_hybrid_search_stub():
    """Create a stub for src.searcher.hybrid_search that won't import lancedb,
    but exposes the same names as the real module so subsequent test_searcher
    imports (MAX_TOP_K, rrf_fusion, SearchResult) don't fail. Also stub
    src.searcher.qa and src.searcher.searcher since test_searcher imports from
    those too.
    """
    if getattr(sys.modules.get("lancedb"), "__file__", None) is not None:
        return
    searcher_pkg = types.ModuleType("src.searcher")
    searcher_pkg.__path__ = [str(Path(__file__).parents[2] / "src" / "searcher")]
    sys.modules["src.searcher"] = searcher_pkg

    hybrid_mod = types.ModuleType("src.searcher.hybrid_search")

    async def _stub_hybrid_search(query, top_k=10, paths=None):
        return []

    hybrid_mod.hybrid_search = _stub_hybrid_search
    hybrid_mod.MAX_TOP_K = 100
    hybrid_mod.rrf_fusion = lambda *args, **kwargs: []
    hybrid_mod.SearchResult = dict
    hybrid_mod.get_embedding_provider = (
        __import__("src.llm.embedding_runtime", fromlist=["get_embedding_provider"])
        .get_embedding_provider
    )
    sys.modules["src.searcher.hybrid_search"] = hybrid_mod
    searcher_pkg.hybrid_search = hybrid_mod.hybrid_search

    # Add a module-level logger for tests that assert on it
    import logging as _logging
    hybrid_mod.logger = _logging.getLogger("src.searcher.hybrid_search")

    # Stub src.searcher.qa (test_searcher imports generate_answer from it)
    qa_mod = types.ModuleType("src.searcher.qa")
    async def _stub_generate_answer(*args, **kwargs):
        return ""
    qa_mod.generate_answer = _stub_generate_answer
    sys.modules["src.searcher.qa"] = qa_mod
    searcher_pkg.generate_answer = qa_mod.generate_answer

    # Stub src.searcher.searcher (no public surface; just needs to exist)
    searcher_mod = types.ModuleType("src.searcher.searcher")
    sys.modules["src.searcher.searcher"] = searcher_mod


_install_hybrid_search_stub()




from src.agent.types import AgentConfig  # noqa: E402
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


def test_agent_planner_prompt_preserves_exact_local_search_terms(ctx, provider_cfg, fake_provider):
    fake_provider.complete.return_value = LLMResponse(
        content=json.dumps({"action": "final", "answer": "done"}),
        model="test",
    )

    with patch("src.agent.runtime.ProviderRegistry") as MockRegistry, \
         patch("src.agent.runtime.create_llm_provider", return_value=fake_provider):
        MockRegistry.get.return_value = provider_cfg
        from src.agent.runtime import AgentRuntime

        _run(AgentRuntime(ctx).run("大纲的重要性"))

    prompt = fake_provider.complete.await_args.kwargs["messages"][0]["content"]
    assert "exact distinctive terms" in prompt
    assert "result_count 0" in prompt
    assert "//" not in prompt
    assert '{"action":"final","answer":"..."}' in prompt


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
    fake_provider.complete.side_effect = [
        LLMResponse(
            content=json.dumps({
                "action": "tool",
                "tool": "wiki.search",
                "query": f"x-{i}",
                "top_k": 5,
            }),
            model="test",
        )
        for i in range(3)
    ]

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


def test_planner_observation_is_compact_without_changing_full_result():
    from src.agent.runtime import _planner_observation

    result = {
        "query": "outline",
        "diagnostics": {"backend": "gbrain"},
        "results": [
            {
                "path": f"wiki/concepts/page-{i}.md",
                "title": f"Page {i}",
                "snippet": "x" * 1000,
                "source": "gbrain",
            }
            for i in range(10)
        ],
    }

    observation = json.loads(_planner_observation("wiki.search", result))

    assert observation["backend"] == "gbrain"
    assert observation["result_count"] == 10
    assert len(observation["results"]) == 5
    assert len(observation["results"][0]["snippet"]) <= 240
    assert result["results"][0]["snippet"] == "x" * 1000


def test_planner_observation_keeps_gbrain_content_excerpt():
    from src.agent.runtime import _planner_observation

    observation = json.loads(_planner_observation("wiki.search", {
        "query": "outline",
        "results": [{"path": "wiki/concepts/outline.md", "content": "evidence" * 100}],
    }))

    assert observation["results"][0]["snippet"].startswith("evidence")


def test_planner_observation_tells_agent_to_finalize_after_read():
    from src.agent.runtime import _planner_observation

    observation = json.loads(_planner_observation("wiki.read_page", {
        "id": "outline",
        "title": "Outline",
        "body": "evidence",
    }))

    assert observation["next_step"] == "finalize"


def test_agent_run_repairs_one_malformed_planner_response(ctx, provider_cfg, fake_provider):
    fake_provider.complete.side_effect = [
        LLMResponse(content='{"action":"final"}{"action":"final"}', model="test"),
        LLMResponse(content=json.dumps({"action": "final", "answer": "recovered"}), model="test"),
    ]

    with patch("src.agent.runtime.ProviderRegistry") as MockRegistry, \
         patch("src.agent.runtime.create_llm_provider", return_value=fake_provider):
        MockRegistry.get.return_value = provider_cfg
        from src.agent.runtime import AgentRuntime

        events = _run(AgentRuntime(ctx).run("answer"))

    assert [e.type for e in events].count("tool_completed") == 0
    assert events[-1].type == "final_answer"
    assert "exactly one JSON object" in fake_provider.complete.await_args_list[1].kwargs["messages"][0]["content"]


def test_agent_run_reports_repeated_malformed_planner_response(ctx, provider_cfg, fake_provider):
    fake_provider.complete.side_effect = [
        LLMResponse(content="not json", model="test"),
        LLMResponse(content="still not json", model="test"),
    ]

    with patch("src.agent.runtime.ProviderRegistry") as MockRegistry, \
         patch("src.agent.runtime.create_llm_provider", return_value=fake_provider):
        MockRegistry.get.return_value = provider_cfg
        from src.agent.runtime import AgentRuntime

        events = _run(AgentRuntime(ctx, AgentConfig(max_iterations=4)).run("answer"))

    assert events[-1].type == "agent_planner_protocol_error"
    assert events[-1].payload["attempts"] == 2


def test_agent_run_does_not_repeat_consecutive_identical_tool_call(ctx, provider_cfg, fake_provider):
    fake_provider.complete.side_effect = [
        LLMResponse(content=json.dumps({"action": "tool", "tool": "wiki.search", "query": "x"}), model="test"),
        LLMResponse(content=json.dumps({"action": "tool", "tool": "wiki.search", "query": "x"}), model="test"),
        LLMResponse(content=json.dumps({"action": "final", "answer": "done"}), model="test"),
    ]
    search = AsyncMock(return_value={"query": "x", "results": []})

    with patch("src.agent.runtime.ProviderRegistry") as MockRegistry, \
         patch("src.agent.runtime.create_llm_provider", return_value=fake_provider):
        MockRegistry.get.return_value = provider_cfg
        from src.agent.runtime import AgentRuntime

        runtime = AgentRuntime(ctx)
        runtime.tools["wiki.search"].execute = search
        events = _run(runtime.run("search"))

    assert search.await_count == 1
    assert events[-1].type == "final_answer"
    assert "already completed" in fake_provider.complete.await_args_list[2].kwargs["messages"][0]["content"]


def test_agent_run_reports_persistent_identical_tool_call(ctx, provider_cfg, fake_provider):
    fake_provider.complete.side_effect = [
        LLMResponse(content=json.dumps({"action": "tool", "tool": "wiki.search", "query": "x"}), model="test"),
        LLMResponse(content=json.dumps({"action": "tool", "tool": "wiki.search", "query": "x"}), model="test"),
        LLMResponse(content=json.dumps({"action": "tool", "tool": "wiki.search", "query": "x"}), model="test"),
    ]
    search = AsyncMock(return_value={"query": "x", "results": []})

    with patch("src.agent.runtime.ProviderRegistry") as MockRegistry, \
         patch("src.agent.runtime.create_llm_provider", return_value=fake_provider):
        MockRegistry.get.return_value = provider_cfg
        from src.agent.runtime import AgentRuntime

        runtime = AgentRuntime(ctx, AgentConfig(max_iterations=6))
        runtime.tools["wiki.search"].execute = search
        events = _run(runtime.run("search"))

    assert search.await_count == 1
    assert events[-1].type == "agent_planner_stalled"


def test_agent_run_returns_read_page_body_when_planner_repeats_read(ctx, provider_cfg, fake_provider):
    read_action = json.dumps({
        "action": "tool",
        "tool": "wiki.read_page",
        "path": "wiki/concepts/outline.md",
    })
    fake_provider.complete.side_effect = [
        LLMResponse(content=read_action, model="test"),
        LLMResponse(content=read_action, model="test"),
    ]
    read_page = AsyncMock(return_value={
        "id": "outline",
        "title": "Outline",
        "body": "Grounded page answer.",
    })

    with patch("src.agent.runtime.ProviderRegistry") as MockRegistry, \
         patch("src.agent.runtime.create_llm_provider", return_value=fake_provider):
        MockRegistry.get.return_value = provider_cfg
        from src.agent.runtime import AgentRuntime

        runtime = AgentRuntime(ctx)
        runtime.tools["wiki.read_page"].execute = read_page
        events = _run(runtime.run("read outline"))

    assert read_page.await_count == 1
    assert events[-1].type == "final_answer"
    assert events[-1].payload["answer"] == "Grounded page answer."
