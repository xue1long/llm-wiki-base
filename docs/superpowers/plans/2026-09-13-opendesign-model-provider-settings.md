# Plan: OpenDesign 模型与提供商设置能力移植

status: planned
branch: feature/2026-09-13-opendesign-model-provider-settings

## Goal

在现有 ruflo-kb 设置页中补齐 OpenDesign 的两条配置能力：本机 CLI 与 API Provider。首期完成全局配置、CLI 检测/测试、API Provider 管理/测试、模型隔离和实际聊天运行时接入；实时模型发现作为独立的最后阶段，不阻塞首期闭环。

## Non-goals

- 不复制 OpenDesign 的 React/TypeScript 组件、Node Daemon 或完整 `AppConfig`。
- 不把 Local CLI 写入 `ProviderConfig`；CLI 不承担 Embedding、Analyzer 或 Generator 的 API 契约。
- 不引入项目级 Provider/CLI 覆盖；本期配置真源保持用户级全局配置。
- 不在首期实现实时远端模型目录发现；该功能单独设计、单独测试、单独验收。
- 不显示后端尚未实现的 API 协议，不做“界面可选但运行时报错”的伪支持。
- 不自动导入 OpenDesign 的 localStorage、daemon 配置或明文密钥。

## Audit baseline

本计划基于以下已核验事实：

- OpenDesign 的设置主界面在 `D:/5-Project/open-design/apps/web/src/components/SettingsDialog.tsx`。
- OpenDesign 使用 `/api/agents` 检测本机 CLI，使用 `/api/test/connection` 统一测试 CLI/API，使用 `/api/app-config` 保存配置，使用 `/api/provider/models` 发现模型。
- OpenDesign 的 CLI 配置由 `agentModels`、`agentCliEnv` 和 `agentCliEnvIntent` 表达，并区分 Local CLI 与 BYOK/API。
- 本项目的 Provider 页面已在 `web/js/views/settings.js` 实现 Provider CRUD、默认 Provider、Chat/Embedding Model、API Key 脱敏和保存后测试。
- 本项目的 `src/server/routes/agent_cli.py` 当前硬编码 Claude CLI，只提供 Claude status/chat；`src/services/chat.py` 当前默认走 `AgentRuntime`，而 `AgentRuntime` 通过 `ProviderRegistry` 选择 LLM。
- 本项目的 `ProviderConfig` 同时承载聊天模型和嵌入模型；`src/llm/provider_factory.py` 当前支持 `openai`、`openai-compatible`、`anthropic`、`ollama`。

## Design

### Configuration ownership

API Provider 继续由 `ProviderRegistry` 管理：

```text
config_dir()/llm-providers.json
```

本机 CLI 新增独立配置文件：

```text
config_dir()/agent-settings.json
```

推荐数据合同：

```json
{
  "schema_version": 1,
  "mode": "api",
  "agent_id": "codex",
  "agent_models": {
    "codex": {
      "model": "default",
      "reasoning": "medium",
      "service_tier": ""
    }
  },
  "agent_cli_env": {
    "codex": {
      "CODEX_BIN": "C:\\path\\to\\codex.exe"
    }
  }
}
```

`mode` 只有 `api` 和 `local_cli`。配置文件通过现有 `config_dir()` 定位，使用临时文件加原子替换；损坏 JSON 必须 fail-closed，并保留旧文件供人工恢复。CLI 环境变量采用每个 Agent 的白名单，不能接受任意环境变量名或任意 shell 命令。

### Runtime boundary

全局配置不等于所有任务都切换到 CLI：

```text
interactive chat + mode=local_cli  -> selected CLI adapter
interactive chat + mode=api        -> ProviderRegistry default
Analyzer / Generator / Embedding   -> existing API Provider path
```

这样可以复用 OpenDesign 的 Local CLI 体验，同时不破坏知识库管线要求的 Embedding 和结构化输出。若未来要求 CLI 驱动后台管线，必须另建能力合同，不能由本计划隐式扩展。

### Public seams

CLI 模块只通过以下公共函数供 route 和 chat service 使用，检测、路径回退和子进程细节保持模块内部：

```python
load_agent_settings() -> AgentSettings
save_agent_settings(settings: AgentSettings) -> AgentSettings
detect_agents(agent_cli_env: dict | None = None) -> list[AgentStatus]
test_agent(request: AgentTestRequest) -> ConnectionTestResult
run_agent_chat(request: AgentChatRequest) -> AsyncIterator[AgentEvent]
```

公共类型的最小字段固定如下；未知字段由边界层拒绝，不由 runner 猜测：

```python
from dataclasses import dataclass, field
from typing import Literal

@dataclass(frozen=True)
class AgentModelSettings:
    model: str = "default"
    reasoning: str = ""
    service_tier: str = ""

@dataclass(frozen=True)
class AgentSettings:
    schema_version: int = 1
    mode: Literal["api", "local_cli"] = "api"
    agent_id: str | None = None
    agent_models: dict[str, AgentModelSettings] = field(default_factory=dict)
    agent_cli_env: dict[str, dict[str, str]] = field(default_factory=dict)

@dataclass(frozen=True)
class AgentTestRequest:
    agent_id: str
    model: str = ""
    reasoning: str = ""
    service_tier: str = ""
    agent_cli_env: dict[str, dict[str, str]] = field(default_factory=dict)

@dataclass(frozen=True)
class AgentChatRequest:
    agent_id: str
    message: str
    model: str = ""
    reasoning: str = ""
    service_tier: str = ""
    session_id: str | None = None
```

HTTP body 与公共函数保持同名字段：

```text
GET  /api/v1/agents
     -> {"agents": [AgentStatus, ...]}

GET  /api/v1/local-cli/settings
     -> {"settings": AgentSettings, "agents": [AgentStatus, ...]}

PUT  /api/v1/local-cli/settings
     body: AgentSettings
     -> {"ok": true, "settings": AgentSettings}

POST /api/v1/local-cli/test
     body: AgentTestRequest
     -> ConnectionTestResult
```

`AgentStatus` 至少包含 `id`、`name`、`bin`、`available`、`version`、`models`；`AgentModelSettings` 只保存用户选择，不把检测出的模型目录写回配置。

Provider 仍通过 `ProviderRegistry` 与 `provider_factory` 暴露，不增加第二套 Provider 真源。

### Connection test contract

CLI 与 Provider 测试返回统一的结构化结果，至少包含：

```text
ok
kind
latency_ms
detail
model
```

CLI 额外包含：

```text
configured_executable_path
detected_executable_path
used_executable_path
used_executable_source
diagnostics.phase
diagnostics.exit_code
diagnostics.stdout_tail
diagnostics.stderr_tail
```

状态值沿用 OpenDesign 语义：`success`、`auth_failed`、`invalid_model_id`、`timeout`、`agent_not_installed`、`agent_auth_required`、`agent_spawn_failed`、`upstream_unavailable`、`unknown`。所有 stdout/stderr 和 detail 在返回前脱敏，不能包含 API Key 或受保护环境变量的值。

### API protocol boundary

首期不改变已有四类 Provider 的 canonical type。OpenDesign 的协议清单作为能力矩阵维护：

```text
openai             -> existing openai adapter
openai-compatible  -> existing compatible adapter
anthropic          -> existing anthropic adapter
ollama             -> existing ollama adapter
azure/google/aihubmix/senseaudio/bedrock
                   -> only expose after a real adapter and credential contract exist
```

协议专属字段只有在对应适配器需要时加入 `ProviderConfig`，不预先增加无消费者的通用字段。Bedrock 的 AWS 凭证不能伪装成普通 API Key。

## File map

### New files

- `src/agent/cli_registry.py`：Agent 描述、PATH 检测、版本和可用状态。
- `src/agent/cli_runner.py`：安全子进程启动、超时、输出解析和测试诊断。
- `src/agent/cli_settings.py`：`agent-settings.json` 的读写、schema 默认值和原子持久化。
- `tests/test_agent/test_cli_registry.py`：CLI 检测、Windows 路径和版本场景。
- `tests/test_agent/test_cli_runner.py`：参数数组、超时、退出码、脱敏和结果分类。
- `tests/test_agent/test_cli_settings.py`：全局配置读写、损坏恢复和模型隔离。
- `tests/test_server/test_agent_cli_settings.py`：Local CLI HTTP 契约和 route 安全边界。

### Modified files

- `src/server/routes/agent_cli.py`：从 Claude 专用实现改为公共 CLI 适配器入口，保留旧 status/chat 路由兼容。
- `src/server/routes/providers.py`：扩展结构化测试结果和已实现协议能力，不破坏现有 Provider CRUD 语义。
- `src/services/chat.py`：根据全局 mode 选择 Local CLI 或现有 AgentRuntime；后台知识库管线不改变。
- `src/llm/types.py`：仅加入已实现协议所需的兼容字段和测试响应类型，旧 JSON 缺省值可读。
- `src/llm/provider_factory.py`：按能力矩阵接入真实 Provider adapter。
- `src/server/app.py`：仅在新增 router 或 lifespan 资源需要时修改；已有 `agent_cli` router 应继续注册。
- `web/js/views/settings.js`：在模型设置中增加“本机 CLI / API 提供商”两个子区域。
- `docs/webui-buttons.md`：同步所有新增按钮、事件和 API 映射。
- `docs/adr/2026-09-13-provider-settings-portability.md`：补充 Local CLI 独立配置和运行时边界；若 ADR 已被人工确认，则只追加实施引用。

## Tasks

### Task 1: Freeze the contracts and write failing tests

- Files: `tests/test_agent/test_cli_settings.py`, `tests/test_agent/test_cli_registry.py`, `tests/test_server/test_agent_cli_settings.py`, existing Provider contract tests.
- Test: 先覆盖配置默认值、`mode` 取值、每 CLI 模型隔离、API Key/环境变量脱敏、CLI 状态枚举、未知 Agent/协议拒绝和旧 Provider JSON 兼容。
- Acceptance: 测试先失败；字段名、HTTP 状态和错误类型固定；不允许测试依赖真实 CLI、真实网络或真实 API Key。
- Status: pending

### Task 2: Implement global Local CLI settings storage

- Files: Create `src/agent/cli_settings.py`; Test `tests/test_agent/test_cli_settings.py`.
- Interfaces: `AgentSettings`, `load_agent_settings()`, `save_agent_settings(settings)`。
- Test: 使用临时 `RUFLO_CONFIG_DIR` 验证首次默认、保存后重载、未知字段保留策略、损坏 JSON fail-closed、并发写入不产生半文件。
- Acceptance: 只写 `config_dir()/agent-settings.json`；不写项目目录；不保存任意未允许字段；保存失败不破坏旧配置。
- Status: pending

### Task 3: Implement Agent registry and safe detection

- Files: Create `src/agent/cli_registry.py`; Test `tests/test_agent/test_cli_registry.py`.
- Interfaces: `AgentDescriptor`、`AgentStatus`、`detect_agents(agent_cli_env=None)`。
- Test: fake PATH、缺失 executable、版本命令非零退出、Windows `.cmd/.exe`、自定义路径有效/无效、未知 Agent ID。
- Acceptance: 至少注册 Claude Code、Codex CLI、Gemini CLI、OpenCode；检测结果不执行用户拼接命令；不可用 Agent 可展示明确原因；自定义路径只接受解析后的文件路径。
- Status: pending

### Task 4: Implement safe CLI runner and connection test

- Files: Create `src/agent/cli_runner.py`; Modify `src/server/routes/agent_cli.py`; Test `tests/test_agent/test_cli_runner.py`, `tests/test_server/test_agent_cli_settings.py`.
- Interfaces: `test_agent(request)`、`run_agent_chat(request)`、`ConnectionTestResult`。
- Test: 断言使用参数数组而非 shell；测试超时会终止子进程；stderr 不泄露密钥；退出码、认证失败、未安装、路径 fallback、无输出均产生稳定 `kind`。
- Acceptance: 现有 `/api/v1/agent-cli/status` 和 `/api/v1/agent-cli/chat` 保持可用；新增 `/api/v1/agents`、`/api/v1/local-cli/settings`、`/api/v1/local-cli/test`；所有子进程有超时和 cwd 边界。
- Status: pending

### Task 5: Expand Provider connection contract without breaking Registry

- Files: Modify `src/server/routes/providers.py`, `src/llm/types.py`, `src/llm/provider_factory.py`; Test existing `tests/test_server/test_provider_routes_contract.py`, `tests/test_llm/test_provider_settings_contract.py`, new protocol tests under `tests/test_llm/`.
- Test: 现有四类 Provider 的成功、401/403、超时、未配置模型、未知协议；验证未暴露字段和 API Key 不丢失。
- Acceptance: 现有 Provider JSON 可读取；默认 Provider 规则不变；未实现协议返回明确不支持错误；Provider 测试结果增加 `kind/latency_ms/detail` 但旧字段继续存在。
- Status: pending

### Task 6: Wire execution mode into interactive chat

- Files: Modify `src/services/chat.py`, `src/server/routes/chat.py`; Test `tests/test_server/test_chat.py` or existing chat service tests plus `tests/test_agent/`.
- Test: `mode=api` 使用显式 Provider default；`mode=local_cli` 使用选中 Agent；切换模式不改变对方模型；Local CLI 失败返回明确错误；Analyzer/Generator/Embedding 的 Provider 路径不改变。
- Acceptance: UI 保存的 mode 能改变交互式聊天实际执行路径；未配置有效 CLI 时不会静默回退到错误 Provider；旧聊天请求没有 mode 时保持 API 默认行为。
- Status: pending

### Task 7: Add native-JS settings UI

- Files: Modify `web/js/views/settings.js`; Test `node --check web/js/views/settings.js` plus browser smoke; Modify `docs/webui-buttons.md`.
- Test: 设置页加载 Provider 和 CLI；CLI/API 模型相互隔离；API Key 和 CLI 环境值只显示掩码；保存失败、测试失败、CLI 未安装、默认 Provider 删除失败均可见。
- Acceptance: 完成 OpenDesign 对应的 Local CLI 与 API Provider 主要交互；按钮请求期间禁用；保存后重开仍保留选择；所有新增按钮和 API 在按钮手册中有映射。
- Status: pending

### Task 8: Add deferred model discovery seam

- Files: `src/server/routes/provider_models.py`, `web/js/views/settings.js`, discovery tests and docs; only start after Tasks 1–7 are accepted.
- Test: Provider/CLI 模型发现成功、超时、空列表、重复项、当前模型不在列表、服务不可用。
- Acceptance: 发现失败不阻塞已有设置；发现结果不覆盖用户显式模型；缓存和刷新策略单独定义；该任务不进入首期发布门。
- Status: deferred by user decision

### Task 9: Documentation and final acceptance

- Files: `docs/adr/2026-09-13-provider-settings-portability.md`, `CONTEXT.md`, `docs/webui-buttons.md`, `.superpowers/sdd/progress.md`, this plan.
- Test: 运行受影响测试、全量测试、Python compile、Node syntax check、`git diff --check`、临时配置目录下的 server `/health` smoke。
- Acceptance: 文档与实际接口/字段一致；所有首期验收项有测试证据；未完成的模型发现仍明确标记 deferred；不自动提交或 push。
- Status: pending

## Implementation order

1. Task 1 冻结契约并让测试先失败。
2. Tasks 2–4 完成本机 CLI 配置、检测和测试。
3. Task 5 扩展 API Provider 测试/协议能力，并保持 Registry 兼容。
4. Task 6 接通交互式聊天实际执行模式。
5. Task 7 完成原生 JS 设置页和按钮文档。
6. Task 9 完成首期验收；Task 8 只在首期稳定后作为最后独立阶段启动。

## Two-round plan audit

### Round 1: 全面漏洞审计

本轮按目标对齐、前提假设、边界场景、依赖、风险、副作用、可执行性、验收、盲区和回滚逐项检查，发现并纳入以下问题：

1. **重大隐患 — 设置保存但运行时不生效**：当前 `AgentRuntime` 直接使用 ProviderRegistry，若只改 UI，Local CLI 永远不会被调用。整改：Task 6 强制验证交互式聊天真实分流。
2. **致命风险 — CLI 被当成普通 Provider**：CLI 没有稳定 Embedding/结构化输出契约，会破坏知识库管线。整改：独立 `agent-settings.json`，明确后台管线继续使用 API Provider。
3. **重大隐患 — OpenDesign 协议被全部照搬但后端不支持**：用户可保存 Azure/Bedrock 等配置，运行时才失败。整改：能力矩阵与后端适配器同步，未实现协议不显示。
4. **重大隐患 — CLI 任意命令注入**：直接把用户输入拼入 shell 可执行命令。整改：固定 Agent adapter、参数数组、白名单环境变量、禁止 shell。
5. **重大隐患 — 密钥从测试、stderr 或日志泄露**：只做 API Key 字段掩码不能保护 CLI 环境变量。整改：统一结果脱敏，禁止保存/回显受保护环境值。
6. **重大隐患 — Windows PATH 和 `.cmd` 行为不同**：PATH 检测成功但 `create_subprocess_exec` 失败。整改：使用解析后的完整路径，并覆盖 `.cmd/.exe` 测试。
7. **重大隐患 — Local CLI 与 API 模型相互覆盖**：切换模式后用户原模型丢失。整改：`agent_models` 按 Agent 隔离，Provider 模型仍由 Registry 管理。
8. **重大隐患 — 测试进程超时不回收**：CLI 卡住会占用请求和子进程。整改：版本探测、测试、聊天均有超时、kill 和 finally 回收。
9. **优化疏漏 — 现有旧入口被新路由替换**：已有 `/api/v1/agent-cli/status` 或 Provider 客户端可能失效。整改：旧接口保留为兼容入口，新接口内部复用公共 runner。
10. **重大隐患 — 全局配置和项目执行边界混淆**：项目聊天读取用户配置，后台任务却可能误读项目配置。整改：配置只经 `config_dir()` 读取，任务类型的执行边界写入契约。
11. **优化疏漏 — 模型发现与首期设置耦合**：发现服务失败会让整个设置页不可用。整改：Task 8 独立，失败只影响发现结果，不影响已保存模型。
12. **重大隐患 — 方案缺少回滚路径**：新增 CLI 配置格式或协议字段出错可能阻塞启动。整改：旧 Provider JSON 不迁移，CLI 配置损坏 fail-closed，删除新增文件即可回到 API 默认路径。

整改后，未发现阻塞编码的致命缺陷；第 2 项最初为致命风险，已通过独立配置和运行时边界关闭。

### Round 2: 压力测试推演

| 场景 | 可能连锁反应 | 必须观察到的结果 |
|---|---|---|
| 没有任何 CLI | 设置页空白或自动选错 Agent | 返回空列表/不可用状态，API 模式仍可用 |
| 自定义 CLI 路径失效但 PATH 有有效版本 | 测试执行错误路径或静默失败 | 返回 configured/detected/used 三类路径，可显式采用检测路径 |
| CLI 版本命令挂死 | 请求长期不返回 | 超时、终止子进程、返回 `timeout` |
| CLI 输出包含 API Key | UI 或日志泄露凭据 | 返回前脱敏，日志只保留稳定错误信息 |
| Provider 返回 401/429/500 | 前端只看到“连接失败”无法处理 | 返回稳定 `kind` 和必要 HTTP 状态 |
| Provider 配置保存成功但测试失败 | UI 误报保存失败或回滚配置 | 明确显示“已保存、测试失败”，配置不自动回滚 |
| 两次保存同时发生 | 后写请求覆盖新字段或产生半 JSON | 原子写入，最终文件始终是完整可解析状态 |
| 删除当前默认 Provider | Registry 进入无默认状态 | 后端返回 409，Provider 文件不变 |
| 旧 Provider JSON 无新字段 | 服务启动失败 | 使用默认值正常读取，未知字段不破坏已有字段 |
| 交互式聊天选择 Local CLI | 设置值保存但实际仍调用 API | 测试 fake runner 被调用，响应标记 `backend=local_cli` |
| Analyzer/Embedding 同时运行 | CLI 模式误接管后台管线 | 仍使用 ProviderRegistry，Embedding 不受影响 |
| 模型发现接口超时 | 设置页被阻塞或覆盖旧模型 | 发现任务独立失败，当前模型保持不变 |
| 服务重启时 CLI 配置损坏 | 启动过程崩溃 | API 默认模式可恢复，错误可诊断，原文件保留 |

### Re-review after fixes

- Round 1：所有致命风险均有独立数据边界、运行时分流或安全约束；重大风险均绑定到具体任务和测试。
- Round 2：覆盖未安装、错误路径、超时、密钥泄露、Provider 错误、并发保存、删除默认项、旧配置、后台管线和模型发现失败。
- 编码门：Task 1 的契约测试、Task 6 的真实执行分流测试和 Task 7 的浏览器冒烟未产生证据前，不得宣称方案完成。

## Acceptance checklist

- [ ] 可列出 Claude Code、Codex CLI、Gemini CLI、OpenCode 的检测状态。
- [ ] 可选择 CLI、保存每 CLI 独立模型、推理等级和 Service Tier。
- [ ] 可保存/测试/清除无效的自定义 CLI 路径。
- [ ] CLI 未安装、认证失败、超时和启动失败均有明确错误类型。
- [ ] API Provider CRUD、默认 Provider、Chat Model、Embedding Model 全部保留。
- [ ] API Key 和 CLI 环境变量不会通过 GET、日志或错误响应泄露。
- [ ] Local CLI 与 API Provider 模型重新打开页面后仍互不覆盖。
- [ ] Local CLI 模式确实影响交互式聊天执行。
- [ ] Analyzer、Generator、Embedding 仍通过 API Provider 工作。
- [ ] 未实现 API 协议不在 UI 中作为可用选项出现。
- [ ] 旧 Provider JSON、旧 status/chat API 和旧 API 模式继续可用。
- [ ] 模型发现明确作为 deferred 阶段，不阻塞首期设置闭环。
- [ ] 受影响测试、全量测试、compile、Node syntax、diff check 和 `/health` smoke 均有记录。

## Rollback

编码前：删除本计划即可，不修改运行配置。

编码后：

- 保留 `llm-providers.json` 原格式和旧 API 路由；Provider 回滚不需要迁移。
- 停用 `local_cli` 分支即可恢复 API 默认聊天路径。
- 删除或改名 `agent-settings.json` 后，服务使用 API 默认模式；损坏文件不覆盖旧 Provider 配置。
- 不删除用户已有 Provider、CLI 可执行文件或非本项目文件。
- 协议适配器逐项启用，单个协议失败不影响已有四类 Provider。

## References

- OpenDesign UI: `D:/5-Project/open-design/apps/web/src/components/SettingsDialog.tsx`
- OpenDesign connection contract: `D:/5-Project/open-design/packages/contracts/src/api/connectionTest.ts`
- OpenDesign model discovery: `D:/5-Project/open-design/apps/web/src/providers/provider-models.ts`
- OpenDesign CLI detection: `D:/5-Project/open-design/apps/daemon/src/runtimes/detection.ts`
- Target Provider UI: `web/js/views/settings.js`
- Target Provider route: `src/server/routes/providers.py`
- Target CLI route: `src/server/routes/agent_cli.py`
- Target runtime: `src/services/chat.py`, `src/agent/runtime.py`
- Existing decision record: `docs/adr/2026-09-13-provider-settings-portability.md`

## Completion evidence

- Final commit: pending
- Tests: pending
- Static checks: pending
- Documentation updated: this plan pending implementation; `docs/webui-buttons.md` required during Task 7
- Progress ledger updated: pending implementation
