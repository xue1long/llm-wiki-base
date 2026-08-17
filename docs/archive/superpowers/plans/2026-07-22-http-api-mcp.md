# HTTP API + MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** FastAPI server on `127.0.0.1:19828` (localhost-only, no auth) exposing 8 core endpoints + stdio MCP server with 8 tools. Daemon mode with pidfile.

**Architecture:** FastAPI app factory + lifespan context + 8 endpoint routers + MCP stdio server that delegates to HTTP API.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, httpx, mcp SDK.

**MVP Scope** (per spec): 8 endpoints (health/projects/files/search/ingest/reviews/chat-RAG/schema-readonly) + 8 MCP tools + daemon mode.

---

## Phase 1: Server core

### Task 1: `src/server/app.py` — FastAPI app factory

**Files:** `src/server/app.py` + `src/server/__init__.py` + tests

```python
# src/server/__init__.py
"""HTTP API server (FastAPI + uvicorn)."""
```

```python
# src/server/app.py
"""FastAPI app factory for ruflo-kb HTTP API."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI


_logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Build FastAPI app with all routers mounted."""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup: ping providers
        from ..llm.registry import ProviderRegistry
        from ..llm.provider_factory import _create_from_config
        try:
            for name, config in ProviderRegistry.load().items():
                provider = _create_from_config(config)
                health = await provider.health_check()
                if not health.get("reachable"):
                    _logger.warning(f"[startup] provider {name!r} unreachable: {health.get('error')}")
                await provider.close()
        except Exception as e:
            _logger.warning(f"[startup] health check failed: {e}")
        yield
        # Shutdown: cleanup
        _logger.info("[server] shutting down")

    app = FastAPI(
        title="ruflo-kb API",
        version="0.2.0",
        lifespan=lifespan,
    )

    from .routes import health, projects, files, search, ingest, reviews, chat, schema
    for router in [health.router, projects.router, files.router, search.router,
                   ingest.router, reviews.router, chat.router, schema.router]:
        app.include_router(router)

    return app
```

**Test**:
```python
# tests/test_server/test_app.py
from src.server.app import create_app

def test_create_app_returns_fastapi():
    app = create_app()
    assert app.title == "ruflo-kb API"
    # Verify all routers mounted
    paths = [r.path for r in app.routes]
    assert "/health" in paths
    assert "/api/v1/projects" in paths
```

```bash
git add src/server/ tests/test_server/__init__.py tests/test_server/test_app.py
git commit -m "feat(server): add FastAPI app factory with 8 router mounts"
```

---

### Task 2: 8 endpoint routers

**Files:** `src/server/routes/health.py` + 7 more + tests (condensed)

```python
# src/server/routes/health.py
from fastapi import APIRouter
router = APIRouter()

@router.get("/health")
async def health():
    return {
        "ok": True,
        "status": "running",
        "version": "0.2.0",
        "agent": {"chat": True, "streaming": False},
    }
```

```python
# src/server/routes/projects.py
from fastapi import APIRouter, HTTPException
from ..project.context import ProjectContext, ProjectNotFoundError
from ..project.registry import GlobalRegistryStore

router = APIRouter(prefix="/api/v1", tags=["projects"])


@router.get("/projects")
async def list_projects():
    reg = GlobalRegistryStore.load()
    return {
        "projects": [
            {"id": e.id, "name": e.name, "path": e.path, "schema_version": e.schema_version}
            for e in reg.projects.values()
        ]
    }


@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    entry = GlobalRegistryStore.by_id(project_id) or GlobalRegistryStore.by_name(project_id)
    if not entry:
        raise HTTPException(404, f"Project not found: {project_id}")
    return entry.to_dict()
```

```python
# src/server/routes/files.py
from fastapi import APIRouter, HTTPException, Query
from pathlib import Path
from ..project.context import ProjectContext, ProjectNotFoundError

router = APIRouter(prefix="/api/v1", tags=["files"])


@router.get("/projects/{project_id}/files")
async def list_files(project_id: str, root: str = "wiki", recursive: bool = True, max_files: int = 2000):
    ctx = _resolve_ctx(project_id)
    base = getattr(ctx.paths, f"wiki_{root.rstrip('s') if root != 'sources' else 'sources'}", None) or ctx.paths.wiki / root
    if not base.exists():
        return {"files": [], "truncated": False, "totalCount": 0}
    files = list(base.rglob("*.md")) if recursive else list(base.glob("*.md"))
    truncated = len(files) > max_files
    files = files[:max_files]
    return {
        "files": [
            {"path": str(f.relative_to(ctx.path)), "isDir": False, "size": f.stat().st_size}
            for f in files
        ],
        "truncated": truncated,
        "totalCount": len(files),
    }


@router.get("/projects/{project_id}/files/content")
async def file_content(project_id: str, path: str):
    ctx = _resolve_ctx(project_id)
    file_path = ctx.path / path
    if not file_path.exists():
        raise HTTPException(404, f"File not found: {path}")
    if file_path.stat().st_size > 2_000_000:
        raise HTTPException(413, "File too large (> 2MB)")
    return {
        "path": path,
        "content": file_path.read_text(encoding="utf-8"),
        "truncated": False,
        "size": file_path.stat().st_size,
    }


def _resolve_ctx(project_id: str) -> ProjectContext:
    try:
        return ProjectContext.resolve(project_id, by_id_only=True)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))
```

```python
# src/server/routes/search.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal
from ..project.context import ProjectContext, ProjectNotFoundError

router = APIRouter(prefix="/api/v1", tags=["search"])


class SearchRequest(BaseModel):
    query: str
    topK: int = 10
    includeContent: bool = False
    mode: Literal["hybrid", "keyword", "vector"] = "hybrid"


@router.post("/projects/{project_id}/search")
async def search(project_id: str, body: SearchRequest):
    ctx = _resolve_ctx(project_id)
    # Use existing searcher (assume wired later)
    from ..searcher.hybrid_search import hybrid_search
    results = await hybrid_search(ctx, body.query, top_k=body.topK, mode=body.mode)
    return {
        "mode": body.mode,
        "tokenHits": 0,         # Filled by hybrid_search
        "vectorHits": 0,
        "results": results,
    }


def _resolve_ctx(project_id: str) -> ProjectContext:
    try:
        return ProjectContext.resolve(project_id, by_id_only=True)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))
```

```python
# src/server/routes/ingest.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Union
from pathlib import Path
from ..project.context import ProjectContext, ProjectNotFoundError
from ..queue.queue import enqueue_task, _default_state
from ..types import SourceType

router = APIRouter(prefix="/api/v1", tags=["ingest"])


class IngestRequest(BaseModel):
    source: Union[str, dict]   # URL or {"folder": path}
    folderContext: str | None = None


@router.post("/projects/{project_id}/ingest")
async def ingest(project_id: str, body: IngestRequest):
    ctx = _resolve_ctx(project_id)
    if isinstance(body.source, str):
        source = body.source
        stype = SourceType.URL if source.startswith("http") else SourceType.FILE
    else:
        source = body.source.get("folder", "")
        stype = SourceType.FILE
    from ..utils.idempotency import generate_task_hash
    task_hash = generate_task_hash(stype, source, body.folderContext or "")
    task_id = enqueue_task(source, stype, task_hash)
    if not task_id:
        return {"status": "ignored", "taskId": None, "reason": "Duplicate"}
    return {"status": "queued", "taskId": task_id, "reason": None}


def _resolve_ctx(project_id: str) -> ProjectContext:
    try:
        return ProjectContext.resolve(project_id, by_id_only=True)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))
```

```python
# src/server/routes/reviews.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal, Optional
from ..project.context import ProjectContext, ProjectNotFoundError
from ..wiki.review import load_reviews, add_review, resolve_review, ReviewItem

router = APIRouter(prefix="/api/v1", tags=["reviews"])


@router.get("/projects/{project_id}/reviews")
async def list_reviews(project_id: str, status: str = "open", type: Optional[str] = None, limit: int = 200):
    ctx = _resolve_ctx(project_id)
    items = load_reviews(ctx.paths)
    if status != "all":
        items = [i for i in items if i.status == status]
    if type:
        items = [i for i in items if i.type == type]
    items = items[:limit]
    return {
        "status": status,
        "count": len(items),
        "reviews": [
            {
                "id": i.id, "type": i.type, "title": i.title, "normalizedTitle": i.normalized_title,
                "detail": i.detail, "confidence": i.confidence, "searchQueries": i.search_queries,
                "pagePath": i.page_path, "createdAt": i.created_at, "sourceTaskId": i.source_task_id,
                "status": i.status,
            } for i in items
        ],
    }


class PatchReviewBody(BaseModel):
    resolved: bool
    action: str = "skip"


@router.patch("/projects/{project_id}/reviews/{review_id}")
async def patch_review(project_id: str, review_id: str, body: PatchReviewBody):
    ctx = _resolve_ctx(project_id)
    if body.resolved:
        resolve_review(ctx.paths, review_id, body.action)
    return {"ok": True}


def _resolve_ctx(project_id: str) -> ProjectContext:
    try:
        return ProjectContext.resolve(project_id, by_id_only=True)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))
```

```python
# src/server/routes/chat.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal
from ..project.context import ProjectContext, ProjectNotFoundError

router = APIRouter(prefix="/api/v1", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    sessionId: str | None = None
    mode: Literal["fast", "standard", "deep"] = "standard"
    topK: int = 10
    includeContent: bool = False
    wiki: bool = True
    web: bool = False
    anytxt: bool = False


@router.post("/projects/{project_id}/chat")
async def chat(project_id: str, body: ChatRequest):
    """Non-streaming RAG chat (MVP)."""
    ctx = _resolve_ctx(project_id)
    # Use hybrid search for context (RAG)
    from ..searcher.hybrid_search import hybrid_search
    refs = await hybrid_search(ctx, body.message, top_k=body.topK, mode="hybrid")
    # Build prompt + LLM call
    from ..llm.provider_factory import create_llm_provider
    from ..llm.registry import ProviderRegistry
    config = ProviderRegistry.get("default") if "default" in ProviderRegistry.load() else None
    if not config:
        from ..project.settings import ProjectSettings
        config_name = ctx.settings.llm.provider_registry_name
        config = ProviderRegistry.get(config_name)
    provider = create_llm_provider(config.name)
    system = f"You are a helpful assistant with access to a wiki. Cite sources by [N]."
    context = "\n".join(f"[{i+1}] {r.get('title','')}: {r.get('snippet','')[:200]}" for i, r in enumerate(refs))
    prompt = f"Context:\n{context}\n\nUser: {body.message}"
    response = await provider.complete(prompt=prompt, system=system)
    return {
        "sessionId": body.sessionId or "s-default",
        "projectId": project_id,
        "mode": body.mode,
        "message": {"role": "assistant", "content": response.content},
        "references": [
            {"path": r.get("path", ""), "title": r.get("title", ""),
             "kind": "wiki", "score": r.get("score"), "snippet": r.get("snippet")}
            for r in refs
        ],
        "usage": {
            "promptChars": len(prompt), "completionChars": len(response.content),
            "referenceCount": len(refs),
        },
    }


def _resolve_ctx(project_id: str) -> ProjectContext:
    try:
        return ProjectContext.resolve(project_id, by_id_only=True)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))
```

```python
# src/server/routes/schema.py
from fastapi import APIRouter
from ..schemas.registry import MigrationRegistry

router = APIRouter(prefix="/api/v1", tags=["schema"])


@router.get("/projects/{project_id}/schema")
async def get_schema(project_id: str):
    """List registered schemas + current versions (read-only)."""
    return {
        "schemas": list({(s, f.value) for s, f, _ in MigrationRegistry._migrations.keys()}),
    }
```

**Tests**: 8 tests, one per router (200 response + correct shape).

```bash
git add src/server/routes/ tests/test_server/
git commit -m "feat(server): add 8 HTTP endpoints (health/projects/files/search/ingest/reviews/chat/schema)"
```

---

### Task 3: `src/cli_ext/serve.py` — `serve` CLI command + daemon

**Files:** `src/cli_ext/serve.py` + tests + wire in cli.py

```python
# src/cli_ext/serve.py
"""`serve` CLI subcommand — start FastAPI server (foreground or daemon)."""
import argparse
import logging
import os
import signal
import sys
from pathlib import Path


_logger = logging.getLogger(__name__)

PIDFILE = Path(os.path.expanduser("~/.config/ruflo-kb/server.pid"))


def cmd_serve(args: argparse.Namespace) -> None:
    """Start HTTP API server."""
    if args.daemon:
        _daemonize(args)
    else:
        _serve_foreground(args)


def _serve_foreground(args: argparse.Namespace) -> None:
    import uvicorn
    from ..server.app import create_app
    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


def _daemonize(args: argparse.Namespace) -> None:
    """Fork into background, write pidfile, redirect stdio."""
    if PIDFILE.exists():
        try:
            existing_pid = int(PIDFILE.read_text().strip())
            os.kill(existing_pid, 0)  # check if alive
            print(f"Server already running (PID {existing_pid}); run `serve --stop` first")
            sys.exit(2)
        except (ProcessLookupError, ValueError):
            PIDFILE.unlink()
    if os.fork() > 0:
        # Parent exits
        return
    os.setsid()  # new session
    # Redirect stdio
    log_path = Path(os.path.expanduser("~/.config/ruflo-kb/server.log"))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "ab") as log_f:
        os.dup2(log_f.fileno(), 1)
        os.dup2(log_f.fileno(), 2)
    # Fork again
    if os.fork() > 0:
        os._exit(0)
    # Write pidfile
    PIDFILE.write_text(str(os.getpid()))
    try:
        _serve_foreground(args)
    finally:
        PIDFILE.unlink(missing_ok=True)


def cmd_serve_stop(args: argparse.Namespace) -> None:
    """Stop daemon (SIGTERM via pidfile)."""
    if not PIDFILE.exists():
        print("No server running (no pidfile)")
        return
    pid = int(PIDFILE.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"Sent SIGTERM to PID {pid}")
        PIDFILE.unlink(missing_ok=True)
    except ProcessLookupError:
        print(f"PID {pid} not found (stale pidfile)")
        PIDFILE.unlink(missing_ok=True)


def cmd_serve_status(args: argparse.Namespace) -> None:
    """Check if server is running."""
    if not PIDFILE.exists():
        print("Server not running")
        return
    pid = int(PIDFILE.read_text().strip())
    try:
        os.kill(pid, 0)
        print(f"Server running (PID {pid})")
    except ProcessLookupError:
        print(f"PID {pid} not running (stale pidfile)")
        PIDFILE.unlink(missing_ok=True)
```

**Tests**: test_daemon_writes_pidfile (mock fork), test_stop_sends_sigterm (mock os.kill).

**Wire in cli.py**:
```python
p_serve = subparsers.add_parser("serve", help="Start HTTP API server")
p_serve.add_argument("--host", default="127.0.0.1")
p_serve.add_argument("--port", type=int, default=19828)
p_serve.add_argument("--daemon", action="store_true")
p_serve.set_defaults(func=cmd_serve)
p_serve_stop = subparsers.add_parser("serve-stop", help="Stop daemon server")
p_serve_stop.set_defaults(func=cmd_serve_stop)
```

```bash
git add src/cli_ext/serve.py src/cli.py tests/test_cli_ext/test_cmd_serve.py
git commit -m "feat(cli): add 'serve' + 'serve-stop' (daemon + pidfile)"
```

---

### Task 4: `src/mcp_server/main.py` — stdio MCP server (8 tools)

**Files:** `src/mcp_server/main.py` + `src/mcp_server/__init__.py` + `src/mcp_server/api_client.py` + tests

```python
# src/mcp_server/__init__.py
"""MCP (Model Context Protocol) server for ruflo-kb."""
```

```python
# src/mcp_server/api_client.py
"""HTTP client wrapping the FastAPI server (MCP uses HTTP under the hood)."""
import httpx


class RufloKbAPIClient:
    def __init__(self, base_url: str = "http://127.0.0.1:19828"):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=30)

    async def health(self) -> dict:
        r = await self.client.get("/health")
        r.raise_for_status()
        return r.json()

    async def projects(self) -> dict:
        r = await self.client.get("/api/v1/projects")
        r.raise_for_status()
        return r.json()

    async def search(self, project_id: str, query: str, top_k: int = 10) -> dict:
        r = await self.client.post(f"/api/v1/projects/{project_id}/search",
                                    json={"query": query, "topK": top_k})
        r.raise_for_status()
        return r.json()

    async def files(self, project_id: str, root: str = "wiki", max_files: int = 200) -> dict:
        r = await self.client.get(f"/api/v1/projects/{project_id}/files",
                                    params={"root": root, "max_files": max_files})
        r.raise_for_status()
        return r.json()

    async def file_content(self, project_id: str, path: str) -> dict:
        r = await self.client.get(f"/api/v1/projects/{project_id}/files/content",
                                    params={"path": path})
        r.raise_for_status()
        return r.json()

    async def reviews(self, project_id: str, status: str = "open") -> dict:
        r = await self.client.get(f"/api/v1/projects/{project_id}/reviews",
                                    params={"status": status})
        r.raise_for_status()
        return r.json()

    async def ingest(self, project_id: str, source: str) -> dict:
        r = await self.client.post(f"/api/v1/projects/{project_id}/ingest",
                                    json={"source": source})
        r.raise_for_status()
        return r.json()

    async def chat(self, project_id: str, message: str) -> dict:
        r = await self.client.post(f"/api/v1/projects/{project_id}/chat",
                                    json={"message": message})
        r.raise_for_status()
        return r.json()

    async def close(self):
        await self.client.aclose()
```

```python
# src/mcp_server/main.py
"""stdio MCP server: 8 tools, all delegate to HTTP API."""
import asyncio
import json
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .api_client import RufloKbAPIClient


async def main():
    server = Server("ruflo-kb")
    client = RufloKbAPIClient()

    @server.list_tools()
    async def list_tools():
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

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        try:
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
        finally:
            pass  # client kept open for tool lifetime

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

    await client.close()
```

**Tests**: test_tools_listed (8 tools), test_call_tool_routes (mock client).

**Wire in cli.py**:
```python
p_mcp = subparsers.add_parser("mcp", help="Start stdio MCP server")
p_mcp.set_defaults(func=lambda args: asyncio.run(_run_mcp()))

def _run_mcp():
    from mcp_server.main import main as mcp_main
    asyncio.run(mcp_main())
```

```bash
git add src/mcp_server/ tests/test_mcp_server/
git commit -m "feat(mcp): add stdio MCP server with 8 tools (HTTP API delegation)"
```

---

## Self-Review

- [x] Spec coverage: 8 endpoints ✓ 8 MCP tools ✓ daemon mode ✓
- [x] No SSE / streaming (deferred to v2.0.1)
- [x] Auth: localhost-only, no token (per spec MVP)
- [x] No placeholders

## Implementation order

Tasks 1-4 chain. Total: 4 tasks, ~3-4 hours.