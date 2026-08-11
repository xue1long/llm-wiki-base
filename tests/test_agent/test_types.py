"""Tests for agent type definitions."""
import json

from src.agent.types import AgentLoopAction, AgentEvent, AgentConfig


def test_agent_loop_action_from_json():
    """Test AgentLoopAction.from_json factory method."""
    raw = json.dumps({
        "action": "tool",
        "tool": "search_kb",
        "query": "vector databases",
        "top_k": 10
    })
    obj = AgentLoopAction.from_json(raw)
    assert obj.action == "tool"
    assert obj.tool == "search_kb"
    assert obj.query == "vector databases"
    assert obj.top_k == 10
    assert obj.allow_overwrite is False


def test_agent_loop_action_from_json_tolerates_topk():
    """from_json must tolerate LLM emitting camelCase 'topK' (and any other unknown keys)."""
    # LLM emits camelCase 'topK' (per PLANNER_PROMPT) — must not raise TypeError.
    raw = json.dumps({
        "action": "tool",
        "tool": "wiki.search",
        "query": "x",
        "topK": 7,
        "extraneous": "ignored",
    })
    obj = AgentLoopAction.from_json(raw)
    assert obj.action == "tool"
    assert obj.tool == "wiki.search"
    # topK normalized to top_k
    assert obj.top_k == 7


def test_agent_event_factory():
    """Test AgentEvent factory methods produce well-formed events."""
    # Test run_started
    run_started = AgentEvent.run_started(session_id="session-123", mode="standard")
    assert run_started.type == "run_started"
    assert run_started.iteration == 0
    assert "sessionId" in run_started.payload
    assert run_started.payload["sessionId"] == "session-123"
    assert run_started.payload["mode"] == "standard"

    # Test tool_started
    tool_started = AgentEvent.tool_started(iteration=1, tool="search_kb", params={"q": "test"})
    assert tool_started.type == "tool_started"
    assert tool_started.iteration == 1
    assert tool_started.payload["tool"] == "search_kb"
    assert tool_started.payload["params"] == {"q": "test"}

    # Test tool_completed
    tool_completed = AgentEvent.tool_completed(iteration=1, tool="search_kb", result={"ok": True})
    assert tool_completed.type == "tool_completed"
    assert tool_completed.iteration == 1
    assert tool_completed.payload["tool"] == "search_kb"
    assert tool_completed.payload["result"] == {"ok": True}

    # Test final_answer
    final_answer = AgentEvent.final_answer(iteration=2, answer="The answer is 42", references=["ref1", "ref2"])
    assert final_answer.type == "final_answer"
    assert final_answer.iteration == 2
    assert final_answer.payload["answer"] == "The answer is 42"
    assert final_answer.payload["references"] == ["ref1", "ref2"]


def test_default_config():
    """Test AgentConfig has expected default values."""
    cfg = AgentConfig()
    assert cfg.model == "gpt-4o-mini"
    assert cfg.max_iterations == 8
    assert cfg.cost_cap_usd == 0.5
