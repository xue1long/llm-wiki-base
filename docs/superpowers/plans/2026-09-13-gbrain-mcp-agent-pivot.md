# GBrain MCP 只读 Agent 试点实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 先验证 WebUI 对话 Agent 能否通过一个真实、可复用、只读的 GBrain MCP stdio 会话检索当前项目知识并回答问题，失败时可靠回退本地 Agent。

**Architecture:** GBrain 是 Agent 的 MCP 工具层，不再是 `services.search` 内部的单次搜索后端。WebUI 只选择 `auto`、`gbrain` 或 `local` 后端；P0 的 GBrain Agent 通过受限 Claude Code Host 调用 `recall/search/get_page/remember`，其中 Wiki 页面只读，长期事实允许写入 GBrain。运行时自动安装、Wiki 导入/同步和独立搜索 hybrid 延后到 P1/P2。

**Tech Stack:** Python 3.11+, FastAPI, 现有 AgentRuntime/LLM provider, GBrain MCP stdio, 项目 Wiki Markdown。

**Spec:** `docs/superpowers/plans/2026-09-12-gbrain-hybrid-pilot-unified.md`、`docs/superpowers/plans/2026-09-12-gbrain-external-runtime-bootstrap.md`；本计划是对两份方案的 P0 收缩和 Agent 边界修正版。

## Global Constraints

- P0 页面只读：禁止 GBrain 写入、删除、恢复 Wiki；仅允许 `remember` 写入长期事实。
- Wiki Markdown 是当前项目事实源；GBrain 只提供检索和读取能力。
- 搜索请求不得触发 clone、安装、升级、全量同步或 Wiki 修改。
- 每次请求先 `recall`；有长期价值时 `remember`。P0 允许每次请求启动独立 GBrain 进程，跨会话记忆由 GBrain 持久化，不依赖 Claude transcript。
- GBrain 缺失、MCP 不可用、工具能力不满足或项目作用域不明时，`auto` 必须回退 local。
- `gbrain` 显式模式失败时必须明确报错，不能伪装成本地成功。
- 所有项目根目录和 source scope 由服务端根据 `project_id` 解析，前端不能传入任意路径。
- WebUI 修改 `web/js/views/*.js` 时必须同步更新 `docs/webui-buttons.md`。

## 目标与阶段边界

### P0：只读 MCP Agent 试点

```text
WebUI 对话
  → Agent backend: auto/gbrain/local
    → gbrain: 一个 chat session 级 MCP stdio 会话
      → initialize → tools/list → search → read page
      → 带来源回答
    → local: 现有 AgentRuntime 和本地工具
```

P0 只证明核心架构，不负责维护 GBrain 索引。

### P1：运行时管理

复用 `2026-09-12-gbrain-external-runtime-bootstrap.md`，解决：

- 项目内或用户目录发现 GBrain；
- 用户显式确认后 clone/install；
- Bun、版本、MCP handshake 校验；
- 安装失败后的本地回退。

P1 不得被聊天请求隐式触发。

### P2：索引和独立搜索

复用 `2026-09-12-gbrain-hybrid-pilot-unified.md`，解决：

- Wiki 初次导入；
- 增量同步和 reconcile；
- 独立搜索页使用 GBrain hybrid；
- source 生命周期和质量对照。

P2 完成前，独立搜索页保持本地搜索；对话 Agent 直接读取已验证的 GBrain 知识源。

### P3：外部 Agent Host

在 P0 稳定后，再接入 Claude Code 或其他支持 MCP 的本地 Agent。P0 不打包或强依赖 Claude Code。

## 关键设计决定

### 1. Agent 选择规则

```text
backend=local  → 只用现有 Python Agent
backend=gbrain → MCP/模型能力不满足时返回明确错误
backend=auto   → GBrain 能力满足则使用，否则回退 local
```

如果当前 LLM provider 不支持稳定的原生 tool calling，P0 不继续扩展自定义 JSON 规划器；`auto` 使用 local，`gbrain` 返回 `agent_tool_calling_unsupported`，等待支持 MCP 的 Agent Host 或 provider。

### 2. MCP session 生命周期

- session key：`project_id + conversation_id`。
- 第一次请求创建并初始化 MCP 子进程。
- 后续同一对话复用进程。
- 对话结束、用户取消、进程异常或空闲超过 TTL 时关闭。
- HTTP 请求只使用 session，不负责启动多个 GBrain。
- 子进程树必须可清理；超时后不能留下 Bun 孤儿进程。

### 3. P0 工具权限

启动后通过 `tools/list` 获取真实工具定义，但只允许经过 capability map 映射的只读工具：

```text
search
页面读取工具
页面列表/状态工具（仅当真实能力存在时）
```

默认拒绝所有未映射工具，尤其是：

```text
put_page / delete_page / restore_page / write / import / sync
```

工具名称和参数以真实 GBrain smoke test 为准，不在代码中凭空假设。

### 4. 项目作用域

- 只允许服务端通过 `resolve_project(project_id)` 得到项目根目录。
- source scope、Wiki 根目录和 GBrain runtime path 不接受浏览器覆盖。
- GBrain 返回的结果必须能映射到当前项目的本地页面。
- 映射失败的结果不得进入最终回答。
- 跨项目访问测试必须为 0。

## 文件职责与接口

### 新增

- Create: `src/agent/mcp_session.py`
  - 提供 `McpSession.open(runtime, project_root, source_scope, conversation_id)`。
  - 提供 `list_tools() -> list[dict]`、`call_read_tool(name, arguments) -> dict`、`close() -> None`。
  - 内部处理 initialize、stdio framing、超时、stderr、子进程清理。
- Create: `src/agent/backends.py`
  - 提供 `run_conversation(request, backend="auto") -> AgentResponse`。
  - 负责后端选择、session 复用、只读工具暴露、失败回退和统一响应。
- Create: `tests/test_agent/test_mcp_session.py`
- Create: `tests/test_agent/test_backends.py`

### 修改

- Modify: `src/agent/runtime.py`
  - 继续作为 local backend。
  - 移除对话路径中通过 `WikiSearchTool → services.search` 间接启动 GBrain 的逻辑。
  - 不再为 GBrain 增加更多自定义 JSON 修复分支。
- Modify: `src/services/chat.py`
  - 路由到 `src/agent/backends.py`。
  - 响应增加 `backend`、`degraded`、`degrade_reason`、`sources`。
- Modify: `src/server/routes/chat.py`
  - 接收可选 `agent_backend` 和 `conversation_id`。
  - 服务端校验 project scope，不接受路径、cwd、命令和 source 覆盖。
- Modify: `src/services/search.py`
  - P0 仅保留独立搜索的现有本地逻辑。
  - 不再作为对话 Agent 的 GBrain 编排入口。
- Modify: `src/agent/tools.py`
  - 保留 local Agent 工具。
  - 停用 project-bound GBrain 搜索包装，避免出现第二个 MCP 入口。
- Modify: `web/js/views/chat.js`（以实际对话视图文件为准）
  - 增加 Agent backend 选择、状态和回退提示。
- Modify: `docs/webui-buttons.md`
  - 记录对话后端按钮、API 字段和回退行为。

## Task 0：真实能力门禁

**Files:**

- Create: `tests/test_integration/test_gbrain_mcp_p0.py`
- Modify: `docs/superpowers/plans/2026-09-12-gbrain-p0-p1-repair.md`

- [ ] 使用真实 GBrain 执行 `bun run src/cli.ts serve`，完成 `initialize`。
- [ ] 完成 `tools/list`，记录实际工具名、参数、只读/写入属性。
- [ ] 在同一 MCP 进程内完成搜索和页面读取。
- [ ] 验证当前 LLM provider 是否支持原生 tool calling。
- [ ] 验证 source/project scope 是否能限制到当前项目。
- [ ] 验证 MCP 超时、退出和非法 payload 的可清理性。
- [ ] 若任一关键能力失败，记录明确错误码，P0 不进入 WebUI 开发。

**真实门禁通过标准：**同一 stdio 进程完成初始化、工具发现、搜索和读取；得到可验证的来源路径；没有跨项目结果；进程能正常退出。

## Task 1：MCP session Adapter

**Files:**

- Create: `src/agent/mcp_session.py`
- Create: `tests/test_agent/test_mcp_session.py`

- [ ] 写测试：同一 `conversation_id` 连续调用两个只读工具时只创建一个子进程。
- [ ] 写测试：未在只读 allowlist 的工具调用被拒绝。
- [ ] 写测试：初始化超时、调用超时、进程退出均返回分类错误并清理进程。
- [ ] 实现最小 stdio session；使用参数数组、`shell=False`，协议 stdout 与日志 stderr 分离。
- [ ] 实现 project root/source scope 的服务端注入和不可覆盖校验。
- [ ] 实现 session TTL、取消和 close。
- [ ] 运行：

```powershell
PYTHONPATH=. python -m pytest tests/test_agent/test_mcp_session.py -v --import-mode=importlib
```

## Task 2：Agent backend seam

**Files:**

- Create: `src/agent/backends.py`
- Create: `tests/test_agent/test_backends.py`
- Modify: `src/agent/runtime.py`

- [ ] 写测试：`local` 不启动 GBrain。
- [ ] 写测试：`gbrain` 使用同一个 MCP session 完成工具调用并返回来源。
- [ ] 写测试：`auto` 在 GBrain 不可用时回退 local，并返回 `degraded=true`。
- [ ] 写测试：`gbrain` 在 provider 不支持 tool calling 时返回 `agent_tool_calling_unsupported`。
- [ ] 实现后端选择，不复制 GBrain 的工具业务逻辑。
- [ ] 让模型只看到真实、已允许的 MCP 工具定义。
- [ ] 统一工具结果、来源、backend、错误和降级字段。
- [ ] 设置单任务最大工具轮数和总 token 上限；超限返回可解释失败。
- [ ] 运行：

```powershell
PYTHONPATH=. python -m pytest tests/test_agent/test_backends.py tests/test_agent/test_runtime.py -v --import-mode=importlib
```

## Task 3：Chat API 接入

**Files:**

- Modify: `src/services/chat.py`
- Modify: `src/server/routes/chat.py`
- Create: `tests/test_server/test_chat_backends.py`

- [ ] 写测试：默认 `auto` 返回 backend、sources 和降级字段。
- [ ] 写测试：GBrain 不可用时 HTTP 仍能返回 local 回答，不返回无依据的 502。
- [ ] 写测试：显式 `gbrain` 失败时返回明确错误，不伪装成本地回答。
- [ ] 使用 `project_id + conversation_id` 绑定 session；不能使用前端传入路径。
- [ ] 请求取消或服务关闭时关闭 session。
- [ ] 保持现有响应兼容字段。
- [ ] 运行：

```powershell
PYTHONPATH=. python -m pytest tests/test_server/test_chat_backends.py tests/test_server/test_service_chat.py -v --import-mode=importlib
```

## Task 4：WebUI 最小状态接入

**Files:**

- Modify: `web/js/views/chat.js`（以实际文件为准）
- Modify: `docs/webui-buttons.md`
- Create: `tests/test_webui/test_chat_backend_contract.py`

- [ ] 增加 `自动 / GBrain MCP / 本地 Agent` 选择。
- [ ] 显示 GBrain 不存在、MCP 失败、模型不支持工具调用和自动回退原因。
- [ ] 不在发送问题时触发安装、clone、同步或升级。
- [ ] 显示 backend 和来源页面，不展示密钥、完整命令或敏感路径。
- [ ] 验证 GBrain 失败后用户仍可继续提问。

## Task 5：P0 真实验收

**Files:**

- Create: `tests/test_integration/test_gbrain_agent_pilot.py`
- Create: `docs/guides/gbrain-mcp-agent-pilot.md`

- [ ] 真实 GBrain：同一对话完成两次问题，不重新启动 MCP 子进程。
- [ ] 真实来源：回答引用当前项目 Wiki 页面标题和路径。
- [ ] 真实隔离：构造另一个项目的相似页面，结果不得泄漏。
- [ ] 真实失败：停止 GBrain 后，`auto` 回退 local，`gbrain` 明确报错。
- [ ] 真实资源：取消请求后无孤儿 Bun 进程。
- [ ] 真实安全：写入/删除工具不能被 Agent 调用。
- [ ] 运行：

```powershell
PYTHONPATH=. python -m pytest tests/test_agent tests/test_server/test_chat_backends.py tests/test_integration/test_gbrain_mcp_p0.py tests/test_integration/test_gbrain_agent_pilot.py -v --import-mode=importlib
python -m py_compile src/agent/mcp_session.py src/agent/backends.py
git diff --check
```

## P1/P2 后续入口

### P1：运行时发现与显式安装

仅在 P0 通过后实施：

- 复用 `2026-09-12-gbrain-external-runtime-bootstrap.md` 的 resolver、版本校验、显式 setup 和回退设计。
- 搜索和对话请求不自动安装。
- 项目内 `external/gbrain`、用户托管目录和显式配置路径按优先级探测。
- 安装到临时目录，验证通过后原子切换；失败不污染 ready 状态。

### P2：索引同步与独立搜索 hybrid

仅在 P0/P1 稳定后实施：

- 复用 `2026-09-12-gbrain-hybrid-pilot-unified.md` 的初次导入、增量同步和 reconcile。
- 同步是独立 job，不属于查询流程。
- 独立搜索页再接入 GBrain；对话 Agent 不回到 `services.search`。
- GBrain 仍然只作为可重建副本，未通过 ready gate 时继续 local。

### P3：Claude Code / 外部 Agent

- 外部 Agent 只需实现统一的 conversation backend 接口。
- WebUI 不感知 Claude Code 的内部协议。
- 外部 Agent 不可绕过项目 scope 和只读权限。

## P0 放行标准

以下条件全部满足才算 P0 完成：

1. 真实 MCP initialize、tools/list、search、页面读取成功。
2. 当前 provider 具备可用的原生 tool calling；否则明确停在 local fallback。
3. 一个 `conversation_id` 只创建一个 MCP 子进程，并能正常关闭。
4. 只读工具白名单生效，写入/删除工具无法调用。
5. 结果全部属于当前项目，且能回读本地来源。
6. GBrain 不可用时 `auto` 可继续使用 local。
7. 显式 `gbrain` 失败时用户能看到真实失败原因。
8. 普通请求不触发安装、同步、升级或 Wiki 写入。
9. WebUI 能显示 backend、来源和降级状态。

## 回滚策略

- 设置 `RUFLO_AGENT_BACKEND=local`，立即停用 GBrain Agent。
- 保留 GBrain 运行时和数据，不删除任何 Wiki 或本地向量数据。
- MCP 进程异常时销毁 session，不影响本地 Agent。
- 不通过回滚机制隐藏真实错误；保留脱敏错误码和任务 ID。

## 整改后的多角度结论

- **第一性原理：** P0 只证明“Agent 能通过 MCP 使用 GBrain”，不把安装、同步和搜索产品化混入核心验证。
- **批判性思维：** 先验证 provider tool calling、真实工具 schema、session 生命周期和 source 隔离，禁止用 mock 或 JSON 提示词成功代替真实能力。
- **奥卡姆剃刀：** P0 从六类系统任务收缩为 MCP session、backend seam、Chat 接入和真实验收四个核心切片。
- **终局思维：** Agent Host 可替换；未来接 Claude Code 不需要重写 WebUI、项目解析和权限控制。
- **全局思维：** Agent、MCP、runtime、index、UI 分层；P0 只打通 Agent/MCP 和最小 UI。
- **二八法则：** 优先解决会话复用、tool calling、只读权限、项目隔离和可靠回退，这五项决定试点是否成立。

## 路线 B 执行修订（2026-09-13）

用户选择路线 B 后，Task 0 已用真实环境完成：Claude Code 2.1.270 通过临时 MCP 配置连接 GBrain 0.50.0.0，完成只读 `search → get_page`，并验证 `put_page` 被权限拒绝。由于当前 Python provider 没有原生 tool calling，路线 A 保持关闭。

P0 实施采用最小桥接：`src/agent/claude_host.py` 启动一次无持久化 Claude Code 进程，固定受限 allowlist（`recall/search/get_page/remember`），复用现有 `.llm-wiki/gbrain-search.json` 和 `.index/gbrain/runtime-state.json`，校验 `source_id` 后仅返回可映射到当前 Wiki 的引用。`local` 为默认后端，`auto` 失败回退 local，显式 `gbrain` 失败返回真实错误；WebUI 已增加后端选择器。

已知边界：当前不做跨请求 Claude/MCP 常驻会话；Claude 每次退出后，GBrain 事实仍可被新会话 recall。也不做自动安装、同步、Wiki 页面写入或独立搜索切换；这些分别留到后续 P1/P2。Windows 路径含空格的 Claude stdio 启动兼容性也需单独验证，当前已验证路径无空格链路可用。

**最终状态：** 路线 B 的 P0 最小只读试点已落地并通过定向测试及真实项目验收；后续只在需要跨请求会话、运行时安装或索引同步时扩展。
