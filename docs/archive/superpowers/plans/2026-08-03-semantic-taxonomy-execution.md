# Semantic Taxonomy System — 融合执行计划 v2

> 基于 `docs/evaluations/semantic-taxonomy-feasibility.md` + 10 轮压力测试发现 + 6 项 tech debt 修复经验  
> 审计修正：`docs/evaluations/audit-2026-08-03-semantic-taxonomy-plan.md` (v3) — 1致命/10重大/10优化  
> 原则：先止血、再增值、后自生长

---

## 0. 不做 STS 的对比基线

维持现状 3 个月的预期状态：
- 标签仍是软约束（提示词引导，写入不校验），值域会逐步漂移
- 检索不可按 tag 过滤——分类信息写入但不消费
- 新概念发现靠人工阅读文档后手动添加 TAG_VALUES，无自动化
- 四图（Knowledge/Taxonomy/Memory/Evidence）各自散落，无统一入口

本方案的增量价值：把已有半成品（tag_namespace/Candidate/Lifecycle/GraphBuilder/Conflicts）**接线成型**，让标签从"配置里的字符串"升级为"可演化的一等知识对象"。

---

## 总览

```
Week 1        Week 2          Week 3-4         Week 5+ (gate)
P0 管线止血    P1 KO+检索      P2 自生长        P3 四图整合
  │              │               │               │
  ├─ reviewer修复(✅done)  ├─ KO tags字段   ├─ tag store    ├─ GraphBuilder扩展
  ├─ 30 stub重摄取       ├─ 关系索引接线   ├─ TaxonomySync ├─ Graph Expansion
  ├─ 值域+配对硬校验      ├─ 检索tag过滤   ├─ 相似度审核    ├─ 三图现状盘点
  ├─ 配对动态化          └─ degradation告警 └─ 规则引擎     └─ 统一入口
  └─ 全量回归(pytest)
```

---

## Phase 0 — 管线止血 + 标签接线（Week 1, 2-3 天）

### 目标

摄取成功率 0% → >80%，标签从"软约束"变成"硬约束"。

### 任务

| # | 任务 | 文件 | 工期 | 验收 |
|---|------|------|------|------|
| **0.1** | `_check_references` 用 `project_path / normalized` | `pipeline/stages/reviewer.py:238` | ✅ done | 端到端验证通过（东方玄幻道教 grade A） |
| **0.2** | 30 个 stub 批量重新摄取 | `_submit_ingest.py` + stub 列表 | 0.5d | ≥24 个转为非 stub，grade ≥ B |
| **0.3** | 历史标签合规确认 + `validate_tag_values()` + `missing_mandatory_tags()` 接入 `write_page` | `wiki/storage/page_writer.py`, `tag_namespace.py` | 0.5d | 无效标签或缺失强制配对时写入抛出 `TagValidationError` |
| **0.4** | UGC 强制标签配对动态化：analyzer 改用 `build_tag_prompt_section()` + 配对加入 `MANDATORY_PAIRS` + 删除硬编码引导 | `tag_namespace.py`, `analyzer.py`, `generator.py` | 0.5d | 改 yaml 即可变更强制配对，不改代码 |
| **0.5** | 全量 pytest 回归 + 随机 10 文档摄取验证（按长度分层） | `pytest tests/` | 0.5d | 回归全绿（扣除预存 6 个失败）；短文档 ≥60%、中 ≥80%、长 ≥90% 非 stub |

### 任务详解

#### 0.3 值域+配对硬校验

**前置检查（1 分钟）：** 扫描全部 wiki 页面确认无非空不合规 tags。实测 748 页面中仅 1 页（`2-刻画人物形象之语言动作描写第-2-段-94eb302e.md`）含裸字符串 `['教程','转录','人物描写']`——P0.3 前手动修复或清空。

**接入两个校验到 `write_page`：**
- `validate_tag_values(tags)` — 值域校验（已存在，未接入写入路径）
- `missing_mandatory_tags(tags)` — 强制配对校验（已存在，未接入写入路径）

任一校验失败 → `TagValidationError`，拒绝写入。

#### 0.4 UGC 配对动态化（4 步）

**现状：**
- Generator 已通过 `TAG_NAMESPACE_RULES = build_tag_prompt_section()`（`generator.py:44`）动态读取 `MANDATORY_PAIRS`，注入全部 7 个 prompt 模板。✅
- Analyzer（`analyzer.py:46-58`）硬编码了 10 个前缀 + UGC 配对规则。不使用 `build_tag_prompt_section()`。❌

**步骤：**
1. **Analyzer 动态化：** 让 analyzer prompt 也使用 `build_tag_prompt_section()`，替换 `analyzer.py:46-58` 硬编码 tag 规则
2. **配置化：** 将 `("素材","ugc")` 和 `("可信度","ugc")` 加入 `MANDATORY_PAIRS`
3. **清理硬编码：** 删除 `analyzer.py:58` 和 `generator.py:256,409` 中的硬编码 UGC 引导文本（generator 的 `TAG_NAMESPACE_RULES` 已自动包含）
4. **防御校验：** 0.3 的 `missing_mandatory_tags()` 已在 write_page 兜底

#### 0.5 验收标准分层

| 文档长度 | 非 stub 率要求 |
|---------|-------------|
| 短文档 (<500 字) | ≥60% |
| 中文档 (500-5000 字) | ≥80% |
| 长文档 (>5000 字) | ≥90% |

"全量回归"指 pytest 全量测试（`pytest tests/`），**不是**全量重摄取 748 文档。

### 依赖

- 无前置依赖。当前管线阻塞所有下游，必须先做。

### 风险

- 0.2 批量重摄取时 LLM API 限流 → 降低并发至 2，间隔 3s/条
- R5: P0 修复后管线仍有残余 bug（概率低/影响高）→ 0.5 全量回归 + 10 文档验证兜底

### 回滚

- 0.3/0.4 的 `TagValidationError` 可临时改为 warn-only（环境变量 `RUFLO_TAG_VALIDATION=warn`），不影响写入但记录告警

---

## Phase 1 — 知识对象结构化 + 检索集成（Week 2, 4-5 天）

### 目标

KO 承载结构化标签引用，检索可按 tag 过滤。**这是 STS 第一个用户可感知的交付物。**

### 任务

| # | 任务 | 文件 | 工期 | 验收 |
|---|------|------|------|------|
| **1.1** | `KnowledgeObject` 增加 `tags: list[TagReference]` 字段（`tag_id, namespace, value, confidence`） | `knowledge/core/object.py` | 1d | KO 序列化含结构化 tag 引用，`from_dict` 向后兼容 |
| **1.2** | 关系索引接入摄取末段（`write_outgoing` + `write_backlinks` + `remove_source_from_index`） | `pipeline/ingest.py`, `wiki/features/relation_index.py` | 1d | 摄取完成后 `.index/relations/outgoing/{id}.json` 有内容 |
| **1.3** | 检索加 `taxonomy_filters`：在 `HybridSearch` 上加 tag 过滤（AND/OR，支持 `namespace:value` 语法） | `searcher/hybrid_search.py`, `server/routes/search.py` | 2d | `GET /search?q=xxx&tags=题材:仙侠,情绪:热血` 返回过滤结果 |
| **1.4** | `degradation_counter` + 阈值暂停：`advance()` 检查连续 stub 次数，≥5 时自动 pause + log warning | `queue/service.py` | 0.5d | 连续 5 次 stub 后队列自动暂停，`.kb-queue-paused` 生成 |

### 任务详解

#### 1.1 KO.tags ↔ WikiPage.tags 关系

- **KO** 是内存中间态（Collector→Analyzer→...→Writer），加 `tags: list[TagReference]` 是纯数据结构变更，不依赖持久化关系确认。可直接启动。
- **序列化方向：** Writer 将 `KO.tags` 序列化为 `WikiPage.tags: list[str]`（`namespace:value` 格式，人类可读）
- **反序列化方向：** 读取 WikiPage 时 `WikiPage.tags: list[str]` → 检索/图构建时解析为 `TagReference`
- P1.3 启动前确认此序列化路径；P1.1 本身不依赖此确认。

#### 1.2 关系索引原子性

前置检查（P1.2 启动前）：读 `relation_index.py` 源码，确认 `write_outgoing`/`write_backlinks` 是否使用 `safe_write`。如果在独立 `safe_write` 中，改为纳入 `write_page` 的 `AtomicContext`。

### 依赖

- Phase 0 全部完成（管线可用，标签已接线）

### 风险

- 1.3 检索 tag 过滤与 LanceDB 查询的集成复杂度 → 先用 post-filter（LanceDB 搜完再按 tag 过滤），后续优化为 pre-filter

### 回滚

- KO.tags 字段可留空（`[]`），不影响现有 pipeline 行为
- 关系索引损坏时 `rebuild_index` 全量重建

---

## Phase 2 — 分类自生长 + 治理（Week 3-4, 7-10 天）

### 目标

新概念自动发现 → 相似度检查 → 人工审核 → 入库。标签体系从"人工维护"进入"AI 辅助演化"。

### 任务

| # | 任务 | 文件 | 工期 | 验收 |
|---|------|------|------|------|
| **2.1** | Tag store 模块：`tag_entities/{tag_id}.json` 独立 JSON 文件（原子覆盖写入），JSONL 仅作审计日志 | `knowledge/storage/tag_store.py`（新建） | 3d | tag 实体 CRUD 完整；并发写入用 `threading.Lock` 保护 |
| **2.2a** | 标注 ground truth：从 1358 文档选 20 篇（每题材 ≥2 篇，含长短文档），由有网文写作经验的人标注应产出的概念 | 人工 | 1-2d | 20 篇 ground truth 标注完成 |
| **2.2b** | LLM 分类质量基准测试：跑标注好的 20 篇，统计精确率/召回率/粒度一致性 | 测试脚本 | 0.5d | 精确率 ≥0.7，粒度一致性 ≥0.6 才能启动 2.3 |
| **2.3** | TaxonomySync：摄取末段挂载，LLM 提取新概念 → `KnowledgeCandidate` → 适配后的 `ReviewerStage` → `CandidatePromoter` | `pipeline/taxonomy_sync.py`（新建），`pipeline/ingest.py` | 3d | 摄取一篇新领域文档后，新概念出现在 `tag_candidates` 中 |
| **2.4** | 相似度两档阈值 + 审核 API：≥0.95 同 namespace 自动 alias；0.85-0.95 进人工审核队列；<0.85 不自动关联。审核者：管理员（默认）或指定领域专家，48h SLA | `knowledge/conflicts/detector.py`, `server/routes/taxonomy.py`（新建） | 2d | 审核 API 支持 `approve`/`reject`/`merge`；超时未审核自动 reject（candidate 可复活） |
| **2.5** | `tag_policy.yaml` 规则引擎：替代 `MANDATORY_PAIRS` 硬编码，支持 `required_if`/`forbidden_with`/`suggest_when` 三种规则 | `tag_namespace.py`, `tag_policy.yaml` | 1d | 改 yaml 无需改代码即可变更分类规则 |

### 任务详解

#### 2.1 Tag store 存储格式

- **真相源：** `tag_entities/{tag_id}.json` — 独立 JSON 文件，更新时 `safe_write` 原子覆盖
- **`tag_id` 格式：** `{namespace}_{value}` 规范化 slug（人类可读，非 hash）
- **审计日志：** `tag_events.jsonl` — append-only，记录所有变更事件（创建/更新/合并/废弃）
- **并发安全：** 写入操作使用 `threading.Lock`；tag candidate 创建前做 `concept_name + namespace` hash idempotency 检查
- **PG 可选：** 当 `storage.backend=postgresql` 时启用 PG 后端（代码已预留钩子）

#### 2.2 标注降级方案

如果找不到标注人（网文写作领域知识）：
- 改为"人工复查 LLM 产出"——只判断产出是否合理（二分类），不统计召回率
- 质量门禁降级为"LLM 产出 ≥70% 被人工接受"
- 标注等待期间不阻塞 2.1 和 2.4 开发

#### 2.3 ReviewerStage 适配

TagCandidate schema 定义后，逐项对照 ReviewerStage 四个检查：
- `_check_schema`: 需适配（tag candidate schema 不同）
- `_check_evidence`: 需适配（claims 结构差异）
- `_check_references`: 需适配（evidence 语义不同——"引用该 tag 的文档"而非"支持 claim 的 evidence 片段"）
- `_check_confidence`: 可直接复用

如有 ≥2 个检查需重写，写独立 `TaxonomyReviewer`。

#### 2.4 审核者 SLA

- 审核者角色：管理员（默认），可委派给领域专家
- SLA：48h 内审核
- 超时策略：自动 reject 但保留 candidate（标记 `timeout_rejected`，可复活）
- 队列深度告警：积压 >20 个时 log warning

### 依赖

- Phase 1 全部完成（KO 有 tags 字段，检索可消费）
- 2.3 依赖 2.2 质量基准通过

### 风险

| 风险 | 缓解 |
|------|------|
| LLM 新概念幻觉率高 | 2.2 质量门禁不通过则降级为"仅人工创建"，不自生长 |
| 相似度误合并污染分类 | alias 存储为可逆边，提供 `/unmerge` API；所有自动 alias 标记 `confidence` 字段 |
| 2.3 工期超 | 砍 2.5 规则引擎到 Phase 3，核心价值在 2.3+2.4 |
| 标注人找不到 | 降级为人工复查二分类（见 2.2 降级方案） |
| 并发 TaxonomySync → tag store 竞态 | `threading.Lock` + tag candidate idempotency hash |

### 回滚

- Tag store 损坏 → 从 `tag_events.jsonl` 审计日志重建
- 自动 alias 误操作 → `/unmerge` API + undo 日志
- 规则引擎 yaml 错误 → 启动时 schema 校验 + 上次有效配置备份

---

## Phase 3 — 四图整合（Week 5+, 3-4 天，Gate 触发）

### 前置 Gate

必须同时满足：
- Phase 2 自生长审核操作 ≥50 次，alias 误合并率 <5%
- 分类体系中有 ≥50 个 approved tag_entities

**降级出口：** 若 4 周内未达 Gate 条件 → 人工决策是否接受部分图整合（仅用已 approved tag 构建子图）。若 P2.2 质量门禁未通过（已退化为人工分类模式）→ Phase 3 整体推迟，待人工分类积累 ≥30 个 tag_entities 后再评估。

### 任务

| # | 任务 | 文件 | 工期 | 验收 |
|---|------|------|------|------|
| **3.1** | `GraphBuilder` 扩展：`NodeType.TAXONOMY` + `EdgeType.PARENT_OF/SAME_AS/ALIAS_OF/CONFLICTS_WITH` | `knowledge/graph/builder.py` | 1d | 分类图可从 tag store 构建 |
| **3.2** | 检索 Graph Expansion：沿 `tag_relations` 图扩展查询（搜"仙侠"自动包含 `parent_of` → 修真/玄幻） | `searcher/hybrid_search.py` | 1.5d | 检索结果含图扩展的关联文档 |
| **3.3** | Memory/Evidence/Knowledge 三图现状盘点 + 与 Taxonomy 图的交叉边定义 | 盘点文档 | 1d | 四图 schema 文档定稿 |
| **3.4** | 统一 GraphQL 入口（可选，视前端需求） | `server/routes/graph.py` | 0.5d | `GET /graph?node=xxx&depth=2` 返回子图 |

### 依赖

- Gate 条件全部满足

---

## 风险矩阵（全局）

| # | 风险 | 阶段 | 概率 | 影响 | 缓解 |
|---|------|------|------|------|------|
| R1 | Phase 0.2 批量重摄取 LLM API 限流 | P0 | 中 | 中 | 并发降至 2，间隔 3s |
| R2 | LLM 分类质量不达标（2.2 gate 不过） | P2 | 中 | 高 | 退化为人工分类模式，不自生长 |
| R3 | 相似度自动合并污染分类体系 | P2 | 高 | 高 | 可逆 alias + 人工兜底 + 保守阈值 |
| R4 | Phase 2 工期超 | P2 | 中 | 中 | 砍 2.5 规则引擎到 P3，P3 本身可延期 |
| R5 | P0 修复后管线仍有残余 bug | P0 | 低 | 高 | 0.5 全量 pytest 回归 + 10 文档验证 |
| R6 | LLM provider 单点故障（minimax 唯一在线） | P0-P2 | 中 | 高 | P2 启动前配置 provider fallback；P0-P1 接受风险（stub 降级兜底） |
| R7 | Tag store 并发写入竞态 | P2 | 中 | 中 | `threading.Lock` + candidate idempotency hash |

---

## 与既有文档的关系

| 文档 | 关系 |
|------|------|
| `docs/evaluations/semantic-taxonomy-feasibility.md` | **本计划的上游评估**，T0-T4 内容已整合进 P0-P3 |
| `docs/evaluations/audit-2026-08-03-semantic-taxonomy-plan.md` | **本计划的独立审计 (v3)**，1致命/10重大/10优化已在此 v2 修复 |
| `docs/superpowers/plans/2026-08-02-ingest-pipeline-completion.md` | **前序依赖**：KO 结构化部分与该方案汇合，建议先完成该方案 Phase 0+1 |
| `docs/ARCHITECTURE.md` | 架构背景参考 |
| `docs/TECH_DEBT_CHECKLIST.md` | 优先级参考；#10/#15 已完成 |
| `out/plans/round_*.md` (10 篇) | **本计划的实证基础**，reviewer bug + stub 降级 + 队列并发等发现 |
