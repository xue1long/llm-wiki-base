# 摄取流程完善方案（Ingest Pipeline Completion Plan）

> Version: v1.1 | 2026-08-02
> Status: **决策已锁定，暂不开工**（待启动指令后从 Phase 0 Task 0.1 开始，按 TDD 逐 Task 提交）
> 关联文档：`docs/superpowers/plans/2026-08-02-knowledge-os-evolution.md` (v1.3)、`docs/ARCHITECTURE.md`、`docs/evaluations/tag-namespace-evaluation.md`
>
> v1.1 变更：3 个关键决策点按推荐方案锁定（见 Task 1.2「已锁定决策」）；CollectorAgent 缓办；Task 1.4 / 2.4 / 风险表同步更新。

---

## 〇、现状盘点 — 本方案的出发点

### 0.1 两条路径并存的真实状态

代码库当前存在**两条摄取路径**：

```
【路径 A — 旧路径（生产运行中）】
collector:start → CollectorStage → run_ingest()
    ├── analyze()          (markdown 模式, AnalysisResult)
    ├── generate()         (两步法) 或 unified_generate() (单步法)
    ├── QualityGate (3 条规则)
    ├── QualityJudge (默认关闭)
    └── Atomic Write → wiki/*.md + index.md + log.md + LanceDB

【路径 B — 新路径（代码就绪，未接线）】
已实现但生产流量不经过：
    analyzer.py: output_format="json" → KnowledgeCandidate  ✅ 代码存在
    stages/reviewer.py: ReviewerStage (4 项规则检查)          ✅ 代码存在
    stages/candidate_promoter.py: Candidate → KnowledgeObject ✅ 代码存在
    generator_constraint.py: GeneratorOutputValidator         ✅ 代码存在
    knowledge/core/*: Object/Lifecycle/VersionManager/Adapter ✅ 代码存在
```

**关键事实**：
- `PipelineService._stages = [CollectorStage(), AnalyzerStage(), GeneratorStage()]`（`src/pipeline/service.py:52`）——ReviewerStage 和 CandidatePromoter **不在**默认 stage 列表
- `_run_for_collector_start_inner()` 只执行 `self._stages[:1]`（Collector）+ 旧 `run_ingest()`
- `analyze()` 的 `output_format` 参数默认 `"markdown"`，**无人传 `"json"`**
- 新组件是"孤岛"：有代码、有测试，但生产路径零调用

### 0.2 KOS Phase 1 任务完成度

| Task | 内容 | 状态 |
|------|------|------|
| 1.0 | PageType 扩展（8 值 + `_TYPE_TO_DIR`） | ✅ 已完成 |
| 1.1 | `src/knowledge/` 包骨架 | ✅ 已完成 |
| 1.2 | KnowledgeObject + KnowledgeType + Provenance | ✅ 已完成 |
| 1.3 | WikiPage ↔ KnowledgeObject Adapter | ✅ 已完成 |
| 1.4 | VersionManager | ✅ 已完成 |
| 1.5 | LifecycleEngine（8 状态） | ✅ 已完成 |
| 1.6 | KnowledgeCandidate | ✅ 已完成 |
| 1.7 | Analyzer JSON 输出（三层验证） | ✅ 已完成 |
| 1.8 | GeneratorOutputValidator | ✅ 已完成 |
| 1.9 | ReviewerStage（规则引擎） | ✅ 已完成 |
| 1.10 | CandidatePromoter | ✅ 已完成 |
| 1.11 | CollectorAgent | ❌ 未开始 |
| 1.12 | KnowledgeKernel 组装 | ❌ 未开始 |
| — | **新路径接入生产流水线** | ❌ **未开始（本方案核心）** |

### 0.3 摄取流程的 9 个独立问题（与 KOS 演进正交）

| # | 严重级 | 问题 | 位置 |
|---|--------|------|------|
| P1 | 🔴 | 大文档截断：`MAX_SOURCE_CHARS = 8000`，超长文档仅处理前 8000 字符，只在 source page body 里加警告 | `generator.py:48,459-462` |
| P2 | 🔴 | unified_generate 单步路径绕过全部分层：Analyzer+Generator 合并为一次 LLM 调用，直接产出最终 WikiPage，无 Candidate、无 Reviewer、无三层验证 | `generator.py:440-642` |
| P3 | 🟡 | 文件夹摄取未接线：路由接受 `{"source": {"folder": ...}}` 但不枚举目录 | `server/routes/ingest.py` |
| P4 | 🟡 | QualityJudge 默认关闭（`QualitySettings.enabled=False`），LLM-as-judge 层形同虚设 | `quality/judge.py` |
| P5 | 🟡 | 标签**值域约束写入强制覆盖不全**：`TAG_VALUES` 已存在，`page_writer.py:74` 对**新建页面**调用 `validate_tag_compliance`（含 `validate_tag_values` + 强制配对），越界值/缺配对会被拒绝；但**更新既有页面时跳过**（`path.exists()`），且 Generator 内部 `_resolve_page_tags` 只按前缀静默过滤、不做值域校验；自由前缀（角色/事件/实体）仍任意取值。配对 `MANDATORY_PAIRS` 已配置化（素材/ugc+可信度/ugc，经 `build_tag_prompt_section` 驱动），仅前缀说明文案在提示词重复（技术债务 #11） | `tag_namespace.py` / `page_writer.py:74` |
| P6 | 🟡 | 溯源仅文件级：`sources: list[str]` 无页码/段落/引用 | `wiki/core/types.py` |
| P7 | 🟡 | `find_duplicates()` 是空实现 MVP，返回空列表 | `wiki/features/dedup.py` |
| P8 | 🔴 | Schema 迁移 v2.1/v2.2 未注册：`migrations/__init__.py` 只导入 v1_to_v2，现存项目无法升级 schema | `schemas/migrations/__init__.py` |
| P9 | 🟡 | 权限白名单不完整：PROCESSOR/LIBRARIAN/SEARCHER 在白名单中无条目 | `permissions.py:42-51` |

---

## 一、目标流程

完善后的摄取流水线（本方案落地后的生产路径）：

```
HTTP/MCP/CLI 摄取请求
    │
    ▼
enqueue_source() ── 幂等哈希, 入队
    │
    ▼ EventBus "collector:start"
CollectorStage
    │  文件/URL 读取 + SSRF 防护 + 权限检查
    │  【新增】大文档检测 → 分块策略 (Phase 2)
    ▼
Sanitizer (规则质量门 1)
    ▼
AnalyzerStage ── output_format="json"
    │  LLM → JSON → 三层验证 (syntax/schema/content)
    ▼
KnowledgeCandidate (status=PENDING)
    ▼
ReviewerStage (规则引擎, 4 项检查)
    │  VALIDATED ──────────────┐
    │  NEEDS_HUMAN_REVIEW ──→ 评审队列 (reviews.json)
    │  REJECTED ────────────→ 记录 + 任务标记
    ▼
CandidatePromoter
    │  VALIDATED Candidate → KnowledgeObject (lifecycle=PROCESSING)
    ▼
GeneratorStage (只渲染)
    │  LLM 渲染 body + frontmatter 从 KO 复制
    │  GeneratorOutputValidator 拒绝自创字段
    ▼
QualityGate (3 规则) + QualityJudge (可选 LLM)
    ▼
commit_ingest() (原子写入)
    │  wiki/*.md + index.md + log.md + LanceDB upsert
    │  VersionManager.snapshot() (变更前快照)
    │  lifecycle → ACTIVE
    ▼
TaskStatus.APPROVED
```

设计约束（与原 KOS 方案一致）：
1. **LLM 不直接写最终知识** — 必须经过 Candidate → Reviewer → Promoter
2. **Generator 只渲染** — 不推断、不修改事实、不自创字段
3. **迁移不重写** — 旧路径保留至新路径验证稳定

---

## 二、实施阶段

### Phase 0 — 基础修复（阻断项，1-2 天）

这些问题不修复，后续 Phase 会在坏地基上施工。

#### Task 0.1 修复 Schema 迁移注册

**文件**: `src/schemas/migrations/__init__.py`

现状：仅 `from . import v1_to_v2`。`v2_to_v2_1.py` 和 `v2_to_v2_2.py` 文件底部有注册代码但从未被导入执行。

修改：
```python
from . import v1_to_v2    # noqa: F401
from . import v2_to_v2_1  # noqa: F401
from . import v2_to_v2_2  # noqa: F401
```

**验证**:
- `python -m src.cli schema list` 显示 v2.0→v2.1、v2.0→v2.2 两条路径
- 新增测试：`tests/test_schemas/test_migration_registration.py` — 断言 `get_migration("wiki", V2_0, V2_1)` 不返回 None
- 在测试项目副本上跑 `schema upgrade` dry-run，确认 preview 无异常

#### Task 0.2 补全权限白名单

**文件**: `src/permissions.py`

现状：`ALLOWED_PATHS` 只有 COLLECTOR 有条目，PROCESSOR/LIBRARIAN/SEARCHER 无白名单。

修改：为三个 AgentType 补充最小必要权限（按各 Agent 的实际读写路径梳理，宁可先宽松加 warn 日志，不可一刀切拒绝）：
```python
AgentType.PROCESSOR: {
    Permission.READ: ["raw/sources", "wiki"],
    Permission.WRITE: ["wiki", ".index"],
},
AgentType.LIBRARIAN: {
    Permission.READ: ["wiki"],
    Permission.WRITE: ["wiki", ".index"],
},
AgentType.SEARCHER: {
    Permission.READ: ["wiki", ".index"],
},
```

**验证**:
- 现有 873 测试全通过（权限变更可能破坏依赖宽松访问的测试）
- 新增测试覆盖每个 AgentType 的允许/拒绝路径

#### Task 0.3 修复 reviewer.py 的导入风格

**文件**: `src/pipeline/stages/reviewer.py:17`、`candidate_promoter.py:11-18`

现状：使用绝对导入 `from src.knowledge.core.candidate import ...`，与项目主流的相对导入风格不一致（CLAUDE.md "Two import styles coexist" 中 `src/sync/file_watcher.py` 是唯一的例外）。

修改：改为相对导入 `from ...knowledge.core.candidate import ...`。

**验证**: 测试通过；`grep -rn "from src\." src/pipeline/` 无新增命中。

---

### Phase 1 — 新管线接线与切换（核心，3-5 天）

**目标：让路径 B 成为生产路径，路径 A 降级为回退。**

#### Task 1.1 KnowledgeKernel 组装（补齐 KOS Task 1.12）

**新文件**: `src/knowledge/kernel.py`

按 KOS v1.3 方案 §1.12 实现：Facade 封装 PermissionEngine + EventBus + LifecycleEngine + VersionManager。per-project 单例，FastAPI lifespan 初始化。

**测试**: `tests/test_knowledge/test_kernel.py`

**说明**: Kernel 是后续 Phase 2/3 的载体，但本任务只组装已有组件，不新增能力。Reviewer/Promoter 的接线（Task 1.2）**不阻塞**于 Kernel——先用最小 Kernel，后续再让 Stage 通过 Kernel 操作。

#### Task 1.2 新管线装配到 PipelineService

**文件**: `src/pipeline/service.py`、`src/pipeline/ingest.py`

这是本方案的核心任务。将 `run_ingest()` 内部流程改造为：

```
run_ingest():
    1. analysis = analyze(source_text, output_format="json")   # ← 改: 传 json
       → KnowledgeCandidate (替代 AnalysisResult)
    2. review = ReviewerStage().review(candidate, paths.root)  # ← 新增
       - REJECTED → 任务 FAILED, 记录原因, 写 quarantine
       - NEEDS_HUMAN_REVIEW → 创建 ReviewItem, 任务 WAITING_REVIEW
       - VALIDATED → 继续
    3. ko = CandidatePromoter().promote(candidate)             # ← 新增
    4. pages = generate(paths, ko, ...)                        # ← 改: 输入 KO
       - Generator 从 KO 复制 frontmatter, LLM 只渲染 body
       - GeneratorOutputValidator 校验无自创字段
    5. (不变) source page 创建 + stub 创建 + QualityGate
    6. (不变) Atomic Write + index + log + vector upsert
    7. VersionManager.snapshot() + lifecycle → ACTIVE          # ← 新增
```

**已锁定决策（2026-08-02 确认，不再评审）**:

| 决策 | 锁定结果 |
|------|----------|
| unified_generate 去留 | **禁用**。统一走两步法（Analyzer→Candidate→Reviewer→Generator），无 fast_path 逃生门。理由：目标流程要求"LLM 不直接写最终知识"，逃生门会在事故时被滥用为常态路径；延迟代价通过 Task 2.4 异步化回收。Task 1.4 中 `unified_generate()` 标记 `DeprecationWarning`，一个版本周期后删除 |
| NEEDS_HUMAN_REVIEW 处理 | **阻断流水线**。任务转 WAITING_REVIEW + 写 ReviewItem 到 reviews.json；人工经 reviews API approve 后继续 Promoter 流程，reject 则任务标记 REJECTED。不做降级写入——边界知识宁可等人，不进库 |
| Analyzer 输出切换 | `output_format="json"` 成为 run_ingest 默认。保留 config flag `analyzer.output_format` **仅作回滚用途**（见 §五），正常使用禁止切回 markdown 模式 |
| CollectorAgent（KOS Task 1.11） | **缓办**，移出本期实施范围（见 Task 1.5）。KOS Phase 2 启动时重新评估其架构对称性价值 |

**测试**:
- `tests/test_pipeline/test_ingest_new_path.py` — 端到端 mock LLM，验证 Candidate→Reviewer→Promoter→Generator 全链路
- 验证 REJECTED candidate 不写任何 wiki 文件
- 验证 NEEDS_HUMAN_REVIEW 创建 ReviewItem 且任务状态正确
- 现有 e2e 测试（test_e2e/test_ingest_happy_path.py）需适配新路径

#### Task 1.3 双跑验证（Shadow Mode）

**目的**: 新路径上线前，用真实流量验证输出质量不退化。

**实现**: config flag `pipeline.shadow_mode=true` 时：
- 主路径仍跑旧路径（生产不受影响）
- 同一 source 异步跑新路径，输出写入 `.index/shadow/<task_id>/`（不进 wiki）
- 生成对比报告：页面数量、类型分布、标签差异、grade 分布

**运行方式**: 选取 20-50 个历史摄取的 raw 文件重放，人工抽查对比报告。

**通过标准**:
- 新路径成功率 ≥ 旧路径（REJECTED 率可解释）
- 抽查 10 个文档，新路径页面质量不劣于旧路径
- 无新增崩溃/异常类型

#### Task 1.4 切换与旧路径弃用

- 默认路径切换为新路径
- 旧 `AnalysisResult` + markdown 模式保留一个版本周期，标记 `DeprecationWarning`
- `unified_generate()` 标记 `DeprecationWarning`（已锁定决策），一个版本周期后删除
- 更新 CLAUDE.md / README.md 的流水线描述

**验证**: 全量测试 + `python -m src.cli serve` + `/health` 200 + 一次真实文档摄取人工核验。

#### Task 1.5（缓办，已移出本期范围）CollectorAgent

**文件**: `src/agent/collector.py`（KOS Task 1.11）

为 Collector 赋予 Agent 身份：权限检查（`raw.create`）、`document.collected` 事件、状态追踪。**已决策缓办**——现有 Collector 功能完整，此任务只有架构对称性价值，不进入本期实施。KOS Phase 2 启动时重新评估。

---

### Phase 2 — 摄取质量缺口（2-3 天）

#### Task 2.1 大文档分块摄取（解决 P1 🔴）

**问题**: `MAX_SOURCE_CHARS = 8000` 硬截断，长文档后半部分知识丢失。

**方案**: 分块摄取（chunked ingestion）

```
source_text > CHUNK_THRESHOLD (如 20000 字符)?
    │
    ├── 否 → 现有单块流程
    │
    └── 是 → 按语义边界分块（章节标题/双换行，目标每块 ≤6000 字符，重叠 500）
             每块独立走 Analyzer → Candidate
             Reviewer 逐块验证
             合并阶段 (MergeStage):
               - 同 slug 实体的 claims 合并（去重 + confidence 取 max）
               - 跨块关系合并
               - source page 记录 chunk_count
```

**文件**: `src/pipeline/chunker.py`（新建）、`analyzer.py`（支持 chunk 上下文）、`ingest.py`（合并逻辑）

**关键设计**:
- 分块在 Sanitizer 之后、Analyzer 之前
- 每块 Candidate 带 `chunk_index` / `chunk_total`，便于溯源和调试
- 合并阶段的实体去重与现有 `dedup_auto.py` 语义对齐

**测试**: 200KB 文档摄取，验证后半部分实体出现在 wiki 中；验证分块边界不切断实体上下文。

#### Task 2.2 文件夹摄取接线（解决 P3 🟡）

**文件**: `src/server/routes/ingest.py`、`src/services/ingest.py`

现状：路由接受 `{"source": {"folder": ...}}` 但不枚举目录（README 明确标注未接线）。

实现：
- `enqueue_source()` 检测 folder 形状 → 调用 `src/wiki/features/folder_ingest.collect_files()` 枚举支持格式文件
- 每个文件创建独立任务（共享 `folder_context` 用于跨文件实体对齐）
- 批量任务组 ID，便于进度追踪（复用 `batch_build_state.json`）

**测试**: 含 5 个文件的文件夹摄取，验证 5 个任务入队且 folder_context 一致。

#### Task 2.3 溯源增强（解决 P6 🟡，与 KOS Phase 2 对齐）

**范围控制**: 本任务只做"管线能记录"的部分，不做"检索能消费"的部分（后者属 KOS Phase 2）。

- Collector：PDF 提取时保留页码标记（`<!-- page: N -->` 注入文本流）
- Analyzer：JSON schema 的 evidence 增加 `page` 字段（提示词引导 LLM 回填）
- Candidate → KO Provenance：携带 page/quote
- WikiPage frontmatter `_ko_extra.provenance` 持久化（Adapter 已支持）

**不做**: 引用片段的字符级 offset、检索时的溯源展示。

#### Task 2.4（可选）异步 Reviewer 提速

unified 路径已禁用（锁定决策），两步法使端到端 LLM 调用次数翻倍，大批量摄取时延迟敏感。可选优化：Reviewer 的规则检查（文件存在性 IO）与 Analyzer 的下一块 LLM 调用并行。仅在 Task 2.1 落地后有意义，否则跳过。

---

### Phase 3 — 治理增强（2-3 天，可与 Phase 2 并行）

#### Task 3.1 标签值域约束（解决 P5 🟡）

依据 `docs/evaluations/tag-namespace-evaluation.md`（已勘误）的整改方向：

- `tag_namespace.py` 的 `TAG_VALUES` **已存在**，且新建页面已通过 `page_writer.py:74` 的 `validate_tag_compliance` 强制校验；本任务改为**补全覆盖**：把 `validate_tag_compliance` 也覆盖到既有页面更新路径，并将自由前缀（角色/事件/实体）逐步纳入受约束值域，而非从零建值域
- LLM 提示词从值域表动态生成（替代硬编码示例文案）
- `MANDATORY_PAIRS` **已配置化**（素材/ugc+可信度/ugc，经 `build_tag_prompt_section` 驱动），本任务只需确认其覆盖全部摄取提示词；消除"前缀说明文案"的 4 处重复（技术债务 #11）
- 存量标签一次性归一化脚本（`题材/现言` → `题材/现代言情` 类映射，dry-run 先行）

#### Task 3.2 QualityJudge 启用策略（解决 P4 🟡）

不建议简单翻转 `enabled=True`（成本 + 延迟翻倍）。改为分级策略：

```yaml
quality_judge:
  enabled: true
  mode: "sample"        # full | sample | off
  sample_rate: 0.2      # 20% 页面过 LLM judge
  always_judge:         # 这些情况下 100% 过 judge
    - grade == "A"      # 高价值页面
    - confidence < 0.7  # Reviewer 标记的边界页面
```

抽样结果用于质量监控仪表盘（metrics），不阻断写入；always_judge 命中的阻断。

#### Task 3.3 dedup 实体识别实现（解决 P7 🟡）

`find_duplicates()` 当前返回空列表。实现第一版：
- 基于 slug 归一化 + 标题编辑距离 + 向量相似度（>0.92）三路候选
- 高置信度自动合并（复用 `dedup_auto.py` 的归档机制）
- 中置信度进 reviews 队列

#### Task 3.4 摄取可观测性

- 每次摄取输出结构化摘要到 `.index/ingest_reports/<task_id>.json`：chunk 数、candidate 数、reviewer  verdict 分布、生成页面数、reject 原因、耗时分解（collector/analyzer/reviewer/generator/write）
- `/metrics` 增加 `ingest_candidate_rejected_total{reason}` 计数器

---

## 三、阶段依赖与排期

```
Phase 0 (1-2d)  ████                      阻断项修复
Phase 1 (3-5d)       ██████████           新管线接线（核心）
Phase 2 (2-3d)                ███████     质量缺口（依赖 Phase 1 的新管线）
Phase 3 (2-3d)                ███████     治理增强（可与 Phase 2 并行）
                              ↑
                         总工期约 8-12 个工作日
```

依赖关系：
- Phase 1 Task 1.2 依赖 Phase 0 全部完成
- Phase 2 Task 2.1（分块）依赖 Phase 1 完成（分块走新管线才有 Reviewer 保护）
- Phase 3 仅弱依赖 Phase 1（标签/判分独立于管线形态），可与 Phase 2 并行

---

## 四、验证标准

### Phase 0 完成标准
- [ ] `schema list` 显示 v2.1/v2.2 迁移路径
- [ ] 全量 873 测试通过
- [ ] 权限白名单覆盖 5 个 AgentType

### Phase 1 完成标准（核心验收）
- [ ] 生产摄取流量 100% 经过 Candidate → Reviewer → Promoter → Generator
- [ ] REJECTED candidate 零 wiki 写入（有测试断言）
- [ ] Generator 自创字段被 GeneratorOutputValidator 拦截（有测试断言）
- [ ] 每次摄取产生 VersionManager 快照 + lifecycle ACTIVE
- [ ] Shadow 双跑 20+ 文档，质量对比通过
- [ ] 全量测试通过 + `/health` 200 + 真实文档摄取人工核验

### Phase 2 完成标准
- [ ] 200KB 文档摄取后，后半部分实体出现在 wiki
- [ ] 文件夹摄取产出 N 个任务 + 统一 folder_context
- [ ] PDF 摄取的页面 provenance 含页码

### Phase 3 完成标准
- [ ] 受控前缀的非法值在写入前被拒绝
- [ ] QualityJudge 按抽样策略运行，成本可预测
- [ ] 摄取报告 JSON 可查，metrics 有 rejected 计数

---

## 五、风险与回滚

| 风险 | 影响 | 缓解 |
|------|------|------|
| 新路径 REJECTED 率过高（LLM JSON 输出不稳定） | 摄取成功率下降 | Analyzer 三层验证已有降级；shadow 阶段先量化 REJECTED 率再切换 |
| 禁用 unified 路径后延迟翻倍（已锁定） | 大批量摄取变慢 | Task 2.4 异步化 + Task 2.1 分块流水并行；接受延迟换取全链路验证完整性 |
| Adapter 往返在老页面上失真 | 旧 wiki 页面读取异常 | Task 1.3 shadow 阶段覆盖读取路径；adapter 测试已有 round-trip 断言 |
| 标签值域约束误杀存量合法标签 | 旧页面 lint 报错 | 值域约束只作用新写入；存量只做归一化建议（dry-run） |
| Schema 迁移修复触发存量项目自动升级 | 数据损坏风险 | 迁移必须显式执行 + BackupManager 自动备份（已有机制） |

**回滚策略**: Phase 1 的每一步都在 config flag 之后。新路径异常时，flag 切回旧路径（`analyzer.output_format=markdown` + 跳过 Reviewer/Promoter），30 秒内完成回滚，无需改代码。

---

## 六、与 KOS 演进方案的边界

本方案**只覆盖摄取流水线**（Collector → ... → commit → ACTIVE），不覆盖：

- KOS Phase 2 的 Claim 结构化、知识图谱（ClaimParser、Indexer Stage、图谱存储）
- KOS Phase 3 的 Decision Memory、MCP Memory API
- KOS Phase 4 的 Curator/Historian/Evolution 循环

但本方案为这些 Phase 铺平了道路：Phase 1 接线后，Candidate/KO/Provenance/VersionManager 全部在生产流量中运转，KOS Phase 2 的 ClaimParser 和 Indexer 可以直接挂载在新管线的对应位置。
