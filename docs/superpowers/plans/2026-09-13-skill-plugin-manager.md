# Plan: Agent Skill Manager

status: planned
branch: feature/2026-09-13-skill-plugin-manager

## Goal

在不改变现有 `.llm-wiki/skills/` 加载行为的前提下，增加一个独立的 Skill Library 管理模块：从受支持的来源读取静态 Skill，生成不可变 Artifact，经用户确认后部署到 Agent。Python 核心同时被 HTTP、JSON CLI 和未来 Agent tool 调用；Settings → Skills 页面只负责调用 HTTP 接口和展示状态。Plugin 仅保留为未来扩展边界，v1 不执行插件代码。

## Non-goals

- 不执行包内任意安装脚本、shell、Python 或 Node 代码。
- v1 只实现静态 Skill；不执行 Plugin、MCP server、hook、二进制或其他生命周期代码。
- 不做 marketplace、账号登录、Git 同步、备份、批量操作、Preset、Tag 或 50+ Agent 适配。
- 不替换现有项目级 `.llm-wiki/skills/`，不改 GBrain runtime。
- 不引入数据库、WebSocket 或新的通用任务框架。
- v1 先支持本地 Skill 目录；公开 GitHub 来源作为下一阶段，必须记录解析后的 commit SHA。

## Design

### Seam and ownership

`src/skill_manager/` 是深模块。外部调用方只依赖以下生命周期接口；HTTP 和 CLI 都是适配器，不包含文件安装逻辑：

```python
inspect_source(source: SourceSpec) -> SourceInspection
import_artifact(plan: ImportPlan, confirmation: str) -> Artifact
list_artifacts() -> list[Artifact]
list_targets() -> list[TargetStatus]
plan_deployment(artifact_id: str, target_ids: list[str]) -> DeploymentPlan
apply_deployment(plan: DeploymentPlan, confirmation: str) -> Operation
get_operation(operation_id: str) -> Operation
```

三种身份不可混用：`Source` 是可变化的来源定位；`Artifact` 是校验后的不可变快照；`Deployment` 是某个 Artifact 到某个具体 Agent 目录的安装记录。更新必须生成新 Artifact，再替换 Deployment。CLI 使用 `--json`、稳定错误码和无交互模式，供脚本或 Agent 调用。

HTTP route 只负责参数校验、loopback/本地授权、确认字段和状态码；WebUI 只负责调用 route。任何 filesystem mutation 都必须经过 `inspect/import/plan → explicit confirm → apply → verify`。

Library 使用现有 `src.project.paths.config_dir()`：

```text
<config_dir>/skill-manager/
├── artifacts/<artifact_id>/
├── deployments/<deployment_id>.json
├── manifest.json
└── operations/<operation_id>.json
```

写入采用临时目录 + 原子 JSON + 跨进程 manager lock。Windows 不能可靠地用 `os.replace` 覆盖非空目录，因此部署更新采用“旧目录改名为备份 → staging 改名为目标 → 失败时恢复备份”；每一步都在锁内完成，并在启动时清理/恢复遗留的 staging 与 backup。当前服务按单进程 `BackgroundTasks` 执行；服务重启后将 `queued/downloading/validating/installing` 标记为 `failed/server_restarted`，不假装自动续跑。跨多个 Agent 目录不宣称真正文件系统事务，失败时执行补偿式回滚并返回 `partial_failure` 明细。

### Package contract

- Skill：根目录必须有 `SKILL.md`，可带 `references/`、`scripts/`、`assets/` 等静态文件；包名优先取合法 frontmatter `name`，否则取源目录名，最终部署目录名必须是合法单段名称。
- SkillBundle / Plugin：v1 不接收 `plugin.json`，统一返回 `UNSUPPORTED_PLUGIN_TYPE`。未来若确定静态 SkillBundle 合同，再单独增加解析和部署规则。
- 所有路径规范化为 project-independent POSIX 相对路径；拒绝绝对路径、`..`、符号链接逃逸、重复目标和超出大小/文件数限制；Windows 下按大小写不敏感规则检查同名路径。
- 下一阶段公开 GitHub 只接受 `https://github.com/...` 与对应 `tree/<ref>/<subdir>` 形式；下载压缩包后只解压声明子目录。下载、解压后总字节数、文件数和单文件大小都有上限，拒绝 zip symlink、绝对路径、`..`、重复路径和压缩炸弹。必须保存请求 ref 与解析后的 commit SHA。私有仓库、Token、任意 Git URL 和安装脚本均延期。

### Deployment rules

Artifact import 与 Deployment 分离。预览返回 Artifact hash、文件数、总大小和目标状态；import/deploy 请求必须携带对应 plan hash，执行时重新校验，防止 TOCTOU。import 只写 Library，不自动写 Agent 目录；deploy 只能引用已验证 Artifact。

每个部署 Skill 目录写入 `.ruflo-skill-manager.json`，包含 `artifact_id`、`content_hash`、`installed_at`、`manager_version`。无 marker 的同名目录视为非托管并返回结构化 `TARGET_CONFLICT`；同 hash 是幂等 no-op；托管目录内容变更时也返回 conflict，不静默覆盖。失败只清理本次 staging，替换已有托管内容时先保留临时备份，失败则执行补偿式恢复。多个目标不承诺跨目录原子性；若恢复也失败，Operation 必须报告 `partial_failure` 和每个目标的事实状态。

默认目标：先实现 `codex`，随后增加 `claude_code`；`agents` 作为明确的自定义/后续目标，避免 global/project scope 混淆。默认目标不存在时，只允许在确认后创建位于当前用户目录下的标准 skill root；自定义 target 必须已存在。解析后必须位于用户允许范围内；拒绝符号链接/junction 逃逸和 manager 自身 Library 目录作为 target。

### Security and recovery invariants

- `plugin.json` 在 v1 不解析、不执行，出现时返回 `UNSUPPORTED_PLUGIN_TYPE`；未来具体 Plugin/SkillBundle 合同必须另行定义字段白名单和权限模型。
- Artifact identity 必须包含规范化内容 hash；GitHub Artifact 还必须包含 resolved commit SHA，不能用 branch/tag 名称作为身份。
- 包不能携带或覆盖 `.ruflo-skill-manager.json`；该文件由 manager 独占生成。目标目录中的 marker 必须同时匹配 Artifact id、content hash 和文件清单，单独存在 marker 不足以证明 ownership。
- 本地 source 不能位于 Library、operation staging、任何 target 目录或其子目录，避免递归复制和自覆盖。
- deploy 只在计划 hash、Artifact hash 与目标 fingerprint 均未变化时继续；任一 target conflict 时不写入目标。已托管且 hash 相同为 no-op，已托管但内容不同也先返回 conflict。
- SkillBundle 的多个 Skill 和多个 target 采用补偿式部署；任一部分失败都必须记录每个目标的成功、回滚或未恢复状态，不能伪报全局成功。
- operation 文件使用临时 JSON + `os.replace`；API/CLI 默认只返回脱敏 source label，不返回本地绝对路径。异常只记录稳定错误码。启动清扫遗留临时目录；若 crash 发生在 target 部署后，marker + content hash 用于识别完整部署，无法证明完整性的 operation 标记为 failed，不自动猜测恢复。
- 变更路由只能在 loopback 请求中执行；若服务显式绑定非 loopback，必须要求本地授权令牌，缺少授权时拒绝所有 import/deploy/remove。

### HTTP and WebUI

新增 `src/server/routes/skill_manager.py` 与 `src/services/skill_manager.py`：

```text
GET  /api/v1/skill-manager/agents
GET  /api/v1/skill-manager/library
POST /api/v1/skill-manager/artifacts/inspect
POST /api/v1/skill-manager/artifacts/import
POST /api/v1/skill-manager/deployments/plan
POST /api/v1/skill-manager/deployments/apply  -> 202 {operationId}
GET  /api/v1/skill-manager/operations/{operation_id}
```

CLI 与 HTTP 使用相同的核心 interface：

```text
python -m src.cli skill-manager list --json
python -m src.cli skill-manager inspect <source> --json
python -m src.cli skill-manager import <source> --plan-hash <hash> --confirm --json
python -m src.cli skill-manager deploy <artifact_id> --agent codex --plan-hash <hash> --confirm --json
python -m src.cli skill-manager status --json
```

Settings modal 在现有“模型 / 搜索”旁增加“Skills”页。页面包含来源输入、Artifact 预览、目标 Agent、冲突提示、确认部署按钮和 operation 轮询结果。路由仍由 `settings.js` 内部切换，不增加顶层导航；Plugin 在 v1 只显示“不支持”，不提供安装按钮。

## Tasks

### Task 1: Domain contract and safe package inspection

- Files: `src/skill_manager/__init__.py`, `src/skill_manager/types.py`, `src/skill_manager/manager.py`, `tests/test_skill_manager/test_package.py`
- Test: 先写 Source/Artifact/Deployment 类型、Skill 识别、`plugin.json` 拒绝、路径穿越、符号链接、大小/文件数限制和稳定 hash 测试。
- Acceptance: 非法包在写入 Library 前失败；相同输入得到相同 Artifact hash；不执行包内文件；出现 `plugin.json` 返回 `UNSUPPORTED_PLUGIN_TYPE`；保留 marker 和 source 自包含均被拒绝。
- Status: complete (commits `183d9996`..`18bd9c49`, review clean)

### Task 2: Library persistence and Agent discovery

- Files: `src/skill_manager/storage.py`, `src/skill_manager/agents.py`, `tests/test_skill_manager/test_storage.py`, `tests/test_skill_manager/test_agents.py`
- Test: 原子写入、损坏 JSON、用户配置目录、默认 Agent 发现、自定义路径越界和 marker round-trip。
- Acceptance: 无数据库；并发写入由 lock 串行；状态损坏 fail-closed；Artifact 与 Deployment 可分别读取；目标路径不会逃出允许根目录；服务重启后的遗留 operation 有明确 failed 状态。
- Status: complete (commit `b8881fea`, manual review clean)

### Task 3: Import, plan and compensating deployment

- Files: `src/skill_manager/sources.py`, `src/skill_manager/manager.py`, `tests/test_skill_manager/test_install.py`
- Test: 本地目录适配、Artifact hash 变化、import/deploy 分离、幂等部署、非托管冲突、托管内容冲突、安装失败恢复和 partial failure。
- Acceptance: import 不写 Agent；deploy 只接受已验证 Artifact；任何冲突不改目标；失败不伪报成功，必要时返回每个目标的补偿结果。
- Status: complete (commits `4fa021d0`..`17230ce2`, review findings fixed; 29 focused tests pass)

### Task 4: HTTP service, JSON CLI and durable operations

- Files: `src/services/skill_manager.py`, `src/server/routes/skill_manager.py`, `src/server/app.py`, `src/cli.py`, `tests/test_server/test_skill_manager.py`, `tests/test_cli_ext/test_skill_manager.py`
- Test: 参数校验、Artifact/import/deploy 分离、确认门禁、CLI `--json`、稳定退出码、202 operation、状态轮询、未知 operation、结构化冲突和 auth/loopback 行为。
- Acceptance: route 和 CLI 不实现文件操作；operation 状态为 `queued/downloading/validating/installing/succeeded/failed/conflict/partial_failure`，重启失败码为 `server_restarted`；非 loopback 无本地授权时不能 mutation；异常只返回稳定错误码，不返回密钥、完整环境变量或本地绝对路径。
- Status: complete (commits `0dc6cf67`..`92c3613d`, 36 focused tests pass)

### Task 5: Settings Skills page

- Files: `web/js/views/settings.js`, `web/style.css`, `web/index.html`, `docs/webui-buttons.md`
- Test: 以现有 WebUI 手工冒烟为主；检查插件页所有按钮与 API 映射文档同步。
- Acceptance: 来源 → inspect → 显式确认 import Artifact → 选 Agent → plan → 显式确认 deploy → 轮询 → 成功/失败可见；按钮在请求期间禁用；冲突不会误触发部署；Plugin 明确显示不支持。
- Status: complete (commit `20b434cf`, Node syntax check passed; manual browser smoke remains rollout gate)

### Task 6: Documentation and rollout

- Files: `CONTEXT.md`, `docs/adr/0010-skill-library-and-agent-deployment.md`, this plan
- Test: 文档中的目录、接口、状态和回滚规则与实现一致。
- Acceptance: ADR、术语表、WebUI 按钮手册、计划和 `.superpowers/sdd/progress.md` 均更新；只在本地真实目标验证通过后启用入口。
- Status: complete (ADR, glossary, button manual, progress ledger synchronized)

### Implementation order

1. 先完成静态 Skill + 本地目录 + Codex target + Python core + JSON CLI。
2. 再接 HTTP 和 Settings 页面；WebUI 与 CLI 必须走同一核心 interface。
3. 通过真实 Codex 目标验证后，再增加 Claude Code。
4. 公开 GitHub、SkillBundle、更新/删除和真正 Plugin Installer 均为后续阶段，不阻塞 v1。

## Audit

### Revision after multi-angle review

本轮整改针对上一轮审查新增以下硬约束：

1. **目标对齐**：增加无交互 JSON CLI，使模块可被 WebUI、脚本和 Agent tool 共同调用。
2. **生命周期**：将 `Source`、不可变 `Artifact`、具体 `Deployment` 设为三个不可互换身份；import 不自动部署。
3. **Plugin 边界**：v1 只接受静态 Skill；出现 `plugin.json` 或其他 Plugin 形态均返回 `UNSUPPORTED_PLUGIN_TYPE`。
4. **网络身份**：公开 GitHub 仅作为后续阶段，并持久化 requested ref 与 resolved commit SHA。
5. **事务诚实性**：跨多个目录只承诺补偿式回滚和 `partial_failure`，不宣称真正原子事务。
6. **本地控制面安全**：mutation route 仅允许 loopback，非 loopback 必须有本地授权令牌。
7. **范围收敛**：v1 先做本地 Skill、一个 Agent、核心 CLI 和 Settings 闭环；GitHub 与第二个 Agent 后置。

### Round 1: 全面漏洞审计

已完成整改；逐项记录如下：

1. **重大隐患 — Windows 非空目录替换**：原设计隐含 `os.replace(staging, target)` 可覆盖目录；Windows 可能失败或留下半状态。改为旧目录改名备份、staging 改名目标、失败恢复，并返回 `target_busy`。
2. **重大隐患 — BackgroundTasks 丢失任务**：进程退出会让 operation 永久停在 installing。启动时扫描 active operation 并标记 `failed/server_restarted`，不宣称可恢复执行。
3. **重大隐患 — GitHub 压缩炸弹**：只校验 URL 不能防大压缩比、超文件数和超单文件。增加下载前、解压中、解压后的字节/文件数限制和 symlink/路径检查。
4. **重大隐患 — Plugin manifest 扩权**：任意字段或路径可能被误解释为执行入口。限定字段、要求合法 id/version/skill path，未知字段不执行。
5. **重大隐患 — marker 可伪造**：仅检查 `.ruflo-skill-manager.json` 会允许源包伪造 ownership。保留 marker 文件名、由 manager 独占生成，并同时校验 package id、hash 和文件清单。
6. **重大隐患 — source 自包含复制**：source 位于 Library 或 target 内时会递归复制、覆盖自身或耗尽磁盘。安装前拒绝 source 与受管目录互为祖先/子孙。
7. **优化疏漏 — `.agents` scope 歧义**：全局 `~/.agents/skills` 与项目 `.agents/skills` 可能显示成同一 Agent。内置只保留 global target，项目目录只能作为明确的 custom target。
8. **重大隐患 — SkillBundle 多 Skill 部分成功**：第一个 Skill 成功、第二个冲突会留下半个 Bundle。整个 package × target 计划必须预检；部署过程失败时执行补偿式回滚并记录无法恢复的目标，不伪报全局原子成功。
9. **重大隐患 — operation JSON 撕裂**：进程在状态写入中断会破坏轮询。所有 operation JSON 使用临时文件加 `os.replace`，损坏状态返回稳定错误码。
10. **重大隐患 — staging/backup 孤儿**：崩溃后旧目录备份可能继续占用空间或被错误当成正式目录。启动清扫并只在 marker/hash 完整时识别部署，否则标记失败。
11. **重大隐患 — TOCTOU**：预览后远程源被替换，用户确认的不是实际安装内容。安装时重新获取并比对 preview hash，不一致则不写入。
12. **重大隐患 — target symlink/junction 逃逸**：自定义路径解析后可能跳出允许根目录。校验 realpath、拒绝 symlink/junction 目标和 Library 目录，并要求 target 已存在。

### Round 2: 压力测试推演

| 场景 | 连锁后果 | 加固结果 |
|---|---|---|
| 网络超时或部分下载 | 预览失败；若错误穿透会污染 Library | 下载只写 staging，失败清理 staging，Library 不变 |
| 磁盘不足 | staging 或 backup 残留，后续部署持续失败 | finally 清理；operation=`failed/disk_full`；目标未切换则不动 |
| 服务重启 | operation 状态与实际目录不一致 | active operation 标 `server_restarted`；下次状态按 marker/hash reconcile |
| 两个安装并发 | 相同 target 同时改名，目录或 manifest 撕裂 | manager lock 串行；第二个 job 重新校验 preview hash |
| Agent 文件被占用 | Windows rename 失败 | 保留原目录，返回 `target_busy`，不删除原内容 |
| SkillBundle 第二个 Skill 冲突 | 第一项已落盘 | 补偿式 rollback，恢复可恢复目录并报告 partial failure |
| source 位于 target | 递归读取并自覆盖 | 预检直接拒绝 `source_target_overlap` |
| Windows 大小写碰撞 | `Foo` 与 `foo` 在 Linux 可并存、Windows 不可并存 | 规范化后按大小写不敏感规则去重 |
| marker 与内容 hash 不一致 | 误判为托管并覆盖人工修改 | 视为 conflict，不覆盖 |
| 默认 target 不存在 | 自动 mkdir 可能写入错误路径 | 仅允许在确认后创建标准用户目录；自定义 target 仍需已存在 |

### Re-review after fixes

Round 1 复审通过：上述 12 项均有对应的接口约束、测试或恢复规则；未发现新的致命缺陷。Round 2 复审通过，但以下风险仍需人工确认：Windows ACL 不由 `chmod` 充分表达；多 worker 不支持跨进程 job executor；跨 Library 与多个 Agent 目录没有真正的文件系统事务。

- Human review: pending.
- Open risks: Windows ACL 不能仅靠 `chmod` 表达；多 worker 部署不支持跨进程 job executor；GitHub URL 解析需限制到公开 codeload；目录改名可能被外部进程占用，必须返回可识别的 `target_busy`；跨 Library 与多个 Agent 目录不存在真正的单文件系统事务，只能通过 lock、staging、备份和启动 reconcile 达到可恢复状态。
- Rollback: 未进入编码前删除本计划/ADR；实现阶段仅删除新增 Library staging/job 文件，已有非托管 Agent 文件永不触碰；托管更新失败从临时备份恢复。

### Revision re-review

本轮整改后的文档级复审结果：

- Round 1：原先的 P0 缺口已关闭——CLI 调用面、Source/Artifact/Deployment 分离、Plugin 拒绝策略、loopback 授权、远程 commit 身份和补偿式回滚均已写入接口与验收标准。
- Round 2：压力推演覆盖 CLI 直接调用、WebUI 两阶段确认、来源变化、目标漂移、非 loopback 请求、进程重启、多目标部分失败和 `plugin.json` 输入；均有明确拒绝、恢复或事实状态出口。
- Implementation gate：仍需通过真实测试确认 CLI 与 HTTP 共享同一核心实现、默认目标创建不越界、Windows ACL/文件占用处理、operation reconcile 和 partial failure 结果；在这些证据出现前，计划保持 `planned`，不宣称完成。

| 压力场景 | 必须观察到的结果 |
|---|---|
| CLI 无交互调用 | 只输出 JSON/稳定退出码，不读 stdin，不绕过核心校验 |
| inspect 后来源变化 | import 拒绝 stale plan，不写 Library 或 Agent |
| import 后 deploy | 只部署已验证 Artifact，不能重新信任原始 source |
| 非托管同名目录 | `TARGET_CONFLICT`，原目录字节不变 |
| 已托管目录被手改 | `TARGET_DRIFT`/conflict，不覆盖、不删除 |
| 非 loopback mutation | 无本地授权时拒绝 |
| 多目标中途失败 | `partial_failure`，逐目标记录成功/回滚/未恢复状态 |
| 输入 `plugin.json` | `UNSUPPORTED_PLUGIN_TYPE`，不执行、不落盘 |

## Completion evidence

- Final commit:
- Tests:
- Static checks:
- Documentation updated: pending
- Progress ledger updated: pending
