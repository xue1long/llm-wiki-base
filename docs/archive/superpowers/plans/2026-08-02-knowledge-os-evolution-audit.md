# Knowledge OS Evolution Plan — Independent Audit Report

**审计日期:** 2026-08-02
**审计对象:** `docs/superpowers/plans/2026-08-02-knowledge-os-evolution.md`
**审计标准:** 可落地性、完整性、一致性、风险可控性
**审计立场:** 独立第三方，批判性审查，不美化

---

## 一、隐含假设清单（共 13 项，标注不确定性）

| # | 假设 | 不确定性 | 位置 |
|---|------|---------|------|
| A1 | LLM 能可靠输出符合 `KnowledgeCandidate` schema 的合法 JSON | **高** — LLM JSON 合规率通常在 70-90%，9 字段嵌套 schema 远超简单 JSON 的难度 | §1.6 行103 |
| A2 | Reviewer 能"检测幻觉" | **极高** — 幻觉检测是 LLM 领域未解决问题。用 LLM 检测 LLM 的幻觉是循环自检，不产生独立信号 | §1.7 行113 |
| A3 | `embedding similarity > 0.85 + negation` 能检测矛盾声明 | **高** — 矛盾声明可能嵌入相似度低（措辞不同），相似嵌入可能是同义改写而非矛盾。Negation 检测召回率通常 <60% | §2.4 行205 |
| A4 | WikiPage ↔ KnowledgeObject 往返无损 | **中** — 嵌套对象（Provenance, VersionRef）经 YAML 序列化再反序列化后类型信息丢失，可能变成 dict | §1.2 行57 |
| A5 | 现有 748 测试通过 = 新代码无回归 | **中** — 现有测试不覆盖新代码路径。通过只证明没破坏旧功能 | §1.9 行139 |
| A6 | Config flag 可安全回滚 | **高** — `analyzer.output_format: json|markdown` 意味着所有下游必须同时处理两种格式，测试矩阵翻倍 | §1.6 行106 |
| A7 | 单 JSON 文件可承载知识图谱 | **高** — `.index/knowledge_graph.json` 在 10 万节点时加载和序列化即成为瓶颈，无增量更新、无并发读 | §2.5 行215 |
| A8 | Task 之间可独立 TDD | **中** — Task 1.7 (Reviewer) 依赖 Task 1.6 (Candidate) 依赖 Task 1.2 (KnowledgeObject)，依赖链不允许独立 TDD | §1 任务分解 |
| A9 | CuratorAgent 能安全地"提升低质知识 C→B" | **极高** — LLM 自主改写知识库内容是知识投毒的高风险路径。一次错误改写污染整个知识库 | §4.1 行344 |
| A10 | Heat=0 → Curator review → Archive 链路不阻塞 | **中** — 若 Curator 宕机或审核队列积压，对象永久卡在 zombie 状态 | §4.2 行355 |
| A11 | `src/research/` 模块功能完好 | **未验证** — 方案假设此模块可被 ResearcherAgent 直接复用，但未提供验证结果 | §4.4 行373 |
| A12 | Reranker 关闭时 MemoryRetrieval 有线性的回退路径 | **中** — §3.6 描述的链路是线性的 QueryUnderstanding→search→Reranker，关闭 Reranker 时的旁路未定义 | §3.5-3.6 |
| A13 | 文件系统 + JSON 在 Phase 1-3 能"处理所需规模" | **未定义** — "所需规模"从未被量化 | 交叉约束 §2 |

---

## 二、未覆盖的异常场景与边缘情况

### E1: JSON 解析失败的实际粒度
**位置:** §1.6 行105
**场景:** LLM 返回的是合法 JSON 但不匹配 schema（字段名拼写错误、缺少必填字段、多了 LLM 自创字段）。方案只说了"JSON parse fails"，未区分 Syntax Error vs Schema Validation Error。前者可能是不可恢复的垃圾，后者可能可以修复（重试/字段映射）。
**后果:** 所有非标准 JSON 被统一按 confidence=0.0 处理，失去细粒度恢复机会。

### E2: LLM 非确定性导致 Reviewer 结果不一致
**位置:** §1.7
**场景:** 同一 Candidate 被 Reviewer 审查两次，因 LLM 温度非零，一次 VALIDATED 一次 REJECTED。方案无幂等性保证。
**后果:** 知识库状态取决于"哪次 LLM 调用运气好"。

### E3: 版本文件无限累积
**位置:** §1.3 行66
**场景:** 一个热点 KnowledgeObject 被 Curator 更新 1000 次 → 1000 个 JSON 文件在 `.index/versions/{id}/`。10K 对象每周更新一次 = 每年 520K 版本文件。
**后果:** 磁盘耗尽，版本查询性能退化到不可用。方案无保留策略、无清理机制。

### E4: 图全量重建的性能崩塌
**位置:** §2.5 行213
**场景:** GraphBuilder "从 KnowledgeObjects + Claims + Relations 构建图"。每次 ingest 后全量重建？10K 对象时图构建的 O(n) 遍历 × 每次 ingest = 不可接受的延迟。
**后果:** 随着知识库增长，每次 ingest 越来越慢，最终 ingest pipeline 超时。

### E5: 冲突检测的组合爆炸
**位置:** §2.4 行205
**场景:** "同一实体的声明两两比较嵌入相似度"。若"Python"实体有 1000 条声明 → 499,500 次嵌入计算。若有 100 个实体各有 100+ 声明 → 数百万次比较。
**后果:** 冲突检测任务耗时从秒级退化到小时级，触发 pipeline 超时。

### E6: Candidate PROMOTED 但 KnowledgeObject 创建失败
**位置:** §2.6 行224（Indexer 负责"过渡到 ACTIVE"）
**场景:** Reviewer VALIDATED → Candidate PROMOTED。Indexer 开始写 KnowledgeObject → LanceDB 写入失败（磁盘满/权限错误）。Candidate 永久停留在 PROMOTED 状态，无对应 KnowledgeObject，无重试机制。
**后果:** 知识丢失 + 状态不一致。需要人工介入清理。

### E7: 源文档删除后的悬空引用
**位置:** §2.3 行195-198
**场景:** 源文档因合规原因被删除。所有从该文档派生的 Claim/KnowledgeObject 的 provenance 链断裂。`provenance show` 返回指向不存在文件的引用。
**后果:** 来源可追溯性承诺被破坏。无级联更新/标记机制。

### E8: 并发写入同一个 KnowledgeObject
**位置:** 交叉 — Pipeline Indexer + CuratorAgent + MCP memory.update 三个写入源
**场景:** Indexer 正在更新 object 的 lifecycle→ACTIVE，同时 Curator 决定 merge 它，同时用户通过 MCP 调用 memory.update。三个写入者操作同一个文件/LanceDB 行。
**后果:** 最后写入者胜出，前两个写入静默丢失。方案无乐观锁、无版本向量、无冲突解决策略。

### E9: 知识图谱 JSON 的并发写损坏
**位置:** §2.5 行215
**场景:** 两个并发的 ingest 同时完成，同时尝试写 `.index/knowledge_graph.json`。方案只提了 `safe_write`（原子替换），但这是 read-modify-write 竞争：A 读图→修改→写回，B 读图→修改→写回，B 覆盖了 A 的修改。
**后果:** A 的 ingest 产生的图节点静默丢失。

### E10: 决策记忆缺乏结果反馈闭环
**位置:** §3.2 行271
**场景:** `record_decision("选 LanceDB", reason="部署简单", timestamp=T)`。一个月后已知结果（好/坏决策）。方案无 `update_decision_outcome()` 机制。
**后果:** 决策记忆变成"只记录选择的墓碑"，无法用于未来决策的参考学习。

---

## 三、逻辑断层 / 步骤缺失 / 前后矛盾

### L1: 【致命】Phase 1 的 KnowledgeCandidate 依赖 Phase 2 才定义的 Claim 模型
**位置:** §1.5 行88 vs §2.1 行159
**矛盾:** KnowledgeCandidate (Phase 1) 包含 `claims: list[ClaimCandidate]` 和 `evidence: list[EvidenceRef]`。但 `Claim` 和 `Evidence` 数据类在 Phase 2 才定义。`ClaimCandidate` 和 `EvidenceRef` 是 Claim/Evidence 的轻量版还是独立类型？如是轻量版，与 Phase 2 正式 Claim 如何转换？方案没说。
**后果:** Phase 1 结束时的 KnowledgeCandidate 含有未定义类型的字段。要么 Phase 2 重构 Phase 1 代码（打破"Phase 独立"承诺），要么 ClaimCandidate 是一个孤儿类型。

### L2: 【致命】Generator 在流水线中的位置与目标架构矛盾
**位置:** §1.8 行123 vs 原方案 §7 流水线
**矛盾:** 原方案目标流水线是：Analyzer → KnowledgeCandidate → Reviewer → validated knowledge → **Graph Builder → Indexer → ACTIVE**。Generator 不在其中。但方案 §1.8 把 Generator 插在 Reviewer 之后。两个问题：(a) 如果 Generator 只渲染 Markdown（不推断不修改），那它在知识流水线中起什么作用？(b) WikiPage 持久化是 Generator 的职责还是 Indexer 的职责？§2.6 说 Indexer "替换 commit_ingest 中的隐式索引"，但 commit_ingest 也负责写 WikiPage 文件。
**后果:** 两个组件职责重叠，数据流不可追踪。实现时必然出现"这个字段该谁写"的争论。

### L3: 【重大】Claim 存储位置自相矛盾
**位置:** §2.2 行187-189
**矛盾:** 同一段两句话："Claims stored as KnowledgeObject(type=claim) pages under `wiki/claims/`" 和 "claims are a subtype of concept for now"。到底是新目录 `wiki/claims/` 还是挂在 `wiki/concepts/` 下？`WikiPaths` 加 `wiki_claims` 还是映射到 `wiki_concepts`？
**后果:** 文件系统布局不确定，后续所有读写 Claim 的代码需要重构。

### L4: 【重大】PageType ↔ KnowledgeType 映射未定义
**位置:** §1.1 行46 vs 现有 PageType
**矛盾:** PageType = {source, entity, concept, synthesis} (4 值)。KnowledgeType = {document, entity, concept, claim, decision, procedure, event} (7 值)。Adapter 要求往返无损，但映射是 N:M：concept→concept (直接)，但 claim→??, decision→??, procedure→??, event→??。如果用 concept 做万能兜底，那往返后 claim 变成 concept，类型信息丢失。
**后果:** Adapter 无法实现真正的往返无损。要么扩展 PageType（改 WikiPage 模型 → 影响所有现有代码），要么接受信息丢失。

### L5: commit_ingest() 职责迁移不完整
**位置:** §2.6 行226
**缺失:** "Replaces the current implicit indexing inside commit_ingest()"。但 commit_ingest() 还做了：(a) 写 WikiPage markdown 文件，(b) 更新 index.md，(c) 记录 log.md。Indexer 替换了其中哪些？如果只替换了向量索引部分，那 WikiPage 文件写入仍然在 commit_ingest 中，Indexer 和 commit_ingest 各管一半。
**后果:** 写入路径分裂，难以保证原子性。

### L6: 搜索路径和摄取路径的组件关系未定义
**位置:** Phase 3 vs Phase 1-2
**缺失:** Phase 1-2 定义了摄取流水线（Collector→Analyzer→Reviewer→Generator→GraphBuilder→Indexer）。Phase 3 定义了搜索流水线（QueryUnderstanding→Search→Reranker）。两条路径的唯一交集是 LanceDB + 知识图谱 JSON。但 MemoryRetrieval (§3.6) 的响应格式包含 `provenance_chain, related_decisions, conflicting_claims`——这些数据在摄取端由 ProvenanceTracker/ConflictDetector 产生，在搜索端如何被关联和返回？谁负责在搜索时组装这个响应？
**后果:** 看似完整的端到端链路实际上在摄取↔搜索的边界处断裂。

### L7: MCP memory.verify(claim_id) 跨 Phase 硬依赖
**位置:** §3.3 行283
**缺失:** Phase 3 的 `memory_verify(claim_id)` 需要 Claim 对象（Phase 2 产物）和证据链（Phase 2 产物）。如果 Phase 2 部分部署或 Claim 模型有破坏性变更，Phase 3 MCP 工具直接崩溃。
**后果:** Phase 之间没有隔离——一个 Phase 的失败级联到后续 Phase。

---

## 四、潜在 Bug / 风险 / 合规 / 资源瓶颈

### B1: 【致命】LLM 成本三倍化且无预算控制
**位置:** Phase 1 流水线变更
**计算:** 当前每次 ingest = 1 次 LLM (Analyzer+Generator 合一)。新流水线 = Analyzer (1) + Reviewer (1) + Generator (1) = **3 次 LLM 调用**。加上 Phase 4 CuratorAgent 每小时扫描全库，成本不可控。方案无预算上限、无 cost estimation、无 token 估算。
**后果:** 上线后 API 账单爆炸。CuratorAgent 每小时一次的 LLM 调用 × 全库扫描可能是每月数千美元。

### B2: 【重大】Reviewer "幻觉检测"是伪功能
**位置:** §1.7 行113
**分析:** 方案要求 Reviewer 检测 Analyzer 输出的幻觉。但 Reviewer 本身是 LLM。用 LLM 检测 LLM 的幻觉 = 循环自检，不产生独立验证信号。要实现真正的幻觉检测需要：(a) 事实验证管道（对比外部权威源），或 (b) 人工审核。两者方案都没提。
**后果:** Reviewer 给幻觉输出打 VALIDATED 的概率与 Analyzer 产生幻觉的概率正相关。幻觉检测变成安慰剂。

### B3: 【重大】CuratorAgent 自主改写知识 = 知识投毒风险
**位置:** §4.1 行344
**分析:** "Improve low-grade knowledge (C-grade → B-grade)" 意味着 LLM 自主改写知识库内容。一次错误改写（如把"Python 3.14 移除了 GIL"改成"Python 3.13 移除了 GIL"）将污染所有依赖该知识的 Agent。没有 human-in-the-loop，没有改写审批流程，没有回滚机制。
**后果:** 知识库正确性随时间退化而非改善。这是比没有 Curator 更糟的结果。

### B4: ResearcherAgent 的 Web 搜索 → 知识投毒路径
**位置:** §4.4 行371-374
**分析:** ResearcherAgent 有 `knowledge.create` 权限，并通过 Tavily 搜索 Web。恶意网页可以通过 SEO 污染搜索结果 → Tavily 返回恶意内容 → ResearcherAgent 创建 synthesis KnowledgeObject → 恶意内容进入知识库。方案无输入消毒、无可信源白名单、无合成内容隔离标记。
**后果:** 知识库被外部攻击者通过 Web 搜索结果间接污染。

### B5: 知识图谱单 JSON 文件在并发写入下的数据损坏
**位置:** §2.5 行215
**分析:** 见 E9。`safe_write` 保证文件级别原子替换（不会出现半写文件），但不解决 read-modify-write 竞争。两个 ingest 并发 → A 读 {v1} → B 读 {v1} → A 写 {v2} → B 写 {v3}，{v2} 中 A 的修改被 B 覆盖。
**后果:** 知识图谱静默丢失节点和边。用户查询时"为什么这条 Claim 在图上找不到"。

### B6: 单点 LLM Provider 故障阻塞全部 Agent
**位置:** 全局
**分析:** Collector→Analyzer→Reviewer→Generator 四个串行步骤中有三步依赖 LLM。LLM Provider 限流/宕机 → 所有 ingest 卡在队列中。方案无降级策略（如跳过 Reviewer 直接 VALIDATED，或使用本地 Ollama 作为 fallback）。
**后果:** 单点故障阻塞整个知识摄取管线。

### B7: 版本 diff 的计算成本
**位置:** §1.3 行65
**分析:** `diff(v1, v2) -> dict`。如果 KnowledgeObject.body 是 50KB 的 Markdown，生成 diff 需要完整的文本比较。对于 1000 个版本的链式 diff（v1→v2, v2→v3, ...），计算成本高。方案没有指定 diff 粒度（字段级？行级？全文？）。
**后果:** 版本 diff 操作可能超时或消耗过多 CPU。

### B8: embedding 模型更替导致全量重索引
**位置:** 未涉及
**缺失:** LanceDB 存储 1536-dim 向量（openai text-embedding-ada-002）。如果未来切换到不同维度的模型（如 3072-dim），所有向量需重索引。方案没有 embedding 模型版本管理。
**后果:** 迁移成本在方案外，但实际发生时需要全量重处理。

---

## 五、信息盲区——缺少这些无法落地

| # | 缺失信息 | 影响范围 | 为什么必须 |
|---|---------|---------|----------|
| I1 | **每次 LLM 调用的 token 成本估算** | Phase 1-4 | 没有成本模型无法决定是否开启 Reviewer/Curator/Reranker |
| I2 | **目标规模**（KnowledgeObject 数量、Claim 数量、日 ingest 量） | 存储/图/冲突检测 | 决定单 JSON 文件存图是否可行、冲突检测是否需要分批 |
| I3 | **延迟 SLO**（ingest 延迟、搜索延迟、图构建延迟） | 全链路 | 决定同步 vs 异步、缓存策略、超时配置 |
| I4 | **现有 wiki pages 迁移方案** | Phase 1 | 数千个现有 .md 文件如何转为 KnowledgeObject？lazy migration on read？批量一次性脚本？ |
| I5 | **回滚程序**（Phase N 部署后如何撤销） | 全部 Phase | 如果 Phase 2 部署后知识图谱损坏，恢复到 Phase 1 的步骤是什么？ |
| I6 | **Reviewer 准确率基准** | Phase 1 | "检测幻觉"功能上线前，Reviewer 在标注数据上的准确率是多少？低于多少不启用？ |
| I7 | **CuratorAgent 改写审批策略** | Phase 4 | 改写是否需要人工确认？自动应用的阈值是什么？改写错误的恢复步骤？ |
| I8 | **Observability 方案** | 全部 Phase | Candidate 拒绝率、Reviewer 通过率、图构建失败率、版本文件数量的监控指标和告警阈值 |
| I9 | **embedding 模型版本管理** | 全部 Phase | 模型切换时的向量迁移策略 |
| I10 | **LLM Provider 降级策略** | 全部 Phase | OpenAI 限流时是否 fallback 到 Ollama？Reviewer 可否被跳过？ |

---

## 六、三级问题分类

### 🔴 致命缺陷（方案按现状无法落地）

| # | 问题 | 位置 |
|---|------|------|
| F1 | KnowledgeCandidate 引用了 Phase 2 才定义的 Claim 模型，Phase 1 无法独立完成 | L1 |
| F2 | PageType↔KnowledgeType 映射未定义，Adapter 无法实现往返无损 | L4 |
| F3 | Generator 在流水线中的位置与目标架构矛盾，且与 Indexer 职责重叠 | L2 |
| F4 | LLM 成本三倍化无预算控制，CuratorAgent 每小时全库扫描成本不可估计 | B1 |

### 🟡 重大隐患（容易导致项目失败）

| # | 问题 | 位置 |
|---|------|------|
| M1 | Reviewer "幻觉检测"是伪功能——LLM 自检 LLM 不产生独立验证信号 | B2 |
| M2 | CuratorAgent 自主改写知识库无人工审批，一次错误改写污染整个知识库 | B3 |
| M3 | 知识图谱单 JSON 文件在并发写入下有数据丢失风险 | B5 |
| M4 | 多个写入源 (Pipeline/Curator/MCP) 并发操作同一 KnowledgeObject 无冲突解决 | E8 |
| M5 | Claim 存储位置自相矛盾（wiki/claims/ vs wiki/concepts/） | L3 |
| M6 | commit_ingest() 职责拆分不完整，Indexer 和 commit_ingest 各管一半写入 | L5 |
| M7 | ResearcherAgent 通过 Web 搜索将外部恶意内容注入知识库 | B4 |
| M8 | 摄取↔搜索边界的数据组装责任未分配 | L6 |
| M9 | Phase 之间无隔离——Phase 3 MCP 工具硬依赖 Phase 2 产物 | L7 |

### 🟢 优化疏漏（可后续修复，但影响质量/性能/可维护性）

| # | 问题 | 位置 |
|---|------|------|
| O1 | 版本文件无保留策略，无限累积 | E3 |
| O2 | 图全量重建 O(n) 随知识库增长退化 | E4 |
| O3 | 冲突检测组合爆炸无分批/限流 | E5 |
| O4 | 决策记忆无结果反馈闭环 | E10 |
| O5 | 源文档删除后悬空引用无级联处理 | E7 |
| O6 | Candidate PROMOTED 状态与 KnowledgeObject 创建之间无事务保证 | E6 |
| O7 | Reviewer 结果无非确定性保证 | E2 |
| O8 | JSON 解析失败未区分 Syntax Error vs Schema Error | E1 |
| O9 | Reranker 关闭时的回退路径未定义 | A12 |
| O10 | embedding 模型更替无迁移方案 | I9 |

---

## 七、整改建议（针对致命缺陷和重大隐患）

### 针对 F1 (Claim 依赖倒置)

**建议:** 将 `ClaimCandidate` 和 `EvidenceRef` 从 KnowledgeCandidate 中剥离。Phase 1 的 KnowledgeCandidate 只包含 `raw_llm_output: dict` + 基础字段。Phase 2 引入 Claim 模型后，再添加 Claim 解析层将 `raw_llm_output` 转化为结构化 Claim。这是渐进式增强，而不是跨 Phase 的硬依赖。

### 针对 F2 (类型映射)

**建议:** 方案必须显式定义映射表：
```
PageType.source    → KnowledgeType.document
PageType.entity    → KnowledgeType.entity
PageType.concept   → KnowledgeType.concept
PageType.synthesis → KnowledgeType.decision  (或新增 synthesis?)
# claim/decision/procedure/event → 新 PageType 值或映射到 concept
```
两种选择：(a) 扩展 PageType 枚举（影响所有现有代码但语义正确），(b) 在 KnowledgeObject 上维护 `_legacy_page_type` 字段用于往返。建议 (a)，一次性重构。

### 针对 F3 (Generator vs Indexer 职责)

**建议:** 在方案开头画一张**更新后的全 Phase 数据流图**，明确：
- Generator 的职责：将 KnowledgeCandidate 渲染为 WikiPage Markdown body（纯渲染，Phase 1 保留）
- Indexer 的职责：向量嵌入 + 知识图谱更新 + 生命周期过渡 → ACTIVE（Phase 2 新增）
- WikiPage 文件写入：保留在 commit_ingest 中，Indexer 是 commit_ingest 之后的独立 stage

### 针对 F4 (成本)

**建议:** Phase 1 Task 0 必须包含成本模型的量化估算：
- 单次 ingest 的 Analyzer/Reviewer/Generator token 估算
- 当前日 ingest 量 × 3 = 日成本
- CuratorAgent 每次扫描的 token 估算 × 扫描频率 = 月成本
- 预算上限设置建议

### 针对 M1 (Reviewer 伪功能)

**建议:** 将 Reviewer 的职责从"检测幻觉"重新定义为可实现的检查：
1. **Schema 合规** — Candidate JSON 是否包含必填字段
2. **证据存在性** — 每条 Claim 是否有引用源文档
3. **引用一致性** — 引用的页码/段落是否在源文档中存在（可自动化）
4. **置信度阈值** — confidence < 阈值的标记为需要人工审核

将"幻觉检测"从 Phase 1 deliverable 中移除或降级为 Phase 4 的研究目标。

### 针对 M2 (Curator 知识投毒)

**建议:** CuratorAgent 的改写必须经过以下安全措施：
1. 改写内容标记为 `lifecycle=REVIEWING`，不是直接 ACTIVE
2. 改写记录包含 `before_snapshot`（已有）和 `diff`（方便人工审查）
3. Curator 只对 C-grade 且 heat < 10 的对象操作（缩小影响面）
4. 所有 Curator 改写写入独立的审核队列，不自动应用
5. Phase 4 初期 Curator 应以 dry-run + report 模式运行

### 针对 M3/M4 (并发安全)

**建议:**
- 知识图谱：从单 JSON 改为 append-only event log + 定期 snapshot，或用 SQLite（零依赖，Phase 1 可用）
- KnowledgeObject 写入：每个 object 加 `_lock` 文件或使用文件系统原子 rename 作为乐观锁
- 所有写入路径统一通过 `VersionManager.snapshot()` 后再写

### 针对 M7 (ResearcherAgent 注入风险)

**建议:** ResearcherAgent 的 synthesis 产物标记 `provenance.source_type = "web_search"` 且默认 lifecycle = PROCESSING（不自动 ACTIVE）。Web 搜索结果在进入知识库前必须经 Reviewer 验证。可信域名白名单。

---

## 八、总结

**方案整体方向正确，但 4 个致命缺陷使其按现状无法开始编码：**

1. Phase 1 的数据模型依赖 Phase 2 的类型定义 → 重构 ClaimCandidate 为 opaque dict
2. PageType/KnowledgeType 映射空白 → 显式定义映射表并扩展 PageType
3. Generator 和 Indexer 职责重叠 → 画全 Phase 数据流图，明确每个组件的唯一职责
4. 无成本模型 → Phase 1 Task 0 必须做成本估算

**修复这 4 个致命缺陷后，方案可以从 Phase 1 开始执行。9 个重大隐患需要在对应 Phase 的实现中逐一解决，不能推迟到 Phase 4。**
