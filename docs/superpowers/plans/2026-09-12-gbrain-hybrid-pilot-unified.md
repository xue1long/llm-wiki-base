# GBrain MCP 项目级 Hybrid 搜索试点：统一实施方案

状态：执行中；Task 1 控制面与显式运行时引导已落地，搜索/导入仍未接通
目标：实现“GBrain MCP 可选 hybrid 搜索试点”，同时解决 GBrain 不在固定路径、换电脑或未安装时的运行时发现与受控安装问题。

本方案合并以下两份文档，后续以本文为唯一实施入口：

- `2026-09-12-gbrain-search-managed-index-pilot.md`
- `2026-09-12-gbrain-external-runtime-bootstrap.md`

GBrain 默认仓库：`https://github.com/garrytan/gbrain.git`。当前 GBrain 真实验证版本为 `0.42.58.0`，正式实施前必须锁定 reviewed tag/commit，不能跟随浮动 `master`。

## 1. 最终方案

把系统拆成两个生命周期，但串成一条门禁链：

```text
外部运行时管理
  发现 GBrain → 校验 Bun/版本/MCP → 用户确认后 clone/install
                                      ↓ runtime ready
项目级索引管理
  创建独立 source → 全量导入 → embedding → manifest/reconcile
                                      ↓ search ready
可选 Hybrid 搜索
  WebUI 开关 → MCP search → 结果映射/过滤 → 失败回退 local
```

关键决定：

1. 不把 GBrain 作为用户运行时唯一的 Git submodule。
2. 搜索请求不自动下载、不自动安装、不自动联网。
3. GBrain 运行时未 ready 或项目索引未 ready 时，始终使用本地搜索。
4. Ruflo Wiki 是事实源，GBrain 是可删除、可重建的检索副本。
5. 初次导入使用 GBrain CLI；增量同步和搜索使用受控 stdio MCP。

## 2. 目标与边界

### 2.1 目标

- 每个 `knowledge/<project>/` 项目实例可独立开启/关闭 GBrain hybrid 搜索；
- 项目移动到另一台电脑后，可通过项目相对目录发现 GBrain；
- 项目内没有 GBrain 时，用户确认后可从 GitHub clone 并安装；
- 初次导入、embedding、source 隔离、路径映射通过后才进入 `ready`；
- 页面新增、修改、删除、归档、恢复最终同步到 GBrain；
- GBrain 任何故障都不影响本地搜索。

### 2.2 非目标

- 不替代 `keyword`、`vector` 和带 `page_type` 的本地搜索路径；
- 不把整个 `knowledge/` 无差别上传，只处理当前项目 Wiki；
- 不让浏览器启动 Bun、读文件或持有 GBrain 写权限；
- 不自动删除 GBrain source；关闭只切回本地，不删除远程数据；
- 不在本方案内解决 embedding 服务部署、Brain 数据迁移或离线安装包分发。

## 3. 部署拓扑与数据边界

### 3.1 同机前提

本期要求 Ruflo server/worker、GBrain 运行时和 GBrain 数据服务位于同一台机器。若 GBrain 在另一台机器，必须改为 HTTP MCP/远程导入方案，不能把本地 Wiki 路径直接传过去。

### 3.2 目录

```text
<ruflo-project>/
├─ knowledge/<project>/
│  └─ wiki/                         # Ruflo 事实源
├─ external/gbrain/                 # 可选：项目级 GBrain 代码
├─ .llm-wiki/
│  ├─ gbrain-runtime.json           # 运行时配置
│  └─ gbrain-search.json            # 项目 source/搜索意图
└─ .index/gbrain/
   ├─ runtime-state.json            # 运行时探测/安装状态
   ├─ search-state.json             # 导入/同步/ready 状态
   └─ manifest.json                 # slug/path/hash 映射
```

共享运行时放在用户目录，例如 Windows：

```text
%LOCALAPPDATA%\ruflo-kb\external\gbrain\<reviewed-ref>/
```

GBrain 代码、Brain 数据、embedding 凭证三者分离；不把 GBrain 数据放进 `knowledge/`，也不把绝对机器路径写入可提交配置。

## 4. 外部运行时发现与安装

### 4.1 发现优先级

从高到低：

1. `.llm-wiki/gbrain-runtime.json` 的显式 `path`；
2. `RUFLO_GBRAIN_HOME`；
3. 项目内 `external/gbrain`；
4. 项目内 `.external/gbrain`；
5. 用户级托管目录；
6. PATH 中的 `gbrain`，仅当用户显式允许时检查。

只扫描明确目录，不递归搜索整块磁盘。显式配置路径存在但校验失败时必须 fail-closed，报告 `invalid_configured_runtime`，不得静默换用另一份 GBrain。

### 4.2 配置

```json
{
  "repository": "https://github.com/garrytan/gbrain.git",
  "ref": "<reviewed-tag-or-commit>",
  "path": null,
  "project_relative_path": "external/gbrain",
  "install_mode": "managed",
  "auto_install": false,
  "allow_path_command": false
}
```

`auto_install` 默认关闭。用户可通过 WebUI 明确确认，或通过 CLI 显式执行 setup；不能由普通搜索动作触发。

### 4.3 运行时校验

目录存在不等于可用，必须依次验证：

- `package.json`、`src/cli.ts`、锁文件存在；
- Bun 存在且版本满足；
- `bun run src/cli.ts --version` 成功；
- Git origin 匹配 allowlist，HEAD 等于 reviewed ref/commit；
- MCP `initialize` 成功；
- 只读 `status/search` smoke test 成功；
- embedding 不可用时只能标记 `degraded`，不能标记 hybrid ready。

状态：`missing`、`found`、`installing`、`ready`、`degraded`、`failed`。

### 4.4 受控安装

CLI：

```text
python -m src.cli gbrain runtime-status
python -m src.cli gbrain setup
python -m src.cli gbrain setup --install
python -m src.cli gbrain upgrade
```

安装流程：

1. 校验 canonical repository 和 reviewed ref；
2. 用户确认网络访问、代码下载和依赖安装；
3. 获取项目/托管目录安装锁，避免并发 clone；
4. clone 到临时目录，不直接覆盖正式目录；
5. 校验 origin、HEAD、关键文件和版本；
6. Bun 缺失时停止并给安装指引，不隐式安装 Bun；
7. 按锁文件安装依赖，默认限制额外 install scripts；
8. 执行 MCP initialize 和只读 search probe；
9. 全部成功后原子移动到正式目录并写入状态；
10. 任一步失败，清理临时目录，保留旧版本和本地搜索。

升级不在启动时自动执行。新版本未 ready 前保留旧版本，升级失败可回滚。

## 5. 项目级索引模型

### 5.1 独立 source

- 每个 Ruflo 项目一个 GBrain source，`federated=false`；
- source ID 首次生成后持久化，不从项目显示名临时猜测；
- source ID 使用项目 UUID 的稳定短哈希，符合 GBrain 约束；
- 所有导入、写入、删除、恢复和搜索固定在该 source scope；
- source ownership 未通过时不自动接管已有 source。

### 5.2 项目搜索配置

`<project>/.llm-wiki/gbrain-search.json`：

```json
{
  "schema_version": 1,
  "enabled": false,
  "source_id": "ruflo-a1b2c3d4e5f6",
  "source_name": "ruflo-kb/<project>",
  "source_path": "<project>/wiki",
  "backend": "gbrain",
  "consent_at": 0,
  "config_epoch": 1
}
```

`<project>/.index/gbrain/search-state.json`：

```json
{
  "status": "disabled|queued|syncing|ready|stale|failed",
  "config_epoch": 1,
  "job_id": "",
  "total_pages": 0,
  "synced_pages": 0,
  "failed_pages": 0,
  "embedding_coverage": 0.0,
  "path_mapping_coverage": 0.0,
  "manifest_hash": "",
  "last_success_at": 0,
  "last_error_code": "",
  "last_sync_duration_ms": 0
}
```

状态不保存 query、正文、API key 或完整环境变量。

## 6. 导入与同步

### 6.1 初次导入

1. 服务端解析 `project_id`，锁定项目同步锁；
2. 扫描 schema 声明的 Wiki page directories；排除 `_archive`、`_stubs`、`.index`、Book 和非 Markdown 文件；
3. 计算 canonical path、GBrain slug、内容 hash、页面类型；
4. 验证 runtime ready、source scope、写权限和 embedding；
5. 后端 worker 通过固定 executable/cwd/参数数组调用 GBrain CLI `sources add` / `import`；
6. 查询 source 页数、chunk 数、embedding 覆盖率；
7. 写入 `slug → canonical Wiki path` manifest；
8. 执行只读 smoke query 和 source isolation 检查；
9. 全部 ready gate 通过后才设置 `search-state.status=ready`。

### 6.2 增量同步

初次导入使用 CLI；增量使用受控 stdio MCP：

- 新增/修改：`put_page`；
- 删除/归档：`delete_page`；
- 恢复：`restore_page`；
- 搜索：只读 `search`。

Wiki 原子写入成功后才产生 sync hint。hint 只负责降低延迟，正确性由 snapshot manifest reconcile 保证。每个 intent 需要幂等键、重试上限、失败记录和进程重启恢复。

同步失败时置为 `stale`，不阻断本地 Wiki 写入，也不继续使用可能陈旧的 GBrain 结果；周期性 reconcile 修复漏发事件和进程崩溃造成的漂移。

### 6.3 关闭/重启

- 关闭只写 `enabled=false`，后续查询立即走 local，不删除 source；
- 重启时恢复 `queued/syncing` 任务；过期 `ready` 标记 `stale`；
- 每次 job 回写检查 `config_epoch` 和 `enabled`，防止关闭后旧任务把状态写回 ready；
- source 删除必须独立 dry-run + 二次确认，本期不提供普通关闭按钮。

## 7. 搜索路由与结果闭环

只有以下条件全部满足才调用 GBrain：

```text
runtime.status=ready
enabled=true
search-state.status=ready
mode=hybrid
page_type 为空
source_id 存在
freshness 未超阈值
embedding coverage=100%
path mapping coverage=100%
```

路由必须先判断 GBrain readiness，再判断本地 vector readiness，避免本地向量未 ready 时提前返回空结果。

Adapter 规则：

1. MCP 只发送 query/limit，source 由受控会话环境固定；
2. 严格校验 `slug/page_id/title/type/chunk_text/score/source_id`；
3. 用 `(source_id, slug)` 映射到本地 Wiki path；
4. 按页面 slug 去重，保留最高分 chunk 作为 snippet；
5. 复用本地 frontmatter/usefulness/filter 规则；
6. 映射失败、非法 payload、远程空结果但本地有结果、超时或异常时整批回退 local；
7. 返回现有 HTTP JSON 契约，diagnostics 只记录 backend、耗时、错误码和状态版本，不记录 query。

## 8. HTTP API 与 WebUI

新增项目级 API：

| API | 行为 |
|---|---|
| `GET /api/v1/projects/{id}/gbrain` | 返回 runtime、source、同步状态和非敏感 diagnostics |
| `POST /api/v1/projects/{id}/gbrain/setup` | 用户确认后创建安装任务，返回 `202 + jobId` |
| `POST /api/v1/projects/{id}/gbrain-search/enable` | 确认后异步创建 source/全量导入，返回 `202 + jobId` |
| `POST /api/v1/projects/{id}/gbrain-search/disable` | 立即切回 local，保留远程 source |
| `POST /api/v1/projects/{id}/gbrain-search/rebuild` | 显式确认后全量重建 |
| `GET /api/v1/projects/{id}/gbrain/jobs/{job_id}` | 查询安装、导入或重建进度 |

WebUI 搜索页：

- 未找到：显示“安装 GBrain”；
- 已找到但不可用：显示“重新验证/修复”；
- runtime ready 但索引未 ready：显示“本地搜索，同步中”；
- search ready：显示“GBrain hybrid”；
- 安装或导入期间搜索继续使用 local；
- 每 2–5 秒轮询任务状态，页面离开后停止轮询；
- 开启前明确提示数据复制、embedding 成本和隐私风险；
- 修改 `web/js/views/search.js` 后同步更新 `docs/webui-buttons.md`。

## 9. 实施任务（TDD）

### 当前执行记录（2026-09-12）

- 已完成 Task 1 的第一批安全闭环：运行时发现、显式路径 fail-closed、版本/MCP 校验、原子状态落盘。
- 已增加 `gbrain runtime-status` 与显式 `gbrain setup --install`；普通搜索不会触发下载或安装。
- 安装必须提供 reviewed `ref`，并通过隔离 clone、Bun 依赖安装、版本和 MCP 校验后才提升为 `ready`。
- 已完成：真实 Ollama + GBrain embedding canary 通过（768 维、100% coverage），真实 stdio MCP 长页面写入与 delete/restore 生命周期通过。
- 未完成：项目级 `knowledge/` 导入、source ownership/snapshot 增量同步、`/search` shadow 对比和 WebUI 接入仍受门禁限制。
- 验证：GBrain 控制面针对性测试 `12 passed`；真实 GBrain P0 记录见 `docs/reports/2026-09-12-gbrain-p0-capability-validation.md`。

### Task 0：冻结契约与 P0 前置条件

冻结 GBrain reviewed ref/commit、真实 payload、source ID 规则、runtime/search 状态机和 ready gate；准备无敏感 fixture；确认 embedding 服务可达。

### Task 1：外部运行时 resolver/setup

新增 `src/integrations/gbrain/`，对外只暴露 `api.py` / `types.py`。实现发现、校验、setup、upgrade、状态脱敏、安装锁和原子切换。

### Task 2：项目配置、source 和 durable job

实现配置读写、source ownership、状态持久化、项目锁、job 去重、重启恢复和错误分类。

### Task 3：初次导入、增量同步、reconcile

实现 Wiki snapshot、manifest、CLI import、MCP put/delete/restore、重试、checkpoint 和 freshness gate；复用现有 safe_write、EventBus、queue 模式。

### Task 4：MCP Adapter 与搜索服务路由

实现严格 payload 校验、chunk 去重、path 映射、source 隔离、readiness 顺序和 local fallback。

### Task 5：HTTP API 与 WebUI

实现异步 setup/enable/rebuild/status/job、权限校验、状态徽标、确认、轮询、关闭回退和文档同步。

### Task 6：真实跨机器验收

验证项目内运行时、用户级运行时、无运行时时显式 clone 三种环境，以及断网、拒绝安装、错误 ref、并发安装、中断恢复、embedding 不可用、source 隔离、页面更新/删除/恢复和本地回退。

## 10. 验收标准

### P0 功能门

- 运行时代码不依赖 `D:\5-Project\gbrain-master` 等绝对路径；
- GBrain 缺失时本地搜索仍 100% 可用；
- 用户显式确认后才能 clone/install；
- clone/install/probe 失败不产生半安装 ready 状态；
- runtime、MCP、source、embedding、path mapping 全部 ready 后才允许 hybrid；
- 每个项目使用独立 source，跨项目泄漏为 0；
- 远程结果 100% 可映射回本地 Wiki；
- 页面最终一致性由 reconcile 保证；
- 关闭后下一次查询立即走 local，不删除 source。

### P1 质量门

- 至少 100 条脱敏查询对照 local/GBrain；
- Recall@10 不低于 local 基线的 95%；
- P95 延迟不超过 local 基线 2 倍；
- 远程错误率低于 1%；
- freshness lag 小于 5 分钟；
- 可检索页面 embedding coverage 100%，排除项单独统计。

## 11. 回滚与安全

- 全局 kill switch：`RUFLO_SEARCH_BACKEND=local`；
- 远程故障：熔断、标记 stale、停止远程写入、继续 local；
- 安装/升级故障：保留旧版本，原子切换失败即回滚；
- Git/Bun/GitHub 不可用：显示明确错误，不影响本地搜索；
- 子进程使用参数数组和 `shell=False`，禁止 shell 拼接；
- 默认只允许 canonical GitHub 仓库和 reviewed commit；
- 不执行来源不明的 install script；
- 不记录密钥、完整环境变量、查询正文或页面全文；
- `external/` 和托管运行时目录加入 `.gitignore`。

## 12. 进入编码前门禁

以下条件全部具备证据后，才开始 Task 1：

1. GBrain reviewed tag/commit 已确定；
2. Git、Bun、GitHub 网络和 MCP 子进程前置条件已确认；
3. embedding 服务可达并能达到 100% coverage；
4. 有无敏感 Ruflo fixture，可验证真实导入、slug/path/source 映射；
5. 真实安装、MCP initialize、search 和 put/delete/restore smoke test 已通过；
6. plan-audit 两轮审查与整改完成。

本方案解决“依赖在哪里、如何安装、如何索引、如何搜索和如何回退”的完整链路，但不把外部依赖可安装误认为 GBrain 本身永远可用。任何外部条件不满足时，产品终局仍是可用的本地搜索。
