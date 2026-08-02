# Knowledge OS Evolution — Implementation Plan

Version: v1.3 | 2026-08-02
Source: `docs/KNOWLEDGE_OS_EVOLUTION_PLAN.md` (vision)
Audit: v1.0 audit, v1.1 audit (v2), v1.2 audit (v3 — 本文件)
Status: v1.3 — 第三轮审计修复 (3 fatal + 6 major + 2 minor)

---

## Principle

**Migration, not rewrite.** Each phase adds new capability while keeping existing
WikiPage, pipeline, and MCP tools fully operational. Old and new coexist until
the new path proves stable, then old paths are deprecated and removed.

---

## Pre-Phase 0 — Prerequisite Decisions (before any code)

These decisions must be made and documented before Phase 1 Task 1.1. They resolve
the 4 fatal defects identified in the independent audit.

### Decision 0.1: PageType ↔ KnowledgeType mapping

PageType 从 4 值扩展到 8 值，与 KnowledgeType 1:1 对应。一次性重构，Phase 1 第一个 task。

```
PageType (after extension)     KnowledgeType       wiki/ subdirectory
─────────────────────────────────────────────────────────────────────
source                         document            wiki/sources/
entity                         entity              wiki/entities/
concept                        concept             wiki/concepts/
claim                          claim               wiki/claims/        (NEW)
decision                       decision            wiki/decisions/     (NEW)
procedure                      procedure           wiki/concepts/      (复用)
event                          event               wiki/concepts/      (复用)
synthesis                      synthesis           wiki/synthesis/
```

`procedure` 和 `event` 使用 `wiki/concepts/` 目录（通过 `_TYPE_TO_DIR` 映射），避免新增过多目录。

### Decision 0.2: KnowledgeCandidate 不提前引用 Claim

Phase 1 的 `KnowledgeCandidate` 的 `claims` 字段使用 opaque `list[dict]`，不在 Phase 1 定义 `ClaimCandidate` 类型。
Phase 2 引入 Claim 模型后，添加 `ClaimParser` 将 `raw_llm_output` 或 `claims: list[dict]` 转化为结构化 `Claim` 对象。
这消除了 Phase 1→Phase 2 的硬依赖。

### Decision 0.3: Generator 与 Indexer 职责边界

```
Generator (Phase 1, 修改现有):
  输入: KnowledgeObject (post-CandidatePromoter, lifecycle=PROCESSING)
  输出: 完整 WikiPage (body 由 LLM 渲染，frontmatter 从 KnowledgeObject 复制)
  不负责: 写文件、更新索引、生命周期变更

Indexer (Phase 2, 新增独立 Stage):
  输入: 已写入的 WikiPage 列表 (由 commit_ingest 写入)
  输出: 向量嵌入 + 知识图谱更新 + 生命周期→ACTIVE
  不负责: WikiPage markdown 文件写入 (仍由 commit_ingest 负责)
```

完整流水线（Phase 2 结束时）：

```
CollectorAgent → Analyzer → [KnowledgeCandidate] → Reviewer
  → CandidatePromoter (VALIDATED Candidate → KnowledgeObject, lifecycle=PROCESSING)
  → Generator (渲染 markdown body)
  → commit_ingest (原子写 WikiPage 文件 + 更新 index.md + 记录 log.md)
  → Indexer (向量嵌入 + 图谱更新 + lifecycle→ACTIVE)
```

### Decision 0.4: 成本基线与预算模型

单次 ingest 的 LLM 调用成本估算（以 gpt-4o-mini 为基准）：

| 步骤 | 输入 token | 输出 token | 估算成本 | 备注 |
|------|-----------|-----------|---------|------|
| Analyzer | ~3K (source) | ~1K (JSON candidate) | ~$0.0006 | LLM |
| Reviewer | — | — | $0 | 规则引擎 (Phase 1) |
| Generator | ~1.5K (candidate) | ~2K (markdown) | ~$0.0005 | LLM |
| **合计** | | | **~$0.0011/ingest** | |

按日 100 次 ingest 估算: ~$0.11/天, ~$3.30/月。
CuratorAgent (Phase 4) 每次扫描全库: 若 10K 对象，抽样 100 个低质对象 × ~$0.001 = ~$0.10/次。每天运行 = ~$3/月。

**所有 LLM 调用必须通过现有的 `LLM.complete()` 统一入口，该入口已集成 circuit breaker。**
**CuratorAgent 默认频率为每天一次（非每小时），由 config flag 控制。**

多 provider 月度成本对照 (100 ingest/天 + Curator 每天 100 对象):

| Provider | Analyzer | Reviewer | Generator | Curator/月 | **合计/月** |
|----------|----------|----------|-----------|-----------|----------|
| gpt-4o-mini | $0.0006 | $0 (规则) | $0.0005 | ~$3 | **~$6** |
| claude-sonnet-4-6 | ~$0.006 | $0 (规则) | ~$0.005 | ~$30 | **~$60** |
| claude-opus-4-7 | ~$0.03 | $0 (规则) | ~$0.025 | ~$150 | **~$300** |
| Ollama (本地) | ~$0 | $0 (规则) | ~$0 | ~$0 | **~$0** |

注意: Phase 1 Reviewer 是规则引擎 (零 LLM 成本)。Phase 4 可选 LLM Reviewer 额外增加成本。

### Decision 0.5: TaskStatus (队列) ↔ LifecycleState (知识) 映射

两套状态机在同一个 ingest pipeline 中并行运转，必须定义映射关系以避免状态不一致：

```
TaskStatus (queue/state.py)     LifecycleState (knowledge/core/lifecycle.py)
────────────────────────────────────────────────────────────────────────────
PENDING                         (KnowledgeObject 尚未创建)
RUNNING                         PROCESSING
WAITING_REVIEW                  REVIEWING
APPROVED                        ACTIVE
REJECTED                        REJECTED
FAILED                          FAILED
ARCHIVED / TIMEOUT              ARCHIVED
DEAD_LETTER                     FAILED (终态)
```

Pipeline 代码在更新 TaskStatus 时必须同步更新 KnowledgeObject.lifecycle。
此映射在 `src/knowledge/core/lifecycle.py` 中实现为 `task_status_to_lifecycle()` 函数。

---

## Phase 1 — Knowledge Core Foundation

**Goal:** Introduce KnowledgeObject + Lifecycle + Candidate layer + Knowledge Kernel.
WikiPage remains the persistence format; KnowledgeObject is the in-memory model.

**Duration estimate:** 12-14 tasks (含 Pre-Phase 0 决策实施 + Knowledge Kernel + Collector Agent)

### Knowledge Kernel — 统一知识基础设施

原方案定义了一个 Knowledge Kernel，包含五个核心子系统。在 Phase 1 中，
这些组件不是从零构建的——两个已有基础，三个新建——Kernel 的角色是
**统一入口 + 生命周期协调**。

```
KnowledgeKernel (src/knowledge/kernel.py)
├── KnowledgeObject     — 核心数据模型 (Task 1.2, 新建)
├── LifecycleEngine     — 状态机 (Task 1.5, 新建)
├── PermissionEngine    — 封装现有 src/permissions.py，扩展 AgentType
├── EventBus            — 封装现有 src/events/event_bus.py，标准化知识事件
└── VersionManager      — 变更追踪 (Task 1.4, 新建)
```

**设计原则:**

- **Kernel 是 Facade，不是新逻辑。** PermissionEngine 和 EventBus 已存在且在生产中使用。Kernel 封装它们为统一 API，Agent 代码通过 Kernel 访问基础设施，而非直接依赖具体模块。
- **所有 Agent 通过 Kernel 操作知识。** 任何对 KnowledgeObject 的读写、生命周期变更、权限检查、事件发布，都经过 Kernel。这提供了一致的审计追踪和权限门禁。
- **Kernel 在 Phase 1 初始化，后续 Phase 增量扩展。** Phase 2 加 Graph 相关 API，Phase 3 加 Memory 相关 API。

```python
# Kernel 统一入口示意
class KnowledgeKernel:
    """知识基础设施的统一入口。封装 PermissionEngine + EventBus + LifecycleEngine。"""

    def __init__(self, project_path: Path):
        self.permissions = PermissionEngine()        # 封装现有
        self.events = EventBus()                     # 封装现有
        self.lifecycle = LifecycleEngine(self.events)  # 新建
        self.versions = VersionManager(project_path)   # 新建

    # Agent 通过 Kernel 执行受控操作
    def create_object(self, obj: KnowledgeObject, agent: AgentType) -> KnowledgeObject:
        self.permissions.check(agent, Permission.KNOWLEDGE_CREATE)
        self.events.emit("knowledge.created", obj)
        return obj

    def transition_lifecycle(self, obj: KnowledgeObject, target: LifecycleState,
                             agent: AgentType, reason: str) -> KnowledgeObject:
        self.permissions.check(agent, Permission.KNOWLEDGE_UPDATE)
        return self.lifecycle.transition(obj, target, reason)
```

**Phase 1 Kernel 覆盖范围:**

| 子系统 | 来源 | Phase 1 工作 |
|--------|------|-------------|
| KnowledgeObject | 新建 Task 1.2 | 完整实现 |
| LifecycleEngine | 新建 Task 1.5 | 完整实现 (8-state, emit event 到 EventBus) |
| PermissionEngine | 已有 `src/permissions.py` | 扩展: 新增 `KNOWLEDGE_CREATE`, `KNOWLEDGE_UPDATE`, `KNOWLEDGE_DELETE`, `CANDIDATE_APPROVE`, `RAW_CREATE`, `RAW_READ` 六个 Permission；新增 `COLLECTOR`, `CURATOR`, `HISTORIAN`, `RESEARCHER` 四个 AgentType |
| EventBus | 已有 `src/events/event_bus.py` | 扩展: 标准化知识事件类型 (`knowledge.created`, `knowledge.updated`, `lifecycle.changed`, `candidate.validated`, `candidate.promoted`) |
| VersionManager | 新建 Task 1.4 | 完整实现 |

### 1.0 Extend PageType enum (Pre-Phase 0 决策实施)

Modify: `src/wiki/core/types.py`

- PageType 新增: `CLAIM = "claim"`, `DECISION = "decision"`, `PROCEDURE = "procedure"`, `EVENT = "event"`
- `_TYPE_TO_DIR` 映射更新: `claim → wiki_claims`, `decision → wiki_decisions`, `procedure → wiki_concepts`, `event → wiki_concepts`
- `WikiPaths` 新增属性: `wiki_claims`, `wiki_decisions`
- `ensure_knowledge_base()` 创建新目录

### 1.1 Create `src/knowledge/` package skeleton

New files: `src/knowledge/__init__.py`, `src/knowledge/core/__init__.py`
Test: `import src.knowledge` succeeds

### 1.2 KnowledgeObject + KnowledgeType + Provenance

New file: `src/knowledge/core/object.py`

```python
@dataclass
class KnowledgeObject:
    id: str
    type: KnowledgeType        # document|entity|concept|claim|decision|procedure|event|synthesis
    title: str
    content: str
    lifecycle: LifecycleState  # CREATED|PROCESSING|REVIEWING|ACTIVE|DEPRECATED|ARCHIVED|FAILED|REJECTED
    confidence: float          # 0.0-1.0
    grade: str                 # A|B|C
    heat: int                  # 0-100
    provenance: Provenance     # {source_path, page, quote, ingested_at, ingestor_version}
    relations: list[Relation]
    versions: list[VersionRef] # {version_id, timestamp, change_description}
    created_at: int
    updated_at: int
```

- `KnowledgeType` enum — 与扩展后的 PageType 1:1 对应 (共 8 值)
- `LifecycleState` enum — 8-state: CREATED, PROCESSING, REVIEWING, ACTIVE, DEPRECATED, ARCHIVED, FAILED, REJECTED
- `Provenance` dataclass — `{source_path, page, quote, ingested_at, ingestor_version}`
- `content` 字段等价于 `WikiPage.body`，存储 Markdown。命名不同是因为 KnowledgeObject 不仅来自 WikiPage（也可来自 API/MCP 直接创建），"content" 比 "body" 更通用。Adapter 直接映射 `content ↔ body`

### 1.3 WikiPage ↔ KnowledgeObject adapter

New file: `src/knowledge/core/adapter.py`

- `wiki_page_to_knowledge_object(page: WikiPage) -> KnowledgeObject`
- `knowledge_object_to_wiki_page(obj: KnowledgeObject) -> WikiPage`
- Round-trip guarantee: `wp == ko_to_wp(wp_to_ko(wp))`。扩展后的 PageType 直接映射到 KnowledgeType，无信息丢失
- Extra KnowledgeObject fields (lifecycle, confidence, provenance) 存储在 WikiPage frontmatter 的 `_ko_extra` 键下（嵌套 YAML），避免与现有 frontmatter 字段冲突
- 单元测试验证：所有现有 WikiPage 字段 + 所有新字段的往返无损

### 1.4 Version Manager

New file: `src/knowledge/core/version_manager.py`

- `VersionManager` — mutation 前快照 KnowledgeObject，分配 version_id
- API: `snapshot(obj) -> VersionRef`, `get_history(object_id) -> list[VersionRef]`, `diff(v1, v2) -> dict`
- 版本存储: `.index/versions/{object_id}/` (JSON)
- **保留策略（审计 O1）:** 每个 object 最多保留最近 50 个版本 + 关键生命周期变更点（CREATED, ACTIVE, ARCHIVED）。超出部分归档到 `.index/versions/{object_id}/_archive/`
- 复用 `safe_write` 保证原子写入

### 1.5 LifecycleEngine

New file: `src/knowledge/core/lifecycle.py`

- `LifecycleEngine` with `can_transition(prev, next) -> bool`, `transition(obj, new_state, reason) -> KnowledgeObject`
- 合法转换（8 状态 × 15 边）:
  ```
  CREATED → PROCESSING, ARCHIVED
  PROCESSING → REVIEWING, FAILED, ARCHIVED
  REVIEWING → ACTIVE, REJECTED, PROCESSING (返工)
  ACTIVE → DEPRECATED, ARCHIVED
  DEPRECATED → ACTIVE (恢复), ARCHIVED
  FAILED → PROCESSING (重试), ARCHIVED
  REJECTED → ARCHIVED
  ARCHIVED → (终态，不可转换)
  ```
- `LifecycleEvent` emit 到 EventBus（不直接写 log.md）。由现有的 pipeline event logger 和 Phase 4 Historian 订阅消费

### 1.6 KnowledgeCandidate — LLM output intermediate

New file: `src/knowledge/core/candidate.py`

```python
@dataclass
class KnowledgeCandidate:
    id: str
    source_id: str             # 源文档 ID
    type: KnowledgeType
    title: str
    claims: list[dict]         # [FIX F1] opaque dict，Phase 2 结构化
    confidence: float
    evidence: list[dict]       # [FIX F1] opaque dict: {source_path, page, quote}
    raw_llm_output: dict       # LLM 原始 JSON (用于调试和 Phase 2 回放)
    status: CandidateStatus    # PENDING|VALIDATED|REJECTED|PROMOTED
```

- `CandidateStatus` enum with transition validation
- **claim dict schema (审计 M12 修复):** 每条 claim 是 `{"statement": "...", "confidence": 0.9, "evidence_refs": [0, 2]}`，其中 `evidence_refs` 是 `candidate.evidence` 列表的索引。ClaimParser 通过索引关联 evidence
- Phase 2 添加 `ClaimParser.extract(candidate) -> list[Claim]` 将 opaque dict 转为结构化类型

### 1.7 Analyzer JSON output

Modify: `src/pipeline/analyzer.py`

- 新 prompt template: 指示 LLM 输出 JSON (非 Markdown)，匹配 KnowledgeCandidate schema
- `AnalyzerOutputParser`: 三层验证:
  1. **Syntax check** — 是否为合法 JSON？失败→重试一次（不同 temperature），仍失败→标记为 REJECTED
  2. **Schema check** — 是否包含必填字段 (source_id, type, title)？
     - `source_id` 缺失 → **不可默认**，直接标记 Candidate REJECTED (无来源 = 不可追溯)
     - `type` 缺失 → 默认 `"concept"`, confidence *= 0.3
     - `title` 缺失 → 从 `claims[0].statement` 截取前 80 字符, confidence *= 0.3
  3. **Content check** — claims 列表非空？为空→标记 confidence=0.3 并 flag 人工审核
- Config flag: `analyzer.output_format: "json"|"markdown"` (default `"markdown"` for backward compat)

### 1.8 Generator role constraint

Modify: `src/pipeline/generator.py`

- 强制执行原方案工程规则 3: Generator 只渲染，不推断/修改/新增
- `GeneratorOutputValidator` — 拒绝生成了输入 Candidate 中不存在的 frontmatter 字段的页面
- Generator 输入: KnowledgeObject (post-CandidatePromoter, lifecycle=PROCESSING)
- Generator 输出: 完整的 WikiPage (含 body + frontmatter)。body 由 LLM 渲染，frontmatter 从 KnowledgeObject 字段复制（title, type, grade, confidence, provenance, relations 等）
- `commit_ingest()` 接口不变——接收 WikiPage 列表，原子写入

### 1.9 Reviewer stage (规则引擎)

New file: `src/pipeline/stages/reviewer.py`

- `ReviewerStage` — Phase 1 为**纯规则引擎** (pipeline stage, 非 LLM Agent)，验证 KnowledgeCandidate 后决定是否晋升
- **可实现的具体检查（审计 M1 修复）:**
  1. **Schema 合规** — Candidate 是否包含必填字段 (规则)
  2. **证据存在性** — 每条 claim 是否至少有 1 条 evidence 引用 (规则)
  3. **引用一致性** — evidence 中的 source_path 在项目内是否存在 (文件系统检查，非 LLM)
  4. **置信度阈值** — confidence < 0.5 → REJECTED, 0.5-0.7 → NEEDS_HUMAN_REVIEW, ≥ 0.7 → VALIDATED
- **明确不检查:** 幻觉检测（这是 LLM 领域未解决问题，不在 Phase 1 范围内）
- **Phase 4 可选升级:** LLM-assisted Reviewer (真正检测语义矛盾)，但 Phase 1 保持纯规则
- 位置: `src/pipeline/stages/reviewer.py` (非 `src/agent/`)。Agent 框架留给 Phase 4 升级
- Permission: `candidate.approve`
- 输出: `CandidateStatus.VALIDATED` | `CandidateStatus.REJECTED` (带 reason)
- **幂等性:** 同一 candidate_id 的多次审查返回缓存结果（复用现有 idempotency 机制，TTL 1h）

### 1.10 CandidatePromoter — Candidate → KnowledgeObject 晋升

New file: `src/pipeline/stages/candidate_promoter.py`

- `CandidatePromoter` — 将 VALIDATED Candidate 转化为 KnowledgeObject
- 输入: validated KnowledgeCandidate (post-Reviewer, status=VALIDATED)
- 输出: KnowledgeObject (lifecycle=PROCESSING) + Candidate status→PROMOTED
- Candidate 和 KnowledgeObject 共享同一 ID
- 转化的 KnowledgeObject 字段映射:
  - `id` ← candidate.id
  - `type` ← candidate.type
  - `title` ← candidate.title
  - `content` ← "" (空，由 Generator 后续填充 markdown body)
  - `lifecycle` ← PROCESSING
  - `confidence` ← candidate.confidence
  - `provenance` ← 从 candidate.source_id + candidate.evidence 构建
  - `versions` ← [VersionRef(version_id="v1", timestamp=now, change_description="created from candidate")]
- 此阶段不写文件——KnowledgeObject 由 commit_ingest 统一持久化

### 1.11 CollectorAgent — 独立 Agent 设计

New file: `src/agent/collector.py`

原方案将 Collector 定位为独立 Agent（非 pipeline stage）。当前 Collector 是 pipeline
的第一个阶段（提取文本 → 传给 Analyzer），功能完整，但缺少 Agent 身份。
Phase 1 为其赋予 Agent 身份，使其具备独立的权限、事件和状态追踪。

```python
class CollectorAgent:
    """独立 Agent — 负责获取源内容 + 元数据提取。

    Pipeline 角色: collector:start → CollectorAgent → collector:done
    Agent 身份: AgentType.COLLECTOR
    权限: raw.create (创建原始内容记录)
    事件: document.collected (源内容获取完成后发布)
    """

    async def collect(self, source: str | Path) -> CollectorResult:
        """获取源内容，提取元数据，发布 document.collected 事件。"""
        ...
```

**与现有 Collector 的关系:**
- 现有 `src/pipeline/collector.py` 的文本提取逻辑**保持不变**，CollectorAgent 封装它
- CollectorAgent 新增职责:
  1. **权限检查** — 通过 Kernel 验证 `raw.create` 权限
  2. **事件发布** — 获取完成后 emit `document.collected` 到 EventBus（含 source_path, content_hash, byte_size, format）
  3. **状态追踪** — 记录 collector:start / collector:done 的时间戳到任务元数据
- 现有 pipeline 的 `collector:start` / `collector:done` 事件继续触发，CollectorAgent 在此基础上增加 Agent 层事件

**AgentType 注册:**
- 新增 `AgentType.COLLECTOR` → `src/permissions.py`
- 权限白名单: `raw.create` (创建 raw source 记录), `raw.read` (读取原始内容)
- 与其他 Agent 一致，`Orchestrator` 始终放行

**事件格式:**
```json
{
  "event": "document.collected",
  "source_path": "/abs/path/to/doc.pdf",
  "content_hash": "md5hex",
  "byte_size": 1048576,
  "format": "pdf",
  "collected_at": 1759430400
}
```

### 1.12 KnowledgeKernel assembly

New file: `src/knowledge/kernel.py`

将所有 Phase 1 基础设施组件组装为统一的 KnowledgeKernel 入口:

```python
class KnowledgeKernel:
    """知识基础设施统一入口。Agent 代码通过此入口访问所有知识操作。"""

    def __init__(self, project_path: Path):
        self.permissions = PermissionEngine()       # 封装现有 src/permissions.py
        self.events = EventBus()                    # 封装现有 src/events/event_bus.py
        self.lifecycle = LifecycleEngine(self.events)  # Task 1.5
        self.versions = VersionManager(project_path)   # Task 1.4

    # Agent 操作入口
    def create_object(self, obj: KnowledgeObject, agent: AgentType) -> KnowledgeObject: ...
    def update_object(self, obj: KnowledgeObject, agent: AgentType, changes: dict) -> KnowledgeObject: ...
    def transition_lifecycle(self, obj, target: LifecycleState, agent: AgentType, reason: str) -> KnowledgeObject: ...
    def get_history(self, object_id: str) -> list[VersionRef]: ...
```

- Kernel 是单例（per project），在 FastAPI lifespan 中初始化
- Phase 2/3/4 通过 Kernel 暴露新能力（Graph API, Memory API, Evolution API）
- 测试: `tests/test_knowledge/test_kernel.py`

### 1.13 Phase 1 tests

New files:
- `tests/test_knowledge/test_object.py`
- `tests/test_knowledge/test_adapter.py` — 含往返无损验证
- `tests/test_knowledge/test_version_manager.py`
- `tests/test_knowledge/test_lifecycle.py`
- `tests/test_knowledge/test_candidate.py`
- `tests/test_knowledge/test_kernel.py` — KnowledgeKernel 组装验证
- `tests/test_pipeline/test_analyzer_json.py` — 含三层验证场景
- `tests/test_pipeline/test_generator_constraint.py`
- `tests/test_pipeline/test_reviewer.py` — 含幂等性测试 (规则引擎)
- `tests/test_pipeline/test_candidate_promoter.py` — Candidate→KnowledgeObject 映射
- `tests/test_agent/test_collector.py` — CollectorAgent 事件+权限

**Phase 1 verification:**
- 现有 748 测试全通过
- PageType 扩展后所有现有页面正常解析
- `wp == ko_to_wp(wp_to_ko(wp))` 往返无损 (含新旧字段)
- LifecycleEngine 拒绝非法转换
- Analyzer JSON 三层验证正确分类格式错误
- GeneratorOutputValidator 拒绝生成自创字段
- ReviewerStage 幂等性: 同一 candidate 两次审查返回相同结果
- CandidatePromoter 正确将 VALIDATED Candidate 转为 KnowledgeObject(PROCESSING)
- CollectorAgent 发布 `document.collected` 事件 + 权限检查生效
- KnowledgeKernel 正确组装 5 个子系统，统一入口可用
- `python -m src.cli serve` + `/health` 200

---

## Phase 2 — Claim + Evidence + Graph

**Goal:** 将 Candidate 中的 opaque dict 结构化为 Claim/Evidence 模型，添加证据链追溯，
构建知识图谱。

**Duration estimate:** 6-7 tasks

### 2.1 Claim + Evidence model

New file: `src/knowledge/claims/model.py`

```python
@dataclass
class Claim:
    id: str
    statement: str
    type: ClaimType       # fact|opinion|hypothesis|warning
    confidence: float
    evidence: list[Evidence]
    status: ClaimStatus   # pending|verified|rejected
    source_objects: list[str]  # 支持此声明的 KnowledgeObject ID 列表
    created_at: int
    updated_at: int

@dataclass
class Evidence:
    source_path: str
    page: int | None
    quote: str
    added_at: int
```

### 2.2 ClaimParser — Phase 1→Phase 2 桥接

New file: `src/knowledge/claims/parser.py`

- `ClaimParser.extract(candidate: KnowledgeCandidate) -> list[Claim]`
- 输入: Phase 1 的 opaque `candidate.claims: list[dict]` + `candidate.evidence: list[dict]`
- 输出: 结构化的 `list[Claim]`，每个 Claim 携带解析后的 Evidence
- 解析失败: 个别 claim dict 不合法 → 跳过该条并记录 warning，不回滚整个 Candidate
- 此模块是 Phase 1 Candidate 和 Phase 2 Claim 之间的唯一桥梁

### 2.3 Claim extraction in Analyzer

Modify: `src/pipeline/analyzer.py`

- **Analyzer prompt 不变** — Phase 1 的 prompt 已在 claims dict 中包含 `evidence_refs`。Phase 2 只新增 ClaimParser 后处理，不改 prompt。Claim type 默认为 `"fact"`，Phase 4 可选升级 prompt 以让 LLM 自行分类 claim type
- Claim 存储为 `KnowledgeObject(type=claim)` → 写入 `wiki/claims/` 目录
- 此路径与 Decision 0.1 中定义的映射一致，消除了审计 L3 的歧义

### 2.4 Provenance tracking

New file: `src/knowledge/provenance/tracker.py`

- `ProvenanceTracker` — 记录 source → claim → knowledge 链
- 存储为每个 KnowledgeObject/WikiPage 的 `provenance` frontmatter 字段
- 查询接口: `get_derived_objects(source_path) -> list[str]` (展示从源 X 派生的所有对象)
- CLI: `python -m src.cli provenance show <object_id>`
- **源文档删除处理（审计 E7）:** 当源文档被删除时，所有派生对象的 provenance 中标记 `source_status: deleted`，保留引用但不返回 404

### 2.5 Conflict detection

New file: `src/knowledge/conflicts/detector.py`

- `ConflictDetector` — 发现同一实体上的矛盾声明
- 两阶段检测:
  1. **候选筛选** — 同一实体的声明按嵌入相似度分组（阈值 0.85），只比较组内
  2. **矛盾判定** — 使用 negation keyword 列表 + LLM 判定 (单次低成本调用，非 pairwise)
- **性能控制（审计 E5）:** 声明数 > 500 的实体跳过 pairwise，改为抽样 100 条做 LLM 全局判定
- 输出: `ConflictReport` — `{claim_a, claim_b, entity, conflict_type, suggested_resolution}`
- CLI: `python -m src.cli conflicts list --project <id>`

### 2.6 Knowledge graph builder

New file: `src/knowledge/graph/builder.py`

- `GraphBuilder` — 从 KnowledgeObjects + Claims + Relations 构建内存图
- Nodes: Entity, Concept, Claim, Decision, Document, Event
- Edges: SUPPORTS, CONTRADICTS, DERIVES_FROM, RELATES_TO, PRECEDES
- **存储方案（审计 M3 修复）:** append-only JSONL 事件日志 + 定期全量 snapshot
  - `.index/knowledge_graph/events.jsonl` — 每次 ingest 追加增量事件 (append-only, 无并发冲突)
  - `.index/knowledge_graph/snapshot.json` — 全量快照
  - **重建触发:** Indexer 内嵌计数器 `_ingest_count_since_snapshot`。每 100 次 ingest 后同步重建 snapshot（Phase 2-3 方案）。Phase 4 可选升级为每天重建（与 Curator 共用 EvolutionLoop scheduler）
  - 查询时: 加载最新 snapshot + 重放 snapshot 之后的 events → 当前完整图
  - 事件格式:
    - `{"action": "upsert_node", "node": {...}, "timestamp": ...}\n`
    - `{"action": "delete_node", "node_id": "...", "timestamp": ...}\n`
    - `{"action": "upsert_edge", "edge": {...}, "timestamp": ...}\n`
    - `{"action": "delete_edge", "edge_id": "...", "timestamp": ...}\n`
  - 写入并发安全: append-only 保证无 read-modify-write 竞争; snapshot 重建由单 worker 负责

### 2.7 Indexer — pipeline terminal stage

New file: `src/pipeline/stages/indexer.py`

- `IndexerStage` — commit_ingest 之后的独立 pipeline stage
- 职责:
  - (a) 向量嵌入 upsert (复用 `src/vector/upsert.py`)
  - (b) 追加知识图谱事件到 events.jsonl
  - (c) 将对象 lifecycle 过渡到 ACTIVE
  - (d) 递增 ingest 计数器; `_ingest_count % 100 == 0` 时同步重建 snapshot
- **与 commit_ingest 的关系（审计 M6 修复）:** commit_ingest 负责原子写 WikiPage 文件 + 更新 index.md + 记录 log.md。Indexer 是独立的后续 stage，不替代 commit_ingest 的任何职责

### 2.8 Phase 2 tests

New files:
- `tests/test_knowledge/test_claims.py`
- `tests/test_knowledge/test_claim_parser.py` — opaque dict → Claim 桥接
- `tests/test_knowledge/test_provenance.py`
- `tests/test_knowledge/test_conflicts.py` — 含性能边界测试 (>500 claims)
- `tests/test_knowledge/test_graph.py` — 含 append-only event 重放测试
- `tests/test_pipeline/test_indexer.py`

**Phase 2 verification:**
- ClaimParser 正确将 Phase 1 opaque dict 转为结构化 Claim
- Provenance 链从 source → claim → knowledge 可追溯
- Conflict detector 在 1000 claims 规模下 30s 内完成
- 知识图谱 append-only 日志 + snapshot 重放一致性
- Indexer 不与 commit_ingest 职责重叠

---

## Phase 3 — Memory System + MCP Upgrade + Retrieval Enhancement

**Goal:** Semantic/Episodic/Decision memory types。MCP 从 `wiki.*` 升级到 `memory.*`。
检索增强 (Query Understanding + Reranker)。

**Duration estimate:** 6-8 tasks

### 3.1 Memory types

New file: `src/knowledge/memory/types.py`

```python
class MemoryType(Enum):
    SEMANTIC = "semantic"     # 事实/知识
    EPISODIC = "episodic"     # 事件/经历
    DECISION = "decision"     # 选择+理由
    PROCEDURAL = "procedural" # 操作流程
```

- 每种 memory type 是一个 `KnowledgeObject`，type 映射到对应的 KnowledgeType
- Decision memory 额外字段存储在 WikiPage frontmatter 的 `_ko_extra.memory.decision` 下: `{context, alternatives, rationale, outcome}`。`outcome` 为 optional，可通过 `update_outcome()` 事后补充
- MemoryRetrieval 读取时从 `_ko_extra.memory` 解析各 memory type 的特有字段

### 3.2 Decision recorder

New file: `src/knowledge/memory/decision.py`

- `DecisionRecorder` — 创建 decision-type KnowledgeObjects
- API: `record_decision(question, decision, context, alternatives, rationale) -> str` (返回 decision_id)
- API: `update_outcome(decision_id, outcome, actual_impact) -> None` — **事后补充结果（审计 E10 修复）**
- Query: `get_decision_context(decision_id)` → 完整 decision + evidence + history + outcome
- CLI: `python -m src.cli memory record-decision --project <id>`

### 3.3 MCP Memory API

Modify: `src/mcp_server/main.py`, new file: `src/mcp_server/memory_tools.py`

New tools:
- `memory_search(query, memory_type)` — 跨 memory type 的语义搜索
- `memory_recall(object_id)` — 检索完整 memory object + provenance
- `memory_explain(object_id)` — 解释知识来源 (provenance chain)
- `memory_verify(object_id)` — 检查证据 + 置信度 (通用接口，不限于 claim)
- `memory_update(object_id, changes)` — 更新 + lifecycle transition 记录

旧工具 `ruflo_kb_search`, `ruflo_kb_read_file`, `ruflo_kb_files`, `ruflo_kb_ingest`, `ruflo_kb_reviews`, `ruflo_kb_projects`, `ruflo_kb_set_project`, `ruflo_kb_status` 保持可用，标记 deprecated。
新增 `ruflo_kb_memory_search`, `ruflo_kb_memory_recall`, `ruflo_kb_memory_explain`, `ruflo_kb_memory_verify`, `ruflo_kb_memory_update`。
`memory_verify` 接受 object_id (非 claim_id)，避免 Phase 3 对 Phase 2 Claim 模型的硬依赖（审计 M9 修复）。

### 3.4 Query understanding

New file: `src/searcher/query_understanding.py`

- `QueryUnderstanding` — 搜索前查询分类与扩展
- 分类: factoid / explanatory / procedural / decision-context
- 路由到对应的 memory type
- 实体识别扩展查询 (复用现有 wiki entities)

### 3.5 Reranker

New file: `src/searcher/reranker.py`

- `Reranker` — 检索后 LLM 或 cross-encoder 重排序
- 输入: vector + graph search 的融合结果
- 输出: 相关性排序结果 + 分数
- Config flag `search.reranker.enabled` (default `false` in Phase 3)
- **关闭时的回退路径（审计 E6/E9 修复）:** Reranker 关闭时，MemoryRetrieval 直接跳过此步骤，输出 vector+graph 融合结果。路径为: `QueryUnderstanding → search → [Reranker if enabled] → response`

### 3.6 Memory retrieval router

New file: `src/knowledge/memory/retrieval.py`

- `MemoryRetrieval` — 编排 QueryUnderstanding → search → [Reranker] → 组装 response
- Response 格式: `{memory_object, provenance_chain, related_decisions, conflicting_claims}`
- **数据组装责任（审计 M8 修复）:** MemoryRetrieval 负责搜索后组装 response。Provenance 数据由 ProvenanceTracker 提供，冲突数据由 ConflictDetector 提供。MemoryRetrieval 是这些组件的编排者，不重复实现它们的逻辑

### 3.7 Phase 3 tests

New files:
- `tests/test_knowledge/test_memory_types.py`
- `tests/test_knowledge/test_decision.py` — 含 outcome 事后更新测试
- `tests/test_searcher/test_query_understanding.py`
- `tests/test_searcher/test_reranker.py` — 含启用/关闭回退路径测试
- `tests/test_knowledge/test_memory_retrieval.py`
- `tests/test_mcp_server/test_memory_tools.py`

**Phase 3 verification:**
- Decision memory 记录并支持事后补充 outcome
- QueryUnderstanding 正确路由 factoid/explanatory/decision 查询
- Reranker 关闭时检索正常返回 (无崩溃)
- MCP `memory.explain()` 返回完整 provenance chain
- 旧 `wiki.search()` 与新 `memory.search()` 并存
- MCP server 启动并注册所有工具

---

## Phase 4 — Autonomous Knowledge Evolution

**Goal:** Curator agent (安全模式), knowledge decay, self-improvement loop,
Researcher agent, Historian agent.

**Duration estimate:** 6-8 tasks

### 4.1 Curator agent

New file: `src/agent/curator.py`

- `CuratorAgent` — 定期后台 agent
- 职责:
  - 合并重复 KnowledgeObjects (扩展现有 dedup)
  - 标记低质知识 (C-grade + heat < 10) 为改进候选
  - 标记过时知识 (DEPRECATED) 为归档候选
  - 标记冲突 (由 ConflictDetector 发现) 为待解决
- **安全措施（审计 M2 修复）:**
  1. Curator **不直接修改**任何 KnowledgeObject。所有改写写入独立的 `.index/curator_proposals/` 审核队列
  2. 每个改写提案包含 `before_snapshot`, `after_snapshot`, `diff`, `reason`
  3. 提案需经 Reviewer 验证后才能应用（复用 Phase 1 Reviewer）
  4. 初始部署以 `dry_run: true` 模式运行 (只生成报告，不提交提案)
  5. 由 config flag `curator.auto_apply` 控制是否自动应用 (default `false`)
- Permission: `knowledge.update` (仅限提案创建)
- 触发: 每天一次 (EvolutionScheduler)，或手动 CLI `python -m src.cli curate --project <id>`
- **成本控制:** 每次运行最多审查 100 个对象 (configurable: `curator.max_objects_per_run`)

### 4.2 Knowledge decay integration

Modify: `src/wiki/features/heat.py` + new file: `src/knowledge/lifecycle/decay.py`

- 扩展现有 5-pool heat 系统以触发 lifecycle transition
- **桥接实现:** 在 `src/wiki/features/heat.py` 的 `decay_all()` 末尾增加回调——当对象 heat 降至 0 时调用 `LifecycleEngine.transition(obj, DEPRECATED, "heat decayed to zero")`
- Heat=0 + zombie → lifecycle → DEPRECATED (not ARCHIVED)
- DEPRECATED 对象定期由 Curator 审查 → ARCHIVED 或 RESTORED
- **阻塞处理（审计 E3 修复）:** 若 Curator 宕机，DEPRECATED 对象保持 DEPRECATED 状态，不影响搜索 (DEPRECATED 对象仍可被检索，仅在结果中标记为 "可能过时")。无 zombie limbo
- 衰减速率受: heat score, last_used_at, grade, has_conflicts 影响

### 4.3 Self-improvement loop

New file: `src/knowledge/evolution/loop.py`

- `EvolutionLoop` — 编排定期自我改进
- Flow: Curator 审查低质对象 → 生成改进提案 → Reviewer 验证 → (auto_apply 开启时) 应用
- 所有变更经由 Historian 记录
- Schedule: 每天一次 (与 Curator 同频)
- 速率限制: `curator.max_objects_per_run` × `curator.auto_apply` flag

### 4.4 Researcher agent

New file: `src/agent/researcher.py`

- `ResearcherAgent` — 跨源深度研究
- 输入: research question → 输出: `ResearchReport` (synthesis-type KnowledgeObject)
- 复用 `src/research/` + Tavily web search
- **安全措施（审计 M7 修复）:**
  1. Web search 结果标记 `provenance.source_type = "web_search"` + 记录搜索 URL 和检索时间
  2. 合成产物 lifecycle 默认为 PROCESSING (不自动 ACTIVE)
  3. 合成内容需经 Reviewer 验证后才能 ACTIVE
  4. 可信域名白名单 (`researcher.allowed_domains`)，Tavily 结果经过域名过滤
- 与 Analyzer 的区别: Researcher 跨多源综合 → synthesis; Analyzer 单源提取 → candidates
- Permission: `knowledge.create` (synthesis only, 且 lifecycle=PROCESSING)

### 4.5 Historian agent

New file: `src/agent/historian.py`

- `HistorianAgent` — 记录知识变更的原因
- **审计 M17 修复:** Historian 订阅 EventBus 的 LifecycleEvent（由 LifecycleEngine emit），不重复实现日志写入。LifecycleEngine 在 Phase 1 只 emit 事件，pipeline event logger 负责写 `wiki/log.md`，Historian 在 Phase 4 订阅同一事件写结构化变更记录
- 每条记录: `{timestamp, agent, object_id, change_type, before_snapshot_id, after_snapshot_id, reason}`
- **变更记录是可查询的:** `get_change_history(object_id)`, `get_changes_by_agent(agent_type, since)`
- 存储位置: `.index/change_history/{object_id}.jsonl`
- Permission: `history.append`

### 4.6 Evolution scheduler

New file: `src/knowledge/evolution/scheduler.py`

- **审计 M16 修复:** 系统没有 cron 基础设施，需新增简单的定时触发机制
- `EvolutionScheduler` — 在 FastAPI lifespan 中启动的后台 asyncio 循环
  - 记录上次运行时间到 `.index/curator_last_run.json`
  - 每 24h 检查一次: 若距上次运行 > 23h 则触发 CuratorAgent + EvolutionLoop
  - 支持手动触发 (CLI `python -m src.cli curate --project <id>` 重置计时器)
- 轻量实现: 不引入 APScheduler/Celery，用 `asyncio.create_task` + `asyncio.sleep(3600)` 每小时检查
- 服务重启后从 `curator_last_run.json` 恢复状态，不会重复运行

### 4.7 Concurrency control (原 §4.6)

New file: `src/knowledge/core/concurrency.py`

- **审计 M4 修复:** KnowledgeObject 有三个写入源 (Pipeline Indexer, Curator, MCP memory.update)
- 采用文件系统乐观锁:
  - 每个 KnowledgeObject 写入前读取 `.index/locks/{object_id}.version` (monotonic counter)
  - 写入时附带 `expected_version`，版本不匹配则重试 (最多 3 次)
  - 写成功后递增 version counter
  - MCP `memory_update` 返回版本冲突错误 (HTTP 409) 供调用方重试

### 4.8 Phase 4 tests

New files:
- `tests/test_agent/test_curator.py` — 含 dry_run 模式、提案队列、auto_apply 测试
- `tests/test_agent/test_researcher.py` — 含 web_search 来源标记、Reviewer 门禁测试
- `tests/test_knowledge/test_decay.py`
- `tests/test_knowledge/test_evolution.py`
- `tests/test_knowledge/test_concurrency.py` — 乐观锁冲突/重试测试
- `tests/test_agent/test_historian.py`
- `tests/test_knowledge/test_evolution_scheduler.py`

**Phase 4 verification:**
- Curator 在 dry_run 模式生成提案但不修改知识库
- Reviewer 门禁阻止 Researcher 的未验证合成内容直接 ACTIVE
- Heat decay 触发 lifecycle → DEPRECATED (非直接 ARCHIVED)
- 并发写入冲突时乐观锁正确拒绝并返回 HTTP 409
- Historian 变更记录完整可查询
- Evolution loop 运行后知识库无数据损坏
- EvolutionScheduler 按 24h 间隔触发，重启后不重复运行

---

## Phase 5 — Storage Evolution

**Goal:** 将元数据从文件系统迁移到 PostgreSQL，原始文件迁移到 Object Storage，
事件日志升级为结构化 Event Store。为多机部署和规模化奠定基础。

**Prerequisite:** Phase 1-4 全部完成并稳定运行。所有 KnowledgeObject 操作
已经过 Kernel 统一入口。

**Duration estimate:** 6-8 tasks

### 5.1 PostgreSQL — 元数据存储

New files: `src/knowledge/storage/postgres.py`, `src/knowledge/storage/migrations/`

将 WikiPage/KnowledgeObject 的元数据（除 body/content Markdown 外）从文件系统
frontmatter 迁移到 PostgreSQL:

- **存储内容:** id, type, title, lifecycle, confidence, grade, heat, provenance, relations, versions, created_at, updated_at
- **不存储:** body/content (Markdown 正文保留在文件系统，PostgreSQL 存文件路径引用)
- **LanceDB 不变:** 向量嵌入继续由 LanceDB 管理，与 PostgreSQL 并行

**Schema 设计（核心表）:**

```sql
CREATE TABLE knowledge_objects (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,              -- KnowledgeType
    title TEXT NOT NULL,
    lifecycle TEXT NOT NULL DEFAULT 'processing',
    confidence REAL DEFAULT 0.0,
    grade TEXT DEFAULT 'B',
    heat INTEGER DEFAULT 50,
    content_path TEXT NOT NULL,       -- 指向 .md 文件的相对路径
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL
);

CREATE TABLE provenance (
    object_id TEXT PRIMARY KEY REFERENCES knowledge_objects(id),
    source_path TEXT,
    page INTEGER,
    quote TEXT,
    ingested_at BIGINT,
    ingestor_version TEXT,
    source_status TEXT DEFAULT 'active'  -- active|deleted
);

CREATE TABLE relations (
    id SERIAL PRIMARY KEY,
    source_id TEXT REFERENCES knowledge_objects(id),
    target_id TEXT REFERENCES knowledge_objects(id),
    relation_type TEXT NOT NULL,
    created_at BIGINT NOT NULL
);

CREATE TABLE versions (
    id SERIAL PRIMARY KEY,
    object_id TEXT REFERENCES knowledge_objects(id),
    version_id TEXT NOT NULL,
    timestamp BIGINT NOT NULL,
    change_description TEXT,
    snapshot JSONB                     -- 完整 KnowledgeObject 快照
);

CREATE INDEX idx_ko_type ON knowledge_objects(type);
CREATE INDEX idx_ko_lifecycle ON knowledge_objects(lifecycle);
CREATE INDEX idx_ko_heat ON knowledge_objects(heat);
CREATE INDEX idx_relations_source ON relations(source_id);
CREATE INDEX idx_relations_target ON relations(target_id);
```

**FilesystemMetadataStore — 现有文件系统读写封装:**

```python
class FilesystemMetadataStore:
    """封装对 WikiPage frontmatter 的文件系统读写。
    在 storage.backend = "filesystem" 时使用，与 Phase 1-4 行为一致。
    """

    def __init__(self, wiki_path: Path):
        self.wiki_path = wiki_path

    def read(self, object_id: str) -> dict:
        """读取 WikiPage 的 frontmatter + body。"""
        ...

    def write(self, object_id: str, frontmatter: dict, body: str) -> None:
        """原子写入 WikiPage (复用 safe_write)。"""
        ...

    def delete(self, object_id: str) -> None:
        """移动 WikiPage 到 _archive/ (复用现有 archive 逻辑)。"""
        ...

    def list_all(self) -> list[str]:
        """列出所有 KnowledgeObject ID (遍历 wiki/ 子目录)。"""
        ...
```

此类是现有代码中 `page_writer.write_page()`, `WikiPage.from_dict()`, `WikiPage.to_frontmatter_dict()` 的薄封装，不引入新逻辑。

**迁移策略:**

1. **Phase 5 启动时:** 现有 wiki/ 目录的 Markdown 文件仍然可读。`WikiPageAdapter` 同时支持文件读取和 PostgreSQL 读取
2. **迁移命令:** `python -m src.cli storage migrate-to-postgres --project <id>` — 遍历所有 WikiPage，逐条写入 PostgreSQL
3. **验证命令:** `python -m src.cli storage verify-migration --project <id>` — 逐条比对文件系统和 PostgreSQL，报告不一致
4. **回退:** Config flag `storage.backend: "filesystem"|"postgresql"` (default `"filesystem"`)。迁移完成并验证后，手动切换到 `"postgresql"`
5. **迁移完成前，文件系统仍是主数据源。** 迁移后两个数据源并存，直到确认无问题后删除文件系统中的 frontmatter（body 保留）

**Config:**
- `storage.backend` — `"filesystem"` (default) | `"postgresql"`
- `storage.postgresql.url` — PostgreSQL 连接字符串
- 通过环境变量 `DATABASE_URL` 注入，不写在配置文件中

**部署影响:**
- 单机部署: `storage.backend = "filesystem"` (默认，零额外依赖)
- 多机部署: `storage.backend = "postgresql"` + PostgreSQL 实例

### 5.2 Object Storage — 原始文件存储

New file: `src/knowledge/storage/object_store.py`

将原始文件（`raw/sources/` 目录）从本地文件系统迁移到 S3 兼容的对象存储:

- **存储内容:** 原始上传文件（PDF, DOCX, XLSX, HTML, MD, TXT）+ 提取的媒体文件（`wiki/media/`）
- **S3 兼容:** 支持 AWS S3, Cloudflare R2, MinIO, 本地文件系统（通过 S3 API 适配层）
- **文件系统 fallback:** 对象存储不可用时自动回退到本地文件系统

**实现:**

```python
class ObjectStore(ABC):
    """对象存储抽象。支持 S3 兼容 + 本地文件系统 fallback。"""

    async def put(self, key: str, data: bytes, content_type: str) -> str: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...
    async def exists(self, key: str) -> bool: ...
    def public_url(self, key: str) -> str: ...

class S3ObjectStore(ObjectStore):
    """S3 兼容实现 (boto3)。"""

class LocalObjectStore(ObjectStore):
    """本地文件系统实现 — 单机部署默认。"""
```

**迁移策略:**
- Config flag `storage.object_store.backend: "local"|"s3"` (default `"local"`)
- `"local"` 模式下，ObjectStore 直接读写 `raw/sources/` 和 `wiki/media/`，与现有行为完全一致
- 切换到 `"s3"` 时，提供迁移命令: `python -m src.cli storage migrate-to-s3 --project <id>`
- 迁移完成后，本地 `raw/sources/` 可保留为缓存或删除

**Config:**
- `storage.object_store.backend` — `"local"` (default) | `"s3"`
- `storage.object_store.s3.endpoint_url` — S3 endpoint
- `storage.object_store.s3.bucket` — bucket 名称
- `storage.object_store.s3.access_key` / `secret_key` — 凭证（通过环境变量注入）

### 5.3 Event Store — 结构化事件存储

New file: `src/knowledge/storage/event_store.py`

将 Phase 2 的 JSONL 事件日志升级为结构化 Event Store:

- **当前 (Phase 2):** `.index/knowledge_graph/events.jsonl` — append-only JSONL 文件
- **Phase 5 升级:** 事件表写入 PostgreSQL（或独立的 SQLite），支持高效查询和重放

**Event Store schema:**

```sql
CREATE TABLE events (
    id BIGSERIAL PRIMARY KEY,
    stream_id TEXT NOT NULL,          -- 事件流标识 (object_id, graph_id, etc.)
    event_type TEXT NOT NULL,         -- knowledge.created|lifecycle.changed|graph.upsert_node|...
    event_version INTEGER NOT NULL,   -- stream 内单调递增
    payload JSONB NOT NULL,           -- 事件体
    occurred_at BIGINT NOT NULL,      -- Unix ms
    recorded_at BIGINT NOT NULL       -- 写入时间
);

CREATE INDEX idx_events_stream ON events(stream_id, event_version);
CREATE INDEX idx_events_type ON events(event_type);
CREATE INDEX idx_events_occurred ON events(occurred_at);
```

**JSONLEventStore — 现有 JSONL 事件读写封装:**

```python
class JSONLEventStore:
    """封装对 events.jsonl 的 append-only 读写。
    在 storage.event_store.backend = "jsonl" 时使用，与 Phase 2-4 行为一致。
    """

    def __init__(self, index_path: Path):
        self.events_path = index_path / "knowledge_graph" / "events.jsonl"

    def append(self, event: dict) -> None:
        """追加单条事件 (JSONL append, 线程安全)。"""
        ...

    def read_all(self, since_version: int | None = None) -> list[dict]:
        """读取事件列表，支持从指定版本增量读取。"""
        ...

    def count(self) -> int:
        """返回事件总数。"""
        ...
```

此类是 Phase 2 GraphBuilder 中 JSONL 操作的薄封装。在 Phase 2-4 期间 GraphBuilder
直接操作 events.jsonl；Phase 5 通过 JSONLEventStore 统一接口访问。

**与 JSONL 的关系:**
- JSONL 在 Phase 2-4 期间作为轻量方案继续使用
- Phase 5 Event Store 提供相同的事件格式（upsert_node, delete_node, upsert_edge, delete_edge），但查询能力更强
- Config flag `storage.event_store.backend: "jsonl"|"postgresql"` (default `"jsonl"`)
- 迁移: `python -m src.cli storage migrate-events --project <id>` — 将 JSONL 内容导入 Event Store

**重放保证:**
- 无论 JSONL 还是 PostgreSQL，事件重放逻辑完全相同（加载事件列表 → 按序重建状态）
- Snapshot 机制不变：每 100 次事件或每天一次全量快照

### 5.4 Storage facade — 统一存储入口

New file: `src/knowledge/storage/facade.py`

```python
class StorageFacade:
    """统一存储入口 — KnowledgeKernel 通过此层访问所有存储后端。

    封装了对 PostgreSQL / ObjectStore / EventStore / LanceDB 的访问，
    根据 config flag 决定使用哪个后端。
    """

    def __init__(self, config: StorageConfig):
        self.metadata = PostgresMetadataStore(config.postgresql_url) \
            if config.backend == "postgresql" \
            else FilesystemMetadataStore(config.wiki_path)
        self.objects = S3ObjectStore(config.s3) \
            if config.object_store_backend == "s3" \
            else LocalObjectStore(config.wiki_path)
        self.events = PostgresEventStore(config.postgresql_url) \
            if config.event_store_backend == "postgresql" \
            else JSONLEventStore(config.index_path)
        self.vectors = LanceDBVectorStore(config.index_path)  # 不变
```

**与 KnowledgeKernel 的关系:**

Phase 1-4 期间，Kernel 的持久化由 commit_ingest（原子写 WikiPage 文件）和
Indexer（向量嵌入 + 图谱事件 JSONL）共同完成。Kernel 不直接访问存储后端。

Phase 5 引入 StorageFacade 后，存储层从 Kernel 中解耦:

```
Agent → KnowledgeKernel (权限 + 生命周期 + 事件)
           ↓
       StorageFacade (元数据 CRUD + 对象读写 + 事件追加)
           ↓
   ┌───────┼───────┐
   │       │        │
PostgreSQL  S3    EventStore
(metadata) (blobs) (events)
```

- KnowledgeKernel 的 `create_object()` / `update_object()` 在 Phase 5 中委托给 StorageFacade 执行实际读写
- StorageFacade 是 Kernel 的**存储后端抽象**，不重复 Kernel 的权限检查/生命周期/事件发布逻辑
- Phase 1-4: Kernel → commit_ingest + Indexer（文件系统路径）
- Phase 5: Kernel → StorageFacade → PostgreSQL/S3/EventStore（可切换后端）
- 过渡期: Config flag `storage.backend` 控制走哪条路径。`"filesystem"` 时行为与 Phase 1-4 完全一致

**Config flags (Phase 5):**

| Flag | Default | 说明 |
|------|---------|------|
| `storage.backend` | `"filesystem"` | metadata: filesystem \| postgresql |
| `storage.object_store.backend` | `"local"` | object: local \| s3 |
| `storage.event_store.backend` | `"jsonl"` | events: jsonl \| postgresql |
| `storage.postgresql.url` | — | 环境变量 `DATABASE_URL` |
| `storage.object_store.s3.*` | — | S3 连接参数 |

### 5.5 Phase 5 tests

New files:
- `tests/test_knowledge/test_storage_postgres.py` — 含迁移+验证测试
- `tests/test_knowledge/test_storage_object_store.py` — S3 + local + fallback
- `tests/test_knowledge/test_storage_event_store.py` — JSONL→PostgreSQL 迁移+重放一致性
- `tests/test_knowledge/test_storage_facade.py` — StorageFacade 后端切换

**Phase 5 verification:**
- `storage.backend = "filesystem"` 时所有现有测试通过（向后兼容）
- 迁移命令正确将文件系统数据导入 PostgreSQL
- 验证命令逐条比对并报告差异
- ObjectStore local/S3 切换后文件读写一致
- Event Store JSONL→PostgreSQL 迁移后重放结果一致
- StorageFacade 根据 config flag 正确选择后端
- `python -m src.cli serve` + `/health` 200（三种存储后端均可用）

---

## Cross-Phase Constraints

1. **WikiPage compatibility throughout.** `WikiPage.from_dict()` / `to_frontmatter_dict()` must accept and preserve all new fields as optional. `_ko_extra` 嵌套 YAML 键用于存储 KnowledgeObject 特有字段，不影响现有 frontmatter 解析。

2. **Phase 1-4: no new database dependency.** PostgreSQL (metadata), Object Storage/S3 (blobs), and Event Store are implemented in Phase 5. 知识图谱使用 JSONL append-only log + periodic snapshot 代替单 JSON 文件。Phase 4 结束后启动 Phase 5 存储迁移。

3. **One commit per task.** TDD: write test → fail → implement → pass → commit. 有依赖的 task 允许先写 interface/stub 再在后续 task 中实现。

4. **Backward-compatible MCP.** Old tools stay functional. New `memory.*` tools are additive. Deprecation notices in tool descriptions.

5. **Config flags for new behavior.** Each new feature gated by a config flag defaulting to `false`. Full list of flags:

   | Flag | Default | Phase |
   |------|---------|-------|
   | `analyzer.output_format` | `"markdown"` | 1 |
   | `knowledge.candidate_layer.enabled` | `false` | 1 |
   | `search.reranker.enabled` | `false` | 3 |
   | `curator.dry_run` | `true` | 4 |
   | `curator.auto_apply` | `false` | 4 |
   | `curator.max_objects_per_run` | `100` | 4 |
   | `researcher.allowed_domains` | `["*"]` | 4 |
   | `storage.backend` | `"filesystem"` | 5 |
   | `storage.object_store.backend` | `"local"` | 5 |
   | `storage.event_store.backend` | `"jsonl"` | 5 |

6. **Server runtime smoke test after every phase.** `python -m src.cli serve --port <free>` + `curl /health` must pass.

7. **All LLM calls go through `LLM.complete()` unified entry point** (existing circuit breaker + retry). No raw `openai.chat.completions.create()` or `anthropic.messages.create()` calls.

8. **Phase isolation.** 每个 Phase 必须可独立部署和回滚。Phase N 功能在 config flag 关闭时完全不可见。Phase N+1 读取 Phase N 写入的数据时，使用兼容读取（接受旧格式 + 新格式），Phase N+1 的 ClaimParser 可直接消费 Phase 1 的 opaque dict。破坏性格式变更（如字段重命名）需包含迁移代码，但前向兼容读取不需要迁移。

---

## File Map (all new files by phase)

```
src/knowledge/                    # NEW top-level package
├── __init__.py                   # Phase 1
├── kernel.py                     # Phase 1 — KnowledgeKernel (统一入口)
├── core/
│   ├── __init__.py               # Phase 1
│   ├── object.py                 # Phase 1 — KnowledgeObject + KnowledgeType + Provenance
│   ├── adapter.py                # Phase 1 — WikiPage ↔ KnowledgeObject
│   ├── version_manager.py        # Phase 1 — VersionManager
│   ├── lifecycle.py              # Phase 1 — LifecycleEngine
│   ├── candidate.py              # Phase 1 — KnowledgeCandidate (opaque claims)
│   └── concurrency.py            # Phase 4 — optimistic locking
├── claims/
│   ├── __init__.py               # Phase 2
│   ├── model.py                  # Phase 2 — Claim + Evidence
│   └── parser.py                 # Phase 2 — ClaimParser (opaque dict → Claim)
├── provenance/
│   ├── __init__.py               # Phase 2
│   └── tracker.py                # Phase 2 — ProvenanceTracker
├── conflicts/
│   ├── __init__.py               # Phase 2
│   └── detector.py               # Phase 2 — ConflictDetector
├── graph/
│   ├── __init__.py               # Phase 2
│   └── builder.py                # Phase 2 — GraphBuilder (JSONL + snapshot)
├── memory/
│   ├── __init__.py               # Phase 3
│   ├── types.py                  # Phase 3 — MemoryType enum
│   ├── decision.py               # Phase 3 — DecisionRecorder (+ outcome update)
│   └── retrieval.py              # Phase 3 — MemoryRetrieval
├── lifecycle/
│   └── decay.py                  # Phase 4 — knowledge decay
├── evolution/
│   ├── __init__.py               # Phase 4
│   ├── loop.py                   # Phase 4 — EvolutionLoop
│   └── scheduler.py              # Phase 4 — EvolutionScheduler
└── storage/                      # Phase 5 — Storage Evolution
    ├── __init__.py               # Phase 5
    ├── facade.py                 # Phase 5 — StorageFacade (统一存储入口)
    ├── postgres.py               # Phase 5 — PostgreSQL metadata store
    ├── object_store.py           # Phase 5 — S3/local ObjectStore
    ├── event_store.py            # Phase 5 — structured Event Store
    └── migrations/               # Phase 5 — DB migration scripts

src/agent/
├── collector.py                  # Phase 1 — CollectorAgent (独立 Agent)
├── curator.py                    # Phase 4 — CuratorAgent (dry_run safe mode)
├── historian.py                  # Phase 4 — HistorianAgent
└── researcher.py                 # Phase 4 — ResearcherAgent (PROCESSING gate)

src/mcp_server/
└── memory_tools.py               # Phase 3 — memory.* MCP tools

src/pipeline/
├── analyzer.py                   # Modified Phase 1 — JSON output + 3-tier validation
├── generator.py                  # Modified Phase 1 — GeneratorOutputValidator
└── stages/
    ├── reviewer.py               # Phase 1 — ReviewerStage (rule engine)
    ├── candidate_promoter.py     # Phase 1 — CandidatePromoter
    └── indexer.py                # Phase 2 — IndexerStage

src/searcher/
├── query_understanding.py        # Phase 3 — QueryUnderstanding
└── reranker.py                   # Phase 3 — Reranker

src/cli_ext/
├── provenance_cmd.py             # Phase 2
├── conflicts_cmd.py              # Phase 2
├── memory_cmd.py                 # Phase 3
└── curate_cmd.py                 # Phase 4

tests/test_knowledge/
├── __init__.py
├── conftest.py                   # Phase 1
├── test_object.py                # Phase 1
├── test_adapter.py               # Phase 1
├── test_version_manager.py       # Phase 1
├── test_lifecycle.py             # Phase 1
├── test_candidate.py             # Phase 1
├── test_kernel.py                # Phase 1 — KnowledgeKernel assembly
├── test_claims.py                # Phase 2
├── test_claim_parser.py          # Phase 2
├── test_provenance.py            # Phase 2
├── test_conflicts.py             # Phase 2
├── test_graph.py                 # Phase 2
├── test_memory_types.py          # Phase 3
├── test_decision.py              # Phase 3
├── test_memory_retrieval.py      # Phase 3
├── test_decay.py                 # Phase 4
├── test_evolution.py             # Phase 4
├── test_evolution_scheduler.py   # Phase 4
├── test_concurrency.py           # Phase 4
├── test_storage_postgres.py      # Phase 5 — migration + verify
├── test_storage_object_store.py  # Phase 5 — S3/local/fallback
├── test_storage_event_store.py   # Phase 5 — JSONL→PG migration
└── test_storage_facade.py        # Phase 5 — backend switching

tests/test_agent/
├── test_collector.py             # Phase 1 — CollectorAgent
├── test_curator.py               # Phase 4
├── test_historian.py             # Phase 4
└── test_researcher.py            # Phase 4

tests/test_pipeline/
├── test_analyzer_json.py         # Phase 1
├── test_generator_constraint.py  # Phase 1
├── test_reviewer.py              # Phase 1 — ReviewerStage (rule-based)
├── test_candidate_promoter.py    # Phase 1 — Candidate→KnowledgeObject
└── test_indexer.py               # Phase 2

tests/test_searcher/
├── test_query_understanding.py   # Phase 3
└── test_reranker.py              # Phase 3

tests/test_mcp_server/
└── test_memory_tools.py          # Phase 3
```

---

## Phase 1 Detailed Task Breakdown

### Task 1.0: Extend PageType enum + WikiPaths
- Files: modify `src/wiki/core/types.py`, `src/wiki/core/paths.py`, `src/wiki/storage/ensure.py`
- PageType 新增 claim/decision/procedure/event。`_TYPE_TO_DIR` 映射。WikiPaths 新属性。ensure_knowledge_base 新目录
- Test: 现有 748 测试通过 + 新 PageType 值可正常序列化/反序列化

### Task 1.1: Create `src/knowledge/` package skeleton
- Files: `__init__.py`, `core/__init__.py`
- Test: `import src.knowledge` succeeds

### Task 1.2: KnowledgeObject + KnowledgeType + Provenance
- Files: `src/knowledge/core/object.py`
- `KnowledgeType` enum (与扩展后 PageType 1:1), `LifecycleState` enum, `Provenance` dataclass, `VersionRef` dataclass, `KnowledgeObject` dataclass
- Test: `tests/test_knowledge/test_object.py`

### Task 1.3: WikiPage ↔ KnowledgeObject adapter
- Files: `src/knowledge/core/adapter.py`
- 双向转换 + 往返无损 (`_ko_extra` 嵌套 YAML 存储额外字段)
- Test: `tests/test_knowledge/test_adapter.py`

### Task 1.4: VersionManager
- Files: `src/knowledge/core/version_manager.py`
- `snapshot()`, `get_history()`, `diff()`。保留策略: 最近 50 个 + 关键生命周期点
- Test: `tests/test_knowledge/test_version_manager.py`

### Task 1.5: LifecycleEngine
- Files: `src/knowledge/core/lifecycle.py`
- `can_transition()`, `transition()`。15 边合法转换图
- Test: `tests/test_knowledge/test_lifecycle.py`

### Task 1.6: KnowledgeCandidate (opaque claims)
- Files: `src/knowledge/core/candidate.py`
- `claims: list[dict]`, `evidence: list[dict]` — opaque，Phase 2 结构化
- Test: `tests/test_knowledge/test_candidate.py`

### Task 1.7: Analyzer JSON output + 3-tier validation
- Files: modify `src/pipeline/analyzer.py`
- JSON prompt, `AnalyzerOutputParser` (syntax→schema→content)
- Config flag: `analyzer.output_format`
- Test: `tests/test_pipeline/test_analyzer_json.py`

### Task 1.8: Generator role constraint
- Files: modify `src/pipeline/generator.py`
- `GeneratorOutputValidator`, 纯渲染
- Test: `tests/test_pipeline/test_generator_constraint.py`

### Task 1.9: ReviewerStage (规则引擎)
- Files: `src/pipeline/stages/reviewer.py`
- 纯规则检查: Schema合规/证据存在/引用一致/置信度阈值 (不检测幻觉，不用 LLM)
- Phase 4 可选升级为 LLM-assisted Reviewer
- Permission: `candidate.approve`。幂等性保证
- Test: `tests/test_pipeline/test_reviewer.py`

### Task 1.10: CandidatePromoter
- Files: `src/pipeline/stages/candidate_promoter.py`
- VALIDATED Candidate → KnowledgeObject(lifecycle=PROCESSING)，共享 ID
- Candidate 状态 → PROMOTED
- Test: `tests/test_pipeline/test_candidate_promoter.py`

### Task 1.11: CollectorAgent — 独立 Agent
- Files: `src/agent/collector.py`, modify `src/permissions.py`
- 新增 `AgentType.COLLECTOR`，权限 `raw.create` + `raw.read`
- 封装现有 Collector pipeline 逻辑，增加权限检查 + 事件发布 (`document.collected`)
- Pipeline 事件 `collector:start` / `collector:done` 保持触发
- Test: `tests/test_agent/test_collector.py`

### Task 1.12: KnowledgeKernel assembly
- Files: `src/knowledge/kernel.py`
- 组装 5 个子系统: PermissionEngine (封装), EventBus (封装), LifecycleEngine, VersionManager, KnowledgeObject 工厂
- 统一入口: `create_object()`, `update_object()`, `transition_lifecycle()`, `get_history()`
- Agent 代码通过 Kernel 访问知识基础设施
- Test: `tests/test_knowledge/test_kernel.py`
