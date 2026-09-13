# GBrain MCP 可选 hybrid 搜索试点实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变本项目现有 HTTP 搜索契约的前提下，提供一个默认关闭、可观测、可回退的 GBrain MCP 可选 `hybrid` 搜索试点。试点只验证远程检索接入与安全回退，不替代本项目全部搜索模式，也不承诺 GBrain 与本地 Wiki 的数据一致性已经解决。

**Architecture:** 在 `src/services/search.py` 与现有 `hybrid_search` 之间放置一个窄而深的 GBrain MCP Adapter。Adapter 负责启动 gbrain stdio MCP、调用只读 `search` 工具、解析和规范化结果；服务层只负责后端选择、项目/source 映射和回退。现有路由、`SearchResult` 形状、项目解析和本地过滤逻辑保持不变。试点默认使用本地 backend，远程 backend 必须显式开启。

**Tech Stack:** Python 3.11+, 现有 `mcp==1.28.1`, `httpx`, FastAPI, pytest/pytest-asyncio；GBrain `0.42.58.0`，Bun stdio MCP。

**Spec:** 本文的“方案与契约”章节；GBrain 侧事实依据为 `D:\5-Project\gbrain-master\src\mcp\server.ts`、`src\core\operations.ts`、`docs\architecture\thin-client.md` 和 `docs\mcp\DEPLOY.md`。

## Global Constraints

- 不改变 `POST /api/v1/projects/{project_id}/search` 的请求和响应格式。
- 不新增 Python 依赖；复用现有 MCP SDK。
- 只把 `mode="hybrid"` 且没有 `page_type` 的请求路由到 GBrain；`keyword`、`vector` 和带类型过滤的请求继续走本地实现。
- 本计划的交付物是“可选 hybrid 搜索试点”，不是本项目搜索功能的全量替代；不得以 MCP 调用成功或存在 fallback 宣称替代完成。
- GBrain MCP 只使用只读 `search` 工具，不调用 `query`、写入、同步或文件工具。
- `project_id` 不得猜测为 GBrain `source_id`；必须通过显式映射配置解析，缺失映射时使用本地搜索。
- GBrain 中必须已有与本项目 Wiki 对应的页面、稳定 slug/path 和可用 embedding；否则不启用远程试点，继续使用本地搜索。
- GBrain 子进程、MCP 会话和超时错误不得泄露查询正文、密钥或完整环境变量。
- 现有工作区存在无关脏改动；实施时只能添加/修改本计划列出的文件。

## 方案与契约

### 1. 后端选择

默认保持当前行为：

```text
RUFLO_SEARCH_BACKEND=local       # 默认
RUFLO_SEARCH_BACKEND=gbrain      # 仅启用 hybrid + 无 type 的远程路径
```

启用 GBrain 时，服务层按以下顺序判断：

1. `mode != "hybrid"`：调用现有本地 `hybrid_search`。
2. `page_type` 非空：调用现有本地搜索和过滤。
3. 未配置 `RUFLO_GBRAIN_SOURCE_MAP`：调用本地搜索，并在 diagnostics 中记录 `gbrain_unmapped`。
4. 条件满足：调用 GBrain MCP `search`。
5. GBrain 超时、启动失败、协议错误、工具错误或结果契约不合法：记录安全诊断并回退本地搜索。

远程失败不应把结果变成空列表；只有本地搜索自身返回空列表时才返回空列表。

### 2. 显式项目/source 映射

使用 JSON 环境变量，避免把本项目 UUID 和 GBrain source 隐式绑定：

```text
RUFLO_GBRAIN_SOURCE_MAP={"project-id":"gbrain-source-id"}
RUFLO_GBRAIN_COMMAND=bun
RUFLO_GBRAIN_ARGS=["run","src/cli.ts","serve"]
RUFLO_GBRAIN_CWD=D:\5-Project\gbrain-master
RUFLO_GBRAIN_TIMEOUT_MS=30000
```

实现时允许 `RUFLO_GBRAIN_ARGS` 为 JSON 数组；命令、参数、cwd 必须作为参数传给子进程 API，禁止拼接 shell 字符串或启用 shell。

GBrain stdio server 当前通过 `GBRAIN_SOURCE` 选择 source。因此每次会话启动时，把已解析的 source 写入该子进程环境；不要把 `source_id` 作为未确认的 MCP 参数发送给 `search`。如果后续改用 HTTP MCP，再单独增加 HTTP Adapter，不在本计划中混合两种传输。

### 3. Adapter 接口

新增 `src/searcher/gbrain_mcp.py`，对服务层只暴露一个函数：

```python
async def search(
    query: str,
    top_k: int,
    *,
    source_id: str,
    command: str,
    args: list[str],
    cwd: str,
    timeout_ms: int,
) -> list[SearchResult]:
    raise NotImplementedError
```

Adapter 内部完成：

- 用现有 MCP SDK 的 stdio client 启动 `command args`，工作目录为 `cwd`。
- 完成 MCP initialize。
- 调用工具名 `search`，参数只发送 `query` 和 `limit=top_k`。
- 从 MCP `content` 中读取 JSON；拒绝纯文本、空对象、缺少结果数组或结果字段类型错误。
- 将 GBrain 结果映射为当前 `SearchResult`：`path`、`title`、`content`、`score`、`source="gbrain"`；保留可用的 `evidence`。
- 对 `top_k` 复用本项目现有上限校验；结果最多返回 `top_k` 条。
- 在 `timeout_ms` 内关闭会话和子进程。

结果字段不足时，整个远程结果视为失败并回退本地；不要返回部分格式不明的数据。

### 4. 当前搜索契约的保留

- `ready` / `diagnostics` 仍由本项目服务层产生。
- GBrain 成功时返回 `ready=true`，诊断至少包含 `backend="gbrain"`、`source_id` 的非敏感标识和耗时；不得记录 query 原文。
- `_filter_actionable` 仍然作用于远程结果，前提是 GBrain path 能解析到本地 Wiki 文件；无法解析时放弃远程结果并回退本地。
- 类型过滤请求不走远程，确保现有 frontmatter 语义不变。
- 本地实现继续负责 vector readiness、unsupported writing query abstention 和全部现有安全过滤。

### 5. 数据前提

GBrain 的代码仓库路径只是 MCP server 的启动目录，不等于它的 Brain 数据目录。启用远程后必须先验证：

- GBrain source 中存在本项目需要检索的页面；
- 页面 slug/path 与本项目 Wiki 可建立确定映射；
- GBrain embedding 已完成且维度/模型可用；
- 读 scope 允许 `search`；
- 20 条代表性查询中，远程结果没有出现跨 source 泄漏。

如果任一项不成立，视为试点未就绪，继续使用本地搜索，不自动导入、删除或覆盖数据。

## Implementation Tasks

### Task 1: Freeze the remote search contract

**Files:**
- Create: `tests/test_searcher/test_gbrain_mcp.py`
- Modify: `tests/test_server/test_service_search.py`

**Interfaces:**
- Produces the exact normalized result contract used by Task 2.

- [ ] **Step 1: Write failing tests**

覆盖以下行为：

```python
async def test_gbrain_result_is_normalized(monkeypatch):
    async def fake_call_tool(_query, _limit, _source_id):
        return [{"page_id": "p1", "slug": "wiki/a", "title": "A",
                 "content": "abc", "score": 0.9, "evidence": []}]
    monkeypatch.setattr(gbrain_mcp, "_call_tool", fake_call_tool)
    assert await gbrain_mcp.search("q", 5, source_id="s", command="bun",
                                   args=["run", "src/cli.ts", "serve"],
                                   cwd="D:/5-Project/gbrain-master",
                                   timeout_ms=1000) == [
        {"path": "wiki/a", "title": "A", "content": "abc", "score": 0.9,
         "source": "gbrain", "evidence": []}
    ]

async def test_invalid_tool_payload_is_rejected(monkeypatch):
    async def fake_call_tool(_query, _limit, _source_id):
        return {"results": "not-a-list"}
    monkeypatch.setattr(gbrain_mcp, "_call_tool", fake_call_tool)
    with pytest.raises(gbrain_mcp.GBrainMcpError):
        await gbrain_mcp.search("q", 5, source_id="s", command="bun",
                                args=[], cwd="D:/5-Project/gbrain-master",
                                timeout_ms=1000)

async def test_gbrain_timeout_is_an_error_for_the_caller(monkeypatch):
    async def slow_call_tool(_query, _limit, _source_id):
        await asyncio.sleep(0.05)
    monkeypatch.setattr(gbrain_mcp, "_call_tool", slow_call_tool)
    with pytest.raises(gbrain_mcp.GBrainMcpError, match="timeout"):
        await gbrain_mcp.search("q", 5, source_id="s", command="bun",
                                args=[], cwd="D:/5-Project/gbrain-master",
                                timeout_ms=1)

async def test_service_uses_local_for_keyword_vector_and_type_filter(monkeypatch):
    assert await _search_with_backend("keyword", None) == "local"
    assert await _search_with_backend("vector", None) == "local"
    assert await _search_with_backend("hybrid", "concept") == "local"
```

测试通过 monkeypatch MCP session/process seam，不启动真实 Bun，不触碰当前工作区数据。

- [ ] **Step 2: Run tests and verify they fail**

```powershell
PYTHONPATH=. python -m pytest tests/test_searcher/test_gbrain_mcp.py tests/test_server/test_service_search.py -v --import-mode=importlib
```

Expected: new adapter tests fail because the module/interface does not exist；既有本地搜索测试不得因本任务预期而被改成远程测试。

- [ ] **Step 3: Commit**

```powershell
git add tests/test_searcher/test_gbrain_mcp.py tests/test_server/test_service_search.py
git commit -m "test: define gbrain MCP search contract"
```

### Task 2: Implement the stdio MCP Adapter

**Files:**
- Create: `src/searcher/gbrain_mcp.py`
- Modify: `tests/test_searcher/test_gbrain_mcp.py`

**Interfaces:**
- Consumes: the configuration and `source_id` from Task 1.
- Produces: `search(query, top_k, *, source_id, command, args, cwd, timeout_ms) -> list[SearchResult]`.

- [ ] **Step 1: Implement only the smallest adapter**

实现单次请求单次 stdio 会话；不引入连接池、缓存、重试队列或新的抽象层。MCP 工具调用参数固定为：

```python
{"query": query, "limit": top_k}
```

子进程环境只增加 `GBRAIN_SOURCE=source_id`，并继承必要的基础环境；不把 token 写入日志。

- [ ] **Step 2: Run focused tests**

```powershell
PYTHONPATH=. python -m pytest tests/test_searcher/test_gbrain_mcp.py -v --import-mode=importlib
```

Expected: all adapter contract tests pass。

- [ ] **Step 3: Commit**

```powershell
git add src/searcher/gbrain_mcp.py tests/test_searcher/test_gbrain_mcp.py
git commit -m "feat(search): add gbrain stdio MCP adapter"
```

### Task 3: Add service routing and safe fallback

**Files:**
- Modify: `src/services/search.py`
- Modify: `tests/test_server/test_service_search.py`

**Interfaces:**
- Consumes: `gbrain_mcp.search` from Task 2.
- Produces: unchanged `search(project_id, query, top_k, mode, page_type) -> dict` response.

- [ ] **Step 1: Add failing routing tests**

至少验证：

```python
test_gbrain_backend_routes_hybrid_search
test_gbrain_failure_falls_back_to_local_search
test_unmapped_project_falls_back_without_guessing_source
test_page_type_never_uses_gbrain_backend
```

- [ ] **Step 2: Implement routing**

只在 `RUFLO_SEARCH_BACKEND=gbrain`、`mode="hybrid"`、无 `page_type` 且有显式 source 映射时调用 Adapter。Adapter 异常统一转为本地回退；本地回退失败时才让原有异常处理生效。

配置解析失败、source map 不是 JSON 对象、project 映射不是字符串、timeout 非正整数时，按未启用 GBrain 处理并写入非敏感 diagnostics，不启动子进程。

- [ ] **Step 3: Run focused tests**

```powershell
PYTHONPATH=. python -m pytest tests/test_server/test_service_search.py tests/test_server/test_search_mode_contract.py -v --import-mode=importlib
```

Expected: new routing tests and all existing search service tests pass。

- [ ] **Step 4: Commit**

```powershell
git add src/services/search.py tests/test_server/test_service_search.py
git commit -m "feat(search): route hybrid queries through gbrain MCP"
```

### Task 4: Add operator documentation and verification

**Files:**
- Create: `docs/guides/gbrain-mcp-search.md`
- Modify: `docs/superpowers/plans/2026-09-12-gbrain-mcp-search-adapter.md`

**Interfaces:**
- Documents the environment contract, data prerequisite, smoke test and rollback.

- [ ] **Step 1: Document setup**

包含 Windows PowerShell 配置示例、GBrain source 映射、启动目录、只读权限、失败回退和关闭方式。明确说明 `D:\5-Project\gbrain-master` 是 server 代码目录，不自动代表数据已经存在于 GBrain Brain。

- [ ] **Step 2: Run static and regression checks**

```powershell
PYTHONPATH=. python -m pytest tests/test_searcher tests/test_server tests/test_mcp_server -v --import-mode=importlib
python -m py_compile src/searcher/gbrain_mcp.py src/services/search.py
git diff --check
```

- [ ] **Step 3: Run one real read-only smoke test**

前置条件：GBrain 已有测试 source、embedding 和可检索页面。使用一个不含敏感内容的查询，确认：MCP initialize 成功、`search` 返回合法数组、结果 path 可映射到本地 Wiki、服务响应仍符合原 JSON 形状。不得执行写入工具。

- [ ] **Step 4: Commit**

```powershell
git add docs/guides/gbrain-mcp-search.md docs/superpowers/plans/2026-09-12-gbrain-mcp-search-adapter.md
git commit -m "docs(search): document gbrain MCP backend"
```

## Acceptance Criteria

以下验收标准只证明“可选 hybrid 搜索试点”可控，不证明本项目搜索已被 GBrain 全量替代。

- 默认配置下，所有既有搜索测试和行为不变。
- GBrain 配置完整且映射明确时，`hybrid` 查询确实调用 MCP `search`，并返回当前 API 的 `results` 结构。
- GBrain 不可用、超时、source 未映射、工具响应非法时，查询在一个有限超时内回退本地搜索，不返回误导性的空结果。
- `keyword`、`vector`、`type` 过滤请求不走远程路径。
- 子进程使用参数数组、固定 cwd、无 shell；日志不包含查询正文或秘密。
- 远程结果 path 与本地 Wiki 无法闭合时，启用远程后放弃远程结果并回退本地，不绕过现有 actionable/type 安全过滤。
- 真实 smoke test 仅调用只读 MCP `search`，且能回读结果。
- 回滚只需设置 `RUFLO_SEARCH_BACKEND=local` 或移除配置；不需要迁移数据库和删除 GBrain 数据。

## Plan Audit

### Round 1 — 全面漏洞审计

| 级别 | 漏洞 | 后果 | 整改 |
|---|---|---|---|
| 致命 | GBrain Brain 未包含本项目 Wiki | 远程搜索永远返回错误数据或空结果 | 把页面闭环、embedding 和 20 条查询列为启用前置条件；不满足则本地回退 |
| 致命 | 将 `project_id` 猜成 `source_id` | 跨项目检索或数据泄漏 | 只接受显式 JSON 映射，缺失即回退 |
| 重大 | MCP 每次请求启动 Bun 失败或超时 | WebUI 搜索卡死 | 单请求有限 timeout，异常统一回退；先不做连接池 |
| 重大 | 远程结果 path 与本地 path 不同 | actionable/type 过滤失效或误删全部结果 | path 无法闭环时判定远程不满足替代契约 |
| 重大 | GBrain `search` 的远程 mode 不等于本地 mode | 用户以为使用 vector/keyword，实际策略不同 | 仅路由 hybrid；其他 mode 保持本地 |
| 重大 | MCP 返回文本错误但 HTTP 层仍 200 | 解析异常或把错误当结果 | 严格校验 content、JSON 顶层和字段类型 |
| 优化 | 诊断日志记录 query | 敏感知识进入日志 | 只记录 backend、错误类别、耗时和非敏感 source 标识 |
| 优化 | GBrain 版本/工具名变化 | 运行时突然全部回退 | 启动时只读探测可选；真实 smoke test 和回退保证可用 |

### Round 2 — 压力测试推演

| 场景 | 预期行为 | 兜底 |
|---|---|---|
| gbrain 命令不存在 | 在 timeout/启动异常内结束 | 本地搜索 |
| Bun 启动但 initialize 不完成 | 超时关闭子进程 | 本地搜索 |
| source map 缺少当前 project | 不启动子进程 | 本地搜索 |
| GBrain 返回跨 source 页面 | source 由 stdio 环境固定；结果闭环校验失败则回退 | 不返回未经校验的远程结果 |
| 返回合法 JSON 但结果字段缺失 | Adapter 判定契约错误 | 本地搜索 |
| 本地 vector 未 ready | hybrid 的既有 readiness 行为继续生效；若远程已启用，必须明确 diagnostics，不假装本地 ready | 远程成功可返回；远程失败后保留原本地空结果语义 |
| 同时大量请求 | 每个请求独立子进程可能拖慢机器 | 先依赖 timeout；只有实测证明不可用时再设计池化 |
| 用户关闭/重启 gbrain | 后续请求重新建立会话 | 本地回退，不持久化远程状态 |

### Open Risks

- GBrain 页面 schema 与本项目 Wiki frontmatter 可能无法一一映射；这是试点资格问题，不在 Adapter 中猜测修复。
- 单请求 stdio 进程的延迟上限未知；先测量，未达到实际瓶颈不引入连接池。
- 远程 embedding 可能产生额外费用或把查询发给外部 Provider；启用前由操作员确认 GBrain 的 embedding 配置和数据范围。

### Rollback

```powershell
$env:RUFLO_SEARCH_BACKEND = "local"
```

回滚不删除 GBrain 数据，不修改本地 Wiki，不回滚 schema；只切换搜索后端配置即可。

## Completion Evidence

- Final commit: pending
- Tests: pending
- Static checks: pending
- Documentation updated: pending
- Progress ledger updated: pending after implementation
