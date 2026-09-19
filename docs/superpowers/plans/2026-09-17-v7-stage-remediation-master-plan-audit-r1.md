# Plan Audit Round 1 — 全面漏洞审计

> **审查对象**：`docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan.md`
> **审查者**：plan-audit Round 1（独立第三方审计专家视角）
> **审查时间**：2026-09-17
> **审查规则**：抛弃方案正向思路，按 audit-prompts.md §1 执行；分级输出；至少找 8 个风险点。

---

## 0. 审查方法学

- **视角**：假设方案作者默认成立的所有条件都不成立
- **重点**：隐含假设、异常场景、逻辑断层、潜在 bug、信息盲区
- **输出**：①致命缺陷 / ②重大隐患 / ③优化疏漏，每条带"漏洞位置 + 风险后果 + 整改建议"
- **数量**：共发现 17 个问题（远超 8 个最低门槛），覆盖所有 9 个审查维度

---

## 1. 致命缺陷（①）— 方案无法落地

### F1. Stage 4 topic_id 脚本化导致 page_id 全面失效，且无 migration 路径

**位置**：Task 12 `Stage 4 — topic_id 脚本生成` + Acceptance "topic_id 形如 `<source_id>-topic-<16hex>`"

**风险后果**：
- 当前 `_stable_page_id(relative, topic.id)` 用 `topic.id` 派生 page_id（`scripts/extract_pilot.py:289`）
- Task 12 后 `topic.id` 从 LLM 字符串改为 hash 字符串
- **所有现存 Wiki page 的 page_id 立即失效**
- 已写盘 Wiki 与未来 ingest 出的 page **不是同一个 id** → wikilink 全部断链
- reconciliation Stage 1 依赖 page_id 稳定（Task 27 假设 `find_canonical_by_page(page_id)`）
- 如果 page_id 改回老格式，会破坏 reconciliation 索引

**整改建议**：
- Task 12 必须包含 **page_id migration 工具**：
  - 读现有 page 文件 → 解析 frontmatter → 重新计算 topic_id → 重命名文件 + 更新 frontmatter
- 或保留 page_id 用 LLM title hash（与 topic.id 解耦），让 page_id 由脚本独立生成
- 在 Task 12 内增加子任务 12.1：`migration_page_id_v3_to_v4`（独立 commit，可独立验证）

---

### F2. 旧 V7 checkpoint（无 `pipeline_fingerprint` 字段）兼容性缺失

**位置**：Task 22 `Stage 7 — Source checkpoint 接入 pipeline_fingerprint`

**风险后果**：
- Task 22 Acceptance 写："pipeline 不变 + source 不变 → 仍可 skip（向后兼容旧 checkpoint 无 fingerprint）"
- 但实现细节未明确：**旧 checkpoint 写入的 source 是 WRITTEN with `written_page_ids`，新 source checkpoint 写入的也是 WRITTEN with `written_page_ids`，但 page checkpoint 内容不同**（新版加了 revision_hash 与 pipeline_fingerprints）
- 如果 source 被 Task 22 视为"可 skip"，但实际 page 写盘用的是新 schema（旧 page frontmatter 无 `revision_hash`）→ `revision_hash` mismatch → page commit 会**强制 update**（不是 skip），导致 **re-ingest 同一 source 时所有 page 被重写**
- 大量现有 source 会被无意义地重写，**污染 wiki git history**

**整改建议**：
- Task 22 必须明确定义"old page in disk + new pipeline_fingerprint"的处理逻辑：
  - 选项 A：旧 page 全部 re-write（一次性迁移）
  - 选项 B：旧 page 视为 orphan → tombstone，新 page 写入
  - 选项 C：page frontmatter 缺 fingerprint → 视为 stale，仍可 rewrite（但要求 manual `--migrate-pages` 标志）
- 增加显式子任务：`migrate_old_pages_frontmatter.py`（一次性 migration 工具，**不在 hot path**）
- Acceptance 增加："迁移完成后，dry-run 显示零 page-rewrite"

---

### F3. Stage 5 reviewer 引入未定义数量的 LLM 调用，缺乏成本预算

**位置**：Task 17 `Stage 5 — Semantic reviewer（high-risk claims）`

**风险后果**：
- Task 17 每个 high-risk claim 调一次 reviewer（且 reviewer 失败 → 降级 insufficient）
- 没有 budget 控制：
  - 一篇 50KB 文章可能产生 50+ high-risk claims
  - 每篇 source 额外 50 次 LLM 调用
  - Stage 5 整改后整体成本**倍增**
- 没有 retry budget 控制
- 没有 max_review_per_source 上限

**整改建议**：
- Task 17 必须增加 budget：
  ```python
  MAX_REVIEW_PER_SOURCE = 5
  MAX_REVIEW_PER_TOPIC = 3
  ```
- reviewer 失败累计 → topic-level 不进入 WRITTEN（防止 silent degradation）
- 增加 metric：`reviewer_invoked / reviewer_contradicted / reviewer_skipped_due_to_budget`
- 子任务 17.1：`test_reviewer_budget_exhaustion_fail_closed`

---

### F4. Reconciliation decision 不传播 fingerprint 升级信号

**位置**：Task 29 `Reconciliation — Identity resolver` + 阶段门控

**风险后果**：
- 每个 Reconciliation job 都有自己的 `resolver_fingerprint`
- 但 fingerprint 变化时，**已稳定的 canonical_id 不重新评估**
- 与 Stage 1-7 的"pipeline_fingerprint 升级 → 重跑"原则**不一致**
- 结果：resolver 算法升级后，旧的 same/alias 决策不会被重新评估，可能错过 merge 机会或维持错误 merge

**整改建议**：
- Task 30 `Canonical registry` 增加 `resolver_fingerprint` 字段到 `CanonicalConcept`
- 加新决策类型或 signal：`STALE_DECISION`（fingerprint 不匹配）
- Reconciliation job 启动时检查：`if cc.resolver_fingerprint != current: mark STALE`
- 第二批再做 incremental re-evaluation；第一批先建立 STALE 标记机制
- 子任务 30.1：`test_resolver_fingerprint_drift_marks_stale`

---

## 2. 重大隐患（②）— 容易失败

### F5. Stage 2 byte offset 与 char offset 混用风险

**位置**：Task 5 `Stage 2 — UTF-8 byte offset 坐标系统一`

**风险后果**：
- `ArticleBoundary.slice(content)` 用的是 `content[start:end]`（Python string char index）
- Task 5 把 start/end 改为 byte offset
- 但 slice 方法用 char index 切 byte offset → **中文 source 切错位置**
- 例如：中文 source 中"知识"是 6 bytes (UTF-8)，Python len 是 2 chars
- 如果 byte offset = 13882 (指"知"第一个字节)，`content[13882:14290]` 会得到错误字符

**整改建议**：
- Task 5 必须**先重写 `ArticleBoundary.slice` 方法**：
  ```python
  def slice_bytes(self, source_bytes: bytes) -> bytes:
      return source_bytes[self.start_byte:self.end_byte]
  def slice_text(self, source_bytes: bytes) -> str:
      return self.slice_bytes(source_bytes).decode("utf-8", errors="replace")
  ```
- 删掉旧的 `slice(content)` 或重命名为 `slice_chars_by_byte_offset`（明确警告）
- 子任务 5.1：`test_chinese_byte_offset_slice_consistent`（必须绿，否则整个 Stage 5 整改不通过）

---

### F6. Stage 7 manifest 持久化路径与现有 checkpoint 共存可能冲突

**位置**：Task 19 `Stage 7 — CommitManifest` + `.index/commits/` 路径

**风险后果**：
- `.index/commits/<commit_id>.json` 路径是新建的
- 但现有 `.index/v7_checkpoint.json` 仍存在
- 如果用户在 Task 19 与 Task 20 之间中断，**：
  - page checkpoint 已升级（新格式含 revisions / pipeline_fingerprints）但
  - CommitManifest 持久化路径未启用
- **不一致状态**：`page_checkpoint.json` 是新版，`commits/` 目录不存在
- `reconcile_unfinished_commits()` 找不到 manifest → 跳过 reconcile → page file 可能与 checkpoint 不一致

**整改建议**：
- Task 19 与 Task 20 必须**同一 commit 完成**，不可拆分
- 或：Task 19 启动时检测现有 checkpoint 格式 → 强制走 migration 路径（不能冷启动）
- Acceptance 增加："reconcile_unfinished_commits 在 .index/commits/ 不存在时不崩溃，返回 empty list"

---

### F7. Stage 5 claim-level evidence 与 Stage 5 v3 已有 SlotEvidence 结构不兼容

**位置**：Task 14-18 全部 Stage 5 任务

**风险后果**：
- 当前 `SlotEvidence`（`slot_filler.py:89-104`）是 slot 级
- Task 14 改为 claim 级（`Claim` / `EvidenceRef`）
- 但现有 Wiki frontmatter `slot_evidence` 字段是 slot 级 JSON
- 老 page frontmatter 用旧格式，新 page frontmatter 用新格式
- Wiki reader / lint / search 都依赖旧格式 → 大量 reader 报错

**整改建议**：
- Task 14 必须包含**frontmatter schema migration**：
  - 旧 `slot_evidence: {slot_name: SlotEvidence}` 迁移到 `claims: [Claim]`
  - 或保留 `slot_evidence` 兼容层，新写盘用 `claims`，reader 两者都接受
- 增加 `MigrationLayer`（`src/wiki/features/claim_evidence_adapter.py`）
- 子任务 14.1：`test_old_slot_evidence_frontmatter_readable`（向后兼容）

---

### F8. Stage 6R 与 Stage 7 Wiki frontmatter relations 字段冲突

**位置**：Task 23-26 Stage 6R + Task 20 Stage 7 frontmatter

**风险后果**：
- Task 20 Wiki frontmatter 写 `relations: [PageRelation.to_dict()]`
- Task 23 Stage 6R 用 `RelationAssertion`（schema 不同）
- 如果 Task 23 改动 Wiki frontmatter 写入 → Stage 7 写盘被破坏
- 如果 Stage 7 不让 Stage 6R 写 frontmatter → relations 不在 page 文件里 → relation 单独存于 `relations.jsonl`
- **跨 Stage 数据流分裂**

**整改建议**：
- Task 23 显式决策："Stage 6R 不修改 Wiki frontmatter；relations 仅存于 RelationStore.relations.jsonl"
- Task 20 frontmatter 不含 `relations` 字段（去掉 `_last_relations` 注入）
- Wiki reader / NDG gate 等需确认 relations 来源统一（要么 frontmatter、要么 RelationStore）
- 子任务 23.1：`test_relations_not_written_to_wiki_frontmatter`（必须绿）

---

### F9. Stage 4 ClusterStatus.UNCERTAIN 触发条件过严导致大量 false positive

**位置**：Task 9 + Acceptance "`article_preservation_ratio < 0.95` 触发 `ClusterStatus.UNCERTAIN`"

**风险后果**：
- collection 文章误判（Stage 1 错分类）→ article preservation 计算异常 → UNCERTAIN → BLOCKED
- 但**实际没有数据丢失**：文章还在 source 里，只是 Stage 4 没识别出来
- 整个 source 被 BLOCKED → 反复 retry 仍是 UNCERTAIN（Stage 1 错分类是 deterministic 的）
- **永久 stuck**

**整改建议**：
- UNCERTAIN 触发阈值改为 `< 0.85`（不是 0.95），给 Stage 1 错分类容错空间
- 增加 metric：`article_preservation_diagnostic`（区分"真正丢失" vs "stage 4 没识别"）
- 子任务 9.1：`test_article_loss_strict_threshold_with_diagnostic`

---

### F10. Reconciliation candidate retrieval 6 策略中 vector_neighbor 缺失会引入回归

**位置**：Task 28 `Reconciliation — Candidate retrieval` + 后续批次"vector_neighbor 留第二批"

**风险后果**：
- 当前 `extract_pilot` 等路径**不依赖** vector_index（依赖 inverted index / 标题 match）
- Task 28 移除 vector_neighbor 策略后，Reconciliation 完全不调用 vector_index
- 但**Reconciliation 场景**（新 page 找同概念）最适合用 vector（语义相似但 title 不同）
- 不上 vector_neighbor → 大量 same-concept 找不到 → canonical concept 爆炸（一个 concept 一个 page）
- **根本性失败**（Phase 1 主要价值丧失）

**整改建议**：
- vector_neighbor 必须进第一批 Task 28
- 实施成本可控：复用现有 vector_index（已存在的 1536-dim LanceDB）
- Acceptance 增加："vector_neighbor retrieval 在 10000 canonical concepts 时 < 100ms"
- 子任务 28.1：`test_vector_neighbor_retrieval_integration`

---

### F11. Stage 7 queue projection pending log 与现有 reviews_queue.jsonl 双写

**位置**：Task 21 `Stage 7 — Durable failure fact` + 现有 `failures.py:_DEFAULT_QUEUE_PATH = .index/reviews_queue.json`

**风险后果**：
- `.index/durable_failure.jsonl` 是新文件
- `.index/reviews_queue.json` 是现有文件
- 两处都记录 failure → operator 看到重复
- 如果 queue_projection_pending.jsonl 与 reviews_queue.jsonl 不一致 → repair job 行为不明确

**整改建议**：
- Task 21 必须明确：durable_failure.jsonl **只记录 stage 7 的 page-level outcome**（committed/blocked/failed）
- reviews_queue.json **只记录需要 review 的人工任务**（语义冲突 / uncertain）
- 两者不重叠
- 子任务 21.1：`test_durable_failure_does_not_pollute_reviews_queue`

---

### F12. Stage 1 traits 字段不被 Stage 2/3/4 消费，造成"接不上的接口"

**位置**：Task 1 `Stage 1 — Classification.traits` + §2.2 共享变量表

**风险后果**：
- Stage 1 输出 `traits` 字段，但 §2.2 共享变量表没有 traits 的消费者
- Stage 2 不消费 traits（Stage 2 用 `SegmentationResult`，自己的 `structural_signals`）
- Stage 3 不消费 traits
- Stage 4 hint 接 `classification_hint`，但**未明确 traits 是否进入 classification_hint**
- traits 是死字段（与 Stage 1 之前的 `incomplete` 类似` 模式）

**整改建议**：
- §2.2 共享变量表增加 `Classification.traits` 字段，Stage 4 `classification_hint` 显式接收
- 或 Task 1 删除 `traits` 字段，只保留 `failed/uncertain/fingerprint/evidence_summary`
- 子任务 1.1：`test_traits_consumed_by_stage4_classification_hint`（必须绿）

---

## 3. 优化疏漏（③）

### F13. 任务编号混乱与依赖图未对齐

**位置**：§2 依赖图与 §4 Tasks

**风险后果**：
- 依赖图显示 Stage 6R 在 Stage 7 之后，但 Tasks 编号 Task 19-22 是 Stage 7，Task 23-26 是 Stage 6R
- 实际执行顺序应该是：Stage 1-5（Task 1-18）→ Stage 7（Task 19-22）→ Stage 6R（Task 23-26）→ Reconciliation（Task 27-31）
- 但 Task 编号是混乱的，可能误导 subagent-driven-development 的任务派发

**整改建议**：
- Task 编号按依赖顺序重排：Task 1-6 Stage 1, Task 7-12 Stage 2, Task 13-15 Stage 3, Task 16-20 Stage 4, Task 21-25 Stage 5, Task 26-29 Stage 7, Task 30-33 Stage 6R, Task 34-38 Reconciliation, Task 39 E2E, Task 40 文档

---

### F14. 关键 invariant 缺乏 enforcement 测试

**位置**：多处 Acceptance "硬指标 0"

**风险后果**：
- `test_hard_invariant_technical_failure_never_mapped_to_incomplete`（Task 6）只是单测
- 没有 E2E enforcement（已在 Task 32，但 Task 32 是最后）
- 没有 CI gate（如果 CI 不跑 Task 32，invariant 可能被破坏）

**整改建议**：
- Acceptance 增加："CI 必须运行 Task 32 测试，否则不接受 commit"
- 写一个 `tests/test_invariants/test_v7_critical_invariants.py` 作为**快速 sanity check**（< 1s），纳入 pre-commit hook
- Acceptance：`pre-commit hook 含 invariants test`

---

### F15. 现有 `SlugAliasRegistry` 与 Reconciliation AliasRecord 双系统可能冲突

**位置**：Task 30 `Canonical registry.add_alias` + 现有 `src/wiki/features/slug_aliases.py`

**风险后果**：
- `SlugAliasRegistry` 已有 `aliases: dict[str, str]`
- `CanonicalRegistry.aliases` 新增 `AliasRecord`
- 同一 alias 在两处可能记录不一致
- operator 用 `--apply` 注册 alias 到 `SlugAliasRegistry`，但 canonical registry 不知道

**整改建议**：
- 显式选其一：
  - 选项 A：Reconciliation AliasRecord 直接调用 SlugAliasRegistry（adapter 模式）
  - 选项 B：删除 SlugAliasRegistry，全部走 Reconciliation
- 在 Task 30 增加显式决策记录
- 子任务 30.2：`test_alias_single_source_of_truth`

---

### F16. Stage 2 invariant "non-overlapping" 与 Stage 5 evidence span 重叠规则不一致

**位置**：Task 3 Stage 2 invariant + Task 14 Claim.evidence_refs

**风险后果**：
- Stage 2 invariant I4：canonical items 之间**不重叠**（intersection == 0）
- Stage 5 evidence_refs：同一 claim 可有多个 evidence spans（**这些 spans 之间允许重叠**）
- 同一 evidence span 可被多个 claim 引用
- 这是**两个语义层级**（segmentation vs claim evidence），没问题
- 但**文档没有明确这一点**，未来 reader 可能误以为 invariant I4 禁止任意 byte span 重叠

**整改建议**：
- Task 3 invariant 文档明确："I4 applies to segmentation-level canonical items, NOT to claim-level evidence spans"
- Task 14 Claim.evidence_refs 文档明确："evidence spans may overlap within or across claims"

---

### F17. plan 中 E2E 测试 Task 32 期望过高，可能不可达

**位置**：Task 32 `test_e2e_*` 多条

**风险后果**：
- Task 32 要求 8 条 E2E 测试全绿
- 但 Task 1-31 任一 task 失败 → E2E 也失败
- Task 32 是 Task 31 完成后才能写，但 Task 1-31 完成后才能跑
- **执行依赖混乱**——subagent-driven-development 派发 Task 32 时，可能无法跑通前置 tasks

**整改建议**：
- Task 32 拆为：
  - Task 32a：`test_e2e_happy_path`（仅依赖 Task 1-6，可先写）
  - Task 32b：`test_e2e_crash_recovery`（依赖 Task 19-22）
  - Task 32c：`test_e2e_reconciliation`（依赖 Task 27-31）
- 每个子任务独立 commit + 独立跑

---

## 4. 信息盲区

| 盲区 | 影响 | 建议补充 |
|---|---|---|
| Stage 4 clusterer_fingerprint 计算口径 | Task 11 未明确包含哪些 hash（prompt hash / ontology hash / reviewer hash）| 补 specification |
| Stage 6R `RelationStore.relations_path` 与现有 `relations` 字段冲突 | wiki frontmatter relations 与 RelationStore 二选一 | Task 23 补决策 |
| Reconciliation 与现有 `SlugAliasRegistry` 整合策略 | Task 30 含糊 | 显式选 A 或 B |
| Topic.id 改名后旧 Wiki page 怎么处理 | F1 致命缺陷 | 必须 migration tool |
| Pipeline fingerprint 各 stage hash 算法 | 跨 stage 一致性 | §3.3 加统一 hash 算法说明 |
| 旧 `fill_slots` legacy adapter 保留多久 | Task 18 含糊 | 显式 deprecation timeline |

---

## 5. 问题分级汇总

| 等级 | 数量 | ID |
|---|---|---|
| ①致命缺陷 | 4 | F1, F2, F3, F4 |
| ②重大隐患 | 8 | F5, F6, F7, F8, F9, F10, F11, F12 |
| ③优化疏漏 | 5 | F13, F14, F15, F16, F17 |
| 信息盲区 | 6 | - |

**总计 17 个问题**（远超 8 个最低门槛）。

---

## 6. 是否通过 Round 1？

**❌ 不通过**。

4 个致命缺陷 + 8 个重大隐患必须整改后重新审计。优化疏漏 5 个建议同步整改。

按 plan-audit §3：**整改后必须再次执行 Round 1 审计，确认所有漏洞已修复，方可进入 Round 2。**

---

## 7. 整改要求汇总（交付用户确认）

### 必须立即修复（（（（（（（（（（（（（（（（（（4 个 ①）
1. **F1** Task 12 增加 migration tool
2. **F2** Task 22 显式处理旧 checkpoint + 旧 page frontmatter
3. **F3** Task 17 增加 reviewer budget + fail-closed
4. **F4** Task 30 CanonicalConcept 增加 resolver_fingerprint + STALE 信号

### 强烈建议修复（8 个 ②）
5. **F5** Task 5 重写 slice 方法 + 测试
6. **F6** Task 19+20 同一 commit + 兼容路径
7. **F7** Task 14 增加 frontmatter migration layer
8. **F8** Task 23 显式 relations 不入 frontmatter 决策
9. **F9** Task 9 阈值放宽 + 增加 diagnostic
10. **F10** Task 28 vector_neighbor 进第一批
11. **F11** Task 21 明确 durable_failure 与 reviews_queue 分工
12. **F12** Task 1 traits 字段明确消费者或删除

### 建议优化（5 个 ③）
13. **F13** Task 编号按依赖顺序重排
14. **F14** CI gate + pre-commit hook
15. **F15** Reconciliation vs SlugAliasRegistry 显式选 A/B
16. **F16** 文档明确 invariant I4 适用范围
17. **F17** Task 32 拆分为 32a/32b/32c

---

## 8. 整改后必须再次执行 Round 1

按 plan-audit §3 第 3 条：**整改后再次执行第一轮审计，确认所有漏洞已修复**。

未通过 Round 1 复审前，**严禁进入 Round 2**。

---

**Round 1 审查完成。等待用户决策：整改 vs 中断。**