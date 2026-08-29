# KC 主线正式发布闭包方案（审计整改版）

## 目标与边界

正式摄取唯一允许的发布链路：

```text
Collector → CanonicalDocument → JSON Analyzer → KnowledgeCandidate
→ source-level structural review → KnowledgeObject bundle
→ Wiki projection bundle → validate → stage → publish → index/vector
```

本阶段只证明来源级结构证据，不证明 claim 的完整真实性：

- `anchored`：quote 唯一命中 canonical source block；
- `structurally_verified`：source、document、block、quote、hash、refs 一致；
- `entailed`：claim 在语义上被证据支持，本阶段不自动判定；
- `unsupported` / `needs_human_review`：不得发布。

保留现有 Collector、Analyzer、Generator、Wiki writer 和 index/vector；不建立第二套独立 claim 页面写入通道。

## 1. 固定映射合同

不假设一对一映射。一次摄取产生一个不可变 `ProjectionBundle`：

- 一个 candidate 可产生多个 `KnowledgeObject`，每个 claim 一个稳定 object id；
- 一个 bundle 可产生多个 WikiPage；
- 每个 WikiPage 必须显式携带其 `knowledge_object_ids`；
- 每个 KnowledgeObject 至少映射一个 WikiPage；
- source page 可作为 bundle 的公共页面，但不能替代 claim page 的 evidence 映射；
- 映射不完整、出现未知 object id 或出现未映射 object 时，禁止 publish。

Generator 的结构化输出必须增加 `knowledge_object_ids`；旧输出没有该字段时进入 `needs_human_review`，不能猜测映射关系。

object id 固定为 `sha256(bundle_key + ":claim:" + claim_index + ":" + normalized_claim_text)[:16]`；同一 bundle 内 claim index 不可重排。page id 沿用 Generator 的稳定 id，重复 id 由现有 content-hash 冲突机制拒绝。

## 2. Source 与 Evidence 合同

### Source canonicalization

- 本地文件：规范化为项目根目录下的相对 POSIX 路径；Windows 比较时 `casefold()`；路径必须位于项目根目录内；
- URL：使用规范化 URL，移除默认端口和 fragment；
- 禁止用原始绝对路径直接比较；
- manifest 同时保存 `source_path`、`source_hash`、`document_id`；source 内容变化必须产生新 bundle。

### Quote 防护

- quote 必须非空且经过 canonical text 规范化；
- quote 长度少于 8 个 Unicode 字符时，只有在整篇文档中唯一命中且同时记录 block_id 才允许；
- quote 长度达到 8 个字符仍必须唯一命中 block；多 block 命中直接进入 `needs_human_review`；
- `quote_hash` 必须由规范化后的 quote 重新计算；
- `source_path`、`document_id`、`block_id`、`quote_hash` 任一不一致即拒绝。

## 3. 状态与兼容迁移

Evidence 新写入只允许：

```text
candidate → anchored → structurally_verified
                         ├→ entailed
                         ├→ unsupported
                         └→ needs_human_review
```

旧数据中的 `verified` 只在读取迁移层映射为 `structurally_verified`，不得继续作为新状态写入，也不得把它解释为 claim truth。

`verify_claim()`、IntegrityGate、projection writer 和检索过滤器必须统一使用新状态；迁移过程写审计日志，不原地覆盖未知历史值。

## 4. Projection Manifest 与发布状态机

每个 task 使用稳定幂等键：

```text
bundle_key = sha256(document_id + candidate_id + projection_version)
```

manifest 存放于：

```text
.index/kc/projections/<bundle_key>.json
```

stage 目录固定为 `.index/kc/staging/<bundle_key>/`，只允许保存 `manifest.json`、`objects.json`、`pages/` 和 `index.patch`；禁止直接写入 `wiki/`、正式 index 或 vector store。

最小结构：

```json
{
  "bundle_key": "...",
  "task_id": "...",
  "document_id": "...",
  "source_path": "raw/sources/a.md",
  "source_hash": "...",
  "candidate_id": "...",
  "projection_version": "kc-wiki-v1",
  "objects": [{"id": "...", "evidence_ids": ["..."]}],
  "page_object_map": [{"page_id": "...", "knowledge_object_ids": ["..."]}],
  "stores": {"wiki": "pending", "index": "pending", "vector": "pending"},
  "status": "preparing"
}
```

状态机：

```text
preparing → staged → published
preparing/staged → failed
published → withdrawn
```

规则：

- `preparing` / `staged` 内容只存在 staging，不进入正式 Wiki/index/vector；
- `published` 只允许在 source/evidence/object/page 映射校验通过后产生；
- vector 失败不得伪装成完成，manifest 标记 `vector=pending`，检索读取水位不得暴露未完成 bundle；
- 进程崩溃后由恢复器扫描 `preparing/staged`，校验 hash 后继续或标记 `failed`；
- 相同 bundle_key 必须幂等返回，禁止重复写 page/index/vector；
- 并发发布使用 manifest 版本和现有 expected-content-hash，冲突进入 `needs_human_review`。

## 5. 实现任务

### Task 1：Structural review

涉及：

- `src/kc/api.py`
- `src/kc/compiler/normalize.py`
- `src/kc/compiler/evidence.py`
- `src/kc/compiler/verify.py`
- `src/kc/contracts/evidence.py`

产出 canonical source、source hash、Evidence 状态和严格失败合同。

### Task 2：Projection bundle

涉及：

- `src/kc/compiler/compile.py`
- `src/kc/adapters/wiki_projection.py`
- `src/pipeline/generator.py`

产出 object/page 显式映射；未知或缺失映射不得自动修复。

### Task 3：Stage/publish writer

涉及：

- `src/kc/adapters/wiki_writer.py`
- `src/pipeline/ingest.py`
- `src/kc/publish/`
- `src/kc/adapters/legacy_write_guard.py`

所有正式写入统一经过 manifest guard；legacy/unified 只能显式兼容运行，不能绕过 writer guard。

writer 暴露单一入口 `publish_bundle(paths, bundle)`：先校验 manifest 与 stage 内容 hash，再在 `AtomicContext` 中发布 Wiki 文件和 index patch，最后登记 vector 状态；任何步骤失败都把 manifest 置为 `failed`，不推进 publication waterline。已有 page 的 expected hash 不匹配时整 bundle 失败，不允许部分发布。

publication waterline 存于 `.index/kc/publication_state.json`，只接受 `status=published` 且 `wiki=index=ready` 的 bundle；vector 为 `pending` 时 bundle 保持不可检索但可由恢复器重试。恢复器只处理 `preparing/staged`，不自动重写 `published/withdrawn`。

### Task 4：入口矩阵

逐项验证：

| 入口 | 真实 caller | 必经路径 | 最终写入 |
|---|---|---|---|
| programmatic | `src/pipeline/ingest.py::run_ingest` | KC bundle | publish writer |
| HTTP | `src/server/routes/ingest.py` → `src/services/ingest.py` | queue → run_ingest | publish writer |
| queue | `src/queue/` worker | run_ingest | publish writer |
| CLI/MCP | 各 adapter | ingest 类命令走 queue→run_ingest；capture 类命令标记人工直写 | 不得隐式绕过 |
| legacy/unified | `RUFLO_PIPELINE_MODE=legacy` | 兼容/禁止发布 | writer guard 拒绝绕过 |

## 6. 测试与验收

必须覆盖：

1. 有效 candidate 完成 `anchored → structurally_verified → bundle → staged → published`；
2. source_path、source_hash、document_id、block_id、quote_hash 任一不匹配即阻断；
3. 短 quote、多 block 命中、空 quote 均阻断或进入人工审核；
4. object/page 映射缺失、重复、未知均阻断；
5. stage/publish 中断后无正式目录、index、vector 新数据；
6. vector 失败只产生 pending，不提升 publication waterline；
7. 相同 bundle 重试不产生重复写入；
8. 两个相同 source 并发时只有一个 bundle 发布；
9. HTTP、service、queue、run_ingest 使用同一 KC 主线；
10. legacy/unified 无法绕过最终 writer guard。

既有真实数据 `novel-wiki` 页数差异单独记录为数据基线问题，不通过修改 KC 逻辑凑数量。

## 完成门槛

只有以下条件全部满足，才进入 Evidence 生命周期的完整下游消费：

- structural review、ProjectionBundle、manifest 状态机和 writer guard 均有实现及测试；
- 所有正式写入均可由 manifest 反查 source、object、page、evidence；
- 失败、重试、崩溃恢复、并发冲突均 fail-closed；
- `anchored / structurally_verified / entailed` 不再混用；
- 定向测试和入口矩阵全部通过；
- 未确认归属的既有文件和 Wiki 产物未被覆盖。
