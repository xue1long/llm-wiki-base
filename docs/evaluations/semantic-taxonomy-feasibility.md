# Semantic Taxonomy System（STS）可行性评估

> Version: v1.0 | 2026-08-03
> 评估对象：`2026-08-03 Semantic Taxonomy System.md`
> 对照基准：当前代码库实测（`src/wiki/features/tag_namespace.py`、`src/knowledge/**`、`src/pipeline/**`）+ 既有架构文档 `docs/ARCHITECTURE.md`、`docs/TECH_DEBT_CHECKLIST.md`

---

## 0. 结论速览

| 维度 | 判断 |
|------|------|
| 方向 | ✅ **正确**。与 Knowledge OS 愿景高度契合，且与代码里已有的 `graph/`、`conflicts/`、`memory/`、`provenance/`、`candidate/lifecycle` 子包形成天然对接 |
| 是否需重写 | ❌ **不需要**。本质是"把已有半成品拼装成型 + 补一处存储抽象"，不是从零发明 |
| 最大风险 | 🔴 **PostgreSQL 作为 source of truth 的假设**。当前系统是零数据库依赖（Markdown 文件为真相源 + LanceDB 派生向量索引 + JSONL 事件日志）。强行上 PG 是重大运维变更 |
| 次大风险 | 🟡 **相似度自动合并（alias）**：embedding 相似度误合并会污染整个分类体系，必须加人工/规则兜底 |
| 落地形态建议 | 在**现有存储门面**（file/JSONL/LanceDB，PG 仅作可选后端）上实现，复用已有的 Candidate→Review→Approve 生命周期与 GraphBuilder |

**一句话：方案可行，但应作为"演进"而非"新建系统"来落地；且 PostgreSQL 不应成为强制前提。**

---

## 1. 方案核心思想复述

把标签从"配置里的字符串"升级为"可演化的一等知识对象"：

- Tag 不再是 `str`，而是 `TagReference{tag_id, namespace, value, confidence, source, status}`
- 维护 `tag_entities` / `tag_relations` / `tag_candidates` / `namespaces` 四张表
- 三层分类：System（不可删）/ Domain（自动成长）/ Project（用户建）
- 自生长机制：Analyzer 发现新概念 → Tag Candidate → 相似度检查 → 合并/累积 → 人工或 Agent 审核 → Approved
- 治理用 `tag_policy.yaml` 规则引擎替代硬编码 `MANDATORY_PAIRS`
- 检索支持 `taxonomy_filters` + LLM Query Planner + Graph Expansion

---

## 2. 与现有代码库契合度（逐组件）

### 2.1 标签命名空间 `tag_namespace.py` —— 方案低估了现状

**实测事实（关键更正见 §5）：**

- 当前 `TAG_PREFIXES` 已经是 **10 个中文前缀**：`题材/功能/角色/事件/情绪/实体/场景阶段/状态/素材/可信度`（不是我上次误判的 8 个英文前缀）。
- **值域约束 `TAG_VALUES` 已经存在**：`题材` 限定 12 个值、`情绪` 8 个、`场景阶段` 8 个、`状态` 6 个、`素材` 5 个、`可信度` 6 个……并配有 `is_valid_value()` / `validate_tag_values()`。
- `MANDATORY_PAIRS` 已存在且**已配置 2 个配对 `[("素材","ugc"),("可信度","ugc")]`**（:49-52，非空）；UGC 强制标签经 `build_tag_prompt_section()`（:163）**配置驱动**注入提示词，并非硬编码。仅"前缀说明文案"在提示词中重复出现（技术债务 #11 范畴）。

**评估：** STS 的"受控词汇 + 规则引擎"目标，**机制层已经具备 80%**（前缀、值域、配对三件套都在）。缺口只是"值域强制覆盖不全（新建页面已接线、更新路径跳过）+ 自由前缀未约束"——配对早已配置化。这与我早先标签评估报告里的 P0 建议方向重合（但 P0 实为"补全覆盖"而非"从零接线"）——**STS 不必重建这些，只需把已有的补全覆盖**。

### 2.2 存储层 —— 方案的最大假设风险

**实测事实：**

- `src/knowledge/storage/event_store.py` 默认后端是 **JSONL 文件**（`index/knowledge_graph/events.jsonl`），PostgreSQL 是**可选后端**（lazy import `psycopg2`，仅当 `storage.backend="postgresql"` 时启用，且 psycopg2 不是项目依赖）。
- `src/knowledge/storage/metadata.py` 同理：PG 是 opt-in。
- 当前**零数据库依赖**，真相源是 Markdown 文件。

**评估：** STS §13 把"PostgreSQL/SQLite + Vector Index + Graph Relation"当作默认前提，**与当前零 DB 架构冲突**。但好消息是存储抽象**已经预留了 PG 钩子**。

→ 策略：STS 的 `tag_entities` 等完全可以用现有 `storage/facade.py` + JSONL/parquet 实现，不必引入 PG。**PG 应作为可选扩展而非强制前提**。这样风险从"重大架构迁移"降为"在已有门面上加一个 tag store 模块"。

### 2.3 知识图 `knowledge/graph/builder.py` —— 可复用，勿并行重建

**实测事实：** 已有 `GraphBuilder`（内存图 + append-only JSONL 事件日志 + 周期快照），含 `NodeType`/`EdgeType` 枚举、`add_node`/`remove_node`/`add_edge`，能从 KnowledgeObject 构建。

**评估：** STS 的 "Taxonomy Graph" 应作为 `GraphBuilder` 的**新节点/边类型**（如 `NodeType.TAXONOMY`、`EdgeType.PARENT_OF`），而非另起一套图系统。当前 `tag_relations` 的 7 种关系（`parent_of`/`same_as`/`alias_of`/`conflicts_with` 等）直接映射到 `EdgeType` 扩展即可。

### 2.4 Candidate / Lifecycle —— 自生长机制的核心已具备

**实测事实：** `src/knowledge/core/candidate.py`（KnowledgeCandidate + CandidateStatus + ReviewVerdict）、`lifecycle.py`、`version_manager.py` 均已写好（但如 ARCHITECTURE.md 所述，未接入生产流水线）。

**评估：** STS 的 "Tag Candidate → Similarity Check → Review → Approved" 与现有 Candidate 生命周期**同构**。直接复用 `KnowledgeCandidate` 模式承载 `tag_candidates`，复用 `LifecycleEngine` 管理 `candidate/approved/deprecated` 状态——**不要为标签另写一套状态机**。

### 2.5 conflicts / memory / provenance —— 最终四图愿景已有种子

**实测事实：**
- `knowledge/conflicts/detector.py` 已用 embedding 做冲突检测（可承载 `conflicts_with` 关系与 alias 相似度）。
- `knowledge/memory/`（`decision.py`/`retrieval.py`/`types.py`）已用 embedding（可承载 "Memory Graph"）。
- `knowledge/provenance/tracker.py` 已存在（可承载 "Evidence Graph"）。

**评估：** STS §15 的"最终形态 = Knowledge Graph + Taxonomy Graph + Memory Graph + Evidence Graph"**不是新发明，而是把现有子包正式命名并连成体系**。这极大提升了可行性——你不是在造四张图，而是在已有四块上做整合。

### 2.6 检索集成 `taxonomy_filters` —— 高价值、低风险

**实测事实：** 当前检索是 hybrid（vector + keyword + RRF）跑在 LanceDB 上；我早先标签评估已指出"标签写入但检索不消费"是错失的机会。

**评估：** STS §12 的 `search(taxonomy_filters=[...])` + Graph Expansion **正好补齐这个缺口**，且实现路径清晰（在现有 HybridSearch 上加 tag 过滤 + 沿 `tag_relations` 图扩展）。这是方案里**投入产出比最高**的一块，建议优先做。

---

## 3. 可行性逐条评估（对照方案 15 节）

| 方案节 | 可行性 | 说明 |
|--------|--------|------|
| §2 Tag 不再是字符串 | ✅ | `tags: list[str]` → `TagReference[]` 是干净的字段演进 |
| §3 tag_entities 表 | ✅ | 用现有 storage 门面即可，不必真建 PG 表 |
| §4 tag_relations | ✅ | 扩展 GraphBuilder.EdgeType |
| §5 Namespace 也是对象 | ✅ | namespaces 可建模为特殊 tag_entities；复杂度可控 |
| §6 三层分类 | ✅ | System/Domain/Project 可用 `level` + `scope` 字段表达 |
| §7 自生长机制 | 🟡 | 流程清晰，但 Similarity Check 误合并风险高（见 §4.2） |
| §8 tag_candidates | ✅ | 复用 KnowledgeCandidate 模式 |
| §9 自动合并(alias) | 🟡 | 需保守阈值 + 人工兜底，否则污染分类 |
| §10 规则引擎替 MANDATORY_PAIRS | ✅ | 但 MANDATORY_PAIRS 当前已存在且已配置 2 个配对、经 `build_tag_prompt_section` 配置驱动；STS 规则引擎应"扩展"而非"从零替代" |
| §11 与 KO 集成 | 🟡 | **KnowledgeObject 当前没有 `tags` 字段**（实测 grep 无结果），需先给 KO 加 taxonomy 字段 |
| §12 检索用法 | ✅ | 高价值，补当前缺口 |
| §13 持久化存储 | 🟡 | PG 不应强制；用现有 file/JSONL/LanceDB 即可 |
| §14 自演化闭环 | ✅ | 可复用 `knowledge/evolution/loop.py` + `scheduler.py` |
| §15 迁移路径 | 🟡 | 步骤合理，但假定 RDBMS；在 file 存储上应改写为"加 tag store 模块" |

---

## 4. 主要风险与阻塞点（按严重度）

### 🔴 R1. PostgreSQL 作为真相源（最大风险）
- **问题**：当前零 DB 依赖，STS §13 默认 PG。若强制，等于把整个存储范式从"文件真相源"翻转为"RDBMS 真相源"，影响 Analyzers/Generator/版本管理/检索全链路。
- **缓解**：把 PG 降级为**可选后端**（代码已支持）；tag store 默认建在现有 `storage/facade` + JSONL/parquet 上。若未来确实需要关系查询，再启用 PG（已有 lazy 钩子）。
- **验收**：STS 可在不安装 psycopg2、不改存储范式的前提下完整运行。

### 🟡 R2. 相似度自动合并的误合并
- **问题**：§9 示例在 similarity 0.96 时自动建立 alias。embedding 相似度对近义/上下位/拼写变体易误判，一旦误合并，分类体系不可逆地污染。
- **缓解**：① 阈值分两档（高置信自动 alias + 中置信进审核队列）；② 合并动作走 ReviewVerdict，默认需人工确认；③ 保留 `alias_of` 可逆（deprecated_by）。
- **验收**：自动合并的误合并率有监控；所有 alias 可回溯/撤销。

### 🟡 R3. KnowledgeObject 缺 tags 字段
- **问题**：STS §11 假定 KO 已带 `taxonomy`，但实测 `knowledge/core/object.py` 无 `tags`。
- **缓解**：先给 KO 增加 `tags: list[TagReference]`（或 `taxonomy_refs`），作为 STS 的集成锚点。这属于 KOS 演进 Phase 1 的一部分。
- **验收**：KO 序列化含结构化 tag 引用，且可被检索消费。

### 🟡 R4. 自生长循环的编排
- **问题**：Taxonomy Agent 需要被触发（每次摄取后？定时？）。当前 `PipelineService._stages` 仍是旧三件套，新 Agent 未接入。
- **缓解**：复用 `knowledge/evolution/loop.py` + `scheduler.py` 做定时演化；摄取流水线在 Candidate 阶段后挂一个 "TaxonomySync" 步骤。
- **验收**：新概念能自动进 candidate 队列，且有人工审核出口。

### 🟢 R5. 四图愿景的过度工程
- **问题**：Knowledge/Taxonomy/Memory/Evidence 四图同时推进易摊薄精力。
- **缓解**：分阶段——先 Taxonomy Graph（与标签强相关），其余三图沿用现有子包，不强求同期成形。
- **验收**：每阶段有独立可验收产出，不绑定"四图齐活"才算成功。

---

## 5. ⚠️ 对我此前结论的更正（重要）

在写本评估前，我在 `docs/reference/ingest-prompts.md` 及回复中声称：

> "标签命名空间实际是 8 个英文前缀（genre/func/...），我之前写的 10 个中文前缀是错的。"

**这是错的，特此更正：**

1. `tag_namespace.py` 的 `TAG_PREFIXES` **确实是 10 个中文前缀**（题材/功能/角色/事件/情绪/实体/场景阶段/状态/素材/可信度）。原 `tag-namespace-evaluation.md` 和 `ARCHITECTURE.md §14` 的"10 中文前缀"描述**是正确的**。
2. 那 8 个英文前缀（`genre/func/char/event/mood/entity/scene_phase/status`）只出现在 `generator.py:79` 的 `_ID_TAG_NS` 里，用途是**从生成正文里抽取实体引用标签以修复 wikilink**，与受控命名空间是两回事。主提示词的 tag guidance 用的仍是中文前缀，与校验器一致。
3. **更关键的更正**：我早先标签评估报告把"无值域约束"列为 🔴 P0——**不准确**。值域约束 `TAG_VALUES` 早已实现，且新建页面已**接线强制**（`page_writer.py:74` 调 `validate_tag_compliance`，内部执行 `validate_tag_values` + 强制配对）。真实问题是**覆盖不全**（更新既有页面时跳过、Generator 内部只按前缀静默过滤）。应改为"P0 值域约束写入强制覆盖不全"。

以上三处偏差不影响 STS 评估方向，但影响对"现状缺口"的判断：STS 要补的其实比我想的更少。

---

## 6. 建议落地路径（演进式，复用优先）

| 阶段 | 内容 | 复用现有 | 工期 |
|------|------|----------|------|
| **T0 补全覆盖** | 值域强制已接线（新建页面 `page_writer.py:74` → `validate_tag_compliance`），本步改为：把 `validate_tag_compliance` 也覆盖到既有页面更新路径 + 自由前缀归一化；确认 `MANDATORY_PAIRS`（素材/ugc + 可信度/ugc）经 `build_tag_prompt_section` 已覆盖全部摄取提示词 | tag_namespace.py 已有 | 1-2 天 |
| **T1 Tag store** | 在 `storage/facade` 上加 `tag_entities`/`tag_relations`/`tag_candidates` 模块（file/JSONL 默认，PG 可选）；KO 加 `tags: list[TagReference]` | storage 门面、KnowledgeObject | 3-4 天 |
| **T2 自生长** | Taxonomy Agent：发现新概念→candidate→相似度检查→审核→approved；复用 `candidate.py`/`lifecycle.py`/`conflicts/detector.py` | candidate/lifecycle/conflicts | 3-5 天 |
| **T3 图与检索** | 扩展 `GraphBuilder` 加 taxonomy 节点/边；检索加 `taxonomy_filters` + Graph Expansion | graph/builder、HybridSearch | 3-4 天 |
| **T4 治理** | `tag_policy.yaml` 规则引擎替代硬编码配对；namespace 对象化 | tag_namespace | 2-3 天 |

> 与既有摄取完善方案（`2026-08-02-ingest-pipeline-completion.md`）的关系：T0/T1 的 KO 改造依赖该方案的 Phase 1 新管线接线；建议**先完成摄取方案 Phase 0+1，再启动 STS T0-T1**。两计划在"KO 结构化"上汇合。

---

## 7. 决策建议

1. **接受方向，但重新措辞**：把方案标题从"设计一个语义分类系统"改为"把已有标签/图/记忆/溯源子包整合为可生长的分类生态"——更准确，也更低风险。
2. **PG 降级为可选**：默认用现有 file/JSONL/LanceDB 实现 tag store，PG 仅作大规scale 时的可选后端（代码已预留）。
3. **复用优先**：Candidate/Lifecycle/GraphBuilder/Conflicts/Memory/Provenance 全部已有种子，STS 应"接线 + 扩展"，不做平行重建。
4. **先修已知缺口**：T0（补全值域强制覆盖——更新路径 + 自由前缀归一化；配对早已配置化无需再做）几乎零成本，却能让当前标签系统立即达标，建议在启动 STS 前就做。
5. **检索集成优先**：`taxonomy_filters` 投入产出比最高，建议作为 STS 第一个交付物。

---

## 附：与既有文档的关系

- 本评估取代/整合了 `docs/evaluations/tag-namespace-evaluation.md` 中关于"缺口"的判断（该文档的 P0 已不准确，见 §5）。
- STS 与 `docs/superpowers/plans/2026-08-02-ingest-pipeline-completion.md` 在"KO 结构化"上汇合，建议联合排期。
- 架构背景见 `docs/ARCHITECTURE.md`；待办优先级见 `docs/TECH_DEBT_CHECKLIST.md`。
