# Plan Audit Round 1 — 重新评估（用户决策后）

> **背景**：用户在收到 Round 1 审计报告后，明确要求：**"不管旧的 wiki，不考虑成本问题，只考虑未来的成果能否达成"** 重新评估。
> **重新评估时间**：2026-09-17
> **重新评估原则**：
> 1. 旧 wiki 不管 → 旧 page 失效 / 旧 checkpoint 兼容性 → 不算缺陷
> 2. 不考虑成本 → reviewer LLM 调用成本 / Stage 6R 异步开销 → 不算缺陷
> 3. 未来成果达成 → 只评估是否影响整改后的"知识库系统"正确运行

---

## 1. 重新评估结果

### ① 致命缺陷（原 4 个 → 现 1 个）

| 编号 | 原结论 | 重新评估 |
|---|---|---|
| **F1** topic_id 改名导致 page_id 失效 | ① 致命 | ✅ **降级为不修复**——旧 wiki 不管，新 ingest 自然产生新 page_id |
| **F2** 旧 checkpoint 无 fingerprint 兼容 | ① 致命 | ✅ **降级为不修复**——旧 checkpoint 失效即失效，新 source 重新跑 |
| **F3** Stage 5 reviewer 无 budget | ① 致命 | ⚠️ **降级为 ② 重大隐患**——成本不管，但**超 budget 时应有 fail-closed 策略**（防止 reviewer 无响应时 silently degrade） |
| **F4** Reconciliation fingerprint 不传播 | ① 致命 | ✅ **保留为 ① 致命**——这是"未来系统"本身的缺陷：resolver 升级后旧 canonical 永远不重判，**真正影响未来成果** |

#### F4 保留理由（重新论证）

Reconciliation 设计的核心价值是"长期稳定的 canonical identity"。

如果 resolver_fingerprint 升级后，旧的 same/alias  decisions 永远不被重新评估，那么：

- 新发现的"RAG = Retrieval-Augmented Generation"（更精确的 LLM）永远不会被识别
- 已建立的 canonical 永远停留在 V1 算法水平
- **Reconciliation Plane 的核心价值被架空**

这是真正的设计缺陷，不是兼容性问题。

---

### ② 重大隐患（原 8 个 → 重新评估）

| 编号 | 原结论 | 重新评估 | 结论 |
|---|---|---|---|
| **F5** byte offset slice 切错 | ② 重大 | byte/char offset 一致性是 Stage 5 整改的基础——如果切错，evidence span 全错 | ✅ **保留为 ② 重大** |
| **F6** Stage 7 manifest 冷启动冲突 | ② 重大 | 旧 wiki 不管 → 冷启动只对全新项目有意义 | ⚠️ **降级为不修复**——新项目没有旧 checkpoint |
| **F7** Stage 5 claim 与旧 SlotEvidence 不兼容 | ② 重大 | 旧 page 不管 → 旧 SlotEvidence 格式不会重新生成 | ⚠️ **降级为不修复**——旧 page 不会被 reader 重新访问 |
| **F8** Stage 6R relations frontmatter 冲突 | ② 重大 | Stage 6R 是新模块，旧 page 没有 relations 字段 → 不算冲突 | ⚠️ **降级为 ③ 优化**——需要确认 Task 23 决策 |
| **F9** UNCERTAIN 阈值过严 | ② 重大 | Stage 1 整改后会带 `traits: [possible_collection]` 给 Stage 4 → article preservation 计算依据更可靠 | ✅ **保留为 ② 重大**——影响未来系统的稳定性 |
| **F10** vector_neighbor 缺失 | ② 重大 | "不考虑成本" 但 vector neighbor 是 Reconciliation Phase 1 核心——没有它 Phase 1 价值大减 | ✅ **保留为 ② 重大** |
| **F11** durable_failure 与 reviews_queue 双写 | ② 重大 | 两个 queue 重复 → 未来 operator 会困惑 | ✅ **保留为 ② 重大**——影响未来可维护性 |
| **F12** traits 死字段 | ② 重大 | 整改的核心就是"trait 跨 stage 传递" | ✅ **保留为 ② 重大** |

#### F8 重新评估理由

F8 的"Stage 6R 与 Stage 7 frontmatter 冲突"——既然旧 wiki 不管，Stage 6R 不修改 frontmatter（relations 仅存于 RelationStore）即可避免。**降级为 ③ 优化疏漏**——需要 Task 23 明确决策。

---

### ③ 优化疏漏（原 5 个 → 重新评估）

| 编号 | 原结论 | 重新评估 |
|---|---|---|
| **F13** 任务编号混乱 | ③ 优化 | ✅ **保留**——影响 subagent-driven-development 派发 |
| **F14** CI gate / pre-commit | ③ 优化 | ✅ **保留**——影响未来系统不回归 |
| **F15** SlugAliasRegistry 双系统 | ③ 优化 | ✅ **保留**——影响未来 alias 行为一致性 |
| **F16** invariant I4 范围文档 | ③ 优化 | ✅ **保留**——影响未来 reader 行为理解 |
| **F17** E2E 任务过大 | ③ 优化 | ⚠️ **降级为不修复**——E2E 任务大但可串行执行 |

---

## 2. 重新评估后的问题清单

### ① 致命缺陷（1 个）
- **F4**: Reconciliation fingerprint 不传播——resolver 升级后旧 canonical 永远不重判

### ② 重大隐患（4 个）
- **F5**: byte offset slice 切错
- **F9**: UNCERTAIN 阈值过严
- **F10**: vector_neighbor 缺失（Reconciliation Phase 1 核心）
- **F11**: durable_failure 与 reviews_queue 双写
- **F12**: traits 死字段

### ③ 优化疏漏（4 个）
- **F8**: Stage 6R relations frontmatter 冲突 → 需 Task 23 明确决策
- **F13**: 任务编号混乱
- **F14**: CI gate / pre-commit
- **F15**: SlugAliasRegistry 双系统

### 不修复（8 个）
- F1（page_id 失效）—— 旧 wiki 不管
- F2（旧 checkpoint）—— 旧 wiki 不管
- F3（reviewer budget）—— 成本不管；但需保留 fail-closed 策略
- F6（manifest 冷启动）—— 全新项目无此问题
- F7（claim/slot 不兼容）—— 旧 page 不重新读
- F16（invariant 文档）—— 降级为优化疏漏
- F17（E2E 任务）—— 可串行执行

---

## 3. 整改要求（重新分级后）

### 必须立即修复（1 个 ① + 5 个 ② = 6 个）

1. **F4** Task 30 增加 `resolver_fingerprint` 字段到 CanonicalConcept + STALE 信号机制
2. **F5** Task 5 重写 `slice` 方法 + byte/char offset 测试
3. **F9** Task 9 UNCERTAIN 阈值改为 < 0.85 + 增加 diagnostic metric
4. **F10** Task 28 vector_neighbor 必须在第一批实施
5. **F11** Task 21 明确 durable_failure 与 reviews_queue 分工
6. **F12** Task 1 traits 字段明确 Stage 4 消费者

### 强烈建议修复（4 个 ③）

7. **F8** Task 23 显式决策：relations 不入 Wiki frontmatter
8. **F13** Task 编号按依赖顺序重排
9. **F14** CI gate + pre-commit hook
10. **F15** Reconciliation vs SlugAliasRegistry 显式选 A/B

### 不修复（但需记录决策，8 个）

11. **F1** 旧 wiki page 失效 — 决策：旧 wiki 不管，新 ingest 产生新 page_id
12. **F2** 旧 checkpoint 兼容性 — 决策：旧 checkpoint 失效即失效
13. **F3** reviewer budget — 决策：成本不管，但 Task 17 需保留 fail-closed 策略
15. **F6** manifest 冷启动 — 决策：新项目无此问题
16. **F7** claim/slot 兼容 — 决策：旧 page 不重新读取
17. **F16** invariant I4 文档 — 决策：降级为优化疏漏
18. **F17** E2E 任务 — 决策：可串行执行

---

## 4. 决策记录（写入 plan §6 Open risks）

以下决策需要写入 master plan 的 §6 Open risks 作为已知决策：

| 决策项 | 决策 | 后果 |
|---|---|---|
| 旧 wiki page 失效 | 不 migration | 旧 wiki 永久失效，新 ingest 正常 |
| 旧 V7 checkpoint 失效 | 不兼容 | 旧 source 重新跑（产生新 page_id） |
| Stage 5 reviewer budget | 不预算上限，但 fail-closed | 超 budget 时 topic 不进入 WRITTEN |
| Stage 7 manifest 冷启动 | 全新项目无问题 | 不需特别处理 |
| Stage 5 claim/slot 兼容 | 旧 page 不重读 | 旧 SlotEvidence 格式无 reader |
| invariant I4 文档 | 文档补充 | 不修改代码 |
| E2E 任务规模 | 串行执行 | 不拆分 |

---

## 5. 是否通过 Round 1？

**✅ 重新评估后通过**（条件：上述 6 个必修 + 4 个建议修整改完成）。

但整改仍需完成。整改完成后再次执行 Round 1 复审（按 plan-audit §3）。

---

## 6. 整改任务清单

### 必修（6 个，1 个 ① + 5 个 ②）

| Task | 整改内容 | 优先级 |
|---|---|---|
| Task 30（修改） | CanonicalConcept 增加 `resolver_fingerprint` 字段；增加 `STALE` 信号机制；Acceptance 增加 `test_resolver_fingerprint_drift_marks_stale` | P0 |
| Task 5（修改） | 重写 `ArticleBoundary.slice` 方法为 `slice_bytes(source_bytes)`；增加 `test_chinese_byte_offset_slice_consistent` | P0 |
| Task 9（修改） | UNCERTAIN 阈值改为 `article_preservation_ratio < 0.85`；增加 diagnostic metric | P0 |
| Task 28（修改） | vector_neighbor 移到第一批；增加 `test_vector_neighbor_retrieval_integration` | P0 |
| Task 21（修改） | 明确 durable_failure.jsonl 仅记 page-level outcome；reviews_queue.json 仅记 review任务 | P0 |
| Task 1（修改） | 显式声明 traits 字段 Stage 4 消费者；增加 `test_traits_consumed_by_stage4_classification_hint` | P0 |

### 建议修（4 个 ③）

| Task | 整改内容 | 优先级 |
|---|---|---|
| Task 23（修改） | 显式决策：relations 不入 Wiki frontmatter；增加 `test_relations_not_written_to_wiki_frontmatter` | P1 |
| Task 编号（修改）| 按依赖顺序重排 Task 1-33 | P1 |
| 文档（修改） | Acceptance 增加 CI gate 要求 + pre-commit hook | P1 |
| Task 30 + SlugAliasRegistry（修改） | 显式选 A：Reconciliation AliasRecord 调 SlugAliasRegistry adapter | P1 |

---

## 7. 整改后流程

按 plan-audit §3：

1. 整改以上 6 + 4 个 task → 修改 master plan
2. **再次执行 Round 1 复审** → 确认所有漏洞已修复
3. 通过后 → 进入 Round 2（压力测试推演）
4. Round 2 通过 → 人工 review
5. 全部通过 → 进入编码阶段

---

**Round 1 重新评估完成。等待用户确认是否启动整改。**