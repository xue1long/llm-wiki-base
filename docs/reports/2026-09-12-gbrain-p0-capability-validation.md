# GBrain MCP 可选 Hybrid 搜索试点：P0 门禁与真实能力验证报告

日期：2026-09-12  
范围：GBrain `0.42.58.0`、真实 CLI、真实 stdio MCP、隔离测试源  
测试原则：不上传或修改 `knowledge/` 现有项目；只在 GBrain 中创建专用测试源，验证后软归档。

## 1. 结论

初次 P0 验证曾被本机 Ollama 未启动阻断；随后完成真实复验，当前结论为：**嵌入能力门禁已通过，但项目级导入、影子搜索和 WebUI 仍未开启**。

已证明：

- GBrain CLI 可运行，支持 `sources add`、`import`、`query/search`、`status`。
- GBrain stdio MCP 可正常完成 JSON-RPC 初始化、工具发现和搜索调用。
- 源级搜索隔离参数可用；测试源只返回自身内容。
- Markdown 批量导入可成功完成：8 个文件、8 页、45 个 chunks、0 errors。
- 本机 `nomic-embed-text` 可通过 Ollama 返回 768 维向量，GBrain provider smoke 为 green。
- 真实 GBrain 语义查询返回预期文档；真实 stdio MCP 的长页面 `put_page → get_page → delete_page → restore_page` 闭环通过。

尚未开放：

- 当前只完成隔离 canary，尚未导入本项目 `knowledge/`，也未接入本项目 `/search`。
- 因此不能把“项目级 hybrid 搜索试点已完成”标记为 Ready；只能把“真实 GBrain 基础能力”标记为通过。

## 2. 实际验证记录

### 2.1 运行与能力发现

| 检查项 | 结果 | 证据 |
|---|---|---|
| CLI 运行 | PASS | `gbrain 0.42.58.0` |
| 批量导入命令 | PASS | `import <dir> --source-id ... --no-embed` 可执行 |
| 源管理 | PASS | `sources add/list/status/remove` 可执行 |
| CLI 关键词搜索 | PASS | `search "MCP deployment" --source ruflo-pilot-0912` 返回命中 |
| CLI query 入口 | PASS（当前退化为非向量结果） | `query ... --no-expand` 返回命中 |
| stdio MCP 初始化 | PASS | 协议版本 `2025-06-18` |
| MCP 工具发现 | PASS | 发现 `search`、`query`、`put_page`、`delete_page`、`restore_page` 等工具 |
| MCP 搜索 | PASS（当前非向量结果） | 返回 `slug/page_id/title/type/chunk_text/score/source_id` |
| GBrain doctor | WARN | health score `85`；连接检查在 `--fast` 下跳过，另有 skills/retrieval-reflex 警告 |

### 2.2 初次隔离源批量导入

测试源：`ruflo-pilot-0912`  
测试目录：GBrain 自身 `docs/mcp`，不包含本项目 `knowledge/` 内容。

实际结果：

```text
Found 8 markdown files
8/8 imported=8 skipped=0 errors=0
chunks=45
```

导入后状态：

```text
pages=8
chunks_total=45
chunks_unembedded=45
embedding_coverage_pct=0
staleness_class=unknown
```

这证明了“目录 → GBrain source → 页面/chunks → 搜索”链路，但由于使用了 `--no-embed` 且环境没有可用嵌入服务，只能证明关键词/数据库检索链路，不能证明完整 hybrid 质量。

### 2.3 初次真实 stdio MCP 写入测试

调用顺序：`initialize` → `put_page` → `get_page` → `delete_page` → `restore_page`。

结果：

- `initialize` 和工具调用协议正常。
- `put_page` 进入真实服务，但在 `ollama:nomic-embed-text` 嵌入调用重试 3 次后失败。
- 失败后 `get_page` 确认测试页不存在，说明没有留下半写入页面。
- 删除/恢复因页面未写入而返回 `page_not_found`，不是删除/恢复逻辑本身的通过证据。

### 2.4 复验结果（2026-09-12）

初次失败根因已定位为本机 Ollama 未启动，而不是 GBrain CLI、MCP 协议或 GBrain provider 配置错误。启动已有 Ollama 后，完成以下真实复验：

| 复验项 | 结果 | 证据 |
|---|---|---|
| Ollama embedding API | PASS | `nomic-embed-text` 返回 `768` 维向量 |
| GBrain provider smoke | PASS | `ollama:nomic-embed-text`，约 `70ms`，`768 dims`，`All probes green` |
| GBrain 真实批量导入与嵌入 | PASS | 隔离源 `8 pages / 45 chunks / 0 unembedded / 100% coverage` |
| GBrain 真实语义查询 | PASS | source-scoped query 返回预期文档，最高分 `0.8748` |
| 真实 stdio MCP 增量写入 | PASS | 长页面 `put_page` 返回 `created_or_updated`，`chunks=1`，`written=true` |
| MCP 生命周期 | PASS | `get_page`、`delete_page`、`restore_page`、恢复后 `get_page` 均成功 |

复验使用两个专用隔离 source，未读取或上传本项目 `knowledge/`。复验 source 已软归档，原有 `default/notes` source 未修改。

## 3. P0 门禁判定

| P0 门禁 | 判定 | 说明 |
|---|---|---|
| GBrain 进程可启动 | PASS | CLI 与 stdio MCP 均可启动 |
| MCP 协议可用 | PASS | 初始化、工具发现、搜索调用均成功 |
| 批量导入可用 | PASS | 8/8 文件成功导入，0 errors |
| 源级隔离可用 | PASS（基础） | CLI 使用显式 source，测试结果带正确 `source_id` |
| 语义嵌入可用 | **PASS（canary）** | 真实 Ollama + GBrain provider + 100% coverage |
| Hybrid 搜索可用 | **项目级 BLOCKED** | 隔离 source 的语义查询通过，但尚未接入 Ruflo 项目索引与 `/search` |
| MCP 增量写入闭环 | **PASS（canary）** | 长页面生命周期闭环通过 |
| 不影响本地搜索 | 未执行 | 尚未接入本项目 WebUI/本地搜索路由 |
| 真实 `knowledge/` 导入 | 未执行 | 有意避免上传现有项目数据；需提供非敏感小样本 |

## 4. 风险与判定边界

1. `--no-embed` 只能作为导入/结构验证手段，不能作为生产试点模式；否则“hybrid”会退化为关键词搜索。
2. 当前默认嵌入服务依赖本机 Ollama，连接失败时 MCP 写入不可用；必须先配置可达且稳定的嵌入提供方。
3. 本次没有把现有 `knowledge/` 上传到 GBrain，故尚未验证 Ruflo 页面 frontmatter、路径映射、增量删除和重建的一致性。
4. 初次测试源的 `sources remove` 触发了 GBrain 破坏性操作保护；为避免强制删除，复验源采用 `sources archive` 软归档，现有 `default/notes` 未受影响。后续是否 purge 需显式确认并单独验证。
5. GBrain doctor 的 `resolver_health`、`retrieval_reflex_health` 警告不直接证明搜索失败，但在正式部署前需要决定是否安装对应 skill/integration，避免把开发环境警告带入生产。

## 5. 进入下一阶段的最小条件

只需补齐以下条件，不建议先做 WebUI：

1. 固化 Ollama 的启动/可达性检查，避免换机或重启后再次出现同类阻断。
2. 使用一份不敏感的小型 Ruflo fixture 验证 frontmatter、slug、source_id 和本地路径映射。
3. 完成项目级 snapshot/incremental 同步与 source ownership 校验。
4. 在本地搜索与 GBrain 搜索上做 shadow 对比，确认失败时本地搜索仍可用。
5. 以上通过后，才可把“项目级 hybrid 试点”状态改为 Ready，并进入 WebUI 开关实现。

## 最终审计意见

原始目标“WebUI 开关后导入 `knowledge/`，随后使用 GBrain 搜索”在架构上可实现。真实复验已证明关键基础能力——本地 embedding、GBrain 语义查询和 MCP 增量生命周期——可用；但项目级 source/index/snapshot/shadow 仍未完成。因此当前审计结论为：**基础能力 P0 通过，项目级 hybrid 试点仍受门禁限制，暂不接入 WebUI**。
