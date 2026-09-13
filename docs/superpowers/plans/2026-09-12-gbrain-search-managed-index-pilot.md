# GBrain MCP 项目级 hybrid 搜索试点方案（历史草案）

> 本文已与外部运行时发现/引导安装方案合并。后续以 [`2026-09-12-gbrain-hybrid-pilot-unified.md`](2026-09-12-gbrain-hybrid-pilot-unified.md) 为唯一实施入口；本文保留作为历史审计上下文。

> 本方案承接 `2026-09-12-gbrain-mcp-search-adapter.md`，将目标从“接入搜索 Adapter”扩展为“项目级索引管理 + 可选 hybrid 搜索”。本方案仍然不是 GBrain 全量替代本项目搜索的方案。

## 1. 目标与边界

### 1.1 目标

为每个 `knowledge/<project>/` 项目实例提供一个可控的 GBrain hybrid 搜索试点：

1. WebUI 搜索页提供项目级 GBrain 开启/关闭控制。
2. 开启后，后台异步扫描该项目的 `wiki/`，导入一个独立的 GBrain source。
3. 初次导入、embedding 和路径校验全部通过后，`hybrid` 且无类型过滤的搜索才切换到 GBrain。
4. 页面新增、修改、删除、归档和恢复后，GBrain 索引进入增量同步。
5. GBrain 不可用、索引未就绪、结果无法映射或同步失败时，自动回退本地搜索。
6. 关闭只切换搜索后端，不删除 GBrain 数据；删除远程索引属于后续独立的破坏性操作。

### 1.2 非目标

- 不替代 `keyword`、`vector` 和带 `page_type` 的搜索路径。
- 不把整个 `knowledge/` 目录无差别导入；只导入当前项目的 Wiki 页面目录。
- 不在 WebUI 请求中同步执行全量导入。
- 不由浏览器直接启动 Bun、访问文件系统或持有 GBrain 写权限。
- 不默认删除 GBrain source，不自动修改本地 Wiki、schema 或 embedding 配置。
- 不把“导入命令成功”当作“搜索质量等价”；必须有 ready gate 和对照验证。

## 2. 已确认的技术约束

- 本项目 WebUI 搜索入口是 `web/js/views/search.js`，搜索请求是 `POST /api/v1/projects/{project_id}/search`。
- 当前 `src/services/search.py` 会在本地 vector readiness 失败时直接返回空结果；远程路由必须在该检查前单独判断。
- 当前本地结果使用 Wiki 文件 `path/content`；GBrain `search` 返回 chunk 级结果，字段是 `slug/page_id/title/type/chunk_text/score/source_id` 等。
- 本项目已有 `src/wiki/features/gbrain_compat.py`，可复用 Wiki path → GBrain slug、wikilink 重写和 relation materialization 逻辑。
- GBrain 的 `search` 是只读 MCP operation；`put_page`、`delete_page`、`restore_page` 是写入 operation。
- GBrain 的目录 `import` 和 `sync_brain` 属于本地 CLI 路径；`sync_brain` 标记为 `localOnly`，不能把现有 MCP `search` 直接当作批量导入接口。
- GBrain source 的 slug 在 source 内唯一，source ID 必须稳定且每个项目独立。
- 本项目 Wiki 是事实源；GBrain 是可删除、可重建的检索副本。

### 2.1 部署前提

- 本期默认 ruflo server/worker 与 `D:\5-Project\gbrain-master`、GBrain 数据目录在同一台机器；若 GBrain 在另一台机器，必须改为 HTTP MCP/远程导入方案，不能把本地路径直接传过去。
- GBrain 的 `GBRAIN_HOME`、embedding Provider、数据库连接和 Bun 路径由服务端运维配置提供，不由 WebUI 传入，也不写入项目状态。
- 开启前必须通过 preflight 验证 executable、cwd、GBrain home、source scope、写权限和 embedding credentials；任何一项失败都保持 local。

## 3. 总体架构

```text
WebUI 开关
  → ruflo HTTP API
  → 项目级配置/状态
  → durable sync job
  → GBrain CLI 初次导入 + MCP 增量写入/删除
  → source/embedding/path/freshness ready gate
  → hybrid 搜索路由到 MCP search
  → chunk 去重 + slug/path 映射 + 本地安全过滤
  → 失败或未就绪时回退 local
```

### 3.1 导入通道选择

采用“CLI 批量初次导入 + MCP 增量变更 + MCP 搜索”的组合：

- 初次全量导入：后端 worker 以固定 executable、固定 cwd、参数数组调用 GBrain CLI `sources add` / `import`。不使用 shell，不接受前端传入命令、cwd 或路径。
- 增量 upsert：worker 通过受控 stdio MCP 会话调用 `put_page`，将变化页面写入指定 source。
- 增量删除/归档：worker 调用 `delete_page`；恢复时调用 `restore_page`。
- 搜索：搜索请求通过只读 MCP `search`。
- 如果未来希望全链路 MCP，需要给 GBrain 增加专用批量同步 MCP operation；不把该需求伪装成现有 `search` 能力。

### 3.2 Source 隔离

- 每个 ruflo 项目对应一个 GBrain source，`federated=false`。
- source ID 首次生成后写入项目状态，不从项目名称临时推导。
- source ID 使用项目 UUID 的稳定短哈希，满足 GBrain 的 1–32 位小写字母/数字/连字符约束。
- 所有搜索、写入、删除请求都携带或固定该 source 作用域。
- 全量扫描只允许从 `resolve_project(project_id)` 得到的项目根目录继续解析，禁止接收任意前端目录。

## 4. 项目级状态与 API 契约

### 4.1 持久化

配置文件：`<project>/.llm-wiki/gbrain-search.json`

```json
{
  "schema_version": 1,
  "enabled": true,
  "source_id": "ruflo-a1b2c3d4e5f6",
  "source_name": "ruflo-kb/<project>",
  "source_path": "<project>/wiki",
  "backend": "gbrain",
  "consent_at": 0,
  "config_epoch": 1
}
```

运行状态：`<project>/.index/gbrain-search/state.json`

```json
{
  "status": "disabled|queued|syncing|ready|stale|failed",
  "config_epoch": 1,
  "job_id": "",
  "total_pages": 0,
  "synced_pages": 0,
  "failed_pages": 0,
  "deleted_pages": 0,
  "embedding_coverage": 0.0,
  "path_mapping_coverage": 0.0,
  "manifest_hash": "",
  "last_success_at": 0,
  "last_error_code": "",
  "last_sync_duration_ms": 0
}
```

配置只保存意图和 source 身份；状态保存进度和非敏感错误分类，不保存 query、页面正文、API key 或完整命令环境。启用/重建 API 必须通过现有写权限校验；只读用户只能查看状态。`config_epoch` 用于防止关闭后旧 job 把状态错误写回 `ready`。

### 4.2 HTTP API

新增 `src/server/routes/gbrain_search.py`：

| API | 行为 |
|---|---|
| `GET /api/v1/projects/{id}/gbrain-search` | 返回配置、同步状态、是否可切换到 GBrain、非敏感 diagnostics |
| `POST /api/v1/projects/{id}/gbrain-search/enable` | 要求 `confirm=true`；写入 enabled，创建/恢复同步 job，返回 `202 + jobId` |
| `POST /api/v1/projects/{id}/gbrain-search/disable` | 立即把搜索后端切回 local；保留 source 和索引 |
| `POST /api/v1/projects/{id}/gbrain-search/rebuild` | 显式确认后执行全量重建；不由普通开关隐式触发 |
| `GET /api/v1/projects/{id}/gbrain-search/jobs/{job_id}` | 查询初次导入或重建进度 |

`enable` 不直接返回“已启用搜索”，只返回 `status=queued/syncing`。只有 ready gate 通过后，状态才允许变为 `ready`。

## 5. 同步模型

### 5.1 初次导入

1. 解析项目并锁定项目级同步锁。
2. 扫描 schema 声明的 Wiki page directories；排除 `_archive`、`_stubs`、`.index`、Book 输出和非 Markdown 文件。
3. 为每个页面计算 canonical path、GBrain slug、内容 hash、页面 type 和是否允许进入语义检索。
4. 检查 GBrain source；不存在时由后端 worker 创建，失败则状态 `failed`，搜索保持 local。
5. 调用 GBrain CLI 批量 import；固定 source ID、项目 Wiki 根目录、timeout 和并发上限。
6. 导入完成后查询 source 页面数、未 embedding chunk 数和错误状态。
7. 建立本地 `slug → canonical Wiki path` manifest，验证所有可返回结果均可回读本地文件。
8. 运行只读 smoke query 和 source isolation 检查。
9. 全部 ready gate 通过后将状态置为 `ready`；否则为 `failed/stale`，不切换搜索后端。

### 5.2 增量同步

页面写入、删除、归档、恢复可以在成功提交后产生 GBrain sync hint，但 hint 不是一致性的唯一来源：

```text
upsert: project_id + canonical_path + content_hash + page_slug
delete: project_id + canonical_path + page_slug
restore: project_id + canonical_path + page_slug
```

同步 hint 必须在 Wiki 原子写入成功后产生；不能在写入前把远程索引标为成功。真正的正确性由周期性 snapshot reconcile 保证，因为项目中存在多种 Wiki 写入路径，不能假设每条路径都能稳定发出事件。intent/hint 需要：

- 幂等键：`project_id + operation + canonical_path + content_hash`
- 重试上限和失败记录
- 进程重启后可恢复
- 同步失败时将状态置为 `stale`，但不破坏本地搜索
- 定时 reconcile 扫描 manifest，修复漏发或进程崩溃造成的远程漂移

优先复用现有 `safe_write`、项目 mutex、EventBus 和 queue 的持久化/重试模式；事件只作为降低延迟的 hint，不能替代 reconcile。不要把 GBrain 同步任务伪装成普通 URL/file ingestion task，避免误进入 Collector → Analyzer → Generator 管线。

### 5.3 关闭和重启

- 关闭：只写 `enabled=false`，后续查询立即走 local；正在执行的同步可以完成或被安全取消，但不得删除 source。
- 服务重启：读取持久化状态；`queued/syncing` 任务重新排队；`ready` 但 freshness 超阈值则标记 `stale` 并回退 local，直到 reconcile 成功。
- job 每次写状态前校验 `config_epoch` 和 `enabled`；关闭或重建时使旧 job 失效，旧 job 即使完成也不能把已关闭项目切回 GBrain。
- source 删除：本期不提供普通 WebUI 按钮；后续若提供，必须二次确认、显示页面数，并先执行 dry-run。

## 6. 搜索路由与结果闭环

只在以下条件全部满足时使用 GBrain：

```text
enabled=true
status=ready
mode=hybrid
page_type 为空
source_id 存在
freshness 未超阈值
```

路由顺序必须先判断 GBrain readiness，再执行本地 vector readiness；否则本地向量未 ready 时会提前返回空结果，远程试点永远无法生效。

Adapter 处理：

1. MCP 调用只发送 `query` 和 `limit`，source 由受控会话环境固定。
2. 校验真实 GBrain payload；读取 `slug/chunk_text/score/source_id`，不使用不存在的 `path/content` 字段。
3. 用 manifest 将 `(source_id, slug)` 映射为本地 Wiki path；映射失败的远程结果整批拒绝并回退 local。
4. 按 `(source_id, slug)` 去重，避免同一页面多个 chunk 占满 topK；保留最高分 chunk 作为 snippet。
5. 保留本地 `用途/可执行` 和 frontmatter 过滤；无法读取本地 frontmatter 时不返回远程结果。
6. GBrain 返回合法空数组时，如果本地结果非空，记录 `remote_empty_mismatch` 并回退 local。
7. 返回原 HTTP JSON 契约，同时 diagnostics 标记 `backend=gbrain|local`、`backend_ready`、`local_vector_ready`、`fallback_reason` 和同步版本，不记录 query。远程 ready 但本地 vector 未 ready 时，`ready` 表示当前选定 backend 的 ready 状态，不再把本地 vector 状态冒充远程 backend 状态。

## 7. WebUI 设计

修改 `web/js/views/search.js`：

- 搜索页新增“GBrain MCP”开关、状态徽标和同步进度摘要。
- 初次点击开启时弹出确认：会复制当前项目 Wiki 到 GBrain，可能产生 embedding 费用；确认后调用 enable API。
- `queued/syncing/stale/failed` 状态显示“本地搜索”，不显示为已启用。
- `ready` 状态显示“GBrain hybrid”；用户搜索时结果来源徽标支持 `gbrain`。
- 关闭按钮调用 disable API 后立即刷新状态，搜索继续使用本地。
- 每 2–5 秒轮询 job/status；页面离开后停止轮询。
- 搜索结果仍通过本项目 `files/content` 读取正文，不能直接信任远程返回正文路径。

同步修改 `docs/webui-buttons.md`，记录按钮位置、确认行为和 API 映射。

## 8. 实施任务（TDD）

### Task 0：冻结真实契约和可运行前置检查

**Files:**

- Create: `tests/test_gbrain_search/test_contract.py`
- Create: `src/gbrain_search/types.py`
- Create: `src/gbrain_search/__init__.py`
- Modify: `src/wiki/features/gbrain_compat.py`（仅在现有映射不足时）

**内容：**用真实 GBrain `SearchResult` fixture、source ID 规则、Wiki path/slug manifest、状态枚举和 ready gate 定义契约。增加 Bun/GBrain CLI/MCP capability preflight、部署拓扑检查和 source ownership 检查；前置失败不得启动导入，发现同名但非本项目 source 时不得自动接管。

### Task 1：项目级配置、状态和 durable job

**Files:**

- Create: `src/gbrain_search/api.py`
- Create: `src/gbrain_search/state.py`
- Create: `src/gbrain_search/jobs.py`
- Create: `tests/test_gbrain_search/test_state.py`
- Create: `tests/test_gbrain_search/test_jobs.py`

**内容：**实现项目路径解析、配置读写、原子状态更新、项目锁、job 去重、重启恢复、错误分类；不保存敏感字段。

### Task 2：初次导入和增量同步 worker

**Files:**

- Create: `src/gbrain_search/sync.py`
- Create: `tests/test_gbrain_search/test_sync.py`
- Modify: `src/events/events.py`（仅增加可选 sync hint 事件）

**内容：**实现 Wiki snapshot、hash manifest、固定参数的 GBrain CLI import、MCP upsert/delete/restore、重试、失败状态和周期性 reconcile。事件 hint 只用于加速，不承担完整性；测试使用 subprocess/MCP seam，不启动真实 Bun。

### Task 3：HTTP API 和服务生命周期

**Files:**

- Create: `src/services/gbrain_search.py`
- Create: `src/server/routes/gbrain_search.py`
- Modify: `src/server/app.py`
- Modify: `src/server/auth_middleware.py`
- Create: `tests/test_server/test_gbrain_search.py`

**内容：**实现 enable/disable/status/rebuild/job API；启用和重建属于写操作并复用现有权限边界；启用操作返回 202；服务启动恢复未完成 job；后端只能从服务端解析当前 project path，不能接受任意导入目录。

### Task 4：MCP 搜索 Adapter 和搜索路由

**Files:**

- Create or modify: `src/searcher/gbrain_mcp.py`
- Modify: `src/services/search.py`
- Modify: `tests/test_searcher/test_gbrain_mcp.py`
- Modify: `tests/test_server/test_service_search.py`

**内容：**基于真实 payload 完成 chunk 去重、source/path 映射、remote-empty mismatch、readiness 顺序和本地回退；保留带类型过滤请求的本地路径。

### Task 5：WebUI 开关与操作文档

**Files:**

- Modify: `web/js/views/search.js`
- Modify: `docs/webui-buttons.md`
- Create: `docs/guides/gbrain-mcp-search-pilot.md`

**内容：**实现确认、状态徽标、轮询、关闭回退、错误显示和来源徽标；文档说明数据复制、embedding 成本、权限、回滚和 source 删除不属于普通关闭。

### Task 6：真实只读验收

**Files:**

- Modify: `docs/superpowers/plans/2026-09-12-gbrain-search-managed-index-pilot.md`
- Create: `tests/test_integration/test_gbrain_search_pilot.py`（如现有集成宿主可隔离）

**Checks:**

```powershell
PYTHONPATH=. python -m pytest tests/test_gbrain_search tests/test_searcher/test_gbrain_mcp.py tests/test_server/test_gbrain_search.py tests/test_server/test_service_search.py -v --import-mode=importlib
PYTHONPATH=. python -m pytest tests/test_searcher tests/test_server tests/test_mcp_server -v --import-mode=importlib
python -m py_compile src/gbrain_search/*.py src/searcher/gbrain_mcp.py src/services/gbrain_search.py
git diff --check
```

真实 smoke 只允许使用无敏感内容的测试项目和 GBrain source，验证初始化、初次导入、embedding、source 隔离、搜索回读、页面更新、删除/恢复、关闭回退和重启恢复。

## 9. 验收标准

### 功能门

- 默认配置和未确认状态下，所有搜索走 local。
- 开启接口返回 `202`，不会阻塞 HTTP 请求。
- 未进入 `ready` 前，WebUI 明确显示本地搜索。
- 初次导入只覆盖当前项目 Wiki，不能越界扫描其他项目。
- 每个项目使用独立 source，100% 的远程结果带正确 source scope。
- 远程结果 100% 能映射回本地 Wiki path；无法映射时整批回退。
- 页面修改、删除、归档、恢复最终都能反映到 GBrain；失败时状态为 stale/failed 且 local 可用。
- 关闭后下一次查询立即走 local，且不删除远程 source。

### 质量门

- 使用至少 100 条脱敏代表性查询进行 local/GBrain 对照。
- GBrain Recall@10 不低于 local 基线的 95%。
- P95 查询延迟不超过 local 基线的 2 倍。
- 远程错误率低于 1%；remote-empty/local-nonempty mismatch 必须可观测。
- 初次导入和增量同步的 freshness lag 目标小于 5 分钟。
- 跨项目/source 泄漏为 0。
- embedding coverage 必须达到所有可检索页面的 100%；被 `embed_skip`/quarantine 排除的页面必须单独统计。

## 10. 回滚与故障处理

- 搜索回滚：项目配置写 `enabled=false`，或全局 kill switch 强制 `RUFLO_SEARCH_BACKEND=local`。
- 同步故障：停止新远程写入，标记 stale，继续 local；修复后从 manifest 重放。
- GBrain 进程异常：熔断一段时间，避免每次搜索/同步反复拉起子进程。
- 部分导入：保留 job checkpoint，允许重跑；不宣称 ready。
- source 数据清理：本方案不自动执行；需要独立 dry-run + 二次确认流程。

## 11. 方案自审与放行门

### Round 1：漏洞审计清单

| 级别 | 风险 | 后果 | 方案控制 |
|---|---|---|---|
| 致命 | 把一次性导入当成持续一致性 | 修改/删除后 GBrain 返回陈旧知识 | sync hint + manifest + 周期性 reconcile + freshness gate |
| 致命 | 用浏览器或用户路径驱动导入 | 越权读取其他项目或任意目录 | 服务端 project resolve + 固定 Wiki 根目录 |
| 致命 | 未 ready 就切换远程 | 索引不完整时返回误导结果 | ready gate，未 ready 固定 local |
| 重大 | 误调用 GBrain CLI-only sync 作为 MCP 工具 | 运行时必然失败 | 初次导入走本地 CLI，增量走受控 MCP |
| 重大 | chunk 无法映射本地页面 | WebUI 点击、过滤和引用失效 | manifest 全量闭环，失败整批回退 |
| 重大 | 远程合法空数组被当作成功 | 索引故障变成静默零结果 | remote-empty mismatch + local fallback |
| 重大 | embedding 费用/隐私未确认 | 意外外发内容或产生高额费用 | 开启前确认、状态提示、配置不存密钥 |
| 重大 | 同步与 Wiki 原子写入顺序错误 | 远程显示未提交或漏同步 | 只在本地 commit 成功后产生 hint，reconcile 负责最终校正 |
| 重大 | 只在部分写入路径接入事件 | capture/heat/relation 等路径修改后远程永久陈旧 | reconcile 是正确性主路径，事件只是加速 hint |
| 重大 | GBrain 与 ruflo 不在同一部署主机 | worker 无法读取本地 Wiki 或启动正确数据目录 | preflight 拒绝本地 CLI 路径，改用远程 MCP 适配方案 |
| 重大 | 关闭后旧 job 覆盖状态 | 用户关闭后搜索又悄悄切回 GBrain | `config_epoch` + enabled 双重校验 |
| 优化 | 页面重复 chunk 挤占 topK | 用户看到重复结果 | `(source_id, slug)` 去重 |
| 优化 | 服务重启丢失导入任务 | UI 显示假 ready 或任务永久挂起 | durable state + startup resume |

### Round 2：压力测试问题清单

| 场景 | 预期 | 加固 |
|---|---|---|
| 4,000+ 页面首次开启 | API 立即返回，后台限速导入 | job checkpoint、并发上限、进度状态 |
| 用户连续点击开启 | 只产生一个 job | project lock + idempotency key |
| 导入中关闭 | 查询立即 local | enabled 与 job 生命周期解耦 |
| 页面写入时 GBrain 不可用 | Wiki 写入成功，远程 stale | intent 重试，不阻塞 Wiki |
| 删除后 GBrain delete 失败 | 不返回陈旧远程结果 | stale + local fallback + reconcile |
| GBrain source 配错 | 不启动错误 source 的搜索 | source preflight + isolation test |
| 本地 vector 未 ready | 远程 ready 时仍可试点搜索 | remote readiness 先于 local vector gate |
| MCP payload 字段升级 | 远程结果拒绝并回退 | schema probe + contract test |
| embedding provider 不可用 | 不进入 ready | coverage gate + 明确错误 |
| 服务重启在导入中 | 不丢任务 | 状态恢复和 checkpoint |

### Round 3：整改后复审

本轮针对 Round 1/2 的关键问题完成复核：

- 一次性导入不再被当作一致性保证；snapshot reconcile 是正确性主路径，事件只做加速 hint。
- 导入目录、GBrain home、命令和权限均由服务端 preflight 控制，部署不满足同机前提时 fail-closed。
- 未 ready、source ownership 不明、embedding 不完整或 path 映射不闭合时不切换远程搜索。
- 关闭/重建通过 `config_epoch` 使旧 job 失效，避免状态回写污染。
- `keyword`、`vector`、类型过滤和正文读取继续保留本地路径，GBrain 只承担限定的 hybrid 检索试点。

复审结论：原有两轮审计问题已纳入方案，但本方案仍须经过独立多角度审计确认。当前状态为**有条件通过，不得跳过 CLI/MCP 双路径一致性、同步状态机、会话并发、成本和绝对质量门**。

### 放行结论

方案方向可实现，但必须先完成多角度审计报告中的 P0/P1 门禁，再开始编码。未通过 ready gate 前只能作为本地搜索系统运行；未通过质量门前不得把 GBrain 设为默认后端。详见 `docs/reports/2026-09-12-gbrain-managed-index-pilot-multi-angle-audit.md`。

## 12. 提交边界

- 本计划只提交方案和测试/实现任务，不在本轮直接修改代码。
- 每个 Task 单独测试、单独提交；完成后更新 `.superpowers/sdd/progress.md`。
- WebUI 变更必须同步更新 `docs/webui-buttons.md`。
- 实施完成后先做整体验收和代码审查，再询问是否 push；不自动 push。
