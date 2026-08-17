# Chat Agent Design Spec

**Date:** 2026-07-21
**Status:** Approved (pending user sign-off)
**Target codebase:** ruflo-kb (Python 3.11+, master @ 64df777, post-quality-gate-v2 spec)
**Inspired by:** llm_wiki-main `src-tauri/src/agent/` (Rust, 3523 lines, 14 builtin tools)

## Goal

Add a true tool-using chat agent to ruflo-kb, accessible via:

- **CLI REPL** (`python -m src.cli chat`) — interactive prompt with rich streaming output + slash commands
- **HTTP SSE** (`POST /api/v1/projects/{id}/chat`) — Server-Sent Events for remote agents
- **MCP** (`ruflo_kb_chat` tool) — for Claude Code / Codex integration

The agent runs a **tool loop** where the LLM emits `AgentLoopAction` JSON each iteration (action="tool" | "final" | "user_input"), the runtime executes the tool (subject to permissions + shell approval), feeds the observation back to the LLM, and continues until the LLM emits "final" or the iteration budget is exhausted.

Built-in tools cover the full llm_wiki-main set: wiki search/read/write, source search, graph search, web search (Tavily + SearXNG), anytxt search, skills loading, workspace file writes, shell execution with approval, deep_research, and final answer generation. Sessions persist per-project to `.llm-wiki/chats/<id>.json` and resume cleanly.

## Non-goals

- No agent observability dashboard / metrics (deferred).
- No skill marketplace / community skill distribution (deferred).
- No cross-project agent runs (deferred — single project per session).
- No image generation / vision input in v1 (deferred).
- No "agent mode" auto-activation in regular ingest pipeline (only triggered explicitly via `chat` command).
- No Firecrawl / Brave / SerpApi / Ollama Web Search providers (only Tavily + SearXNG in v1; others added on demand).
- No agent-vs-agent collaboration.
- No automatic prompt A/B testing (deferred).


## Input Contract

> Reference: [`_input_contracts.md`](_input_contracts.md) for cross-spec dependency map.

**This spec provides** (consumed by other specs):

- `AgentRuntime` + `run_agent_loop`
- `AgentLoopAction` JSON schema
- 14 builtin tools (MVP: 5)
- `ChatSession` persistence (deferred)
- SSE streaming (deferred)

**This spec requires from other specs**:

- **Project multi-instancing (REQUIRED)**: per-project `ProjectContext`
- **Wiki v2.0 (REQUIRED)**: wiki.search / wiki.read_page tools
- **Multi-Provider LLM (REQUIRED)**: streaming + completion
- **AtomicContext (OPTIONAL)**: for atomic chat session commits
- **src/shared/**: `EventName` extended with `agent:*` events

**Phase**: Phase 4 — Advanced
**Priority**: P0 — MVP for HTTP endpoint only

## Architecture

### Pipeline integration

```
CLI REPL / HTTP SSE / MCP
        │
        ▼
ChatSession (.llm-wiki/chats/<id>.json)
        │
        ▼
AgentRuntime.run_agent_loop(ctx, session, message, mode)
        │
        │  while iteration < max_iterations_for_mode:
        │    1. build_agent_context() → system + history + retrieved docs
        │    2. llm.complete_stream(prompt) → async iterator of chunks
        │    3. parse AgentLoopAction from accumulated buffer
        │    4. route action:
        │       - "tool" → check permission → execute → emit AgentEvent
        │       - "final" → save session → return
        │       - "user_input" → request_user_input() → emit response → continue
        │    5. if cost > cost_cap_per_session → break + emit error
        │
        ▼
14 builtin tools (wiki / source / graph / web / anytxt / skills / workspace / shell / deep_research / llm.generate)
        │
        ▼
AgentEvent stream → SSE / MCP notifications / CLI REPL rendering
```

### Lifecycle

- **CLI REPL**: `python -m src.cli chat [--resume SESSION_ID] [--model PRESET]`
- **HTTP**: `POST /api/v1/projects/{id}/chat` returns SSE; `GET /api/v1/projects/{id}/sessions` (list); `GET /api/v1/projects/{id}/sessions/{sid}` (resume); `DELETE /api/v1/projects/{id}/sessions/{sid}` (delete); `POST /api/v1/projects/{id}/sessions/{sid}/cancel` (cancel in-flight run)
- **MCP**: `ruflo_kb_chat(project_id, message, session_id?, mode?, top_k?, skills?)` — returns final answer + tool events; `ruflo_kb_cancel_chat(project_id, session_id)` for cancellation

### Session persistence

`.llm-wiki/chats/<session_id>.json` schema:

```json
{
  "id": "uuid",
  "projectId": "uuid",
  "createdAt": 1721558400000,
  "updatedAt": 1721558600000,
  "activeSkills": ["research-assistant"],
  "messages": [
    {"role": "user", "content": "What is backprop?", "timestamp": 1721558400000},
    {"role": "tool", "toolName": "wiki.search", "toolResult": {...}, "timestamp": 1721558401000},
    {"role": "assistant", "content": "Backprop is...", "timestamp": 1721558402000}
  ],
  "metadata": {
    "totalCostUsd": 0.045,
    "totalPromptTokens": 12500,
    "totalCompletionTokens": 4800,
    "modes": ["standard"],
    "totalIterations": 5
  }
}
```

## Components

### New modules

```
src/agent/
├── __init__.py
├── runtime.py            # AgentRuntime + run_agent_loop
├── tools.py              # 14 builtin tools + ToolSpec + ToolRegistry
├── permissions.py        # AgentCapability + PermissionPolicy
├── providers.py          # Streaming LLM provider abstraction
├── router.py             # input → mode + tools routing
├── context.py            # build_agent_context
├── session.py            # ChatSession persistence
├── events.py             # AgentEvent types + SSE serialization
├── cancel.py             # AgentCancellationToken
├── workspace.py          # .agent-workspace/ directory management
├── skills.py             # project skill scanner
├── user_input.py         # AgentUserInputRequest / Response
├── approval.py           # Shell approval workflow
├── types.py              # AgentMode, AgentLoopAction, AgentReference
├── web_search/
│   ├── __init__.py
│   ├── base.py           # WebSearchProvider protocol
│   ├── tavily.py
│   └── searxng.py
└── prompts/
    ├── __init__.py
    ├── planner.py        # Agent loop prompt
    ├── tool_descriptions.py   # Tool specs as text
    └── synthesis.py      # Final answer prompt

src/cli_ext/
├── chat.py               # cmd_chat (REPL)
└── chat_approval.py      # Interactive shell approval

src/server/
├── chat_sse.py           # SSE endpoint for /chat (extends HTTP API spec)
└── chat_sessions.py      # Session CRUD endpoints

src/mcp_server/
└── (extend with ruflo_kb_chat + ruflo_kb_chat_sessions_*)

tests/test_agent/
├── __init__.py
├── test_runtime.py
├── test_tools.py            # one test per tool
├── test_permissions.py
├── test_session.py
├── test_events.py
├── test_workspace.py
├── test_skills.py
├── test_approval.py
├── test_router.py
├── test_context.py
├── test_user_input.py
├── test_web_search_tavily.py
├── test_web_search_searxng.py
└── test_cost_cap.py

tests/test_cli_ext/test_chat_repl.py
tests/test_integration/test_chat_sse_e2e.py
tests/test_integration/test_agent_loop_e2e.py
```

### Modified modules

| Path | Change |
|---|---|
| `pyproject.toml` | `dependencies` add `rich>=13.0`, `prompt-toolkit>=3.0`, `sse-starlette>=2.0` |
| `src/cli.py` | `chat` subcommand dispatch to `src/cli_ext/chat.py` |
| `src/server/app.py` | Mount `/sessions` routes from `src/server/chat_sessions.py` |
| `src/server/chat.py` (HTTP API spec) | Convert to SSE streaming using `sse-starlette` |
| `src/mcp_server/main.py` | Add `ruflo_kb_chat` + `ruflo_kb_chat_sessions_list/get/delete/cancel` tools |
| `src/project/settings.py` | `ProjectSettings` add `agent: AgentSettings` block |
| `src/llm/base.py` | `LLMProvider` add `complete_stream(prompt, response_format) -> AsyncIterator[str]` |
| `src/llm/openai_provider.py` / `anthropic_provider.py` | Implement `complete_stream` |
| `src/types.py` | `WikiPage` add `agent_modified: bool = False`; `KnowledgeTask` add `chat_session_id: str | None = None` |
| `src/wiki/page_writer.py` | `write_page(path, content, allow_overwrite=False)` |

## 14 Built-in tools

### Read tools

| Tool | Effect | Description | Args |
|---|---|---|---|
| `wiki.search` | Read | Hybrid search wiki/ | `query: str, topK: int = 5` |
| `wiki.read_page` | Read | Read single page (incl. frontmatter) | `path: str` |
| `source.search` | Read | Keyword search raw/sources/ | `query: str, topK: int = 5` |
| `graph.search` | Read | Find neighbors via wikilinks | `query: str, topK: int = 5` |
| `anytxt.search` | Read | Query external AnyTXT JSON-RPC | `query: str, topK: int = 5` |
| `skills.load` | Read | List available project skills | (none) |
| `skill.read_file` | Read | Read reference file from active skill | `skill: str, path: str` |

### Write tools

| Tool | Effect | Description | Args |
|---|---|---|---|
| `wiki.write_page` | Write | Create new page under wiki/ (default create-only) | `path: str, content: str, allowOverwrite: bool = False` |
| `workspace.write_file` | Write | Write to .agent-workspace/ | `path: str, content: str` |
| `workspace.append_file` | Write | Append to .agent-workspace/ | `path: str, content: str` |

### Process tools

| Tool | Effect | Description | Args |
|---|---|---|---|
| `shell.exec` | Process | Run shell command in project workspace | `command: str, timeoutSeconds: int = 30` |

### Network tools

| Tool | Effect | Description | Args |
|---|---|---|---|
| `web.search` | Network | Web search via Tavily or SearXNG | `query: str, topK: int = 5` |
| `deep_research.run` | Network + Read | Multi-source deep research; auto-writes wiki/synthesis/<slug>.md | `query: str, sources: list[str] = ["web", "wiki", "source"]` |

### Coordinator tools

| Tool | Effect | Description | Args |
|---|---|---|---|
| `llm.generate` | Network | Final answer synthesis (internal) | (none) |

### Hard limits (per tool)

| Limit | Value |
|---|---|
| Max read size | 2 MB |
| Max write size | 2 MB |
| Workspace rollback size | 512 KB |
| Shell command length | 4000 chars |
| Shell timeout | 30 s |
| Shell output cap | 20000 chars |
| Web search timeout | 30 s |
| Wiki search topK cap | 10 |
| anytxt search topK cap | 100 |

### Path safety

- **Path traversal**: Reject any path containing `..` or absolute paths.
- **Symlink overwrite**: Reject `workspace.write_file`/`append_file` if target is a symlink.
- **Path scope**:
  - `wiki.write_page` paths must start with `wiki/` and end with `.md`; no hidden segments.
  - `workspace.*` paths must be relative under `.agent-workspace/`; no `wiki/` or `raw/` prefix.
  - `wiki.read_page` paths must start with `wiki/` or be `purpose.md`/`schema.md`; max 2 MB.

## Agent loop

```python
# src/agent/runtime.py
class AgentRuntime:
    def __init__(self, ctx: ProjectContext, llm: LLMProvider, tool_registry: ToolRegistry,
                 workspace: AgentWorkspace, skill_loader: SkillLoader):
        self.ctx = ctx
        self.llm = llm
        self.tool_registry = tool_registry
        self.workspace = workspace
        self.skill_loader = skill_loader
        self.permission_policy = PermissionPolicy.from_settings(ctx.settings.agent)
        self.cost_tracker = CostTracker(cap=ctx.settings.agent.cost_cap_per_session_usd)
    
    async def run_agent_loop(
        self,
        session: ChatSession,
        message: str,
        mode: AgentMode,
        cancellation: AgentCancellationToken | None = None,
    ) -> AsyncIterator[AgentEvent]:
        max_iters = agent_loop_iteration_budget(mode, has_skills=bool(session.active_skills))
        history = session.get_history_for_llm(self.ctx.settings.agent.max_history_messages)
        
        yield AgentEvent.run_started(session.id, mode)
        
        # Add user message to history
        session.add_message("user", message)
        
        for iteration in range(max_iters):
            if cancellation and cancellation.is_cancelled:
                yield AgentEvent.cancelled(iteration)
                return
            
            # 1. Build context
            context = await build_agent_context(
                ctx=self.ctx,
                session=session,
                user_message=message if iteration == 0 else None,
                mode=mode,
            )
            
            # 2. Stream LLM
            buffer = ""
            async for chunk in self.llm.complete_stream(context.prompt, response_format=AgentLoopAction):
                if cancellation and cancellation.is_cancelled:
                    yield AgentEvent.cancelled(iteration)
                    return
                buffer += chunk.delta
                yield AgentEvent.partial_answer(iteration, chunk.delta)
                self.cost_tracker.add(chunk.usage)
            
            # 3. Cost cap check
            if self.cost_tracker.total_usd > self.cost_tracker.cap:
                yield AgentEvent.cost_cap_exceeded(self.cost_tracker.total_usd, self.cost_tracker.cap)
                return
            
            # 4. Parse action
            try:
                action = AgentLoopAction.from_json(buffer)
            except (JSONDecodeError, ValidationError) as e:
                yield AgentEvent.error(iteration, f"Failed to parse LLM response: {e}")
                # Inject corrective prompt and retry
                session.add_message("system", f"Your previous response was not valid JSON: {buffer[:500]}. Please retry with strict JSON matching the AgentLoopAction schema.")
                continue
            
            # 5. Route action
            if action.action == "final":
                yield AgentEvent.final_answer(iteration, action.answer, session.collect_references())
                session.add_message("assistant", action.answer)
                session.metadata["totalCostUsd"] = self.cost_tracker.total_usd
                session.save()
                return
            
            if action.action == "tool":
                yield AgentEvent.tool_started(iteration, action.tool, action.params)
                
                # Permission check
                capability_check = self.permission_policy.capability_for(action.tool)
                if not capability_check.allowed:
                    yield AgentEvent.error(iteration, f"Tool {action.tool} not permitted: {capability_check.reason}")
                    session.add_message("tool", content=f"error: denied ({capability_check.reason})", tool_name=action.tool)
                    continue
                
                # Shell approval
                if action.tool == "shell.exec":
                    approved = await self.request_shell_approval(action.command, action.timeout_seconds)
                    if not approved:
                        yield AgentEvent.shell_denied(iteration, action.command)
                        session.add_message("tool", content="user denied", tool_name=action.tool)
                        continue
                
                # Execute
                try:
                    result = await self.tool_registry.execute(
                        action.tool, action.params, self._build_tool_context())
                    yield AgentEvent.tool_completed(iteration, action.tool, result)
                    session.add_message("tool", content=json.dumps(result, ensure_ascii=False)[:2000], tool_name=action.tool)
                except ToolError as e:
                    yield AgentEvent.error(iteration, str(e))
                    session.add_message("tool", content=f"error: {e}", tool_name=action.tool)
            
            elif action.action == "user_input":
                response = await self.request_user_input(action.fields)
                session.add_message("user", json.dumps(response.answers, ensure_ascii=False))
                continue
            
            else:
                yield AgentEvent.error(iteration, f"Unknown action: {action.action}")
                return
        
        yield AgentEvent.max_iterations_reached(max_iters)
```

### Iteration budget

```python
def agent_loop_iteration_budget(mode: AgentMode, has_skills: bool) -> int:
    base = {
        AgentMode.FAST: 4,
        AgentMode.STANDARD: 8,
        AgentMode.DEEP: 12,
    }[mode]
    return base + (4 if has_skills else 0)
```

### `AgentLoopAction` schema

```python
@dataclass
class AgentLoopAction:
    action: Literal["final", "tool", "user_input"]
    tool: str | None = None
    query: str | None = None
    command: str | None = None
    path: str | None = None
    content: str | None = None
    allow_overwrite: bool = False
    top_k: int = 5
    timeout_seconds: int = 30
    fields: list[dict] | None = None    # for user_input
    answer: str | None = None            # for final
```

JSON Schema (enforced by LLM):
```json
{
  "type": "object",
  "properties": {
    "action": {"enum": ["final", "tool", "user_input"]},
    "tool": {"type": "string"},
    "query": {"type": "string"},
    "command": {"type": "string"},
    "path": {"type": "string"},
    "content": {"type": "string"},
    "allowOverwrite": {"type": "boolean"},
    "topK": {"type": "integer", "minimum": 1, "maximum": 10},
    "timeoutSeconds": {"type": "integer", "minimum": 1, "maximum": 30},
    "fields": {"type": "array"},
    "answer": {"type": "string"}
  },
  "required": ["action"],
  "additionalProperties": false
}
```

## Streaming (SSE) protocol

### HTTP endpoint

`POST /api/v1/projects/{id}/chat` — request body same as HTTP API spec; response is `text/event-stream`.

### SSE event types

```python
class AgentEvent:
    @classmethod
    def run_started(cls, session_id: str, mode: str) -> "AgentEvent":
        return cls(type="run_started", payload={"sessionId": session_id, "mode": mode})
    
    @classmethod
    def tool_started(cls, iteration: int, tool: str, params: dict) -> "AgentEvent": ...
    @classmethod
    def tool_completed(cls, iteration: int, tool: str, result: dict) -> "AgentEvent": ...
    @classmethod
    def partial_answer(cls, iteration: int, delta: str) -> "AgentEvent": ...
    @classmethod
    def final_answer(cls, iteration: int, answer: str, references: list[dict]) -> "AgentEvent": ...
    @classmethod
    def error(cls, iteration: int, message: str) -> "AgentEvent": ...
    @classmethod
    def cancelled(cls, iteration: int) -> "AgentEvent": ...
    @classmethod
    def max_iterations_reached(cls, limit: int) -> "AgentEvent": ...
    @classmethod
    def cost_cap_exceeded(cls, current_usd: float, cap_usd: float) -> "AgentEvent": ...
    @classmethod
    def shell_approval_required(cls, command: str, timeout: int) -> "AgentEvent": ...
    @classmethod
    def shell_denied(cls, iteration: int, command: str) -> "AgentEvent": ...
    @classmethod
    def user_input_required(cls, fields: list[dict]) -> "AgentEvent": ...
```

### SSE wire format

```
data: {"type": "run_started", "sessionId": "abc", "mode": "standard"}

data: {"type": "tool_started", "iteration": 0, "tool": "wiki.search", "params": {"query": "backprop"}}

data: {"type": "tool_completed", "iteration": 0, "tool": "wiki.search", "result": {"mode": "hybrid", "results": [...]}}

data: {"type": "partial_answer", "iteration": 1, "delta": "Looking"}

data: {"type": "partial_answer", "iteration": 1, "delta": " at"}

data: {"type": "final_answer", "iteration": 1, "answer": "Backprop is...", "references": [...]}

data: {"type": "shell_approval_required", "command": "ls -la", "timeout": 10}
data: {"type": "shell_denied", "command": "ls -la"}

data: {"type": "max_iterations_reached", "limit": 8}
data: {"type": "cancelled"}
```

## Session CRUD endpoints (HTTP)

```
GET    /api/v1/projects/{id}/sessions                       # list (id, createdAt, updatedAt, messageCount, preview)
GET    /api/v1/projects/{id}/sessions/{sid}                # full session JSON
DELETE /api/v1/projects/{id}/sessions/{sid}                # delete session file
POST   /api/v1/projects/{id}/sessions/{sid}/cancel         # cancel in-flight run for session
```

## CLI REPL

```
$ python -m src.cli chat [--resume <session_id>] [--model <preset>] [--mode fast|standard|deep]

[ruflo-kb chat] session: abc-123 | mode: standard | tools: 14 enabled | skills: 2 active
> What is backprop?

[→ iter 0] tool wiki.search {query: "backprop"}
[← iter 0] wiki.search: 5 results in 230ms
[→ iter 1] tool wiki.read_page {path: "wiki/concepts/backprop.md"}
[← iter 1] wiki.read_page: 1 page in 50ms

Looking at the wiki...

[← iter 2] final answer in 3.2s:
Backprop is short for backpropagation, a method used in...

references:
  [1] wiki/concepts/backprop.md (score 0.92)
  [2] wiki/concepts/gradient-descent.md (score 0.78)

> /mode deep
[mode] → deep (12 iterations max)

> /skills
[available]: research-assistant, code-reviewer, doc-writer
[active]: research-assistant
> /skill research-assistant code-reviewer
[active] → research-assistant, code-reviewer

> /history
[10 messages in current session]

> /quit
[session saved to .llm-wiki/chats/abc-123.json]
```

Slash commands:
- `/mode fast|standard|deep` — switch iteration budget
- `/skills` — list available skills; `/skill NAME [NAME...]` to activate
- `/shell ls -la` — preview shell policy (no exec)
- `/tools` — list enabled tools
- `/history` — show message history
- `/clear` — clear screen (session preserved)
- `/resume SESSION_ID` — load another session
- `/quit` / `/exit` — save and exit (Ctrl-D also works)

## Web search providers

```python
# src/agent/web_search/base.py
class WebSearchProvider(Protocol):
    async def search(self, query: str, top_k: int) -> list[AgentReference]: ...
    async def close(self) -> None: ...

# src/agent/web_search/tavily.py
class TavilySearchProvider:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=30)
    
    async def search(self, query: str, top_k: int) -> list[AgentReference]:
        response = await self.client.post(
            "https://api.tavily.com/search",
            json={"api_key": self.api_key, "query": query, "max_results": top_k, "search_depth": "advanced"},
        )
        ...

# src/agent/web_search/searxng.py
class SearXNGSearchProvider:
    def __init__(self, base_url: str, categories: list[str] = None):
        self.base_url = base_url.rstrip("/")
        self.categories = categories or ["general"]
        self.client = httpx.AsyncClient(timeout=30)
    
    async def search(self, query: str, top_k: int) -> list[AgentReference]:
        ...
```

`web.search` tool dispatcher:
```python
def get_web_search_provider(settings: AgentSettings) -> WebSearchProvider:
    if settings.web_search_provider == "tavily":
        return TavilySearchProvider(api_key=settings.tavily_api_key)
    if settings.web_search_provider == "searxng":
        return SearXNGSearchProvider(base_url=settings.searxng_url, categories=settings.searxng_categories)
    raise ValueError(f"Unknown provider: {settings.web_search_provider}")
```

## Skills system

```
<project>/.llm-wiki/skills/<name>/
├── SKILL.md              # Required: frontmatter + instructions
└── references/           # Optional: extra files
    ├── types.md
    └── examples.md
```

`SKILL.md` format:
```markdown
---
name: research-assistant
description: Helps with literature research and synthesis
required_tools: ["wiki.search", "web.search"]
optional_tools: ["deep_research.run"]
---

# Research Assistant

You are an expert research assistant. When asked a question:
1. Search wiki first
2. If insufficient, web search
3. Synthesize with citations
```

`skills.load` tool: scans `<project>/.llm-wiki/skills/*/SKILL.md`, parses frontmatter, returns list of skill metadata. Skills must be explicitly activated via `/skill NAME` (CLI REPL) or `chat.skills=[...]` parameter (HTTP/MCP).

`skill.read_file` tool: reads `<project>/.llm-wiki/skills/<name>/references/<filename>`. Path traversal rejected.

## Workspace (.agent-workspace/)

`.agent-workspace/` location: `<project>/.agent-workspace/` (hidden, project-local).

Allowed paths: relative paths under `.agent-workspace/`; no `wiki/` or `raw/` prefix; no hidden segments.

Examples:
- `.agent-workspace/cover.svg` — generated SVG
- `.agent-workspace/report.html` — generated HTML report
- `.agent-workspace/data/2026-07-21-stats.csv` — nested subdirs OK

Tools:
- `workspace.write_file` — create or overwrite (refuses symlinks)
- `workspace.append_file` — append (refuses symlinks)

`.agent-workspace/` content is NOT auto-ingested into wiki. Users explicitly review and `chat.save_to_wiki` if desired (future spec).

## Error handling

| Stage | Error | Strategy |
|---|---|---|
| Runtime init | LLM provider not configured | 502 + hint `python -m src.cli configure --provider openai --openai-key <KEY>` |
| Agent loop | LLM timeout (stream interrupted) | Yield `error` + exit; session saved with partial state |
| Agent loop | Max iterations reached | Yield `max_iterations_reached` + partial final answer if any |
| Agent loop | Cost cap exceeded | Yield `cost_cap_exceeded(current, cap)` + exit |
| Action parse | JSON malformed | Inject corrective prompt into history + continue (1 retry); if 2nd fail → yield error + exit |
| Permission | Tool denied | Yield error with reason; tool observation "denied"; agent continues |
| Shell approval | User denies | Yield `shell_denied`; tool observation "user denied"; agent continues |
| Shell execution | Timeout | Yield `tool_completed` with `timedOut: true` |
| Path traversal | Any tool | Raise `ToolError`; yield `error`; tool observation "path error" |
| File size | read/write > 2MB | Raise `ToolError` |
| Symlink | workspace overwrite | Raise `ToolError` |
| Skill load | Malformed SKILL.md | Warning + skip; other skills still load |
| Session persist | `.llm-wiki/chats/` not writable | Warning; session in-memory only |
| SSE stream | Client disconnects mid-run | Trigger `AgentCancellationToken.cancel()`; partial state saved |
| CLI REPL | EOF (Ctrl-D) | Save session + exit gracefully |
| web.search | Tavily/SearXNG API error | Yield `tool_completed` with `error` field; agent continues |
| deep_research.run | Multi-source failure | Partial results returned; agent sees error per source |

## Backwards compatibility

- New `chat` subcommand: purely additive
- HTTP `/chat` endpoint changes from non-streaming JSON response to SSE streaming: **BREAKING** for clients expecting JSON. Mitigations:
  - Document migration in spec
  - Add `?mode=non_streaming` query param fallback that returns JSON (drops streaming) — covers simple clients
  - Version the endpoint: new clients use `/chat/v2` (SSE); old clients keep `/chat` (JSON)
- New `/sessions` endpoints: purely additive
- New MCP tools: purely additive

## Testing strategy

### Unit tests

| Module | Test focus |
|---|---|
| `src/agent/runtime.py` | run_agent_loop happy path; iteration budget enforcement; cancellation; cost cap |
| `src/agent/tools.py` | one test per tool; size caps; path traversal rejection; symlink rejection |
| `src/agent/permissions.py` | capability check; master switch off; overwrite lock |
| `src/agent/session.py` | create/load/save/delete/list; history truncation; metadata update |
| `src/agent/events.py` | event schema; SSE serialization |
| `src/agent/workspace.py` | path whitelist; symlink rejection; rollback |
| `src/agent/skills.py` | SKILL.md scanner; malformed skip; tool name validation |
| `src/agent/approval.py` | shell approval flow; deny; timeout |
| `src/agent/router.py` | input → mode + tools |
| `src/agent/context.py` | system prompt assembly; history window |
| `src/agent/user_input.py` | field validation; field type constraints |
| `src/agent/web_search/tavily.py` | httpx mock; success + error responses |
| `src/agent/web_search/searxng.py` | httpx mock; success + error responses |
| `src/llm/openai_provider.py` | `complete_stream` async generator |
| `src/llm/anthropic_provider.py` | `complete_stream` async generator |

### Integration tests

```python
# tests/test_integration/test_agent_loop_e2e.py
async def test_simple_qa_no_tools():
    # LLM 直接 final answer
    # Verify: 1 iteration, final_answer event emitted

async def test_search_then_answer():
    # LLM: wiki.search → final
    # Verify: 2+ iterations, tool_started/completed/final_answer

async def test_wiki_write_creates_page():
    # LLM: wiki.write_page → page in wiki/queries/
    # Verify: file exists, frontmatter correct

async def test_shell_exec_approval_granted():
    # Mock: shell approval = True
    # Verify: command executed, exit code in result

async def test_shell_exec_approval_denied():
    # Mock: shell approval = False
    # Verify: shell_denied event; agent continues with observation

async def test_max_iterations_reached():
    # LLM 一直 tool never finalizes
    # Verify: max_iterations_reached event after 8 iterations

async def test_cost_cap_exceeded():
    # Mock LLM with high token count
    # Verify: cost_cap_exceeded event after $0.50

async def test_session_persistence_resume():
    # Create session, add message, save, close
    # Reopen via --resume; verify messages preserved

async def test_sse_event_stream():
    # httpx.AsyncClient with sse parsing
    # Verify: tool_started, partial_answer, final_answer sequence

async def test_repl_basic_flow():
    # spawn chat subprocess; stdin/stdout interaction
    # Verify: exit clean, session file created

async def test_concurrent_sessions():
    # Two parallel sessions in same project
    # Verify: no cross-talk; each session has independent history

async def test_concurrent_runways():
    # Run agent loop while wiki.write_page modifying files
    # Verify: workspace mutex prevents overlap
```

## Cost estimation

Agent turn (standard mode, 4 tool iterations + 1 final):

| Component | Tokens |
|---|---|
| Per-iter LLM call | ~3000 in + 1500 out |
| Tool execution | ~0 (cheap operations) |
| Final synthesis | ~3000 in + 1500 out |

Per turn: 5 LLM calls × ~4500 tokens avg = ~22500 tokens.
Default model (gpt-4o-mini / claude-haiku-4-5): ~$0.025-0.045 per standard turn.
Deep mode (12 iter): ~$0.06-0.10 per turn.

REPL 1-hour chat (10 turns): ~$0.30-0.50.

Cost cap (default 0.5 USD/session) limits runaway.


## MVP Scope / Polish / Deferred

> This section partitions the spec's features into delivery tiers. See [`_input_contracts.md`](_input_contracts.md) for cross-spec context.

### MVP Scope (P0)

- 5 tools only: wiki.search / wiki.read_page / source.search / graph.search / web.search
- HTTP /chat endpoint (non-streaming JSON response)
- 8 iterations max (fast=4 / standard=8 / deep=12)
- No SSE, no REPL, no skills, no workspace, no shell
- No cost cap

### Polish (v2.0.1 or later)

- CLI REPL (`chat`)
- SSE streaming for HTTP
- 9 remaining tools (wiki.write_page / workspace.* / skills.* / shell.exec / deep_research.run / llm.generate)
- Session persistence to `.llm-wiki/chats/`
- Cost cap (0.5 USD/session)

### Deferred (v2.1+)

- Skills marketplace
- Voice I/O
- Sub-agent delegation
- Multi-provider per-task routing

## Implementation order

10 phases, each independently committable:

1. **Foundation** — `src/agent/types.py` + `AgentSettings` + `src/agent/permissions.py` + tests
2. **Tool registry** — `src/agent/tools.py` (read tools first: wiki/source/graph/skill) + tests
3. **Workspace** — `src/agent/workspace.py` + tests
4. **Shell + approval** — `src/agent/approval.py` + `shell.exec` tool + tests
5. **Web search** — `src/agent/web_search/{base,tavily,searxng}.py` + tests
6. **LLM streaming** — `LLMProvider.complete_stream` for OpenAI + Anthropic + tests
7. **Session + events** — `src/agent/session.py` + `src/agent/events.py` + tests
8. **Runtime + context + router** — `src/agent/runtime.py` + `context.py` + `router.py` + tests
9. **CLI REPL** — `src/cli_ext/chat.py` + rich/prompt_toolkit integration + slash commands + tests
10. **HTTP SSE + Sessions CRUD + MCP** — `src/server/chat_sse.py` + `chat_sessions.py` + MCP tools + integration tests

Each phase follows TDD per-task rhythm; one commit per task.

## Cost estimation summary

Total estimated effort: ~3000 lines of new code + ~1500 lines of tests.
Total dependencies added: rich (~3MB) + prompt-toolkit (~1MB) + sse-starlette (~1MB).

## Open questions / deferred (v3.0+)

- **Multi-provider LLM** — additional providers (Google Gemini, Ollama, Custom OpenAI-compatible)
- **Image generation / vision input** — multimodal tools
- **Agent observability dashboard** — cost tracking, iteration histograms, error rates
- **Skill marketplace** — community-contributed skills via Git repos
- **Auto agent mode in ingest** — pipeline-level auto-judging for low-quality pages
- **Cross-project agent runs** — single session spanning multiple KBs
- **Agent-vs-agent collaboration** — sub-agent delegation
- **Streaming tool results** — partial results for long-running tools (e.g. shell.exec)
- **Voice input/output** — speech-to-text / text-to-speech integration
- **Mermaid / SVG generation tools** — explicit tool for generating diagrams
- **Save-to-Wiki from chat** — auto-ingest agent-generated content into wiki/queries/