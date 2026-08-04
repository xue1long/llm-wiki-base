# LLM-Wiki（ruflo-kb）项目架构文档 v2.1

> 版本：v2.1 ｜ 更新日期：2026-08-04
> 产品代号：**ruflo-kb**（配置目录 `~/.config/ruflo-kb/`）｜ 仓库目录：`LLM-Wiki`
> 本文档为**单一可信源**，整合自：
> - 演进方案可行性验证报告
> - 标签命名空间配置评估
> - 摄取流程完善方案（v1.1，决策已锁定）
> - 对 `LLM-Wiki/src/` 的实地代码核查（2026-08-03）
> - **v2.1 更新**：WikiPage 时间戳改为 ISO 8601 格式（2026-08-04）
>
> 它取代了先前分散的 `KNOWLEDGE_OS_EVOLUTION_FEASIBILITY_REPORT.md`、`tag-namespace-evaluation.md` 等文档中的重复描述。

---

## 目录

1. [系统定位与核心能力](#1-系统定位与核心能力)
2. [当前真实状态（必读）](#2-当前真实状态必读)
3. [整体架构图](#3-整体架构图)
4. [接口层](#4-接口层)
5. [服务层](#5-服务层)
6. [流水线层（Pipeline）](#6-流水线层pipeline)
7. [知识层（Knowledge OS — 已建未接）](#7-知识层knowledge-os--已建未接)
8. [数据模型层（Wiki v2）](#8-数据模型层wiki-v2)
9. [存储层](#9-存储层)
10. [LLM Provider 层](#10-llm-provider-层)
11. [检索层](#11-检索层)
12. [治理层（Governance）](#12-治理层governance)
13. [基础设施层](#13-基础设施层)
14. [标签命名空间评估要点](#14-标签命名空间评估要点)
15. [已知问题与技术债务](#15-已知问题与技术债务)
16. [演进路线与文档地图](#16-演进路线与文档地图)

---

## 1. 系统定位与核心能力

LLM-Wiki 是一个**多 Agent 知识库平台**：将原始文档（PDF/DOCX/XLSX/HTML/MD/TXT/URL）转化为结构化 Wiki 知识库，提供混合检索和 MCP 集成。

**核心能力**：

| 维度 | 能力 |
|------|------|
| 摄取 | 7 种格式（PDF/DOCX/XLSX/HTML/MD/TXT/URL），含 SSRF 防护与 CJK 编码修复 |
| 处理 | Collector → Analyzer → Generator 三阶段 LLM 流水线（旧路径）；Candidate → Reviewer → Promoter 分层验证（新路径，已建未接） |
| 存储 | 文件系统 Markdown（source of truth）+ LanceDB 派生向量索引 |
| 检索 | 向量搜索 + 关键词搜索 + RRF 融合 |
| 服务 | HTTP API（FastAPI）+ MCP Server（stdio）+ CLI 三入口 |
| 治理 | Sanitizer / QualityGate / QualityJudge / NDG Gate / Lint / Dedup / Heat / Schema 迁移 |

**5 个关键设计决策**：

1. **文件系统 Markdown 是 source of truth**，LanceDB 仅派生向量索引
2. **LLM 不应直接写最终知识**（目标流程：LLM → Candidate → Validation → Knowledge）——旧路径未严格遵守，新路径已落实
3. **事件驱动**：`EventBus` 模块级单例驱动流水线各阶段
4. **原子写入**：`AtomicContext` + `safe_write` + `DELETE_SENTINEL`
5. **Schema 版本化**：v1.0 → v3.0 可逆迁移（⚠️ v2.1/v2.2 注册有 bug，见 §15）

---

## 2. 当前真实状态（必读）

> 理解本系统最大的陷阱是：**文档描述的"新架构"代码已写好，但生产流量并未走它。**

### 2.1 两条路径并存

```
【路径 A — 旧路径（生产运行中，流量 100% 在此）】
collector:start
  → CollectorStage（读取文件/URL）
  → run_ingest()
       ├── analyze()         [markdown 模式 → AnalysisResult]
       ├── generate()        [两步法]  或  unified_generate() [单步法，绕过验证]
       ├── QualityGate       [3 条规则]
       ├── QualityJudge      [默认关闭]
       └── Atomic Write      → wiki/*.md + index.md + log.md + LanceDB
  实际执行：service.py 仅跑 self._stages[:1]（Collector）+ 旧 run_ingest()

【路径 B — 新路径（Knowledge OS，代码就绪，生产零调用）】
analyzer.py     output_format="json" → KnowledgeCandidate   ✅ 代码存在
stages/reviewer.py        ReviewerStage（4 项规则检查）      ✅ 代码存在
stages/candidate_promoter.py  Candidate → KnowledgeObject   ✅ 代码存在
generator_constraint.py   GeneratorOutputValidator         ✅ 代码存在
knowledge/*（core/claims/conflicts/evolution/graph/memory/provenance/storage）
                          KnowledgeObject/Lifecycle/VersionManager/Kernel ✅ 代码存在
```

### 2.2 关键事实清单

| # | 事实 | 证据 | 影响 |
|---|------|------|------|
| 1 | 默认 stage 列表不含 Reviewer/Promoter | `src/pipeline/service.py:52` → `[CollectorStage, AnalyzerStage, GeneratorStage]` | 新验证层形同虚设 |
| 2 | collector-start 只跑 `self._stages[:1]` | `service.py:108` | 新路径完全不触发 |
| 3 | `analyze()` 默认 `output_format="markdown"`，无人传 `"json"` | `analyzer.py` 签名默认值 | Candidate 层不被激活 |
| 4 | `knowledge/` 包已相当完整（33 个 .py 文件） | `src/knowledge/**` | 不是从零开始，而是"接线工程" |
| 5 | `unified_generate()` 单步法绕过全部分层 | `generator.py:440-642` | 违反"LLM 不直接写知识"原则 |

**结论**：系统当前是一个**架构先进但接线未完成的半成品**。所有演进所需的基础设施（KnowledgeObject、Candidate、Reviewer、Promoter、VersionManager、Lifecycle、Provenance）都已写好并通过测试——缺的是把它们接入 `PipelineService.run_ingest()` 并切换流量（详见"摄取流程完善方案"）。

### 2.3 演进就绪度速览

| 组件 | 状态 | 说明 |
|------|------|------|
| WikiPage / PageType | ✅ 生产 | 4 型：source/entity/concept/synthesis |
| Collector / Analyzer / Generator | ✅ 生产 | 旧路径运行 |
| QualityGate / Sanitizer / NDG Gate | ✅ 生产 | 治理生效 |
| KnowledgeObject（8 型） | 🟡 已建未接 | document/entity/concept/claim/decision/procedure/event/synthesis |
| Lifecycle（8 态） | 🟡 已建未接 | created→processing→reviewing→active→... |
| KnowledgeCandidate | 🟡 已建未接 | pending/validated/rejected/promoted |
| VersionManager | 🟡 已建未接 | 历史快照 |
| ReviewerStage / CandidatePromoter | 🟡 已建未接 | 验证链 |
| 图 / 记忆 / 演化 / 冲突检测 | 🟡 已建未接 | claims/conflicts/evolution/graph/memory/provenance/storage 子包齐全 |
| KnowledgeKernel 组装 | ✅ 已建 | `src/knowledge/kernel.py` 存在 |
| 新路径接入生产 | ❌ 未开始 | **本系统最大缺口** |

---

## 3. 整体架构图

```
┌──────────────────────────────────────────────────────────────┐
│                        接口层 (Interfaces)                    │
│  CLI (argparse, 21 模块)   HTTP API (FastAPI, 12 路由)   MCP │
│                              │  api_client.py (MCP 委托 HTTP)  │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                    服务层 (Services, 10 模块)                  │
│  ingest / search / projects / files / schema / reviews /      │
│  chat / tags / wiki_analysis                                  │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                    流水线层 (Pipeline)                         │
│                                                              │
│  【路径 A — 运行】 Collector → run_ingest → Atomic Write      │
│  【路径 B — 未接】 Collector → Analyzer(json) → Candidate     │
│                  → Reviewer → Promoter → Generator → Commit   │
└───────────────┬──────────────────────────────┬───────────────┘
                │                               │
                ▼                               ▼
┌──────────────────────────┐   ┌────────────────────────────────┐
│  数据模型层 (Wiki v2)     │   │  知识层 (Knowledge OS, 未接)    │
│  WikiPage (17 字段)       │   │  KnowledgeObject (8 型)         │
│  Relation (17 类型)       │   │  KnowledgeCandidate            │
│  KnowledgeTask (9 态)     │   │  Lifecycle / VersionManager    │
│                          │   │  Kernel / Graph / Memory       │
└────────────┬─────────────┘   └────────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────────────────────────┐
│                     存储层 (Storage)                           │
│  文件系统 (source of truth)        LanceDB (派生向量索引)       │
│  wiki/ + raw/sources/ + .llm-wiki/ + .index/    chunks 表      │
│  队列持久化: .kb-queue.json                                │
└──────────────────────────────────────────────────────────────┘

横切能力（任意层可调用）：
  LLM Provider 层（OpenAI/Anthropic/Ollama/Compatible）
  检索层（hybrid_search + RRF）
  治理层（QualityGate/Judge/NDG/Lint/Dedup/Heat）
  基础设施层（权限/断路器/队列/幂等/项目/指标）
```

---

## 4. 接口层

### 4.1 CLI
- 入口：`src/cli.py`（argparse）；子命令在 `src/cli_ext/`（21 个模块）
- 调用：`python -m src.cli <command>`
- 分类：项目管理 / LLM 配置 / 模板 / 服务 / 健康检查 / 关系 / 字段验证 / 标签 / 热度 / 占位页 / 去重 / Lint / Schema / MCP / 研究 / 缓存 / 指标 / 视觉
- ⚠️ **部分命令直接调用 `wiki/features` 和 `pipeline` 模块，绕过 Services 层**

### 4.2 HTTP API
- 入口：`src/server/app.py` → `create_app()`（FastAPI）
- 路由：`src/server/routes/`（12 模块，见 §5）
- 启动：`python -m src.cli serve --host 127.0.0.1 --port 8765`
- Lifespan：初始化 Embedding → LanceDB → 自动发现项目 → 健康检查 → 队列恢复 → 后台缓存清理
- ⚠️ **Web UI**：`app.py` 有条件挂载代码，但 `web/` 目录不存在，**当前未启用**
- 文件夹摄取路由接受 `{"source": {"folder": ...}}` 但**未枚举目录**（未接线）

### 4.3 MCP Server
- 入口：`src/mcp_server/main.py`（stdio）
- 链路：**MCP → `api_client.py` → HTTP API → routes → Services**（多一层网络跳转，非直接调 Services）
- 8 个工具：`ruflo_kb_status` / `projects` / `set_project` / `files` / `read_file` / `search` / `ingest` / `reviews`

---

## 5. 服务层

目录：`src/services/`（10 模块）。原则：依赖 `src.lib.*` 和 `src.wiki.*`，**不依赖** `src.server.*`；HTTP routes 是 thin adapter。

| 模块 | 关键函数 | 说明 |
|------|----------|------|
| `ingest.py` | `enqueue_source()` | 确定 SourceType，生成幂等哈希，入队 |
| `search.py` | `search()` | 委托 `hybrid_search()`，支持 page_type 后过滤 |
| `projects.py` | 项目 CRUD | 创建/列出/导入/遗忘/重命名 |
| `files.py` | 文件列表/读取 | Wiki 文件树浏览 |
| `schema.py` | Schema 管理 | 版本查询/迁移执行 |
| `reviews.py` | 评审项管理 | 列出/解决评审项 |
| `chat.py` | 聊天 | 对话式交互 |
| `tags.py` | 标签验证 + 索引 | `build_tag_index()` 聚合视图 |
| `wiki_analysis.py` | Wiki 分析 | 页面统计 |

---

## 6. 流水线层（Pipeline）

### 6.1 双层架构

函数式实现 + Stage Protocol 包装器：

| 层 | 文件 | 说明 |
|---|------|------|
| 抽象 | `src/pipeline/ports.py` | `PipelineContext` / `StageResult` / `PipelineStage` |
| Stage 包装器 | `stages/collector.py` `stages/analyzer.py` `stages/generator.py` | 包装函数式实现 |
| 函数式 | `collector.py` `analyzer.py` `generator.py` | 实际逻辑 |
| 核心入口 | `ingest.py` | `run_ingest()` / `generate_ingest()` / `commit_ingest()` |
| 编排 | `runner.py` `service.py` `dispatcher.py` | `PipelineRunner` / `PipelineService` / 事件分发 |

> ⚠️ **`stages/reviewer.py` 与 `stages/candidate_promoter.py` 虽存在，但不在 `service.py` 默认 stage 列表**（见 §2.2）。

### 6.2 旧路径（路径 A）详解

**Collector**（`collector.py`）：`collect(task_id, source, source_type, project_id) → CollectorDonePayload`
- 支持 PDF(fitz) / DOCX(python-docx) / XLSX(openpyxl) / MD-TXT(CJK 检测) / HTML(仅 URL) / URL(SSRF 防护)
- 权限：`raw/sources` READ + WRITE（白名单）

**Analyzer**（`analyzer.py`）：`analyze(source_text) → AnalysisResult`
- 单次 LLM 调用（JSON 解析失败重试 1 次）
- 输出：`summary` / `key_facts` / `entities` / `concepts` / `suggested_pages`(PageSpec) / `links_to_existing`
- ⚠️ 默认 markdown 模式；JSON 模式存在但无人调用

**Generator**（`generator.py`）：`generate()` + `unified_generate()`
- 两步法：`generate()` 填充模板槽位
- 统一法：`unified_generate()` 合并 Analyze+Generate 为单次调用（**默认路径**，绕过分层）
- 确定性补全（与"只渲染"原则冲突）：`_auto_fill_deterministic_slots()` / `_ensure_required_slots_filled()` / `_sanitize_generated_id()` / Wikilink 修复

### 6.3 新路径（路径 B）设计（接线后）

```
CollectorStage → Sanitizer → AnalyzerStage(json) → KnowledgeCandidate(PENDING)
  → ReviewerStage (VALIDATED / NEEDS_HUMAN_REVIEW / REJECTED)
  → CandidatePromoter → KnowledgeObject(lifecycle=PROCESSING)
  → GeneratorStage(只渲染, 从 KO 复制 frontmatter) → GeneratorOutputValidator
  → QualityGate + QualityJudge → commit_ingest()
  → VersionManager.snapshot() + lifecycle=ACTIVE
```

**已锁定决策**（见摄取方案 v1.1）：
- ❌ 禁用 `unified_generate`，统一走两步法（无 fast_path 逃生门）
- ⛔ `NEEDS_HUMAN_REVIEW` 阻断流水线，转人工评审队列（不降级写入）
- `output_format="json"` 成为 `run_ingest` 默认

### 6.4 质量门控（流水线内）

| 层级 | 组件 | 位置 | 触发时机 |
|------|------|------|----------|
| 1 | Sanitizer | `pipeline/sanitizer.py` | Collector 后，Analyzer 前 |
| 2 | QualityGate | `pipeline/quality_gate.py` | Generator 后，写入前（3 规则：PREFIX_GHOST/EMPTY_BODY/INTRA_BATCH_DUPE） |
| 3 | QualityJudge | `quality/judge.py` | 写入前（**默认关闭**，6 维评分，阈值 0.7） |
| 4 | EnsembleJudge | `quality/ensemble.py` | `ensemble_judges` 非空时（多 Judge + 事实性 veto） |
| 5 | HardAudit | `orchestrator/audit_hard.py` | Orchestrator 执行 |
| 6 | QuarantineStore | `quality/quarantine.py` | LLM Judge 拒绝时隔离 |

### 6.5 事件驱动

`EventBus`（`events/event_bus.py`）：模块级单例，9 种事件，快照迭代 + 异常隔离。并发控制 `asyncio.Semaphore(max_concurrency=6)`。

---

## 7. 知识层（Knowledge OS — 已建未接）

> 这是系统最大的"隐藏资产"。代码完整、测试通过，但生产未接线。本节描述其真实结构（基于 `src/knowledge/` 实地核查）。

### 7.1 包结构（33 个 .py）

```
src/knowledge/
├── __init__.py
├── kernel.py                  ← KnowledgeKernel Facade（已建）
├── core/                      ← 核心对象
│   ├── object.py              KnowledgeObject / KnowledgeType(8) / LifecycleStatus(8) / Provenance
│   ├── candidate.py           KnowledgeCandidate / CandidateStatus(4)
│   ├── adapter.py             WikiPage ↔ KnowledgeObject 适配器
│   ├── lifecycle.py           LifecycleEngine
│   ├── version_manager.py     VersionManager（历史快照）
│   └── concurrency.py
├── claims/                    Claim 模型 + 解析器
├── conflicts/                 ConflictDetector（CONTRADICTS 自动检测）
├── evolution/                 EvolutionLoop / Scheduler（自主演化，未定义）
├── graph/                     GraphBuilder（图谱节点扩展）
├── lifecycle/                 decay.py（热度衰减下沉）
├── memory/                    Decision 记忆 + 检索 + 类型
├── provenance/                ProvenanceTracker（细粒度溯源）
└── storage/                   event_store / metadata / object_store / wiki_adapter / facade
```

### 7.2 KnowledgeObject 核心定义

```python
# knowledge/core/object.py
class KnowledgeType(str, Enum):
    DOCUMENT = "document"     ENTITY = "entity"       CONCEPT = "concept"
    CLAIM = "claim"          DECISION = "decision"   PROCEDURE = "procedure"
    EVENT = "event"          SYNTHESIS = "synthesis"   # 8 型

class LifecycleStatus(str, Enum):
    CREATED / PROCESSING / REVIEWING / ACTIVE /
    DEPRECATED / ARCHIVED / FAILED / REJECTED         # 8 态

class Provenance:
    quote: str                # 原文引用片段
    page: int                 # 页码
    ingestor_version: str
    change_description: str   # 变更描述

class KnowledgeObject:
    id / title / type / grade("A"|"B"|"C") / lifecycle / provenance / ...
```

> 对比 WikiPage（§8）：KnowledgeObject 是更丰富的超集——多了 `claim/decision/procedure/event` 型、`lifecycle` 状态机、`confidence`、`provenance`（页码+引用）、`versions`（VersionManager 提供）。WikiPage 经 `core/adapter.py` 双向兼容。

### 7.3 KnowledgeCandidate

```python
class CandidateStatus(str, Enum):
    PENDING / VALIDATED / REJECTED / PROMOTED
# can_transition() 状态机守卫

class KnowledgeCandidate:
    status: CandidateStatus = PENDING
    # 承载 Analyzer JSON 输出 + Reviewer 判定 + Promoter 提升结果
```

### 7.4 支撑组件

| 组件 | 文件 | 职责 |
|------|------|------|
| VersionManager | `core/version_manager.py` | 每次变更前快照，支持历史重建 |
| LifecycleEngine | `core/lifecycle.py` | 8 态状态机驱动 |
| ProvenanceTracker | `provenance/tracker.py` | 细粒度溯源（page + quote） |
| ConflictDetector | `conflicts/detector.py` | CONTRADICTS 关系自动检测 |
| GraphBuilder | `graph/builder.py` | Claim 级图谱节点扩展 |
| Memory（Decision） | `memory/` | Decision 记忆类型 + 检索 |
| EventStore | `storage/event_store.py` | 持久化事件（Event Sourcing） |
| KnowledgeKernel | `kernel.py` | Facade：Permission + EventBus + Lifecycle + VersionManager |

### 7.5 为何未接线（根因）

1. `PipelineService._stages` 硬编码旧三件套（§2.2）
2. `run_ingest()` 未改造为调用 `analyze(json) → Candidate → Reviewer → Promoter → Generator`
3. `unified_generate` 单步法仍是默认入口
4. 切换需配套 Phase 0 基础修复（schema 注册、权限白名单）

> 详细接线方案见 `docs/superpowers/plans/2026-08-02-ingest-pipeline-completion.md`。

---

## 8. 数据模型层（Wiki v2）

### 8.1 WikiPage

定义：`src/wiki/core/types.py`（17 字段 dataclass）

```python
@dataclass
class WikiPage:
    id: str                      # kebab-case slug 或 card_<...>_<slug>
    title: str
    type: PageType               # source | entity | concept | synthesis
    sources: list[str]           # ⚠️ 仅文件级，无页码
    created_at / updated_at: str  # ISO 8601 format (v3.2), e.g., "2024-08-04T10:30:00Z"
    body: str                    # Markdown（含 [[wikilinks]]）
    relations: list[Relation]
    grade: str                   # A / B / C
    processing_depth: str
    is_immutable: bool
    heat: int                    # 0-100，默认 50
    last_used_at: str            # ISO 8601 format (v3.2)
    zombie_since: str | None     # ISO 8601 format (v3.2)
    tags: list[str]              # 受控命名空间
    category / taxonomy_sub: str # v3.1
```

**时间戳格式（v3.2）**：所有时间戳字段已从 Unix 毫秒（`int`）改为 ISO 8601 字符串（`str`），默认值为空字符串 `""`。旧数据在读取时自动转换。工具函数：`src/utils/timestamp.py`。

**缺失字段**（演进目标，已由 KnowledgeObject 覆盖）：`lifecycle` / `confidence` / `provenance`（页码级）/ `versions` / `schema_version`

### 8.2 Relation

`src/wiki/features/relations.py`：17 种内置类型（`is_part_of`/`contains`/`references`/`causes`/`contradicts`/`supports`/...）+ `x-*` 自定义。
图查询：`list_relations()` / `find_backlinks()`（全盘扫描 O(n)）/ `find_neighbors()`（BFS）/ `find_path()`（BFS）。
⚠️ **O(n) 全盘扫描在页面 >1000 时不可扩展**。

### 8.3 KnowledgeTask

`src/types.py`：`TaskStatus` 9 态 + 15 转换边（PENDING→RUNNING→WAITING_REVIEW/APPROVED/FAILED→...）。

### 8.4 模板系统

每种 PageType 有章节模板，三级覆盖：`bundled/` → `~/.config/ruflo-kb/wiki-templates/` → `<project>/.wiki-templates/`。

---

## 9. 存储层

### 9.1 双层架构

```
文件系统 (source of truth)                LanceDB (派生向量索引)
<project>/                                .index/lancedb/
├── wiki/                                  chunks 表 (6 列):
│   ├── sources/ entities/ concepts/         id / task_id / content /
│   ├── synthesis/ _stubs/ _archive/         embedding(1536 f32) / path / updated_at
│   ├── index.md (目录)  log.md (审计)
├── raw/sources/                         队列持久化
├── .llm-wiki/ (project.json 等)          .kb-queue.json (MAX_RETRIES=3 → dead-letter)
└── .index/ (lint_cache / heat_events.log /
             reviews.json / staging / quarantine /
             dedup_history / quality_settings.json)
```

### 9.2 Schema 迁移

| 版本 | 内容 | 状态 |
|------|------|------|
| v1.0 | 初始 | — |
| v1.0→v2.0 | Notes/ → wiki/sources/，加 id/type/sources/时间戳 | ✅ 已注册 |
| v2.0→v2.1 | 加 `relations: []` | ⚠️ **文件存在但未导入 `__init__.py`** |
| v2.0→v2.2 | 加 grade/depth/is_immutable + UUID v7 | ⚠️ **同上** |
| v3.0 | 当前最新 | — |

⚠️ **存量项目无法升级到 v2.1/v2.2**（迁移未注册）。

---

## 10. LLM Provider 层

| Provider | 类 | type | 默认模型 |
|----------|-----|------|----------|
| OpenAI | `OpenAIProvider` | `openai` / `openai-compatible` | gpt-4o-mini |
| Anthropic | `AnthropicProvider` | `anthropic` | claude-haiku-4-5 |
| Ollama | `OllamaProvider` | `ollama` | qwen2.5:7b |
| MiniMax | `MiniMaxEmbeddingProvider` | (embedding) | — |

- 抽象：`llm/base.py`（`LLMProvider` / `EmbeddingProvider` ABC）
- 注册：`llm/registry.py`（4 级默认解析；`aclose_all()` 释放资源）
- 国产模型（DeepSeek/Kimi/GLM）经 `openai-compatible` 接入
- 预算：`lib/budgeted.py`（`BudgetedLLM`）

---

## 11. 检索层

`searcher/hybrid_search.py` → `hybrid_search(query, top_k, paths)`：

```
Query
 ├─► Vector Search (LanceDB): score = 1 - distance
 ├─► Keyword Search: rglob("*.md") 子串匹配 + 标题加成 2x（跳过 _archive/_stubs/index/log）
 └─► RRF Fusion (k=60): score = Σ 1/(k+rank)，单侧降级
```

`services/search.py` 支持 `page_type` 后过滤。**注意：标签不参与检索**（见 §14）。

---

## 12. 治理层（Governance）

| 层 | 名称 | 文件 | 说明 |
|----|------|------|------|
| 1 | Sanitizer | `pipeline/sanitizer.py` | 噪声检测 + 评分 + 规范化 |
| 2 | QualityGate | `pipeline/quality_gate.py` | 3 规则 |
| 3 | QualityJudge | `quality/judge.py` | 6 维评分（默认关闭） |
| 4 | EnsembleJudge | `quality/ensemble.py` | 多 Judge 投票 + factuality veto |
| 5 | HardAudit | `orchestrator/audit_hard.py` | 文件存在性 + frontmatter + quality_score |
| 6 | QuarantineStore | `quality/quarantine.py` | 隔离拒绝项 |

**辅助治理**：
- **Dedup**：`wiki/features/dedup.py` 的 `find_duplicates()` 当前**返回空列表**（MVP）；`dedup_auto.py` 自动合并高置信度重复
- **Lint**：`wiki/features/lint.py` 9 项检查（缓存 TTL 24h）
- **Heat**：`wiki/features/heat.py`（`HEAT_DECAY_DAYS=30`，`HEAT_DECAY_AMOUNT=10`）；`zombie.py` ZombieDetector
- **NDG Gate**：`wiki/features/ndg_gate.py` 7 项检查（含 UGC 可信度配对 P4b 硬阻断）
- **标签命名空间**：`wiki/features/tag_namespace.py`（见 §14）

---

## 13. 基础设施层

| 能力 | 文件 | 说明 |
|------|------|------|
| 权限 | `permissions.py` | 5 AgentType × READ/WRITE × 路径白名单 |
| 断路器 | `circuit_breaker.py` | 连续 3 失败 → OPEN；60s 后半开；2 成功恢复 |
| 队列 | `queue/`（9 模块） | `QueueService` 单例，JSON 持久化，MAX_RETRIES=3 |
| 幂等 | `utils/idempotency.py` | md5 去重，TTL 7 天 |
| 项目 | `project/context.py` + `lib/project.py` | `ProjectContext` / `WikiPaths` / `resolve_project()` |
| 指标 | `metrics/` | `/metrics` 端点 |
| 同步 | `sync/` | `SnapshotStore` JSON 快照变更检测 |

⚠️ **权限白名单不完整**：仅 COLLECTOR 有条目，PROCESSOR/LIBRARIAN/SEARCHER 无白名单（所有访问被拒）。

---

## 14. 标签命名空间评估要点

> 详细版：`docs/evaluations/tag-namespace-evaluation.md`

**设计**：`src/wiki/features/tag_namespace.py`，10 个受控前缀（`题材/功能/角色/事件/情绪/实体/场景阶段/状态/素材/可信度/`），`is_valid()` 仅校验前缀。

**验证链路**：LLM 提示词（软）→ Generator 写入前过滤（静默丢弃非法）→ NDG Gate P4b（UGC 配对硬阻断）→ CLI `tags validate`（审计）。

**核心问题**：
| 严重 | 问题 |
|------|------|
| 🔴 | **无值域约束**——`题材/现言` 与 `题材/现代言情` 都合法，标签碎片化 |
| 🔴 | **前缀语义重叠**——`题材/`vs`实体/`、`功能/`vs`场景阶段/`、`状态/`vs`场景阶段/` 难区分 |
| 🟡 | **领域偏向强**——6 个前缀偏向网文，通用不足 |
| 🟡 | **配对规则硬编码 4 处**（analyzer/generator×2/ndg_gate） |
| 🟡 | **标签不参与检索**——`build_tag_index()` 构建了聚合但未消费 |
| 🟢 | 无标签数量上限；中英文混用不一致 |

**改进优先级**：P0 高频前缀建值域约束 → P1 消除前缀重叠 → P2 标签参与检索 → P3 配对规则配置化。

---

## 15. 已知问题与技术债务

| # | 级 | 问题 | 位置 | 状态 |
|---|----|------|------|------|
| 1 | 🔴 | Schema 迁移 v2.1/v2.2 未注册，存量项目无法升级 | `schemas/migrations/__init__.py` | 待修 |
| 2 | 🔴 | 权限白名单不完整（PROCESSOR/LIBRARIAN/SEARCHER 空） | `permissions.py` | 待补 |
| 3 | 🔴 | 大文档截断：`MAX_SOURCE_CHARS=8000`，超长仅处理前半 | `generator.py` | 待改 |
| 4 | 🔴 | 新路径（Knowledge OS）已建未接，分层验证未生效 | `pipeline/service.py` | 待接 |
| 5 | 🔴 | `unified_generate` 单步法绕过全部分层 | `generator.py` | 设计权衡 |
| 6 | 🟡 | Web UI 目录不存在但 app.py 有条件挂载 | `server/app.py` | 待实现 |
| 7 | 🟡 | WikiPage 无内容版本历史 | `wiki/core/types.py` | 演进目标 |
| 8 | 🟡 | 图查询 O(n) 全盘扫描 | `wiki/features/relations.py` | 性能优化 |
| 9 | 🟡 | 文件夹摄取路由未枚举目录 | `server/routes/ingest.py` | 待接 |
| 10 | 🟡 | QualityJudge 默认关闭，形同虚设 | `quality/judge.py` | 待启用策略 |
| 11 | 🟡 | 标签无值域约束 | `tag_namespace.py` | 待改 |
| 12 | 🟡 | 溯源仅文件级 | `wiki/core/types.py` | 待增强 |
| 13 | 🟡 | `find_duplicates()` 空实现 | `wiki/features/dedup.py` | 待实现 |
| 14 | ✅ | `FileSyncWatcher` 已移除（2026-08-03） | `sync/` | 已解决 |
| 15 | 🟢 | CLI 部分命令绕过 Services | `cli_ext/` | 架构一致性 |
| 16 | 🟢 | 无 linter/formatter/type-checker 配置 | `pyproject.toml` | 待配 |
| 17 | 🟢 | Server runtime 不被测试覆盖 | `tests/` | 测试覆盖 |

---

## 16. 演进路线与文档地图

### 16.1 摄取流程完善（近期，决策已锁定，暂不开工）

详见 `docs/superpowers/plans/2026-08-02-ingest-pipeline-completion.md`：

```
Phase 0 (1-2d)  基础修复：schema 注册 / 权限白名单 / 导入风格
Phase 1 (3-5d)  新管线接线：KnowledgeKernel 组装 + run_ingest 改造 + Shadow 双跑 + 切换
Phase 2 (2-3d)  质量缺口：大文档分块 / 文件夹摄取 / 溯源增强
Phase 3 (2-3d)  治理增强：标签值域 / QualityJudge 抽样 / dedup / 可观测性（可并行）
```

核心：让路径 B 成为生产路径，路径 A 降级回退。**30 秒可经 config flag 回滚**。

### 16.2 Knowledge OS 演进（中长期）

| Phase | 内容 | 就绪度 |
|-------|------|--------|
| Phase 1 | KnowledgeObject + Lifecycle + Candidate 层 | 🟢 基础设施已建，待接线 |
| Phase 2 | Claim + Evidence + Graph（细粒度溯源） | 🟡 claims/conflicts/graph 子包已建 |
| Phase 3 | Decision Memory + MCP Memory API | 🟡 memory/ 子包已建 |
| Phase 4 | 自主演化（需前序稳定后明确定义） | 🟡 evolution/ 骨架已建 |

> 关键洞察：KOS 演进的**基础设施 80% 已写好**。"新建系统"的叙事应改为"接线 + 修复 + 增强"。

### 16.3 文档地图

| 文档 | 内容 |
|------|------|
| `docs/ARCHITECTURE.md`（本文件） | 单一可信架构源 |
| `docs/superpowers/plans/2026-08-02-ingest-pipeline-completion.md` | 摄取完善方案 v1.1（决策锁定） |
| `docs/evaluations/tag-namespace-evaluation.md` | 标签命名空间评估 |
| `docs/KNOWLEDGE_OS_EVOLUTION_FEASIBILITY_REPORT.md` | 演进方案可行性验证 |
| `docs/superpowers/plans/2026-08-02-knowledge-os-evolution.md` (v1.3) | 原始 KOS 演进方案 |

---

## 附录

### A. 依赖清单（关键）

lancedb 0.27.1 ｜ pyarrow 25.0.0 ｜ pypdf ｜ python-docx ｜ openpyxl ｜ pyyaml ｜ httpx ｜ fastapi ｜ uvicorn ｜ mcp

### B. 测试

- 873+ 测试，全部通过
- 运行：`PYTHONPATH=. python -m pytest --import-mode=importlib`（必须 importlib 模式）
- Windows 需剥离代理：`env -u HTTP_PROXY ...`

### C. 关键事实纠正（对外描述时务必注意）

| 旧叙述 | 真实情况 |
|--------|----------|
| "Web UI 存在" | ❌ `web/` 不存在 |
| "MCP 直接调 Services" | ❌ MCP → HTTP API → routes → Services |
| "LanceDB 是主存储" | ❌ 仅为派生向量索引，source of truth 是文件系统 |
| "已有完整的 Reviewer/Promoter 分层" | ⚠️ 代码已建，但生产未接线 |
| "统一生成路径是优化" | ⚠️ 它绕过了 Candidate/Reviewer 全部分层验证 |
