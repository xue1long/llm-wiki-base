"""Tests for src/mcp_server/memory_tools.py — 5 MCP memory tools.

We test each handler function directly by calling it with mock data.
No running MCP server is needed.
"""
import json
from unittest.mock import MagicMock

import pytest

from src.mcp_server.memory_tools import (
    MEMORY_TOOLS,
    _memory_handlers,
    register_memory_tools,
    _memory_search,
    _memory_recall,
    _memory_explain,
    _memory_verify,
    _memory_update,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_retrieval(search_results=None, recall_result=None):
    """Create a mock MemoryRetrieval."""
    mock = MagicMock()
    if search_results is not None:
        mock.retrieve.return_value = search_results
    if recall_result is not None:
        mock.recall.return_value = recall_result
    return mock


def _make_memory_response(memory_object=None, provenance_chain=None,
                          related_decisions=None, conflicting_claims=None,
                          ranked_results=None, query="", query_type=""):
    """Create a mock MemoryResponse."""
    from src.knowledge.memory.retrieval import MemoryResponse
    return MemoryResponse(
        memory_object=memory_object,
        provenance_chain=provenance_chain,
        related_decisions=related_decisions or [],
        conflicting_claims=conflicting_claims or [],
        ranked_results=ranked_results or [],
        query=query,
        query_type=query_type,
    )


# ---------------------------------------------------------------------------
# Test tool definitions
# ---------------------------------------------------------------------------

def test_memory_tools_count():
    assert len(MEMORY_TOOLS) == 5


def test_all_handlers_registered():
    expected = {
        "ruflo_kb_memory_search",
        "ruflo_kb_memory_recall",
        "ruflo_kb_memory_explain",
        "ruflo_kb_memory_verify",
        "ruflo_kb_memory_update",
    }
    assert set(_memory_handlers.keys()) == expected


def test_memory_search_tool_definition():
    tool = [t for t in MEMORY_TOOLS if t.name == "ruflo_kb_memory_search"][0]
    assert tool.description
    assert tool.inputSchema["type"] == "object"
    assert "query" in tool.inputSchema["required"]
    assert "memory_type" in tool.inputSchema["properties"]


def test_memory_recall_tool_definition():
    tool = [t for t in MEMORY_TOOLS if t.name == "ruflo_kb_memory_recall"][0]
    assert "object_id" in tool.inputSchema["required"]


def test_memory_explain_tool_definition():
    tool = [t for t in MEMORY_TOOLS if t.name == "ruflo_kb_memory_explain"][0]
    assert "object_id" in tool.inputSchema["required"]


def test_memory_verify_tool_definition():
    tool = [t for t in MEMORY_TOOLS if t.name == "ruflo_kb_memory_verify"][0]
    assert "object_id" in tool.inputSchema["required"]


def test_memory_update_tool_definition():
    tool = [t for t in MEMORY_TOOLS if t.name == "ruflo_kb_memory_update"][0]
    assert "object_id" in tool.inputSchema["required"]
    assert "changes" in tool.inputSchema["required"]


def test_memory_tool_names_are_unique():
    """No duplicate names within MEMORY_TOOLS."""
    names = [t.name for t in MEMORY_TOOLS]
    assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# Test memory_search
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_memory_search_returns_results(monkeypatch):
    """Mock MemoryRetrieval → returns MemoryResponse with results."""
    from src.searcher.reranker import RankedResult
    response = _make_memory_response(
        memory_object={"object_id": "obj-1", "title": "Test", "content": "body", "score": 0.9, "source": "vector"},
        ranked_results=[
            RankedResult(object_id="obj-1", title="Test", content="body", score=0.9, source="vector"),
        ],
        query="test query",
        query_type="semantic",
    )
    mock_retrieval = _make_mock_retrieval(search_results=response)
    monkeypatch.setattr("src.mcp_server.memory_tools._memory_retrieval", mock_retrieval)

    result = await _memory_search({"query": "test query"})
    text = json.loads(result[0].text)
    assert text["memory_object"] is not None
    assert text["memory_object"]["object_id"] == "obj-1"
    assert text["query"] == "test query"
    assert text["query_type"] == "semantic"


@pytest.mark.asyncio
async def test_memory_search_with_memory_type_filter(monkeypatch):
    """memory_type parameter is reflected in output metadata."""
    response = _make_memory_response(
        memory_object={"object_id": "obj-1", "title": "T", "content": "C", "score": 0.5, "source": "vector"},
        ranked_results=[],
        query="test",
        query_type="semantic",
    )
    mock_retrieval = _make_mock_retrieval(search_results=response)
    monkeypatch.setattr("src.mcp_server.memory_tools._memory_retrieval", mock_retrieval)

    result = await _memory_search({"query": "test", "memory_type": "decision"})
    text = json.loads(result[0].text)
    assert text["filter_memory_type"] == "decision"


@pytest.mark.asyncio
async def test_memory_search_no_retrieval_configured(monkeypatch):
    """Returns error when memory retrieval is not set up."""
    monkeypatch.setattr("src.mcp_server.memory_tools._memory_retrieval", None)
    result = await _memory_search({"query": "test"})
    text = json.loads(result[0].text)
    assert "error" in text


# ---------------------------------------------------------------------------
# Test memory_recall
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_memory_recall_returns_object(monkeypatch):
    """Mock recall → returns object with provenance."""
    response = _make_memory_response(
        memory_object={"object_id": "obj-1", "title": "T", "content": "C", "score": 1.0, "source": "recall"},
        provenance_chain={"source_path": "/src/doc.md"},
        query="obj-1",
        query_type="recall",
    )
    mock_retrieval = _make_mock_retrieval(recall_result=response)
    monkeypatch.setattr("src.mcp_server.memory_tools._memory_retrieval", mock_retrieval)

    result = await _memory_recall({"object_id": "obj-1"})
    text = json.loads(result[0].text)
    assert text["memory_object"]["object_id"] == "obj-1"
    assert text["provenance_chain"] == {"source_path": "/src/doc.md"}


@pytest.mark.asyncio
async def test_memory_recall_nonexistent(monkeypatch):
    """Mock recall returns empty response → error."""
    response = _make_memory_response(memory_object=None, query="missing")
    mock_retrieval = _make_mock_retrieval(recall_result=response)
    monkeypatch.setattr("src.mcp_server.memory_tools._memory_retrieval", mock_retrieval)

    result = await _memory_recall({"object_id": "missing"})
    text = json.loads(result[0].text)
    assert "error" in text
    assert "not found" in text["error"].lower()


@pytest.mark.asyncio
async def test_memory_recall_no_retrieval(monkeypatch):
    """Returns error when retrieval not configured."""
    monkeypatch.setattr("src.mcp_server.memory_tools._memory_retrieval", None)
    result = await _memory_recall({"object_id": "obj-1"})
    text = json.loads(result[0].text)
    assert "error" in text


# ---------------------------------------------------------------------------
# Test memory_explain
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_memory_explain_returns_provenance(monkeypatch):
    """ProvenanceTracker returns chain."""
    mock_provenance = MagicMock()
    mock_provenance.get_provenance_chain.return_value = {
        "source_path": "/src/doc.md",
        "derived_from": "/src/doc.md",
        "derived_objects": ["obj-1", "obj-2"],
        "source_status": "active",
    }
    monkeypatch.setattr("src.mcp_server.memory_tools._provenance_tracker", mock_provenance)
    monkeypatch.setattr("src.mcp_server.memory_tools._memory_retrieval", None)

    result = await _memory_explain({"object_id": "obj-1"})
    text = json.loads(result[0].text)
    assert text["object_id"] == "obj-1"
    assert text["provenance"]["source_path"] == "/src/doc.md"
    assert text["provenance"]["source_status"] == "active"
    assert len(text["provenance"]["derived_objects"]) == 2


@pytest.mark.asyncio
async def test_memory_explain_fallback_to_recall(monkeypatch):
    """No ProvenanceTracker → falls back to MemoryRetrieval.recall()."""
    monkeypatch.setattr("src.mcp_server.memory_tools._provenance_tracker", None)

    response = _make_memory_response(
        memory_object={"object_id": "obj-1", "title": "T", "content": "C", "score": 1.0, "source": "recall"},
        provenance_chain={"source_path": "/src/doc.md"},
    )
    mock_retrieval = _make_mock_retrieval(recall_result=response)
    monkeypatch.setattr("src.mcp_server.memory_tools._memory_retrieval", mock_retrieval)

    result = await _memory_explain({"object_id": "obj-1"})
    text = json.loads(result[0].text)
    assert text["provenance"]["source_path"] == "/src/doc.md"


@pytest.mark.asyncio
async def test_memory_explain_no_provenance_found(monkeypatch):
    """No provenance tracker and recall has no provenance → error."""
    monkeypatch.setattr("src.mcp_server.memory_tools._provenance_tracker", None)
    response = _make_memory_response(
        memory_object={"object_id": "obj-1", "title": "T", "content": "C", "score": 1.0, "source": "recall"},
        provenance_chain=None,
    )
    mock_retrieval = _make_mock_retrieval(recall_result=response)
    monkeypatch.setattr("src.mcp_server.memory_tools._memory_retrieval", mock_retrieval)

    result = await _memory_explain({"object_id": "obj-1"})
    text = json.loads(result[0].text)
    assert "error" in text


@pytest.mark.asyncio
async def test_memory_explain_provenance_tracker_returns_empty(monkeypatch):
    """ProvenanceTracker returns empty chain → falls back to recall."""
    mock_provenance = MagicMock()
    mock_provenance.get_provenance_chain.return_value = {}
    monkeypatch.setattr("src.mcp_server.memory_tools._provenance_tracker", mock_provenance)

    response = _make_memory_response(
        provenance_chain={"source_path": "/src/fallback.md"},
    )
    mock_retrieval = _make_mock_retrieval(recall_result=response)
    monkeypatch.setattr("src.mcp_server.memory_tools._memory_retrieval", mock_retrieval)

    result = await _memory_explain({"object_id": "obj-1"})
    text = json.loads(result[0].text)
    assert text["provenance"]["source_path"] == "/src/fallback.md"


# ---------------------------------------------------------------------------
# Test memory_verify
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_memory_verify_existing_verified(monkeypatch):
    """Object exists with provenance → verdict 'verified'."""
    response = _make_memory_response(
        memory_object={"object_id": "obj-1", "title": "T", "content": "C", "score": 0.95, "source": "recall"},
        provenance_chain={"source_path": "/src/doc.md"},
    )
    mock_retrieval = _make_mock_retrieval(recall_result=response)
    monkeypatch.setattr("src.mcp_server.memory_tools._memory_retrieval", mock_retrieval)
    monkeypatch.setattr("src.mcp_server.memory_tools._provenance_tracker", None)

    result = await _memory_verify({"object_id": "obj-1"})
    text = json.loads(result[0].text)
    assert text["exists"] is True
    assert text["has_evidence"] is True
    assert text["verdict"] == "verified"
    assert text["confidence"] == 0.95


@pytest.mark.asyncio
async def test_memory_verify_exists_uncertain(monkeypatch):
    """Object exists but no provenance → verdict 'uncertain'."""
    response = _make_memory_response(
        memory_object={"object_id": "obj-2", "title": "T", "content": "C", "score": 0.7, "source": "recall"},
        provenance_chain=None,
    )
    mock_retrieval = _make_mock_retrieval(recall_result=response)
    monkeypatch.setattr("src.mcp_server.memory_tools._memory_retrieval", mock_retrieval)
    monkeypatch.setattr("src.mcp_server.memory_tools._provenance_tracker", None)

    result = await _memory_verify({"object_id": "obj-2"})
    text = json.loads(result[0].text)
    assert text["exists"] is True
    assert text["has_evidence"] is False
    assert text["verdict"] == "uncertain"


@pytest.mark.asyncio
async def test_memory_verify_nonexistent(monkeypatch):
    """Object doesn't exist → verdict 'unverified'."""
    response = _make_memory_response(memory_object=None)
    mock_retrieval = _make_mock_retrieval(recall_result=response)
    monkeypatch.setattr("src.mcp_server.memory_tools._memory_retrieval", mock_retrieval)
    monkeypatch.setattr("src.mcp_server.memory_tools._provenance_tracker", None)

    result = await _memory_verify({"object_id": "missing"})
    text = json.loads(result[0].text)
    assert text["exists"] is False
    assert text["verdict"] == "unverified"


@pytest.mark.asyncio
async def test_memory_verify_with_provenance_tracker(monkeypatch):
    """ProvenanceTracker also contributes to evidence check."""
    response = _make_memory_response(
        memory_object={"object_id": "obj-1", "title": "T", "content": "C", "score": 0.5, "source": "recall"},
        provenance_chain=None,  # recall has no provenance
    )
    mock_retrieval = _make_mock_retrieval(recall_result=response)
    monkeypatch.setattr("src.mcp_server.memory_tools._memory_retrieval", mock_retrieval)

    mock_provenance = MagicMock()
    mock_provenance.get_provenance_chain.return_value = {
        "source_path": "/src/doc.md",
        "derived_objects": ["obj-1", "obj-2", "obj-3"],
    }
    monkeypatch.setattr("src.mcp_server.memory_tools._provenance_tracker", mock_provenance)

    result = await _memory_verify({"object_id": "obj-1"})
    text = json.loads(result[0].text)
    assert text["has_evidence"] is True
    assert text["source_count"] == 3
    assert text["verdict"] == "verified"


# ---------------------------------------------------------------------------
# Test memory_update
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_memory_update_applies_changes(monkeypatch):
    """Valid changes applied to existing object."""
    response = _make_memory_response(
        memory_object={"object_id": "obj-1", "title": "Old Title", "content": "Old", "score": 0.9, "source": "recall"},
    )
    mock_retrieval = _make_mock_retrieval(recall_result=response)
    monkeypatch.setattr("src.mcp_server.memory_tools._memory_retrieval", mock_retrieval)

    result = await _memory_update({
        "object_id": "obj-1",
        "changes": {"title": "New Title", "grade": "A"},
    })
    text = json.loads(result[0].text)
    assert text["status"] == "updated"
    assert text["updated_fields"] == {"title": "New Title", "grade": "A"}
    assert text["updated_object"]["title"] == "New Title"
    assert text["updated_object"]["grade"] == "A"
    # Original field preserved
    assert text["updated_object"]["content"] == "Old"


@pytest.mark.asyncio
async def test_memory_update_rejects_invalid_field(monkeypatch):
    """Trying to change 'id' or 'type' → error."""
    response = _make_memory_response(
        memory_object={"object_id": "obj-1", "title": "T", "content": "C", "score": 0.5, "source": "recall"},
    )
    mock_retrieval = _make_mock_retrieval(recall_result=response)
    monkeypatch.setattr("src.mcp_server.memory_tools._memory_retrieval", mock_retrieval)

    result = await _memory_update({
        "object_id": "obj-1",
        "changes": {"id": "hacked", "type": "concept"},
    })
    text = json.loads(result[0].text)
    assert "error" in text
    assert "restricted" in text["error"].lower()
    assert "allowed_fields" in text


@pytest.mark.asyncio
async def test_memory_update_rejects_lifecycle_field(monkeypatch):
    """Trying to change 'lifecycle' → error."""
    response = _make_memory_response(
        memory_object={"object_id": "obj-1", "title": "T", "content": "C", "score": 0.5, "source": "recall"},
    )
    mock_retrieval = _make_mock_retrieval(recall_result=response)
    monkeypatch.setattr("src.mcp_server.memory_tools._memory_retrieval", mock_retrieval)

    result = await _memory_update({
        "object_id": "obj-1",
        "changes": {"lifecycle": "archived"},
    })
    text = json.loads(result[0].text)
    assert "error" in text
    assert "restricted" in text["error"].lower()


@pytest.mark.asyncio
async def test_memory_update_nonexistent(monkeypatch):
    """Object doesn't exist → error."""
    response = _make_memory_response(memory_object=None)
    mock_retrieval = _make_mock_retrieval(recall_result=response)
    monkeypatch.setattr("src.mcp_server.memory_tools._memory_retrieval", mock_retrieval)

    result = await _memory_update({
        "object_id": "missing",
        "changes": {"title": "New"},
    })
    text = json.loads(result[0].text)
    assert "error" in text


@pytest.mark.asyncio
async def test_memory_update_no_retrieval(monkeypatch):
    """No retrieval → optimistic accept."""
    monkeypatch.setattr("src.mcp_server.memory_tools._memory_retrieval", None)

    result = await _memory_update({
        "object_id": "obj-1",
        "changes": {"grade": "A"},
    })
    text = json.loads(result[0].text)
    assert text["status"] == "updated"
    assert "note" in text  # optimistic note


@pytest.mark.asyncio
async def test_memory_update_accepts_content_field(monkeypatch):
    """Changing 'content' is allowed."""
    response = _make_memory_response(
        memory_object={"object_id": "obj-1", "title": "T", "content": "Old Content", "score": 0.5, "source": "recall"},
    )
    mock_retrieval = _make_mock_retrieval(recall_result=response)
    monkeypatch.setattr("src.mcp_server.memory_tools._memory_retrieval", mock_retrieval)

    result = await _memory_update({
        "object_id": "obj-1",
        "changes": {"content": "New Content"},
    })
    text = json.loads(result[0].text)
    assert text["status"] == "updated"
    assert text["updated_object"]["content"] == "New Content"


# ---------------------------------------------------------------------------
# Test register_memory_tools
# ---------------------------------------------------------------------------

def test_register_memory_tools_sets_state():
    """register_memory_tools sets module-level state correctly."""
    import src.mcp_server.memory_tools as mt

    mock_mr = MagicMock()
    mock_dr = MagicMock()
    mock_pt = MagicMock()

    # Reset state
    mt._memory_retrieval = None
    mt._decision_recorder = None
    mt._provenance_tracker = None

    register_memory_tools(
        mcp_server=MagicMock(),
        memory_retrieval=mock_mr,
        decision_recorder=mock_dr,
        provenance_tracker=mock_pt,
    )

    assert mt._memory_retrieval is mock_mr
    assert mt._decision_recorder is mock_dr
    assert mt._provenance_tracker is mock_pt


def test_register_memory_tools_accepts_none():
    """register_memory_tools with None defaults works."""
    import src.mcp_server.memory_tools as mt
    mt._memory_retrieval = MagicMock()  # set something
    register_memory_tools(MagicMock())
    assert mt._memory_retrieval is None


# ---------------------------------------------------------------------------
# Test old tools unaffected
# ---------------------------------------------------------------------------

def test_memory_tools_dont_overlap_legacy():
    """Memory tools list doesn't include old tool names."""
    memory_names = {t.name for t in MEMORY_TOOLS}
    old_names = {
        "ruflo_kb_status", "ruflo_kb_projects", "ruflo_kb_set_project",
        "ruflo_kb_files", "ruflo_kb_read_file", "ruflo_kb_search",
        "ruflo_kb_ingest", "ruflo_kb_reviews",
    }
    assert memory_names.isdisjoint(old_names)


# ---------------------------------------------------------------------------
# Test dispatcher integration (call_tool routes to memory handlers)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_call_tool_routes_memory_search(monkeypatch):
    """call_tool dispatches ruflo_kb_memory_search to the memory handler."""
    from src.mcp_server.main import call_tool

    # Patch the memory retrieval to return a search result
    response = _make_memory_response(
        memory_object={"object_id": "m1", "title": "Result", "content": "body", "score": 0.8, "source": "search"},
        query="test",
        query_type="semantic",
    )
    mock_retrieval = _make_mock_retrieval(search_results=response)
    monkeypatch.setattr("src.mcp_server.memory_tools._memory_retrieval", mock_retrieval)

    result = await call_tool("ruflo_kb_memory_search", {"query": "test"})
    text = json.loads(result[0].text)
    assert text["memory_object"]["object_id"] == "m1"


@pytest.mark.asyncio
async def test_call_tool_routes_memory_verify(monkeypatch):
    """call_tool dispatches ruflo_kb_memory_verify to the memory handler."""
    from src.mcp_server.main import call_tool

    response = _make_memory_response(
        memory_object={"object_id": "v1", "title": "T", "content": "C", "score": 0.9, "source": "recall"},
        provenance_chain={"source_path": "/src/doc.md"},
    )
    mock_retrieval = _make_mock_retrieval(recall_result=response)
    monkeypatch.setattr("src.mcp_server.memory_tools._memory_retrieval", mock_retrieval)
    monkeypatch.setattr("src.mcp_server.memory_tools._provenance_tracker", None)

    result = await call_tool("ruflo_kb_memory_verify", {"object_id": "v1"})
    text = json.loads(result[0].text)
    assert text["verdict"] == "verified"
