# GBrain MCP P0 能力门禁报告

日期：2026-09-13

结论：**GBrain MCP 服务能力通过；路线 B（Claude Code 外部 Agent Host）真实门禁通过；跨会话 recall/remember 闭环已接入。**

## 已验证通过

环境：

- GBrain：`C:\Users\HP\AppData\Local\ruflo-kb\external\gbrain\v0.50.0.0`
- GBrain 版本：`0.50.0.0`
- 实际 Bun：`C:\Users\HP\.bun\bin\bun.exe`
- Bun 版本：`1.3.14`
- 项目 source：`ruflo-5b626bbb6f2f`
- 当前 Wiki：`E:\002-Pr\20260910\llm-wiki-base\knowledge\novel-wiki\wiki`

真实执行结果：

1. `initialize` 成功，server identity 为 `gbrain/0.50.0.0`。
2. `tools/list` 成功，返回 135 个 MCP 工具。
3. 真实 `search` 成功，返回 `source_id=ruflo-5b626bbb6f2f` 的结果。
4. 真实 `get_page` 成功，返回页面完整 `content`、`slug`、`source_id` 和 frontmatter。
5. `sources_list` 只返回当前 source，页面数为 1738，`federated=false`。
6. 显式 `source_id` 作用域生效；使用 `__all__` 仍未出现其他 source。
7. 缺少 `query` 的非法搜索请求返回结构化 `invalid_params`，没有挂起或静默扩大范围。
8. 同一 MCP stdio 进程完成 initialize、tools/list、search、get_page 后可以被清理。
9. Claude Code `2.1.270` 使用临时 `--mcp-config` 成功连接 GBrain stdio，完成真实 `search → get_page`，返回正确的标题、slug、source_id 和正文。
10. Claude Code 的 `--allowed-tools mcp__gbrain__search,mcp__gbrain__get_page` 配合 `--permission-mode dontAsk --permission-prompts none` 成功拒绝 `mcp__gbrain__put_page`，未发生写入。
11. 新增 Python bridge 使用临时 MCP 配置文件（运行结束删除），真实调用当前 `knowledge/novel-wiki` 成功返回 Markdown 回答、`source_id=ruflo-5b626bbb6f2f` 和可映射的 Wiki 引用。
12. 真实跨会话闭环通过：请求 A 由 `remember` 写入唯一测试事实；请求 B 在全新 Claude/GBrain 进程中由 `recall` 找回；测试 fact 随后按 `fact_id` 清理。

## 未通过项

### 路线 A 阻断：当前 LLM provider 不支持原生 tool calling

证据：

- `src/llm/base.py` 的 `LLMResponse` 只有文本 `content`，没有 tool call 结构。
- `src/llm/base.py` 的 `LLMProvider.complete()` 没有工具调用契约。
- `src/llm/openai_provider.py` 构造请求 body 时只传递 `model`、`messages`、`temperature`、`max_tokens`、`response_format`，没有 `tools` 或 `tool_choice`。
- `src/llm` 中没有 `tool_calls`、`function_call` 或 `tool_choice` 的实现。

因此，当前 Python Agent 不能把 GBrain 的真实 MCP 工具定义交给模型并接收原生工具调用。继续修改 `AgentRuntime` 提示词只能回到自定义 JSON 规划器，不能满足本计划的 MCP Agent 目标。

错误分类：`agent_tool_calling_unsupported`。

### 阻断 2：默认 `bun` 命令是失效 shim

证据：

- PowerShell 中的 `bun` 指向 `C:\Users\HP\AppData\Roaming\npm\bun.ps1`。
- 该 shim 引用不存在的 `C:\Users\HP\AppData\Roaming\npm\node_modules\bun\bin\bun.exe`。
- 实际 Bun 位于 `C:\Users\HP\.bun\bin\bun.exe`，但不在当前 PATH 中。
- 当前 `src/integrations/gbrain/runtime.py` 使用 `shutil.which("bun")`，所以运行时探测会把“已安装但 PATH 不可见”判定为不可用。

这不是路线 B 的阻断，但必须在 P1 runtime resolver 中修复为显式 Bun 探测；不能依赖失效 shim。

## 不应继续做的事情

- 不继续给 `src/agent/runtime.py` 增加 JSON 修复、重复调用拦截或提示词补丁。
- 不新增 `src/agent/mcp_session.py` 生产实现，直到 provider tool calling 门禁通过。
- 不接入 WebUI GBrain Agent 开关。
- 不在聊天请求中触发 Bun 修复、安装、同步或索引重建。
- 不把“Python 手工调用 MCP 成功”记录为“Agent MCP 能力通过”。

## 下一步放行条件

二选一：

### 路线 A：补齐本项目 provider 原生 tool calling

需要先完成并验证：

1. `LLMResponse` 增加结构化 tool call 表达。
2. `LLMProvider.complete()` 增加 `tools`、`tool_choice` 和 assistant tool-call 消息契约。
3. OpenAI-compatible provider 将字段真实传到 `/chat/completions`。
4. 使用当前配置的 provider/model 完成一次合成工具的调用和结果回传。
5. 再把 GBrain MCP 工具接入 Agent。

### 路线 B：使用外部 MCP Agent Host（已通过门禁）

使用 Claude Code 或其他已支持 MCP 的本地 Agent 作为 Agent Host，ruflo-kb 只负责：

- 启动/选择 Agent Host；
- 注入项目 scope；
- 接收回答和来源；
- 失败时回退本地 Agent。

本机已检测到并验证 `Claude Code 2.1.270` 可以从隔离目录启动，使用显式 Bun 路径连接 GBrain MCP，复用同一轮 MCP 会话完成检索与取页，并以结构化 JSON 返回结果。写工具拒绝也已通过。

当前未覆盖跨请求的 `conversation_id` 会话复用；P0 bridge 明确采用每次请求独立、无持久化 Claude 进程。WebUI/API 接入已完成定向测试，常驻会话作为后续增强。

这条路线不要求当前 Python provider 立即具备原生 tool calling，但需要先验证外部 Agent Host 的 CLI/API、会话复用和 Windows 进程清理。

## 门禁状态

```text
GBrain runtime：通过（使用显式 bun.exe）
MCP initialize：通过
MCP tools/list：通过
MCP search：通过
MCP get_page：通过
source scope：通过（单 source fixture）
Claude Code 页面只读 + 记忆事实 allowlist：通过（put_page 被拒绝）
provider native tool calling：未通过
Claude Code 单轮 MCP 会话：通过
ruflo-kb Agent 单请求桥接：通过
GBrain 跨 Claude 会话记忆：通过（recall/remember）
Claude/MCP 跨请求常驻会话：后置
WebUI 接入：通过（默认 local，可选 auto/gbrain）
```

最终决定：**路线 A 不放行；路线 B P0 受限记忆桥接已放行。允许 GBrain 事实 remember，禁止 Wiki 页面写入；暂不做 Claude/MCP 常驻会话、自动安装、同步和独立搜索切换。**
