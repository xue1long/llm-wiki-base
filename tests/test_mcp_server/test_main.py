"""Tests for src/mcp_server/main.py — stdio MCP server with 8 tools.

We test the tool-routing logic by directly invoking ``list_tools()`` and
``call_tool()`` against a mocked ``RufloKbAPIClient``. The MCP Server object
itself is created once per test (its decorators just register handlers).
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.mcp_server.api_client import RufloKbAPIClient
from src.mcp_server.main import call_tool, list_tools


# ---------------------------------------------------------------------------
# list_tools
# ---------------------------------------------------------------------------

EXPECTED_TOOL_NAMES = {
    "ruflo_kb_status",
    "ruflo_kb_projects",
    "ruflo_kb_set_project",
    "ruflo_kb_files",
    "ruflo_kb_read_file",
    "ruflo_kb_search",
    "ruflo_kb_ingest",
    "ruflo_kb_reviews",
}


def test_list_tools_returns_eight_tools():
    tools = list_tools()
    assert len(tools) == 8
    names = {t.name for t in tools}
    assert names == EXPECTED_TOOL_NAMES


def test_list_tools_each_has_description_and_schema():
    tools = list_tools()
    for tool in tools:
        # MCP requires both fields; missing ones fail at runtime.
        assert tool.description, f"{tool.name} missing description"
        assert tool.inputSchema, f"{tool.name} missing inputSchema"
        assert tool.inputSchema.get("type") == "object"


def test_list_tools_required_fields_marked():
    tools = {t.name: t for t in list_tools()}
    # ruflo_kb_files requires project_id only
    assert tools["ruflo_kb_files"].inputSchema["required"] == ["project_id"]
    # ruflo_kb_search requires project_id + query
    assert set(tools["ruflo_kb_search"].inputSchema["required"]) == {"project_id", "query"}
    # ruflo_kb_set_project requires project_id
    assert tools["ruflo_kb_set_project"].inputSchema["required"] == ["project_id"]
    # ruflo_kb_read_file requires project_id + path
    assert set(tools["ruflo_kb_read_file"].inputSchema["required"]) == {"project_id", "path"}


# ---------------------------------------------------------------------------
# call_tool routing
# ---------------------------------------------------------------------------


def _patch_client(monkeypatch, **return_values):
    """Replace RufloKbAPIClient methods with AsyncMocks returning given dicts."""
    mock = MagicMock(spec=RufloKbAPIClient)
    for method, value in return_values.items():
        setattr(mock, method, AsyncMock(return_value=value))
    # close() is async but we don't assert on it here
    mock.close = AsyncMock()
    monkeypatch.setattr(
        "src.mcp_server.main._get_client", lambda: mock
    )
    return mock


@pytest.mark.asyncio
async def test_call_tool_status_combines_health_and_projects(monkeypatch):
    client = _patch_client(
        monkeypatch,
        health={"ok": True, "status": "running"},
        projects={"projects": ["a", "b"]},
    )
    result = await call_tool("ruflo_kb_status", {})
    client.health.assert_awaited_once()
    client.projects.assert_awaited_once()
    assert len(result) == 1
    assert "ok" in result[0].text
    assert "projects" in result[0].text


@pytest.mark.asyncio
async def test_call_tool_projects_lists(monkeypatch):
    client = _patch_client(monkeypatch, projects={"projects": ["x"]})
    result = await call_tool("ruflo_kb_projects", {})
    client.projects.assert_awaited_once()
    assert "x" in result[0].text


@pytest.mark.asyncio
async def test_call_tool_set_project_noop(monkeypatch):
    _patch_client(monkeypatch)
    result = await call_tool("ruflo_kb_set_project", {"project_id": "proj-42"})
    # No client methods should be called
    assert "proj-42" in result[0].text


@pytest.mark.asyncio
async def test_call_tool_files(monkeypatch):
    client = _patch_client(
        monkeypatch, files={"files": [{"path": "wiki/a.md"}]}
    )
    result = await call_tool(
        "ruflo_kb_files", {"project_id": "p1", "root": "wiki"}
    )
    client.files.assert_awaited_once_with("p1", "wiki")
    assert "wiki/a.md" in result[0].text


@pytest.mark.asyncio
async def test_call_tool_files_default_root(monkeypatch):
    client = _patch_client(monkeypatch, files={"files": []})
    await call_tool("ruflo_kb_files", {"project_id": "p1"})
    client.files.assert_awaited_once_with("p1", "wiki")


@pytest.mark.asyncio
async def test_call_tool_read_file_returns_content_string(monkeypatch):
    client = _patch_client(
        monkeypatch, file_content={"content": "# Hello", "path": "wiki/a.md"}
    )
    result = await call_tool(
        "ruflo_kb_read_file", {"project_id": "p1", "path": "wiki/a.md"}
    )
    client.file_content.assert_awaited_once_with("p1", "wiki/a.md")
    # read_file returns content directly (not json-wrapped)
    assert result[0].text == "# Hello"


@pytest.mark.asyncio
async def test_call_tool_search(monkeypatch):
    client = _patch_client(
        monkeypatch, search={"results": [{"id": "1", "score": 0.9}]}
    )
    result = await call_tool(
        "ruflo_kb_search",
        {"project_id": "p1", "query": "foo", "top_k": 5},
    )
    client.search.assert_awaited_once_with("p1", "foo", 5)
    assert "results" in result[0].text


@pytest.mark.asyncio
async def test_call_tool_search_default_top_k(monkeypatch):
    client = _patch_client(monkeypatch, search={"results": []})
    await call_tool("ruflo_kb_search", {"project_id": "p1", "query": "foo"})
    client.search.assert_awaited_once_with("p1", "foo", 10)


@pytest.mark.asyncio
async def test_call_tool_ingest(monkeypatch):
    client = _patch_client(
        monkeypatch, ingest={"task_id": "t1", "status": "queued"}
    )
    result = await call_tool(
        "ruflo_kb_ingest", {"project_id": "p1", "source": "http://x"}
    )
    client.ingest.assert_awaited_once_with("p1", "http://x")
    assert "queued" in result[0].text


@pytest.mark.asyncio
async def test_call_tool_reviews_default_status(monkeypatch):
    client = _patch_client(monkeypatch, reviews={"reviews": []})
    await call_tool("ruflo_kb_reviews", {"project_id": "p1"})
    client.reviews.assert_awaited_once_with("p1", "open")


@pytest.mark.asyncio
async def test_call_tool_reviews_custom_status(monkeypatch):
    client = _patch_client(monkeypatch, reviews={"reviews": []})
    await call_tool("ruflo_kb_reviews", {"project_id": "p1", "status": "closed"})
    client.reviews.assert_awaited_once_with("p1", "closed")


@pytest.mark.asyncio
async def test_call_tool_unknown_returns_error(monkeypatch):
    _patch_client(monkeypatch)
    result = await call_tool("ruflo_kb_does_not_exist", {})
    assert "Unknown tool" in result[0].text


# ---------------------------------------------------------------------------
# api_client — basic request shape (uses an in-memory mock transport)
# ---------------------------------------------------------------------------


def test_api_client_strips_trailing_slash():
    c = RufloKbAPIClient(base_url="http://example.com/")
    assert c.base_url == "http://example.com"


def test_api_client_default_base_url():
    c = RufloKbAPIClient()
    assert c.base_url == "http://127.0.0.1:19828"