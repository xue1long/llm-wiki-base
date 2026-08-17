# Knowledge OS Evolution Plan — Second Audit (v1.1)

**审计日期:** 2026-08-02
**审计对象:** `docs/superpowers/plans/2026-08-02-knowledge-os-evolution.md` v1.1
**审计范围:** v1.0→v1.1 修正后残留 + 新增缺陷

---

## 一、新发现的致命缺陷

### F5: KnowledgeType 缺少 `synthesis` 值

**位置:** §1.2 行119 vs Decision 0.1 行37
**矛盾:** §1.2 注释写 `document|entity|concept|claim|decision|procedure|event` (7值)。Decision 0.1 映射表包含 `synthesis → synthesis → wiki/synthesis/` (8行)。synthesis 是现有 PageType 且保持使用。
**后果:** 实现 KnowledgeType 枚举时会遗漏 synthesis，导致现有 synthesis 类型页面无法转换为 KnowledgeObject。Adapter 往返对 synthesis 页面直接崩溃。
**建议:** KnowledgeType 补上 `synthesis`，共 8 值。

### F6: LifecycleState 枚举缺少 FAILED 和 REJECTED

**位置:** §1.5 行164-169 vs §1.2 行134
**矛盾:** §1.2 定义 LifecycleState 为 "6-state: CREATED, PROCESSING, REVIEWING, ACTIVE, DEPRECATED, ARCHIVED"。§1.5 状态转换图包含 `PROCESSING → FAILED` 和 `REVIEWING → REJECTED`。FAILED 和 REJECTED 不在 6-state 枚举中。
**后果:** 实现 LifecycleEngine.transition() 时，PROCESSING→FAILED 和 REVIEWING→REJECTED 无处可转。要么扩充枚举为 8-state，要么删除这两条边。
**建议:** 扩充 LifecycleState 为 8-state: 增加 FAILED 和 REJECTED。两者均为终态（不可再转换）或 FAILED 可转回 PROCESSING（重试）。

### F7: TaskStatus (队列) 和 LifecycleState (知识) 两套状态机无关联

**位置:** 全 Phase 未涉及
**缺失:** 现有队列状态机 `TaskStatus`: PENDING→RUNNING→WAITING_REVIEW→APPROVED/REJECTED→ARCHIVED。新知识生命周期 `LifecycleState`: CREATED→PROCESSING→REVIEWING→ACTIVE→DEPRECATED→ARCHIVED。两套状态机在同一个 ingest pipeline 中并行运转，但方案从未定义它们的映射关系。例如：TaskStatus 的 WAITING_REVIEW 对应 LifecycleState 的哪个状态？Task APPROVED 时 Lifecycle 是什么？
**后果:** Pipeline 代码中两套状态同时更新，无映射规则 = 必然出现状态不一致（如 Task=APPROVED 但 Lifecycle=PROCESSING）。
**建议:** 定义明确的映射表：
```
TaskStatus        LifecycleState
PENDING           (尚未创建 KnowledgeObject)
RUNNING           PROCESSING
WAITING_REVIEW    REVIEWING
APPROVED          ACTIVE
REJECTED          REJECTED (新增)
FAILED            FAILED (新增)
ARCHIVED          ARCHIVED
```

### F8: MCP 工具名与代码库不匹配

**位置:** §3.3 行413 vs 实际代码 `src/mcp_server/main.py`
**实际:** 当前 MCP 工具名为 `ruflo_kb_search`, `ruflo_kb_read_file`, `ruflo_kb_ingest` 等 (8 个 ruflo_kb_* 前缀工具)。方案写成 `wiki.search`, `wiki.read_page`。
**后果:** 实现者看到 "mark wiki.search deprecated" 但在代码库中找不到 wiki.search → 困惑或标注了错误的工具。
**建议:** 方案中使用实际工具名。新增 memory.* 工具也加统一前缀（如 `ruflo_kb_memory_search`）或全部重命名。明确写出 deprecated 列表。

---

## 二、新发现的重大隐患

### M10: Candidate→KnowledgeObject 晋升流程未定义

**位置:** Phase 1→Phase 2 过渡
**缺失:** CandidateStatus 有 PROMOTED 状态。KnowledgeObject 有 ACTIVE 生命周期。Candidate PROMOTED 后：(a) 谁创建 KnowledgeObject？(b) Candidate 和 KnowledgeObject 的 ID 是同一个还是两个？(c) PROMOTED Candidate 被修改后，对应 KnowledgeObject 是否同步更新？
**后果:** 实现时发现从 Candidate 到 KnowledgeObject 的转化链路是断的——Reviewer APPROVED 之后、Indexer 之前，缺少 "CandidatePromoter" 步骤。
**建议:** Phase 1 Task 1.9 (ReviewerAgent) 之后增加 Task 1.10: `CandidatePromoter` — 将 VALIDATED Candidate 转化为 KnowledgeObject (lifecycle=PROCESSING)，Candidate 状态变为 PROMOTED，二者共享同一 ID。

### M11: commit_ingest 接口需从 Candidate 构建 frontmatter

**位置:** §1.8 行212
**缺失:** §1.8 说 "frontmatter 由 commit_ingest 从 Candidate 构建"。当前 `commit_ingest()` 接收 `list[WikiPage]`，每个 WikiPage 自带完整 frontmatter。改为从 Candidate 构建意味着 commit_ingest 签名变为 `commit_ingest(pages, candidates)` 或 WikiPage 在进 commit_ingest 之前已由 Generator 设置了 frontmatter。
**后果:** commit_ingest 的接口变更未被方案追踪。如果 Generator 设置 frontmatter (与 §1.8 "markdown body only" 矛盾)，如果 commit_ingest 构建 (需改签名)。
**建议:** 明确: Generator 输出 WikiPage (含 body + frontmatter)，frontmatter 字段从 Candidate 复制。GeneratorOutputValidator 验证 Generator 未自创字段。commit_ingest 接口不变。

### M12: opaque dict 中 evidence 与 claim 的关联方式未定义

**位置:** §1.6 行184-186 vs §2.2 行290
**缺失:** `KnowledgeCandidate` 有两个独立字段: `claims: list[dict]` 和 `evidence: list[dict]`。它们是两个平行列表。ClaimParser 如何知道 evidence[2] 属于 claims[0] 还是 claims[1]？两种可能：(a) 每个 claim dict 内部有 `evidence_refs: [0, 2]` (按索引引用 evidence 列表)，(b) evidence dict 有 `claim_index: 0`。方案都没说。
**后果:** ClaimParser 无法正确关联 evidence→claim，所有 Claim 的 evidence 列表为空或全量。
**建议:** 定义 claim dict schema: `{"statement": "...", "confidence": 0.9, "evidence_refs": [0]}`，其中 evidence_refs 是 `candidate.evidence` 列表的索引。

### M13: 知识图谱的删除事件未定义

**位置:** §2.6 行336
**缺失:** 事件格式只定义了 `"action": "upsert_node"`。当对象被归档/删除时，图谱需要移除节点。JSONL append-only 模型中没有 `"action": "delete_node"` 和 `"action": "delete_edge"`。
**后果:** 图谱只增不减，归档的对象永远残留在图中，查询返回过时节点。
**建议:** 增加 `delete_node` 和 `delete_edge` 事件类型。查询重放时 upsert 创建、delete 移除。

### M14: Snapshot 重建调度器无归属

**位置:** §2.6 行334, §2.7 行348
**缺失:** 方案说 "每 100 次 ingest 或每天一次全量重建" 和 "触发 snapshot 重建检查"。但谁负责？Indexer (Phase 2) 做检查，但 Curator 的 cron (Phase 4) 可能触发重建。Phase 2-3 没有 cron 基础设施。
**后果:** Phase 2 部署后 snapshot 永远不会被重建，events.jsonl 无限增长，查询性能退化到每次加载全量事件。
**建议:** Phase 2 Indexer 内嵌简单的计数触发器 (ingest_count % 100 == 0 → 同步重建 snapshot)。这是确定性逻辑，不需要 cron。Phase 4 的每天重建可以和 Curator 共用调度。

### M15: Heat→Lifecycle 桥接代码归属不明

**位置:** §4.2 行494-497
**缺失:** "Heat=0 + zombie → lifecycle → DEPRECATED"。现有 `src/wiki/features/heat.py` 管理热度数值，但不触发 lifecycle transition。谁在监测 heat 变化并调用 `LifecycleEngine.transition()`？方案没说这段桥接代码放在哪。
**后果:** Heat 降到 0 后对象保持原 Lifecycle 状态。DEPRECATED 转换永远不会被触发。知识衰减功能形同虚设。
**建议:** 在 `src/wiki/features/heat.py` 的 `decay_all()` 或 `update_heat()` 末尾增加回调: 当 heat=0 时调用 `LifecycleEngine.transition(obj, DEPRECATED, "heat decayed to zero")`。

### M16: Curator/Evolution 的 cron 机制不存在

**位置:** §4.1 行487, §4.3 行507
**缺失:** 方案要求 Curator "每天一次 (cron)"。当前系统没有 cron 基础设施。Queue 有 scheduler 但用于任务调度（选下一个 PENDING 任务），非周期性触发。需要新增定时触发机制。
**后果:** Curator 永远不会自动运行，除非手动 CLI。自改进循环停留在纸面。
**建议:** Phase 4 新增简单的定时触发器: `src/knowledge/evolution/scheduler.py` — 复用现有 queue infrastructure 或简单的 `asyncio.create_task` + `asyncio.sleep` 循环（在 FastAPI lifespan 中启动）。记录上次运行时间到 `.index/curator_last_run.json`，避免重复运行。

### M17: LifecycleEngine 日志与 Historian 日志重复

**位置:** §1.5 行171 vs §4.5 行530
**重复:** §1.5 说 LifecycleEngine 记录 "LifecycleEvent 到 wiki/log.md"。§4.5 说 HistorianAgent 记录 "结构化变更记录" 含 timestamp/agent/object_id/change_type/before/after/reason。两个组件都在记录变更。LifecycleEngine 在 Phase 1 就开始写 log.md，Historian 在 Phase 4 又写一份。这是两套日志还是同一套？
**后果:** 同一变更被记录两次（Phase 1 lifecycle log + Phase 4 historian record），或 Historian 需要回填 Phase 1-3 的缺失记录。
**建议:** LifecycleEngine 不直接写 log.md。它 emit 一个 `LifecycleEvent` 到 EventBus。log.md 的写入由现有的 pipeline logger 处理。Phase 4 Historian 订阅同一个 EventBus 事件，写入结构化变更日志。一事件、多消费者。

---

## 三、信息缺失与歧义

### I11: ReviewerAgent 是规则引擎还是 LLM Agent？

**位置:** §1.9 行218-227
**歧义:** 检查 1-3 是纯规则检查（字段存在、文件存在），不需要 LLM。检查 4（置信度阈值）也不需要 LLM。那 ReviewerAgent 为什么放在 `src/agent/` 下？为什么需要 `candidate.approve` 权限？如果 Reviewer 是纯规则引擎，它应该放在 `src/pipeline/stages/reviewer.py`，不需要 LLM 调用、不需要 Agent 框架。
**后果:** 实现者可能过度设计（用 LLM Agent 做规则检查）或错误放置（放在 agent/ 但被 pipeline 直接调用）。
**建议:** 明确: Phase 1 Reviewer 是 **规则引擎** (pipeline stage)，不是 LLM Agent。Phase 4 可选升级为 LLM-assisted Reviewer (真正检测语义矛盾)。命名: `ReviewerStage` → `src/pipeline/stages/reviewer.py`。

### I12: KnowledgeObject.content 字段语义

**位置:** §1.2 行121
**缺失:** `content: str` — 这是 Markdown？纯文本？WikiPage 有 `body: str` (markdown body)。KnowledgeObject 的 content 和 WikiPage 的 body 是什么关系？如果 content=body，为什么不直接叫 body？
**后果:** Adapter 实现时不知道 `wiki_page.body` 映射到 `knowledge_object.content` 还是另有逻辑。
**建议:** 明确: `KnowledgeObject.content` 等价于 `WikiPage.body`，存储 Markdown。命名差异是因为 KnowledgeObject 不仅来自 WikiPage（也可来自 API/MCP 直接创建），"content" 比 "body" 更通用。

### I13: `researcher.allowed_domains: []` 语义

**位置:** §5 行586
**歧义:** 空列表 `[]` 是 "allow all domains" 还是 "allow no domains (block all web search)"？安全角度看应该是 "block all" (白名单为空=禁止所有)。但默认值 `[]` 会使 Researcher 的 web search 功能默认不可用。
**后果:** 用户开启 Researcher 后 web search 静默失败（所有域名被过滤），误以为是 bug。
**建议:** 默认值改为 `["*"]` = allow all，或文档明确标注 `[]` = block all, 需手动配置。

### I14: Decision memory 的额外字段存储位置

**位置:** §3.1 行390
**缺失:** "Decision memory 额外字段: context, alternatives, rationale, outcome" — 这些存在 WikiPage frontmatter 的哪里？`_ko_extra.decision` 子键？顶层 frontmatter 字段？Markdown body 中？
**后果:** DecisionRecorder 和 MemoryRetrieval 对同一字段的读写路径不一致。
**建议:** 存在 `_ko_extra.memory.decision` 下（嵌套 YAML）。MemoryRetrieval 读取时从 `_ko_extra.memory.decision` 解析。

### I15: Analyzer Phase 1→Phase 2 prompt 变化未描述

**位置:** §2.3 行299
**缺失:** §2.3 说 "新增 claim extraction prompt"。但 Phase 1 Analyzer 已经输出 claims (opaque dict)。Phase 2 的 prompt 变化是什么？是让 LLM 在 claim dict 中增加字段 (type, evidence_refs) 还是保持 prompt 不变、靠 ClaimParser 后处理？
**后果:** 如果 Phase 2 改 prompt，所有依赖 Phase 1 prompt 的测试需要更新。如果不改 prompt，ClaimParser 需要从有限字段推断 claim type。
**建议:** 明确: Phase 2 不改 Analyzer prompt。ClaimParser 从 Phase 1 的 opaque dict 推断 claim type (默认 "fact") 并关联 evidence (按 evidence_refs 索引或全量关联)。

### I16: 成本模型仅覆盖 gpt-4o-mini

**位置:** Decision 0.4 行73-83
**缺失:** 成本估算基于 gpt-4o-mini (~$0.15/M input token)。当前系统支持 OpenAI/Anthropic/Ollama。若用 Anthropic Claude Opus (~$15/M input token)，成本是 100 倍。若用 Ollama 本地模型，成本趋近于 0 但质量不可控。
**后果:** 用户用 Claude Opus 开启全部 Phase 4 功能后收到 $450/月账单而非 $4.50/月。
**建议:** 增加多 provider 成本对照表:
| Provider | Analyzer | Reviewer | Generator | Curator/月 |
|----------|---------|----------|-----------|-----------|
| gpt-4o-mini | $0.0006 | $0.0004 | $0.0005 | ~$3 |
| claude-sonnet-4-6 | ~$0.006 | ~$0.004 | ~$0.005 | ~$30 |
| claude-opus-4-7 | ~$0.03 | ~$0.02 | ~$0.025 | ~$150 |

### I17: Analyzer schema check 缺少具体默认值

**位置:** §1.7 行201
**缺失:** "缺失→填充默认值"。source_id 的默认值是什么？空字符串？type 的默认值？"concept"？
**后果:** 填充了无意义的默认值后，Candidate 进入 Reviewer/Generator，下游代码基于空 source_id 运行 → 无法追溯来源。
**建议:** source_id 缺失 → 不填充默认值，标记 Candidate 为 REJECTED (source_id 是必填字段，不可默认)。type 缺失 → 默认 "concept" 并标记 confidence *= 0.3。title 缺失 → 从 source_id 或 claims[0].statement 截取前 80 字符。

---

## 四、三级问题汇总 (v1.1 新增)

### 🔴 致命缺陷

| # | 问题 | 位置 |
|---|------|------|
| F5 | KnowledgeType 遗漏 synthesis → Adapter 对现有 synthesis 页面崩溃 | §1.2 |
| F6 | LifecycleState 缺少 FAILED/REJECTED → transition() 目标状态不存在 | §1.5 vs §1.2 |
| F7 | TaskStatus 与 LifecycleState 两套状态机零映射 → 必然状态不一致 | 全局 |
| F8 | MCP 工具名称与代码库不匹配 (wiki.search vs ruflo_kb_search) | §3.3 |

### 🟡 重大隐患

| # | 问题 | 位置 |
|---|------|------|
| M10 | Candidate→KnowledgeObject 晋升流程缺失 → 转化链路断裂 | Phase 1→2 |
| M11 | commit_ingest 从 Candidate 构建 frontmatter 的接口变更未追踪 | §1.8 |
| M12 | evidence 列表与 claims 列表无关联方式 → ClaimParser 无法正确关联 | §1.6/§2.2 |
| M13 | 知识图谱无删除事件 → 归档对象残留在图中 | §2.6 |
| M14 | Snapshot 重建调度器无归属 → Phase 2-3 events.jsonl 无限增长 | §2.6/§2.7 |
| M15 | Heat→Lifecycle 桥接代码归属不明 → 知识衰减不会触发 | §4.2 |
| M16 | Curator/Evolution 的 cron 机制不存在 → 自动运行永远不会发生 | §4.1/§4.3 |
| M17 | LifecycleEngine 日志与 Historian 日志功能重复 | §1.5/§4.5 |

### 🟢 优化疏漏

| # | 问题 | 位置 |
|---|------|------|
| O11 | ReviewerAgent 应为规则引擎而非 LLM Agent (Phase 1) | §1.9 |
| O12 | KnowledgeObject.content 语义不明 | §1.2 |
| O13 | `researcher.allowed_domains: []` 语义歧义 | §5 |
| O14 | Decision memory 额外字段存储位置未定义 | §3.1 |
| O15 | Analyzer Phase 1→2 prompt 变化未描述 | §2.3 |
| O16 | 成本模型仅覆盖 gpt-4o-mini，缺 Anthropic/Ollama 对照 | §0.4 |
| O17 | Analyzer schema check 默认值未指定 (source_id 不可默认) | §1.7 |

---

## 五、整改优先级

**在开始编码前必须解决 (第二轮修复):**

1. **F5-F8 四个致命缺陷** — 逐个修改方案文档
2. **M10 (Candidate→KnowledgeObject 晋升)** — Phase 1 新增 Task 1.10 CandidatePromoter
3. **M11 (commit_ingest 接口)** — 明确 Generator 负责完整 WikiPage 构建
4. **M12 (evidence-claim 关联)** — 定义 claim dict schema
5. **M13 (图谱删除事件)** — 扩展事件格式
6. **M17 (日志重复)** — LifecycleEngine 改为 emit event 而非直接写 log.md

**可在各 Phase 实现时解决:**

7. **M14-M16** — 在对应 Phase 的实现 task 中补充具体方案
8. **I11-I17** — 在对应模块的详细设计文档中明确 (不需要阻塞整体方案)
