# KC 主线三层实施方案（精简整改版）

## 总原则

按风险和依赖递进实施，不跨层级建设：

```text
L1 来源结构证据门
        ↓
L2 现有 Wiki 投影与 commit 闭包
        ↓
L3 全局发布一致性与完整 Evidence 生命周期
```

L1、L2 必须保持现有 Wiki、index、vector 和 queue 机制不变；L3 只有在前两层稳定后才启动。

本方案只把 `structurally_verified` 定义为 source-level structural evidence，不把它解释为 claim truth。`entailed` 留在 L3。

## L1：来源结构证据门（立即实施）

### 目标

确保任何进入 Generator 的 candidate 都具备可回溯、可复核的来源结构证据。

### 流程

```text
CanonicalDocument
→ candidate adapter
→ anchored
→ structurally_verified / needs_human_review
→ Generator
```

### 规则

- 本地 `source_path` 统一为项目根目录下的相对 POSIX 路径；项目外路径拒绝；
- URL 暂不纳入本层，沿用现有 URL 入口；
- quote 必须非空，且唯一命中 canonical block；
- quote 少于 `MIN_SHORT_QUOTE_CHARS = 8` 个 Unicode 字符时，必须唯一命中，否则 `needs_human_review`；该常量只定义一次；
- quote hash 由 canonical quote 重新计算；
- `evidence_refs` 必须引用有效 evidence；
- L1 复用现有 `document_id` 作为内容身份，不另建独立 source hash；只有 L3 需要跨存储校验时再增加原始字节 hash；
- 失败不调用 Generator，不进入 commit；
- 新写入不再使用完整语义 `verified`，只使用 `anchored` 或 `structurally_verified`；
- 旧数据中的 `verified` 只在读取时兼容映射为 `structurally_verified`，不得回写为 `verified`；
- `verify_claim()` 在 L1 内统一接受 `structurally_verified`，所有旧值转换集中在读取适配层。

### 代码范围

- `src/kc/api.py`
- `src/kc/compiler/normalize.py`
- `src/kc/compiler/evidence.py`
- `src/kc/compiler/verify.py`
- `src/kc/contracts/evidence.py`
- `src/pipeline/ingest.py`

不新增 manifest、staging、waterline 或新的 writer。

### L1 验收

- 有效 candidate 可进入 Generator；
- source_path、quote、block、hash、refs 任一错误都被阻断；
- Generator/commit 在结构证据失败时不执行；
- `run_ingest`、service/queue 使用同一 gate；
- 现有 KC、Collector、pipeline 回归通过。

## L2：现有 Wiki 投影与 commit 闭包

### 前置条件

L1 全部通过，且没有未分类的结构证据失败。

### 目标

让 KC 校验结果与现有 Generator 输出和 `commit_ingest()` 建立可追踪关系，但不建立第二套页面系统。

### 最小合同

- 一次 ingest 产生一个 KC review result；
- Generator 输出的每个正式 WikiPage 必须能回到本次 source/document；
- source/document/evidence refs 持久化位置固定：页面的 `evidence_refs` 只保存 evidence id，`_ko_extra.kc_document_id` 保存 document id，`_ko_extra.kc_projection_version` 保存 projection 版本；
- 本层只保证页面级来源追踪，不推断 claim-to-page 映射；
- 不要求 LLM 生成 `knowledge_object_ids`，也不按 claim index 猜测页面归属；
- 页面级 provenance 缺失或不一致时拒绝提交，不猜测、不自动补页；
- 继续复用现有 `AtomicContext`、`expected_content_hash`、`commit_ingest()` 和 vector pending。

### 代码范围

- `src/kc/compiler/compile.py`
- `src/kc/adapters/wiki_projection.py`
- `src/pipeline/generator.py`
- `src/pipeline/ingest.py`
- 必要时 `src/wiki/core/types.py` 的既有 evidence 字段

### L2 验收

- KC projection 与最终 WikiPage 的 source/document/evidence 可反查；
- 本层不宣称 claim 与页面之间已建立完整语义映射；
- review 失败、页面级 provenance 缺失、内容 hash 冲突时不写 Wiki/index；
- 正常提交仍只经过一个 `commit_ingest()`；
- 重试不产生重复页面或重复 index；
- 不新增独立 claim page、staging writer 或 publication waterline。

## L3：全局发布一致性与完整 Evidence 生命周期（延期）

L3 的首个可执行切片已单独收敛为：[L3 Vector Publication Intent Implementation Plan](2026-08-28-kc-l3-vector-publication-intent.md)。该子方案只处理 Wiki 提交与 vector pending ledger 之间的真实崩溃窗口；其余 claim truth、`entailed`、manifest、waterline 和完整 Evidence 生命周期继续延期，不能由本切片顺带实现。

### 启动条件

只有 L1、L2 连续回归通过，并且确认现有 vector pending 机制无法满足实际一致性要求时才启动。

### 目标

处理跨 Wiki、index、vector、历史 Evidence 和并发恢复的一致性问题。

### 可选能力

- Evidence 完整状态机：`anchored → structurally_verified → entailed / unsupported / needs_human_review`；
- claim-to-page 的显式映射和 KnowledgeObject bundle；
- 历史 `verified` 读取兼容和审计迁移；
- Projection manifest；
- staging/publish 状态机；
- publication waterline；
- vector 可见性控制；
- 崩溃恢复和并发发布冲突处理；
- legacy/unified 全入口最终 writer guard。

### L3 原则

- 每项能力先有真实失败场景，再增加实现；
- 不为假设的并发、恢复或跨存储问题预先建框架；
- 不改变 L1/L2 的 source-level structural evidence 语义；
- L3 独立形成新方案和迁移报告，不回填为 L1/L2 的隐含要求。

## 入口策略

| 入口 | 真实 caller | L1 必经 gate | L2 最终 writer/test |
|---|---|---|---|
| `run_ingest` | `src/pipeline/ingest.py::run_ingest` | `generate_ingest` 内 structural review | `commit_ingest`; `tests/test_pipeline/test_ingest_kc_mainline.py` |
| HTTP | `src/server/routes/ingest.py` → `src/services/ingest.py::enqueue_source` | queue worker 最终调用 `run_ingest` | `commit_ingest`; `tests/test_server/test_service_ingest.py` + route tests |
| queue | `src/queue/` worker → `src/services/ingest.py::run_ingest_pipeline` | 复用 `run_ingest` | `commit_ingest`; queue integration tests |
| CLI/MCP ingest | 各 adapter 的 ingest caller | 必须进入 queue/pipeline | 复用 `commit_ingest`; 对应 adapter tests |
| capture | `src/services/capture.py` / `src/cli_ext/capture_cmd.py` | 人工直写，单独标记 | 不伪装为 KC ingest，不纳入 L1/L2 |
| legacy/unified | `src/pipeline/ingest.py` 的 legacy 分支 | 不得冒充 candidate | 兼容路径测试；L3 再统一 writer guard |

## 统一停止条件

任一层遇到以下情况立即停止该层，不进入下一层：

- source_path 归属无法确认；
- evidence 状态含义冲突；
- projection 与 WikiPage 无法确定映射；
- 现有 AtomicContext 无法保证该层的写入边界；
- 测试失败无法区分代码问题和环境问题；
- 需要覆盖、删除或批量迁移既有用户数据。

## 最终验收顺序

```text
L1 定向单测
→ L1 pipeline 回归
→ L2 projection/commit 测试
→ HTTP/service/queue 入口测试
→ 真实数据只读核对
→ 评估是否有必要启动 L3
```

`novel-wiki` 页数差异属于独立数据基线问题，不作为 L1/L2 的代码通过条件，也不通过修改逻辑凑数量。
