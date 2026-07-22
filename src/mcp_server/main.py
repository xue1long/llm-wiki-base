"""stdio MCP server: 8 tools, all delegate to HTTP API."""
import asyncio
import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .api_client import RufloKbAPIClient


# ---------------------------------------------------------------------------
# Module-level singletons (created lazily so tests can monkeypatch _get_client)
# ---------------------------------------------------------------------------

_client: RufloKbAPIClient | None = None


def _get_client() -> RufloKbAPIClient:
    global _client
    if _client is None:
        _client = RufloKbAPIClient()
    return _client


# ---------------------------------------------------------------------------
# Tool definitions and routing (extracted as plain functions for testability)
# ---------------------------------------------------------------------------

def _build_tools() -> list[Tool]:
    return [
        Tool(name="ruflo_kb_status", description="Health check + project list",
             inputSchema={"type": "object", "properties": {}}),
        Tool(name="ruflo_kb_projects", description="List all projects",
             inputSchema={"type": "object", "properties": {}}),
        Tool(name="ruflo_kb_set_project", description="Pin this MCP session to one project",
             inputSchema={"type": "object", "properties": {"project_id": {"type": "string"}}, "required": ["project_id"]}),
        Tool(name="ruflo_kb_files", description="List wiki files",
             inputSchema={"type": "object", "properties": {"project_id": {"type": "string"}, "root": {"type": "string"}}, "required": ["project_id"]}),
        Tool(name="ruflo_kb_read_file", description="Read wiki file",
             inputSchema={"type": "object", "properties": {"project_id": {"type": "string"}, "path": {"type": "string"}}, "required": ["project_id", "path"]}),
        Tool(name="ruflo_kb_search", description="Hybrid search",
             inputSchema={"type": "object", "properties": {"project_id": {"type": "string"}, "query": {"type": "string"}, "top_k": {"type": "integer"}}, "required": ["project_id", "query"]}),
        Tool(name="ruflo_kb_ingest", description="Ingest a source",
             inputSchema={"type": "object", "properties": {"project_id": {"type": "string"}, "source": {"type": "string"}}, "required": ["project_id", "source"]}),
        Tool(name="ruflo_kb_reviews", description="List reviews",
             inputSchema={"type": "object", "properties": {"project_id": {"type": "string"}, "status": {"type": "string"}}, "required": ["project_id"]}),
    ]


def list_tools() -> list[Tool]:
    """Return the 8 tools advertised by this MCP server.

    Kept as a plain function (not a coroutine) so unit tests can call it
    directly without spinning up an asyncio loop.
    """
    return _build_tools()


async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Dispatch a single tool call to the appropriate API client method.

    Returns a list with one ``TextContent`` so the MCP client always sees
    consistent content framing.
    """
    client = _get_client()
    if name == "ruflo_kb_status":
        h = await client.health()
        p = await client.projects()
        return [TextContent(type="text", text=json.dumps({**h, **p}, indent=2))]
    elif name == "ruflo_kb_projects":
        p = await client.projects()
        return [TextContent(type="text", text=json.dumps(p, indent=2))]
    elif name == "ruflo_kb_set_project":
        # No-op for MVP (session-less)
        return [TextContent(type="text", text=json.dumps({"pinned": arguments["project_id"]}))]
    elif name == "ruflo_kb_files":
        f = await client.files(arguments["project_id"], arguments.get("root", "wiki"))
        return [TextContent(type="text", text=json.dumps(f, indent=2))]
    elif name == "ruflo_kb_read_file":
        c = await client.file_content(arguments["project_id"], arguments["path"])
        return [TextContent(type="text", text=c["content"])]
    elif name == "ruflo_kb_search":
        s = await client.search(arguments["project_id"], arguments["query"], arguments.get("top_k", 10))
        return [TextContent(type="text", text=json.dumps(s, indent=2))]
    elif name == "ruflo_kb_ingest":
        r = await client.ingest(arguments["project_id"], arguments["source"])
        return [TextContent(type="text", text=json.dumps(r, indent=2))]
    elif name == "ruflo_kb_reviews":
        r = await client.reviews(arguments["project_id"], arguments.get("status", "open"))
        return [TextContent(type="text", text=json.dumps(r, indent=2))]
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


# ---------------------------------------------------------------------------
# stdio entry point
# ---------------------------------------------------------------------------

async def main():
    """Run the MCP server over stdio.

    Handlers delegate to the module-level ``list_tools``/``call_tool``
    functions so the same routing logic exercised in tests is what runs
    in production.
    """
    server = Server("ruflo-kb")

    @server.list_tools()
    async def _list_tools():
        return list_tools()

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict):
        return await call_tool(name, arguments or {})

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())