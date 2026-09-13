# ADR-0010: Separate Skill Artifact from Agent Deployment

- Status: **Accepted** (v1 static Skill implementation complete; remote/plugin extensions remain deferred)
- Date: 2026-09-13
- Owners: ruflo-kb platform team
- Related: `src/skill_manager/`, `src/services/skill_manager.py`, `src/cli.py`, `web/js/views/settings.js`

## Context

用户希望从 WebUI 设置页安装 Skill 或 Plugin 到本机 Agent。公开的
`xingkongliang/skills-manager` 展示了一个关键边界：包先进入中央 Library，再由用户显式部署到 Agent；目标目录不是管理器创建或托管的内容时不能被覆盖。

ruflo-kb 已有项目级 `.llm-wiki/skills/` 加载约定和显式确认的外部 runtime 安装流程。直接把 WebUI 按钮连接到 Agent 文件夹会绕过来源校验、ownership 和回滚，也会把管理逻辑散落到 HTTP/UI 调用方。原方案还缺少 Agent/脚本可调用的稳定控制面，并且没有把来源、不可变内容和部署记录分成不同身份。

## Decision

增加独立的 Skill manager module，拥有 Source 解析、不可变 Artifact Library、Agent 发现、预览、ownership marker 和部署操作。HTTP route、JSON CLI 和 WebUI 都是薄适配器，不能各自实现文件操作。

v1 只支持带 `SKILL.md` 的静态 Skill。出现 `plugin.json` 时统一返回 `UNSUPPORTED_PLUGIN_TYPE`；可执行 Plugin、MCP server、hook、二进制和安装脚本均延期，未来必须先定义具体宿主协议。

生命周期固定为 `Source → Artifact → Deployment → Agent`。Artifact identity 包含内容 hash，远程来源还必须包含 resolved commit SHA。Library 使用现有用户配置目录，不引入数据库。Deployment 只允许写入标准 Agent 目录或经过显式确认且通过路径校验的自定义目录。非托管同名内容返回结构化冲突，不能覆盖。

所有变更必须经过 `inspect/import/plan → explicit confirm → apply → verify`。提供无交互 JSON CLI；HTTP mutation 仅允许 loopback，非 loopback 必须有本地授权令牌。跨多个 Agent 目录只承诺补偿式回滚和事实状态，不承诺跨目录原子事务；无法完整恢复时，Operation 必须返回 `partial_failure` 及逐目标事实状态。

## Alternatives rejected

1. **WebUI 直接复制到 Agent 目录**：实现短，但校验、ownership、回滚和其他调用方无法复用。
2. **复刻 skills-manager 的完整桌面架构**：引入 Tauri、Rust、SQLite、marketplace 和同步能力，超出 ruflo-kb 当前需求。
3. **立即支持任意插件脚本**：把下载动作升级为远程代码执行，安全边界不可接受。
4. **只提供 WebUI/HTTP**：无法满足 Agent 或自动化脚本的解耦调用需求；CLI 必须与核心模块共享同一 interface。

## Consequences

正面：导入和部署逻辑可被 CLI、HTTP、未来 Agent tool 独立调用；所有调用方共享同一套校验、幂等和冲突保护；保留现有项目级 Skill 行为。

代价：v1 只能处理静态 Skill；公开 GitHub、第二个 Agent、SkillBundle、更新/卸载、marketplace、同步和跨进程 operation executor 后置；Windows 自定义目录权限需要额外人工确认。

## Implementation notes

- Core: `src/skill_manager/api.py` exposes inspect/import/plan/apply; Library state is JSON-backed under the user config directory.
- Adapters: `src/services/skill_manager.py`, `/api/v1/skill-manager/*`, `skill-manager` JSON CLI, and Settings → Skills all share the core.
- v1 deployment is synchronous behind a durable Operation record; restart recovery marks in-flight operations as `failed/server_restarted`.
- Verification: focused Skill Manager, HTTP, and CLI tests pass; real user Codex target verification remains the rollout gate.
