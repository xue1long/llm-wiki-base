# Plan Audit Round 2 — 压力测试推演

> **审查对象**：master plan（Round 1 复审通过版本）
> **审查者**：plan-audit Round 2（压力测试推演）
> **审查时间**：2026-09-17
> **审查规则**：按 audit-prompts.md §2 —— 模拟多种失败路径，推演连锁反应，验证兜底覆盖，寻找边界临界点

---

## 0. 审查方法

针对整改后的方案开展极限压力推演：

1. **模拟失败路径**：人员缺位、资源不足、接口报错、超时、突发变更
2. **推演连锁反应**：一处出错是否引发雪崩
3. **验证兜底机制**：现有预案能否覆盖推演故障
4. **寻找边界临界点**：方案"可行"→"失效"的临界条件
5. **输出**：《压力测试问题清单》+ 加固方案

---

## 1. 失败路径推演

### FP1: Stage 1 LLM Provider 持续 timeout（24 小时）

**触发场景**：
- Open provider  关键 service 全面故障
- Stage 1 classifier 每次调用都 timeout
- 所有 source ingest 卡在 Stage 1

**连锁反应推演**：
1. Stage 1 重试 3 次 → 全部失败 → `failed=True`
2. `extract_pilot.py:Task 2`（失败入队分支）记录到 reviews queue
3. source 在 queue 中堆积
4. 24 小时后 queue 满 → 写入失败 → `reviews_queue.json` IO error
5. Stage 1 failure 记录丢失 → 后续无法追溯

**现有兜底**：
- ✅ Stage 1 失败入队（Task 2）
- ✅ 失败走 `ExtractionStatus.FAILED` → 不会假装 WRITTEN

**临界点**：
- reviews queue IO error 时 Stage 1 failure 不可追溯
- 但 source checkpoint 也不会被错误标记为 WRITTEN（因为没走到 Stage 7）
- **这是 fail-closed**，不是数据坏

**加固建议**：
- Task 2 增加：`reviews_queue.json` IO 失败 → 写 `.index/durable_failure.jsonl`（与 Stage 7 一致）
- 第二批：加 batch-level health check（`python -m src.cli health --project <id>`）

---

### FP2: Stage 3 LLM 在 evidence pack 边界给出反向判断

**触发场景**：
- source 内容： "方法 A 在小数据集上效果较差。"
- Stage 3 evidence pack 只看 HEAD（"下面我们介绍三种方法..."）和 TAIL（"...未完待续"）
- LLM 看 HEAD/TAIL + Stage 2 signals，输出：
  ```json
  {"assessment": "appears_truncated", "confidence": 0.9}
  ```
- 实际原文完整，只是 evidence pack 截断导致 LLM 看不到中部

**连锁反应推演**：
1. Stage 3 → `CompletenessStatus.INCOMPLETE`
2. → `ExtractionStatus.INCOMPLETE`
3. → checkpoint 标记 INCOMPLETE（带 fingerprint）
4. pipeline_fingerprint 不变 → 下次 ingest 直接 skip
5. **永久丢失一个真正完整的 source**

**现有兜底**：
- ✅ evidence pack 含 Stage 2 signals（Task 7）
- ✅ checkpoint 双键（Task 8）：fingerprint 升级后可重判

**临界点**：
- 当前 fingerprint 不变 → 永久 skip
- 只有 fingerprint 升级（Prompt 改动）才能触发重判

**加固建议**：
- Task 7 evidence pack 加中部采样窗口（不只 HEAD/TAIL）：
  ```python
  EVIDENCE_PACK_HEAD_TAIL_BYTES = 2000
  EVIDENCE_PACK_MIDDLE_SAMPLE_BYTES = 500
  EVIDENCE_PACK_MIDDLE_SAMPLE_POSITIONS = (0.25, 0.5, 0.75)  # 三个中段采样点
  ```
- 已有 Stage 1 整改的 `evidence_summary` 也记录中部覆盖度
- 第二批考虑加 `time_based_re_evaluation`：超过 30 天的 INCOMPLETE source 自动 re-evaluate

---

### FP3: Stage 4 UNCERTAIN 永久 stuck

**触发场景**：
- source 是 50 篇 collection，每篇 1000 字
- Stage 2 正确切出 50 个 article item
- Stage 4 cluster 误判：`article_preservation_ratio = 0.86`（介于 0.85-0.95 之间）
- 整改前：触发 UNCERTAIN → BLOCKED → permanent stuck
- 整改后：`article_preservation_diagnostic = "stage4_missed"` → 不再 stuck（阈值 < 0.85）

**连锁反应推演（整改后）**：
1. `article_preservation_ratio = 0.86` → 不触发 UNCERTAIN
2. 继续走正常流程
3. 但 7 篇文章仍未被 cluster 接入 → 进 `__other__` → unresolved
4. metric 含 `unresolved_item_ratio = 14%`

**现有兜底**：
- ✅ F9 整改后阈值 < 0.85
- ✅ Stage 4 `__other__` 改 unresolved signal

**临界点**：
- 14% unresolved 不阻断 → 但有 7 篇文章确实没被 cluster
- 后续 Stage 5 不为这些 page 生成 page → `__other__` 进 BLOCKED → reviews queue

**加固建议**：
- Task 9 `ClusterMetrics` 增加 `unresolved_article_ratio`（专门跟踪 article item 的 unresolved 比例）
- 验收增加：`unresolved_article_ratio > 0.1` 触发 DEGRADED（不是 UNCERTAIN）
- 第二批：cluster retry with `--relaxed-thresholds`

---

### FP4: Stage 5 reviewer LLM Provider 全面故障

**触发场景**：
- reviewer LLM 全部 timeout
- Stage 5 reviewer 重试 3 次失败
- 每个 high-risk claim 都无法 review

**连锁反应推演**：
1. reviewer failure → high-risk claims 全部降级 INSUFFICIENT
2. topic 含 high-risk claims 的 slot 都变 INSUFFICIENT
3. `FillStatus.INSUFFICIENT` → `map_fill_to_extraction` → `ExtractionStatus.BLOCKED`
4. 大量 topic BLOCKED → source 整体 BLOCKED（**如果 topic_completion_ratio < 0.4**）
5. 整个 source 永久 BLOCKED 直到 reviewer LLM 恢复

**现有兜底**：
- ✅ reviewer failure → fail-closed（不静默退化）
- ✅ Task 17 reviewer 失败处理

**临界点**：
- reviewer LLM 故障期间**所有** source 全部 BLOCKED
- 即使非 high-risk claims 的 topic 也 BLOCKED（因为 topic completion ratio 受影响）

**加固建议**：
- Task 17 增加 `reviewer_invoke_budget`：
  ```python
  MAX_REVIEWER_INVOKES_PER_SOURCE = 10  # 限制总 reviewer 调用
  MAX_REVIEWER_INVOKES_PER_TOPIC = 3    # 每个 topic 最多审 3 次
  ```
  超 budget → 该 topic 跳过 reviewer（**仅 non-high-risk 直接 accept**，high-risk 仍 fail-closed）
- 第二批：分级 reviewer 模型（high-risk 用大模型，low-risk 用小模型）

---

### FP5: Stage 6R relations 与 page frontmatter 分离后，Wiki reader 找不到 relations

**触发场景**：
- Task 23 整改后 relations 不入 frontmatter
- Wiki reader（web UI）渲染 page 时显示 "Related: ..." 需要 relations
- relations 仅在 `RelationStore.relations.jsonl`
- web UI 不读 `RelationStore` → page 显示无 relations

**连锁反应推演**：
1. wiki frontmatter 无 relations 字段
2. web UI 渲染 page → 显示 "无 relations"
3. Stage 6R enrichment 完成后 relations 在 `RelationStore`
4. 但 web UI / search index 不读 RelationStore
5. **用户看不到 relations**

**现有兜底**：
- ⚠️ Task 23 仅删 frontmatter 注入；未明确 reader 改造

**临界点**：
- Wiki reader / web UI / search index / NDG gate 都依赖 frontmatter relations
- 任一依赖未改 → 关系显示丢失

**加固建议**：
- Task 23 增加显式子任务 23.2：`update_relations_readers`：
  - Wiki reader / web UI / search index / NDG gate 都改为读 `RelationStore`
  - 或保留 frontmatter 注入，但仅在 commit 时注入（与 `page_sink` 协调）
- 第二批：明确"Wiki reader 的 relations 来源是 frontmatter 还是 RelationStore"的统一规范

---

### FP6: Stage 7 crash 在 publish 阶段后、checkpoint 写入前

**触发场景**：
- 10 个 page 要写盘
- page 1-5 已成功 publish（文件存在）
- 进程被 kill -9 在 checkpoint 写入之前
- manifest 处于 `PUBLISHING` phase

**连锁反应推演（整改后）**：
1. 重启 → `reconcile_unfinished_commits()` 扫描 `.index/commits/`
2. 发现 manifest 在 `PUBLISHING` phase
3. 遍历 `page_records`：每个 committed record 校验 file 存在 + hash 匹配
4. page 1-5 校验通过 → 重新 update index + checkpoint
5. manifest 标 `RECONCILED`
6. page 6-10 仍未写 → 下次 ingest 重试

**现有兜底**：
- ✅ Task 19 CommitManifest
- ✅ Task 19 reconcile_unfinished_commits

**临界点**：
- reconcile 假设 file system 一致（disk 不丢）
- 如果 disk 也 crash → page file 丢失但 checkpoint 仍记录 → checkpoint vs file 不一致

**加固建议**：
- Task 19 reconcile 增加 file vs checkpoint 交叉验证（已部分实现）
- 测试：`test_e2e_crash_during_publish_recovers_via_manifest`（Task 32 已规划）

---

### FP7: Reconciliation vector_index 不可用

**触发场景**：
- LanceDB index 损坏 / vector dim 不一致 / vector store 初始化失败
- Task 28 vector_neighbor retrieval 失败
- Reconciliation 5 种 retrieval 策略中 1 种失败

**连锁反应推演**：
1. vector_neighbor 失败 → try/except 包住
2. 其他 5 种 retrieval 仍工作 → candidate retrieval 仍返回 top-N
3. Reconciliation 继续运行（仅 loss 一种 retrieval 策略）
4. 但**新发现**的 same-concept 减少（vector semantic 相似但 title 不同）

**现有兜底**：
- ✅ Task 28 vector_neighbor 在 try/except 内
- ✅ 5 种 fallback retrieval

**临界点**：
- canonical concept 数量低于应有数量
- "新" canonical 增量创建过多（false positive distinct 决策）

**加固建议**：
- Task 28 增加：`vector_index_unavailable` → 记 warning metric，继续其他 retrieval
- 测试：`test_vector_index_unavailable_falls_back_to_other_strategies`
- 第二批：定期 `vector_index_health_check` CLI

---

### FP8: Reconciliation fingerprint 升级 → 旧 canonical 标 STALE → 触发大批 re-evaluation

**触发场景**：
- resolver 算法 v1 → v2
- Task 30 `reconcile_stale_concepts(v2_fingerprint)` 标所有 active canonical 为 STALE
- 10000 个 canonical 全部 STALE
- 增量 re-evaluation 需要 LLM 调用 10000 次

**连锁反应推演**：
1. 标 STALE 后不立即 re-evaluate（Task 30 仅标，不立即跑）
2. 但用户可能想立即 re-evaluate → 跑 reconcile 任务
3. 10000 个 canonical 每个候选检索 + LLM decision = 大量 LLM 调用
4. 成本爆炸 / rate limit

**现有兜底**：
- ✅ Task 30 STALE 信号已实现（按 plan）
- ✅ 不立即 re-evaluate

**临界点**：
- 何时 re-evaluate STALE canonical
- re-evaluation 是手动还是自动

**加固建议**：
- Task 30 明确：`reconcile_job --re-evaluate-stale` 显式命令（默认不跑）
- 第四批：`incremental_re_evaluation` 基于 change-driven（仅 re-evaluate 周边 N 个）
- 测试：`test_stale_can_be_re_evaluated_incremental`（Task 30 已规划）

---

### FP9: 同一 source 并发 ingest

**触发场景**：
- 同一 source.md 两个 user 同时 ingest
- 两个 `extract_pilot` 进程同时跑
- 写 `.index/v7_checkpoint.json` 冲突

**连锁反应推演**：
1. 进程 A 读 checkpoint → "page X 不存在"
2. 进程 B 读 checkpoint → "page X 不存在"
3. 进程 A 写 page X + checkpoint
4. 进程 B 也写 page X + checkpoint（覆盖 A 的 checkpoint）
5. 最后 checkpoint 是 B 的状态，但 A 的 page write 已成功
6. 可能：page A 文件 + checkpoint B 不一致

**现有兜底**：
- ⚠️ Task 19 manifest 是单文件 tmp+rename，但并发写 `.index/v7_checkpoint.json` 仍是 race
- ⚠️ `.index/durable_failure.jsonl` append 也可能 race

**临界点**：
- 并发 ingest 没有 lock 机制
- 当前 `_atomic_write` 只保证单进程原子

**加固建议**：
- Task 19 增加：**per-source lock file**（`.index/locks/<source_md5>.lock`）
- lock 检测 → 失败 → return `ExtractionStatus.SKIPPED` + reason "concurrent_run"
- 测试：`test_concurrent_ingest_serialized_via_lock`

---

### FP10: Stage 2 byte offset 与 Stage 5 evidence span 坐标系不一致

**触发场景**：
- Task 5 整改：byte offset against source bytes
- 但 Stage 5 evidence span 也是 byte offset against **item.text**（decoded string 的 byte offset）
- 两个 byte offset **不是同一个坐标系**
- 假设 item.text 从 source bytes 切出来，但 item.text 的 byte offset 与 source byte offset 一致

**连锁反应推演（如果实现错误）**：
1. Stage 2 给定 `CanonicalItem(start_byte=1000, end_byte=5000, text="...")`
2. Stage 5 构造 `CanonicalSpan(start_byte=2000, end_byte=3000)` against item.text
3. 但 Stage 5 的 byte offset 实际是 item.text 内的相对偏移
4. Stage 5 应该用 `item.start_byte + 2000` 才映射回 source
5. 如果实现错误：Stage 5 直接用 `start_byte=2000` 对 source bytes 切片 → 切错位置

**现有兜底**：
- ⚠️ Task 5 仅重写 `slice` 方法，未明确 item.text byte offset 语义
- ⚠️ Task 14 canonical_spans 未明确 byte offset 坐标系

**临界点**：
- 两层 byte offset 必须严格区分（item-relative vs source-absolute）

**加固建议**：
- Task 5 明确文档：`CanonicalItem.start_byte/end_byte` 是 source bytes offset；`item.text` 是 decoded string
- Task 14 CanonicalSpan 增加 `byte_offset_kind` 字段（"item_relative" vs "source_absolute"）
- 测试：`test_canonical_span_byte_offset_against_item_relative_consistent`

---

## 2. 边界临界点汇总

| 临界点 | 当前方案行为 | 是否可接受 |
|---|---|---|
| LLM 全面故障 24h+ | 所有 source 卡在 Stage 1 | ✅ fail-closed |
| Stage 3 evidence pack 边界判断错误 | INCOMPLETE → 永久 skip | ⚠️ 需中部采样 |
| Stage 4 14% unresolved article | 进 unresolved metric，源不 BLOCKED | ✅ 但需 reviewer 关注 |
| Stage 5 reviewer 全面故障 | 所有 high-risk topic BLOCKED | ⚠️ 需 budget 控制 |
| Stage 6R relations 不入 frontmatter | Wiki reader 找不到 relations | ⚠️ 需 reader 改造 |
| Stage 7 disk crash | reconcile 失败 | ⚠️ 需 cross-validate |
| Reconciliation vector_index 不可用 | 5 种 retrieval 仍工作 | ✅ graceful degradation |
| Reconciliation fingerprint 升级 | STALE 信号 + 手动 re-evaluate | ✅ 但需 incremental |
| 并发 ingest | race condition | ⚠️ 需 per-source lock |
| byte offset 坐标系混淆 | 切错位置 | ⚠️ 需严格文档 + 测试 |

---

## 3. 加固方案（按优先级）

### P0 必须加（Round 2 必加）

| 加固项 | 来源 FP | 加到 Task |
|---|---|---|
| durable_failure 用于 Stage 1 reviews queue IO 失败 | FP1 | Task 2（Stage 1 失败入队） |
| evidence pack 中部采样 + 时间触发 re-evaluation | FP2 | Task 7（Stage 3 evidence pack） |
| `unresolved_article_ratio` metric | FP3 | Task 9（Stage 4 metrics） |
| reviewer invoke budget | FP4 | Task 17（Stage 5 reviewer） |
| update_relations_readers 子任务 | FP5 | Task 23（Stage 6R） |
| per-source lock file | FP9 | Task 19（Stage 7 manifest） |
| byte offset 坐标系文档 + 测试 | FP10 | Task 5 + Task 14 |

### P1 建议加（后续批次）

| 加固项 | 来源 FP | 留后续 |
|---|---|---|
| Reconciliation incremental re-evaluation | FP8 | 第四批 |
| vector_index health check | FP7 | 第三批 |
| batch-level health check | FP1 | 第二批 |
| 分级 reviewer 模型 | FP4 | 第二批 |

---

## 4. 加固后是否需要复审？

按 plan-audit §3：**加固后再执行 Round 2 复审**确认覆盖。

但加固项 P0 都是**显式子任务**追加，不改变架构——只需确认子任务已写入 plan，不必复审全套。

---

## 5. Round 2 是否通过？

**✅ 条件性通过**：

- 现有兜底覆盖：6/10 个失败路径（FP1/3/7/8 现有兜底足够）
- 需要加固：4/10 个失败路径（FP2/4/5/9/10）需追加 P0 子任务
- 架构层无新缺陷，仅细节需加固

**Round 2 通过条件**：
1. 7 个 P0 加固项已 inline 到对应 Task
2. 每个加固项都有对应测试

---

## 6. 加固要求汇总（交付用户确认）

### P0 加固（7 项，inline 到 plan）

1. **Task 2**: Stage 1 reviews queue IO 失败 → durable_failure
2. **Task 7**: evidence pack 中部采样 + 时间触发 re-evaluation
3. **Task 9**: `unresolved_article_ratio` metric
4. **Task 17**: reviewer invoke budget (`MAX_REVIEWER_INVOKES_PER_SOURCE=10`)
5. **Task 23**: `update_relations_readers` 子任务（Wiki reader / web UI / search index 改造）
6. **Task 19**: per-source lock file（`.index/locks/<source_md5>.lock`）
7. **Task 5 + Task 14**: byte offset 坐标系文档 + 测试

### P1 留后续批次

8. **Task 30**（后续）：Reconciliation incremental re-evaluation
9. **Task 28**（后续）：vector_index health check
10. **Task 32**（后续）：batch-level health check
11. **Task 17**（后续）：分级 reviewer 模型

---

## 7. 加固后 Round 2 复审要求

按 plan-audit §3 第 3 条：加固后再次执行 Round 2 复审。

未通过 Round 2 复审前，**严禁进入人工 review**。

---

**Round 2 压力测试完成。等待用户确认是否启动 P0 加固。**