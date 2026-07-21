# HTTP API + MCP Server Design Spec

**Date:** 2026-07-21
**Status:** Approved (pending user sign-off)
**Target codebase:** ruflo-kb (Python 3.11+, master @ 1a046f1, post-Project-multi-instancing spec)
**Inspired by:** llm_wiki-main `api_server.rs` (Rust/tiny_http) + `mcp-server/` (Node.js stdio MCP)

## Goal

Expose ruflo-kb to external agents (Claude Code, Codex, custom scripts) via two complementary interfaces:

1. **HTTP API** — FastAPI server on `127.0.0.1:19828` (localhost-only, no auth). 13 endpoints covering project listing, file I/O, search, ingest, reviews, graph, chat (RAG), and lifecycle commands (cascade delete, lint, dedup).
2. **MCP server** — stdio MCP server (`python -m src.cli mcp`) wrapping the HTTP API. 15 tools enabling Claude Code / Codex to discover projects, read wiki content, search, ingest new sources, manage reviews, and chat with the KB.

This spec unlocks the killer feature of llm_wiki-main: external agents (Claude Code, Codex) can directly interact with the KB. The split architecture (HTTP API + stdio MCP) matches llm_wiki-main's pattern, isolates concerns, and enables multi-MCP-client scenarios where two agents share one server.

## Non-goals

- No remote/LAN access by default. Binding to `0.0.0.0` requires explicit two-step confirmation.
- No token-based auth. Localhost-only; user is responsible for firewall.
- No agent loop with tool use (deferred to separate spec). Chat endpoint is RAG-only (search + LLM synthesis).
- No streaming responses in v1.0 (SSE upgrade deferred to v1.1 with backward-compatible response shape).
- No web search / Deep Research integration (depends on separate spec).
- No graph relevance scoring (4-signal model deferred to v2.1). v1 graph returns wikilink-direct edges only.
- No project template marketplace / skill library sharing.
- No metrics endpoint (Prometheus / OpenTelemetry). v1 logs to file only.


## Input Contract

> Reference: [`_input_contracts.md`](_input_contracts.md) for cross-spec dependency map.

**This spec provides** (consumed by other specs):

- FastAPI server on 127.0.0.1:19828
- stdio MCP server (`python -m src.cli mcp`)
- Daemon mode with pidfile management

**This spec requires from other specs**:

- **Project multi-instancing (REQUIRED)**: `ProjectContext`, `ProjectSettings`
- **Wiki v2.0 (REQUIRED)**: search / files / ingest / reviews / chat endpoints
- **Multi-Provider LLM (REQUIRED)**: LLM provider resolution per project
- **Quality Gate (REQUIRED for /quality endpoint)**: `Judgment`, scoring
- **AtomicContext (OPTIONAL)**: for atomic multi-step HTTP handlers

**Phase**: Phase 2 — Core
**Priority**: P0 — MVP

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│ Terminal 1: HTTP server (long-running)                            │
│ $ python -m src.cli serve [--port 19828] [--bind 127.0.0.1]      │
│ $ python -m src.cli serve --daemon                                │
│                                                                  │
│ Process A: uvicorn + FastAPI                                     │
│   /api/v1/health                                                 │
│   /api/v1/projects                                               │
│   /api/v1/projects/{id}/files[?root=&recursive=&max_files=]      │
│   /api/v1/projects/{id}/files/content?path=                      │
│   /api/v1/projects/{id}/search         (POST)                    │
│   /api/v1/projects/{id}/ingest         (POST)                    │
│   /api/v1/projects/{id}/reviews                                   │
│   /api/v1/projects/{id}/reviews/{review_id}  (PATCH)             │
│   /api/v1/projects/{id}/reviews/resolve      (POST)              │
│   /api/v1/projects/{id}/graph                                    │
│   /api/v1/projects/{id}/sources/rescan       (POST)              │
│   /api/v1/projects/{id}/chat                  (POST)              │
│   /api/v1/projects/{id}/chat/{session_id}/cancel (POST)          │
│   /api/v1/projects/{id}/cascade-delete        (POST)             │
│   /api/v1/projects/{id}/lint                  (POST)             │
│   /api/v1/projects/{id}/dedup                 (POST)             │
│                                                                  │
│ Bind 127.0.0.1 only (no auth).                                   │
│ pidfile: ~/.config/ruflo-kb/server.pid                           │
│ log:    ~/.config/ruflo-kb/server.log                            │
└──────────────────────────────────────────────────────────────────┘
                                  ▲
                                  │ HTTP (localhost)
                                  │
┌──────────────────────────────────────────────────────────────────┐
│ Terminal 2: MCP server (one per agent)                           │
│ $ python -m src.cli mcp                                          │
│   (stdio MCP; connects to running server)                        │
│                                                                  │
│ Process B: mcp SDK + stdio transport                             │
│   15 tools (ruflo_kb_*), all delegate to HTTP API                │
└──────────────────────────────────────────────────────────────────┘
```

### Concurrency model

- HTTP server is **async** (asyncio via uvicorn + FastAPI). Each request is a coroutine.
- Project-scoped mutations acquire `with_project_lock(project_id, ...)` to serialize ingest / cascade_delete / lint --fix / dedup / chat.
- Read-only endpoints (search, read_file, graph, reviews list) do **not** take the lock; they can run concurrently.
- The HTTP server is single-process; concurrency within one project is sequential per-project but parallel across projects.

### Daemon mode

`serve --daemon`:
1. Fork the process
2. Detach from controlling terminal
3. Write PID to `~/.config/ruflo-kb/server.pid`
4. Redirect stdout/stderr to `~/.config/ruflo-kb/server.log`
5. Parent exits with code 0

`serve --stop` reads PID file and sends SIGTERM.

`serve --status` checks if PID file's process is alive.

### MCP session semantics

`ruflo_kb_set_project` pins a project to the MCP session:
- All subsequent tool calls in the same session default to the pinned project
- `project_id` parameter in tool calls overrides the pin if provided
- New MCP session starts unpinned; first call without explicit `project_id` uses `current` (= `last_project` from registry)

## Components

### New modules

```
src/server/
├── __init__.py
├── app.py                # FastAPI app factory
├── lifespan.py           # startup/shutdown hooks
├── routes/
│   ├── __init__.py
│   ├── health.py
│   ├── projects.py
│   ├── files.py
│   ├── search.py
│   ├── ingest.py
│   ├── reviews.py
│   ├── graph.py
│   ├── rescan.py
│   ├── chat.py
│   ├── cascade_delete.py
│   ├── lint.py
│   └── dedup.py
├── middleware/
│   ├── __init__.py
│   ├── rate_limit.py     # token bucket per IP (default 120/s)
│   ├── body_limit.py     # per-route body limits (1MB / 40MB chat)
│   ├── bind_guard.py     # reject 0.0.0.0 without allow_lan
│   └── panic_guard.py    # catch exceptions → 500
├── deps.py               # FastAPI DI: resolve_project_ctx(project_id)
├── errors.py             # APIError + handlers
├── models.py             # Pydantic request/response models
├── daemon.py             # --daemon: fork, pidfile, stdio redirect
└── shutdown.py           # SIGTERM/SIGINT handlers

src/mcp_server/
├── __init__.py
├── main.py               # mcp SDK entry (stdio transport)
├── api_client.py         # httpx client wrapping FastAPI server
├── project_binding.py    # session-scoped project pinning
├── tools.py              # tool implementations (delegate to api_client)
└── formatters.py         # human-readable Markdown output

src/cli_ext/
├── serve.py              # cmd_serve, cmd_serve_stop, cmd_serve_status
└── mcp.py                # cmd_mcp

tests/test_server/
├── test_app.py
├── test_health.py
├── test_projects.py
├── test_files.py
├── test_search.py
├── test_ingest.py
├── test_reviews.py
├── test_graph.py
├── test_chat.py
├── test_cascade_delete.py
├── test_lint.py
├── test_dedup.py
├── test_daemon.py
├── test_rate_limit.py
├── test_body_limit.py
└── test_bind_guard.py

tests/test_mcp_server/
├── test_api_client.py
├── test_project_binding.py
├── test_tools.py
└── test_formatters.py

tests/test_cli_ext/
├── test_cmd_serve.py
└── test_cmd_mcp.py

tests/test_integration/
└── test_http_to_mcp_e2e.py
```

### Modified modules

| Path | Change |
|---|---|
| `pyproject.toml` | `dependencies` add `fastapi>=0.110`, `uvicorn>=0.27`, `httpx>=0.26`, `mcp>=1.0` (MCP Python SDK) |
| `src/cli.py` | New `serve` and `mcp` subcommands dispatching to `src/cli_ext/{serve,mcp}.py` |
| `src/project/settings.py` | `ProjectSettings` adds `server: ServerSettings` block |
| `src/project/context.py` | `resolve_project()` adds `by_id_only: bool = False` mode (HTTP/MCP disable CWD/last_project fallback) |
| `src/orchestrator/orchestrator.py` | `Orchestrator.process_for_api(ctx, input_text)` — HTTP-facing entry (returns dict, no stdout output) |

## Data structures

### Settings extension

```python
# src/project/settings.py (additions)
@dataclass
class ServerSettings:
    host: str = "127.0.0.1"
    port: int = 19828
    allow_lan: bool = False                                    # explicit two-step gate
    rate_limit_per_second: int = 120
    in_flight_max: int = 64
    max_body_mb: int = 1
    max_chat_body_mb: int = 40
```

### Pydantic models (request/response)

```python
# src/server/models.py
from pydantic import BaseModel, Field
from typing import Literal

class HealthResponse(BaseModel):
    ok: bool
    status: Literal["starting", "running", "port_conflict", "error"]
    version: str
    agent: dict
    rateLimit: dict
    maxBodyMb: int
    maxChatBodyMb: int

class ProjectEntry(BaseModel):
    id: str
    name: str
    path: str
    schemaVersion: str
    lastOpened: int

class ProjectsResponse(BaseModel):
    projects: list[ProjectEntry]
    currentProject: ProjectEntry | None

class FileNode(BaseModel):
    path: str
    isDir: bool
    size: int | None = None
    modifiedAt: int | None = None
    children: list["FileNode"] | None = None

class FilesResponse(BaseModel):
    files: list[FileNode]
    truncated: bool
    totalCount: int

class FileContentResponse(BaseModel):
    path: str
    content: str
    truncated: bool
    size: int

class SearchRequest(BaseModel):
    query: str
    topK: int = 10
    includeContent: bool = False
    mode: Literal["hybrid", "keyword", "vector"] = "hybrid"

class SearchResult(BaseModel):
    path: str
    title: str
    score: float
    vectorScore: float | None = None
    snippet: str | None = None

class SearchResponse(BaseModel):
    mode: str
    tokenHits: int
    vectorHits: int
    results: list[SearchResult]

class IngestRequest(BaseModel):
    source: str | dict                            # URL / file path / {"folder": path}
    folderContext: str | None = None

class IngestResponse(BaseModel):
    status: Literal["queued", "ignored", "searching"]
    taskId: str | None = None
    reason: str | None = None

class ReviewItem(BaseModel):
    id: str
    type: str
    title: str
    normalizedTitle: str
    detail: str
    confidence: float
    searchQueries: list[str]
    pagePath: str | None
    createdAt: int
    sourceTaskId: str | None
    status: str                                    # "open" | "resolved" | "dismissed"

class ReviewsResponse(BaseModel):
    status: str
    count: int
    reviews: list[ReviewItem]

class PatchReviewRequest(BaseModel):
    resolved: bool
    action: Literal["create-page", "deep-research", "skip", "merge"] | None = None

class BulkResolveRequest(BaseModel):
    ids: list[str]
    action: str

class BulkResolveResponse(BaseModel):
    resolved: int
    notFound: int
    count: int

class GraphNode(BaseModel):
    id: str
    label: str
    type: str
    path: str | None
    linkCount: int

class GraphEdge(BaseModel):
    source: str
    target: str
    weight: float = 1.0
    kind: Literal["direct"] = "direct"

class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]

class RescanResponse(BaseModel):
    newFiles: int
    modifiedFiles: int
    deletedFiles: int
    tasksCreated: int

class ChatRequest(BaseModel):
    message: str
    sessionId: str | None = None
    mode: Literal["fast", "standard", "deep"] = "standard"
    topK: int = 10
    includeContent: bool = False
    wiki: bool = True
    web: bool = False                                # future
    anytxt: bool = False                             # future

class ChatReference(BaseModel):
    path: str
    title: str
    kind: str                                       # "wiki" | "source"
    score: float | None
    snippet: str | None

class ChatUsage(BaseModel):
    promptChars: int
    completionChars: int
    referenceCount: int

class ChatMessage(BaseModel):
    role: Literal["assistant"]
    content: str

class ChatResponse(BaseModel):
    sessionId: str
    projectId: str
    mode: str
    message: ChatMessage
    references: list[ChatReference]
    usage: ChatUsage

class CascadeDeleteRequest(BaseModel):
    taskId: str | None = None
    sourcePath: str | None = None

class LintRequest(BaseModel):
    fix: bool = False
    noLlm: bool = False

class DedupRequest(BaseModel):
    auto: bool = False
    threshold: Literal["low", "medium", "high"] = "low"

class APIError(BaseModel):
    ok: Literal[False] = False
    error: str
    code: str | None = None
```

### Server-side errors

```python
# src/server/errors.py
class APIError(Exception):
    """Base class for HTTP-mapped errors."""
    def __init__(self, status: int, message: str, code: str | None = None):
        self.status = status
        self.message = message
        self.code = code

class ProjectNotFoundAPIError(APIError):
    def __init__(self, project_id: str):
        super().__init__(404, f"Project not found: {project_id}", code="project_not_found")

class ProjectPathMissingAPIError(APIError):
    def __init__(self, path: str):
        super().__init__(503, f"Project path does not exist on disk: {path}", code="project_path_missing")

class BodyTooLargeAPIError(APIError):
    def __init__(self, limit_mb: int):
        super().__init__(413, f"Request body exceeds {limit_mb}MB limit", code="body_too_large")

class RateLimitedAPIError(APIError):
    def __init__(self):
        super().__init__(429, "Too many requests", code="rate_limited")

class ServerBusyAPIError(APIError):
    def __init__(self):
        super().__init__(503, "Server is busy (in-flight limit reached)", code="server_busy")

class ServiceUnavailableAPIError(APIError):
    def __init__(self, message: str):
        super().__init__(503, message, code="service_unavailable")

# Global FastAPI exception handler
async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={"ok": False, "error": exc.message, "code": exc.code}
    )
```

## API endpoints (detail)

### `GET /api/v1/health`

No auth, no params. Always reachable even if API is "disabled" (v1 has no disable flag, but the pattern is preserved from llm_wiki-main).

```json
{
  "ok": true,
  "status": "running",
  "version": "0.2.0",
  "agent": {"chat": true, "streaming": false},
  "rateLimit": {"perSecond": 120, "inFlightMax": 64},
  "maxBodyMb": 1,
  "maxChatBodyMb": 40
}
```

### `GET /api/v1/projects`

```json
{
  "projects": [
    {"id": "550e...", "name": "research", "path": "/home/user/research", "schemaVersion": "v2.0", "lastOpened": 1721558400000}
  ],
  "currentProject": {"id": "550e...", "name": "research", "path": "/home/user/research", ...}
}
```

### `GET /api/v1/projects/{id}/files`

Query: `root=wiki|sources|all` (default `wiki`), `recursive=true` (default `true`), `max_files=2000` (default, hard cap 10000).

```json
{
  "files": [
    {"path": "wiki/index.md", "isDir": false, "size": 1234, "modifiedAt": 1721558400000},
    {"path": "wiki/entities", "isDir": true, "children": [...]}
  ],
  "truncated": false,
  "totalCount": 142
}
```

### `GET /api/v1/projects/{id}/files/content?path=...`

Hard cap 2MB response. Returns 413 if file exceeds limit.

```json
{
  "path": "wiki/entities/backprop.md",
  "content": "---\nid: backprop\n...",
  "truncated": false,
  "size": 1234
}
```

### `POST /api/v1/projects/{id}/search`

Body: `SearchRequest`. Response: `SearchResponse`.

### `POST /api/v1/projects/{id}/ingest`

Body: `IngestRequest`. Source can be:
- String (URL or file path): `{"source": "https://..."}`
- Folder: `{"source": {"folder": "/path/to/folder"}, "folderContext": "papers/energy"}`

Response: `IngestResponse` (`queued` / `ignored` / `searching`).

### `GET /api/v1/projects/{id}/reviews`

Query: `status=unresolved|resolved|all` (default `unresolved`), `type=...` (optional), `limit=200` (default, hard cap 1000).

Response: `ReviewsResponse`.

### `PATCH /api/v1/projects/{id}/reviews/{review_id}`

Body: `PatchReviewRequest`. Response: updated `ReviewItem`.

### `POST /api/v1/projects/{id}/reviews/resolve`

Body: `BulkResolveRequest`. Response: `BulkResolveResponse`.

### `GET /api/v1/projects/{id}/graph`

Query: `q=text` (optional filter), `node_type=entity|concept|source|query|synthesis|comparison` (optional), `limit=500` (default).

**v1 edges are wikilink-direct only** (`kind: "direct"`). 4-signal relevance scoring deferred to v2.1.

Response: `GraphResponse`.

### `POST /api/v1/projects/{id}/sources/rescan`

Body: empty. Response: `RescanResponse`.

### `POST /api/v1/projects/{id}/chat`

Body: `ChatRequest`. Response: `ChatResponse`.

**RAG pipeline**:
1. Hybrid search `wiki/` for top-K references (uses `ctx.settings.search.default_top_k` if `topK` not provided)
2. Build prompt: system (with output_language) + numbered references + user message
3. Call LLM via `LLMProvider.complete()`
4. Return `{message, references, usage}`

**mode → topK mapping**:
- `fast`: topK=5, no LLM re-ranking
- `standard`: topK=10, no re-ranking
- `deep`: topK=20, with optional LLM re-ranking (not in v1)

### `POST /api/v1/projects/{id}/chat/{session_id}/cancel`

Body: empty. Response: 204 No Content.

### `POST /api/v1/projects/{id}/cascade-delete`

Body: `CascadeDeleteRequest` (must specify `taskId` OR `sourcePath`). Acquires `with_project_lock`. Response: `CascadeDeleteResult` (from wiki v2.0 spec).

### `POST /api/v1/projects/{id}/lint`

Body: `LintRequest`. Acquires `with_project_lock` if `fix=True`. Response: `LintReport`.

### `POST /api/v1/projects/{id}/dedup`

Body: `DedupRequest`. Acquires `with_project_lock` if `auto=True`. Response: `{groups: [DuplicateGroup], merged: []}`.

## MCP tools (detail)

| MCP tool | HTTP endpoint | Notes |
|---|---|---|
| `ruflo_kb_status` | `GET /health` | |
| `ruflo_kb_projects` | `GET /projects` | |
| `ruflo_kb_set_project` | (client-side state) | Pins project for session |
| `ruflo_kb_files` | `GET /projects/{id}/files` | Output: Markdown file tree |
| `ruflo_kb_read_file` | `GET /projects/{id}/files/content` | Output: Markdown with path header |
| `ruflo_kb_search` | `POST /projects/{id}/search` | Output: numbered Markdown results with scores |
| `ruflo_kb_ingest` | `POST /projects/{id}/ingest` | Output: status message |
| `ruflo_kb_reviews` | `GET /projects/{id}/reviews` | Output: Markdown review list |
| `ruflo_kb_resolve_review` | `PATCH /projects/{id}/reviews/{rid}` | Output: updated review |
| `ruflo_kb_graph` | `GET /projects/{id}/graph` | Output: Markdown summary with top nodes |
| `ruflo_kb_rescan_sources` | `POST /projects/{id}/sources/rescan` | Output: stats |
| `ruflo_kb_chat` | `POST /projects/{id}/chat` | Output: Markdown response with references |
| `ruflo_kb_cascade_delete` | `POST /projects/{id}/cascade-delete` | Output: Markdown summary of cleanup |
| `ruflo_kb_lint` | `POST /projects/{id}/lint` | Output: Markdown lint report |
| `ruflo_kb_dedup` | `POST /projects/{id}/dedup` | Output: Markdown group list |

**Tool schemas** (input/output) are JSON Schema definitions served by the MCP server. All tool inputs have `project_id` (optional, default = pinned or `current`). All outputs are formatted as Markdown text for LLM-friendly consumption.

**Error mapping** (HTTP → MCP):
- 404 → `McpError(InvalidParams)`
- 413 → `McpError(InvalidParams)` (with body limit hint)
- 429 → `McpError(InternalError)` (with backoff hint)
- 503 → `McpError(InternalError)` (with retry hint)
- 500 → `McpError(InternalError)` (with sanitized message)

## CLI surface

```
python -m src.cli serve [--port 19828] [--bind HOST] [--daemon]
python -m src.cli serve --stop                  # SIGTERM via pidfile
python -m src.cli serve --status                # check pidfile
python -m src.cli serve --log-file PATH         # override default log path

python -m src.cli mcp                            # start stdio MCP server

python -m src.cli config set server.allow_lan true --project research    # before --bind 0.0.0.0
python -m src.cli config set server.port 9000 --project research         # overrides default for next serve
```

`serve` validates:
- `--bind 0.0.0.0` requires `settings.server.allow_lan=true`; else auto-falls-back to 127.0.0.1 with warning
- Port not already bound (try 3 times with 2s backoff)
- pidfile stale → overwrite; pidfile live → error + hint `serve --stop`

`serve --daemon` lifecycle:
1. Fork
2. Parent: write pid, redirect stdio, exit 0
3. Child: drop controlling tty, become session leader
4. Child: run uvicorn

## Security

- Bind 127.0.0.1 by default (no LAN exposure)
- `allow_lan=true` requires explicit config + explicit `--bind` (two-step)
- Body size limits per route
- Rate limit (120 req/s) + in-flight cap (64)
- All handlers wrapped in panic_guard → 500 (never leak stack traces to client)
- All file path resolution uses normalized + relative paths (no traversal)
- `path` parameter in `/files/content` validated against project's allowed dirs (`wiki/`, `raw/sources/`)
- Server log includes request method + path + status + duration (no body content)

## Error handling

| Stage | Error | Strategy |
|---|---|---|
| `serve` startup | Port already bound | Retry 3x with 2s backoff; final fail exits 2 |
| `serve` startup | `--bind 0.0.0.0` + `allow_lan=false` | Auto-revert to 127.0.0.1 + stderr warning |
| `serve --daemon` | Fork fails | Exit 1 |
| `serve --daemon` | pidfile live | Exit 2 + hint `--stop` |
| `serve --stop` | pidfile stale | Clean up pidfile + warning |
| `serve` request | `project_id` UUID not in registry | 404 + hint `project list` |
| `serve` request | Project path missing on disk | 503 + hint update registry |
| `serve` request | Body > limit | 413 |
| `serve` request | > 120 req/s | 429 |
| `serve` request | > 64 in-flight | 503 |
| `serve` request | Handler raises | 500 (sanitized message; full traceback to log) |
| `serve` request | LLM timeout | 504 + retry hint |
| `mcp` startup | `serve` not reachable | Error to stderr + exit 1; hint `serve` first |
| `mcp` tool call | HTTP non-2xx | Throw `McpError` with formatted message |
| `mcp` set_project | Project not found | `McpError(InvalidParams)` |
| API `cascade-delete` | Source missing | 200 + warning in response |
| API `lint --fix` | Auto-fix conflict | 200 + `autoFixed: []` + error in report |
| API `dedup --auto` | LLM detect fails | 200 + fallback report (slug match only) |
| API `chat` | Search returns 0 results | 200 + empty references + LLM-synthesized answer based on user message alone |

## Backwards compatibility

- New subcommands: `serve`, `mcp`, `serve --stop`, `serve --status` — purely additive
- New settings block: `server` — additive (defaults match v1 behavior)
- `ProjectContext.resolve(by_id_only=True)` is opt-in via HTTP/MCP path; CLI behavior unchanged
- All existing CLI subcommands unchanged

## Testing strategy

### Unit tests

| Module | Test focus |
|---|---|
| `src/server/app.py` | FastAPI factory; routes mounted; OpenAPI schema |
| `src/server/middleware/rate_limit.py` | Token bucket; 120 req/s allowed; 121st rejected |
| `src/server/middleware/body_limit.py` | 1MB body OK; 1.1MB rejected; chat route allows 40MB |
| `src/server/middleware/bind_guard.py` | 127.0.0.1 OK; 0.0.0.0 + allow_lan=True OK; 0.0.0.0 + allow_lan=False rejected |
| `src/server/middleware/panic_guard.py` | Raising handler → 500 + log; traceback not leaked |
| `src/server/daemon.py` | Fork success; pidfile write; stdio redirect; stale pidfile cleanup |
| `src/server/routes/*.py` | Each route: happy path; 404; 413; 429; 503 |
| `src/server/deps.py` | `resolve_project_ctx(project_id)` returns ProjectContext or raises ProjectNotFoundAPIError |
| `src/mcp_server/api_client.py` | httpx mock; serialization; timeout; error handling |
| `src/mcp_server/project_binding.py` | Pin/unpin; session isolation; InvalidParams on bad UUID |
| `src/mcp_server/tools.py` | Each tool: happy path; arg validation; HTTP error → McpError mapping |
| `src/mcp_server/formatters.py` | Markdown output; empty results; truncation |
| `src/cli_ext/serve.py` | `--daemon`, `--stop`, `--status`, `--bind 0.0.0.0` validation |
| `src/cli_ext/mcp.py` | Server-alive check; tool registration |

### Integration test

```python
# tests/test_integration/test_http_to_mcp_e2e.py
async def test_full_flow():
    # 1. Spin up uvicorn in subprocess (or in-process via ASGITransport)
    # 2. Spawn MCP server subprocess
    # 3. Send initialize + tools/list + tools/call via stdio
    # 4. Verify response format
    # 5. Verify cross-project isolation
    # 6. Verify daemon lifecycle (spawn --daemon, kill via pidfile, verify cleanup)
```

### Test fixture: isolated config dir

Reuse `tests/_helpers/temp_config_dir.py` from Project spec. HTTP server writes to `~/.config/ruflo-kb/`; tests redirect this to tmpdir.


## MVP Scope / Polish / Deferred

> This section partitions the spec's features into delivery tiers. See [`_input_contracts.md`](_input_contracts.md) for cross-spec context.

### MVP Scope (P0)

- 8 core endpoints: health / projects / files / search / ingest / reviews / chat (RAG) / schema (read-only)
- 8 core MCP tools: status / projects / set_project / files / read_file / search / ingest / reviews
- Auth: localhost-only, no token
- Session CRUD: list / get / delete
- No SSE (deferred)
- Daemon mode: simple fork + pidfile

### Polish (v2.0.1 or later)

- SSE streaming for /chat
- Session cancellation endpoint
- --metrics flag for daemon
- Remaining 5 endpoints (graph / rescan / cascade-delete / lint / dedup)

### Deferred (v2.1+)

- LAN access (allow_lan flag)
- Token-based auth
- SSE for /research, /lint, /dedup

## Implementation order

8 phases, each independently committable:

1. **Foundation** — `src/server/{__init__,app,lifespan,deps,errors,models}.py` + `pyproject.toml` deps + basic `GET /health` route + tests
2. **Middleware** — rate_limit / body_limit / bind_guard / panic_guard + tests
3. **Read-only routes** — projects / files / search / graph / rescan + tests
4. **Mutation routes** — ingest / reviews (list + patch + bulk) / cascade_delete / lint / dedup + tests
5. **Chat route (RAG)** — chat endpoint + cancel + tests
6. **Daemon** — `--daemon` / `--stop` / `--status` + pidfile management + tests
7. **MCP server** — `src/mcp_server/` (main / api_client / project_binding / tools / formatters) + `cmd_mcp` + tests
8. **Integration** — `tests/test_integration/test_http_to_mcp_e2e.py` + end-to-end smoke

Each phase follows TDD per-task rhythm; one commit per task.

## Cost estimation

- New dependencies: `fastapi` (~5MB), `uvicorn` (~3MB), `httpx` (already present), `mcp` (~2MB). Total +~10MB.
- New code: ~2500 lines (server + MCP + tests + integration)
- Migration: zero — purely additive
- Backwards compat: 100%

## Open questions / deferred

- **Streaming chat (SSE)** — defer to v1.1; keep response shape compatible (add `streamUrl` field)
- **Agent loop with tool use** — separate spec; chat endpoint can grow `mode="agent"` later
- **Graph relevance scoring (4-signal)** — v2.1; add edge `weight` field without breaking v1 clients
- **Web search integration** — separate spec; `web` field in chat is reserved but ignored
- **Authentication / multi-user** — v3.0+; current model is single-user local
- **Metrics endpoint (Prometheus)** — v1.1; reuse rate_limit middleware counters
- **Project template marketplace** — out of scope
- **MCP over HTTP/SSE** — out of scope; stdio covers Claude Code / Codex
- **Lan access via reverse proxy** — out of scope; reverse proxy in front of server with TLS

## Dependency graph

```
src/server/app.py ──► src/server/routes/*.py ──► src/server/deps.py ──► src/project/context.py
                   │                              │
                   │                              └─► src/project/registry.py
                   │
                   ├─► src/server/middleware/* ──► src/project/settings.py (read server config)
                   │
                   └─► src/server/daemon.py (separate; uses pidfile in src/project/paths.py)

src/mcp_server/main.py ──► src/mcp_server/tools.py ──► src/mcp_server/api_client.py (httpx)
                                                       │
                                                       └─► src/mcp_server/project_binding.py

src/cli_ext/serve.py ──► src/server/app.py + src/server/daemon.py
src/cli_ext/mcp.py ────► src/mcp_server/main.py

All API routes ──► src/project/context.py (ProjectContext)
                 ──► src/pipeline/* (via ctx-aware stage functions)
                 ──► src/wiki/* (page_writer, cascade_delete, lint, dedup)
                 ──► src/orchestrator/orchestrator.py (process_for_api)
```