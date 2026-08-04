# ruflo-kb 吸收 Nash 功能演进方案

> 版本：v1.0 | 日期：2026-08-04
> 目的：基于模块对比分析，制定功能吸收计划，明确新增/强化分类

---

## 一、方案总览

### 1.1 演进原则

| 原则 | 说明 |
|------|------|
| **保持架构优势** | Knowledge OS + 治理层是核心资产，不因吸收而稀释 |
| **补齐功能缺口** | 网络、前端、检索增强是明显短板，优先吸收 |
| **接线优于重写** | Candidate/Reviewer/Promoter 已建，先接线再迭代 |
| **渐进式演进** | 按 Phase 分批实施，每 Phase 可独立交付 |

### 1.2 吸收分类定义

| 类型 | 定义 | 工作量特征 |
|------|------|-----------|
| **新增模块** | ruflo-kb 完全没有的功能 | 需新建文件、目录、API |
| **强化模块** | ruflo-kb 已有但功能不足 | 改造现有代码、扩展接口 |
| **架构激活** | 代码已存在但未接线 | 配置调整、调用路径修改 |

### 1.3 Phase 规划

```
Phase 1 (1-2周): 架构激活 + 基础增强
Phase 2 (2-4周): 检索增强 + 网络集成
Phase 3 (1-2月): 前端实现 + Agent 工具化
Phase 4 (持续):  可选增强 + 体验优化
```

---

## 二、Phase 1：架构激活 + 基础增强

### 2.1 架构激活（优先级最高）

这些是 ruflo-kb 已有代码但未接线的模块，激活后可立即获得架构设计收益。

#### 2.1.1 Candidate/Reviewer/Promoter 接线

**类型**：架构激活

**现状**：
- `src/knowledge/core/candidate.py` ✅ 代码存在
- `src/pipeline/stages/reviewer.py` ✅ 代码存在
- `src/pipeline/stages/candidate_promoter.py` ✅ 代码存在
- `src/pipeline/service.py` 默认 stage 列表不含这些模块

**改造点**：

| 文件 | 改动 |
|------|------|
| `src/pipeline/service.py` | 修改 `_stages` 列表，加入 Reviewer + Promoter |
| `src/pipeline/ingest.py` | `run_ingest()` 默认使用 `output_format="json"` |
| `src/pipeline/generator.py` | 禁用 `unified_generate()` 或加 config flag 控制 |

**代码示例**：

```python
# src/pipeline/service.py
class PipelineService:
    def __init__(self, ...):
        # 旧：self._stages = [CollectorStage, AnalyzerStage, GeneratorStage]
        # 新：
        self._stages = [
            CollectorStage,
            AnalyzerStage,  # 默认 json 模式
            ReviewerStage,  # 新增
            CandidatePromoter,  # 新增
            GeneratorStage,
        ]
```

**验收标准**：
- [ ] Ingest 流程走 Candidate → Reviewer → Promoter → Generator
- [ ] `NEEDS_HUMAN_REVIEW` 状态正确进入 Review 队列
- [ ] `REJECTED` 状态正确进入 Quarantine
- [ ] 单测覆盖新路径

---

#### 2.1.2 KnowledgeObject 接线

**类型**：架构激活

**现状**：
- `src/knowledge/core/object.py` ✅ KnowledgeObject 定义完整
- `src/knowledge/core/adapter.py` ✅ WikiPage ↔ KnowledgeObject 适配器
- 生产代码仍使用 WikiPage

**改造点**：

| 文件 | 改动 |
|------|------|
| `src/pipeline/generator.py` | Generator 从 KnowledgeObject 读取 frontmatter |
| `src/wiki/storage/page_writer.py` | 写入时同步更新 KnowledgeObject |
| `src/services/search.py` | 检索返回 KnowledgeObject 元数据 |

**验收标准**：
- [ ] 新页面有 lifecycle 状态
- [ ] 新页面有 confidence 字段
- [ ] Provenance 记录页码级溯源

---

#### 2.1.3 VersionManager 激活

**类型**：架构激活

**现状**：
- `src/knowledge/core/version_manager.py` ✅ 代码存在
- `src/wiki/features/version_history.py` ✅ 骨架存在
- 页面修改不产生版本快照

**改造点**：

| 文件 | 改动 |
|------|------|
| `src/wiki/storage/page_writer.py` | 写入前调用 `VersionManager.snapshot()` |
| `src/wiki/features/version_history.py` | 实现 `list_versions()` / `restore_version()` |
| `src/services/files.py` | 暴露版本 API |

**验收标准**：
- [ ] 修改页面产生版本快照
- [ ] 可查看历史版本
- [ ] 可恢复到历史版本

---

### 2.2 强化模块（补齐功能缺口）

#### 2.2.1 两步法 Ingest 强制执行

**类型**：强化模块

**现状**：
- `analyze()` + `generate()` 两步法存在
- 默认走 `unified_generate()` 单步法绕过验证

**吸收来源**：Nash 强制两步法

**改造点**：

| 文件 | 改动 |
|------|------|
| `src/pipeline/ingest.py` | 移除 `unified_generate` 默认路径 |
| `src/pipeline/generator.py` | 保留 `unified_generate` 但加 config flag |
| `src/pipeline/schemas.py` | 强化 AnalysisResult → generate() 传参 |

**配置项**：

```python
# src/config.py
RUFLO_PIPELINE_MODE: Literal["candidate", "legacy"] = "candidate"
RUFLO_ALLOW_UNIFIED_GENERATE: bool = False  # 禁用单步法
```

**验收标准**：
- [ ] 默认路径走 analyze(json) → generate()
- [ ] `RUFLO_PIPELINE_MODE=legacy` 可回退旧路径
- [ ] 日志记录两步法耗时

---

#### 2.2.2 增量缓存增强

**类型**：强化模块

**现状**：
- `src/utils/idempotency.py` 幂等缓存（md5，TTL 7天）
- 无内容变更检测

**吸收来源**：Nash SHA256 内容哈希

**改造点**：

| 文件 | 改动 |
|------|------|
| `src/utils/idempotency.py` | 新增 `content_hash_cache` |
| `src/pipeline/collector.py` | 入队时计算 SHA256 |
| `src/services/ingest.py` | 检查内容哈希，未变更则跳过 |

**代码示例**：

```python
# src/utils/idempotency.py
import hashlib

def compute_content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()

def is_content_processed(project_id: str, content_hash: str) -> bool:
    # 检查是否已处理过相同内容
    ...

def mark_content_processed(project_id: str, content_hash: str, page_id: str):
    # 记录内容哈希 → 页面映射
    ...
```

**验收标准**：
- [ ] 相同内容不重复 Ingest
- [ ] 日志显示跳过原因
- [ ] Token 节省统计

---

#### 2.2.3 overview.md 自动更新

**类型**：强化模块（新增功能）

**现状**：无 overview.md 维护

**吸收来源**：Nash 每次摄取后更新全局摘要

**新增文件**：

| 文件 | 功能 |
|------|------|
| `src/wiki/features/overview.py` | overview.md 生成/更新逻辑 |

**改造点**：

| 文件 | 改动 |
|------|------|
| `src/pipeline/ingest.py` | `commit_ingest()` 后调用 `update_overview()` |
| `src/services/projects.py` | 项目初始化时创建 overview.md |

**代码示例**：

```python
# src/wiki/features/overview.py
from pathlib import Path
from ..core.types import WikiPage

def update_overview(project_path: Path, pages: list[WikiPage]) -> None:
    """基于当前 Wiki 内容生成全局摘要"""
    # 收集统计
    stats = {
        "total_pages": len(pages),
        "by_type": {},
        "recent_updates": [],
    }
    
    for p in pages:
        stats["by_type"][p.type] = stats["by_type"].get(p.type, 0) + 1
    
    # LLM 生成摘要（可选）
    overview_content = generate_overview_content(pages, stats)
    
    # 写入
    (project_path / "wiki/overview.md").write_text(overview_content)
```

**验收标准**：
- [ ] 每次 Ingest 后 overview.md 更新
- [ ] 包含页面统计
- [ ] 可配置是否启用 LLM 生成

---

#### 2.2.4 EPUB/MOBI 解析

**类型**：强化模块（扩展格式支持）

**现状**：仅 PDF/DOCX/XLSX/HTML/MD/TXT/URL

**吸收来源**：Nash epub + mobi 库

**新增文件**：

| 文件 | 功能 |
|------|------|
| `src/utils/extract/ebook.py` | EPUB/MOBI 解析 |
| `src/pipeline/collector.py` | 新增 SourceType.EPUB / MOBI |

**依赖**：

```toml
# pyproject.toml
[project.dependencies]
ebooklib = ">=0.18"  # EPUB
mobi = ">=0.3"       # MOBI（或类似库）
```

**代码示例**：

```python
# src/utils/extract/ebook.py
from pathlib import Path
import ebooklib
from ebooklib import epub

def extract_epub(path: Path) -> str:
    """提取 EPUB 文本内容"""
    book = epub.read_epub(str(path))
    texts = []
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            texts.append(item.get_content())
    return "\n\n".join(texts)
```

**验收标准**：
- [ ] EPUB 文件可正确解析
- [ ] MOBI 文件可正确解析
- [ ] 保留章节结构

---

## 三、Phase 2：检索增强 + 网络集成

### 3.1 新增模块

#### 3.1.1 图扩展检索

**类型**：新增模块

**现状**：`hybrid_search()` 无图扩展阶段

**吸收来源**：Nash 4-Signal 相关性模型 + 图扩展

**新增文件**：

| 文件 | 功能 |
|------|------|
| `src/searcher/graph_expansion.py` | 图扩展检索逻辑 |
| `src/searcher/relevance_model.py` | 4-Signal 相关性计算 |

**新增 API**：

```python
# src/searcher/graph_expansion.py
from dataclasses import dataclass
from typing import Literal

@dataclass
class RelevanceSignal:
    signal_type: Literal["direct_link", "source_overlap", "adamic_adar", "type_affinity"]
    weight: float
    score: float

def compute_relevance(page_a: str, page_b: str, paths: WikiPaths) -> float:
    """计算两页面相关性分数"""
    score = 0.0
    
    # Signal 1: 直接链接 ×3.0
    if has_direct_link(page_a, page_b):
        score += 3.0
    
    # Signal 2: 源文档重叠 ×4.0
    overlap = compute_source_overlap(page_a, page_b)
    score += overlap * 4.0
    
    # Signal 3: Adamic-Adar ×1.5
    aa_score = compute_adamic_adar(page_a, page_b)
    score += aa_score * 1.5
    
    # Signal 4: 类型亲和 ×1.0
    if get_page_type(page_a) == get_page_type(page_b):
        score += 1.0
    
    return score

def expand_with_graph(
    seed_pages: list[str],
    max_depth: int = 2,
    decay: float = 0.5,
) -> list[tuple[str, float]]:
    """图扩展：从种子节点扩展相关页面"""
    ...
```

**改造点**：

| 文件 | 改动 |
|------|------|
| `src/searcher/hybrid_search.py` | 新增 `hybrid_search_with_graph()` |
| `src/services/search.py` | 暴露图扩展参数 |

**验收标准**：
- [ ] 相关性模型 4 个 Signal 正确计算
- [ ] 图扩展返回相关页面
- [ ] 召回率提升可测量

---

#### 3.1.2 预算控制

**类型**：新增模块

**现状**：无 token 预算分配

**吸收来源**：Nash context-budget.ts

**新增文件**：

| 文件 | 功能 |
|------|------|
| `src/lib/context_budget.py` | Token 预算计算 |

**代码示例**：

```python
# src/lib/context_budget.py
from dataclasses import dataclass

@dataclass
class ContextBudget:
    max_tokens: int
    response_reserve: int
    index_budget: int
    page_budget: int
    max_page_size: int

def compute_context_budget(max_context_tokens: int) -> ContextBudget:
    """计算各部分 token 预算"""
    RESPONSE_RESERVE_FRAC = 0.15
    INDEX_BUDGET_FRAC = 0.05
    PAGE_BUDGET_FRAC = 0.50
    
    return ContextBudget(
        max_tokens=max_context_tokens,
        response_reserve=int(max_context_tokens * RESPONSE_RESERVE_FRAC),
        index_budget=int(max_context_tokens * INDEX_BUDGET_FRAC),
        page_budget=int(max_context_tokens * PAGE_BUDGET_FRAC),
        max_page_size=int(max_context_tokens * PAGE_BUDGET_FRAC * 0.3),
    )

def allocate_pages(
    pages: list[str],
    budget: ContextBudget,
) -> list[str]:
    """按预算分配页面内容"""
    ...
```

**改造点**：

| 文件 | 改动 |
|------|------|
| `src/pipeline/analyzer.py` | 使用预算控制 |
| `src/services/chat.py` | 聊天上下文使用预算 |

**验收标准**：
- [ ] 可配置上下文窗口大小
- [ ] 页面按预算截断
- [ ] 不超 LLM 限制

---

#### 3.1.3 网络搜索集成

**类型**：新增模块

**现状**：无网络搜索功能

**吸收来源**：Nash Tavily/SerpApi/SearXNG

**新增文件**：

| 文件 | 功能 |
|------|------|
| `src/searcher/web_search.py` | 网络搜索抽象层 |
| `src/searcher/providers/tavily.py` | Tavily Provider |
| `src/searcher/providers/serpapi.py` | SerpApi Provider |
| `src/searcher/providers/searxng.py` | SearXNG Provider |
| `src/services/research.py` | Deep Research 服务 |

**目录结构**：

```
src/searcher/
├── __init__.py
├── hybrid_search.py
├── graph_expansion.py      # 新增
├── web_search.py           # 新增
├── providers/              # 新增目录
│   ├── __init__.py
│   ├── base.py
│   ├── tavily.py
│   ├── serpapi.py
│   └── searxng.py
└── context_budget.py       # 新增
```

**依赖**：

```toml
# pyproject.toml
[project.optional-dependencies]
web-search = ["tavily-python>=0.3.0"]
```

**代码示例**：

```python
# src/searcher/web_search.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

@dataclass
class WebSearchResult:
    title: str
    url: str
    snippet: str
    source: str

class WebSearchProvider(ABC):
    @abstractmethod
    async def search(self, query: str, max_results: int) -> list[WebSearchResult]:
        ...

# src/searcher/providers/tavily.py
from tavily import TavilyClient

class TavilyProvider(WebSearchProvider):
    def __init__(self, api_key: str):
        self.client = TavilyClient(api_key=api_key)
    
    async def search(self, query: str, max_results: int) -> list[WebSearchResult]:
        results = self.client.search(query, max_results=max_results)
        return [
            WebSearchResult(
                title=r["title"],
                url=r["url"],
                snippet=r["content"],
                source="tavily",
            )
            for r in results["results"]
        ]
```

**验收标准**：
- [ ] Tavily 搜索可用
- [ ] SerpApi 搜索可用
- [ ] SearXNG 搜索可用
- [ ] 配置切换 Provider

---

#### 3.1.4 Deep Research

**类型**：新增模块

**现状**：无 Deep Research 功能

**吸收来源**：Nash deep-research.ts

**新增文件**：

| 文件 | 功能 |
|------|------|
| `src/services/research.py` | Deep Research 主逻辑 |
| `src/services/research_types.py` | ResearchTask 等类型 |

**代码示例**：

```python
# src/services/research.py
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Literal

class ResearchStatus(str, Enum):
    PENDING = "pending"
    SEARCHING = "searching"
    SYNTHESIZING = "synthesizing"
    DONE = "done"
    FAILED = "failed"

@dataclass
class ResearchTask:
    id: str
    topic: str
    queries: list[str]
    status: ResearchStatus
    results: list[str]
    synthesis: str | None
    created_at: datetime
    updated_at: datetime

class DeepResearchService:
    def __init__(
        self,
        project_path: str,
        web_search_provider: str,
        llm_provider: LLMProvider | None = None,
    ):
        self.project_path = project_path
        self.provider = get_web_search_provider(web_search_provider)
        self.llm = llm_provider or get_default_provider()
    
    async def queue_research(self, topic: str, queries: list[str] | None = None) -> str:
        """入队研究任务"""
        if queries is None:
            queries = await self._generate_queries(topic)
        
        task = ResearchTask(
            id=generate_task_id(),
            topic=topic,
            queries=queries,
            status=ResearchStatus.PENDING,
            results=[],
            synthesis=None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        
        await self._save_task(task)
        return task.id
    
    async def _generate_queries(self, topic: str) -> list[str]:
        """LLM 生成搜索查询"""
        prompt = f"Generate 3-5 web search queries for researching: {topic}"
        response = await self.llm.complete(prompt)
        return parse_queries(response)
    
    async def process_task(self, task_id: str) -> ResearchTask:
        """处理研究任务"""
        task = await self._load_task(task_id)
        
        # 1. 网络搜索
        task.status = ResearchStatus.SEARCHING
        for query in task.queries:
            results = await self.provider.search(query, max_results=10)
            task.results.extend([r.url for r in results])
        
        # 2. 自动 Ingest 结果
        for url in task.results[:20]:
            await ingest_service.enqueue_source(url, self.project_path)
        
        # 3. 生成综合页
        task.status = ResearchStatus.SYNTHESIZING
        task.synthesis = await self._synthesize(task)
        
        task.status = ResearchStatus.DONE
        await self._save_task(task)
        return task
```

**验收标准**：
- [ ] 可创建研究任务
- [ ] 自动生成搜索查询
- [ ] 自动 Ingest 结果
- [ ] 生成综合研究页

---

### 3.2 强化模块

#### 3.2.1 Review 系统增强

**类型**：强化模块

**现状**：
- `ReviewerStage` 存在但未接线
- 无预生成搜索查询
- 无建议动作类型

**吸收来源**：Nash 预定义动作 + 预生成查询

**改造点**：

| 文件 | 改动 |
|------|------|
| `src/knowledge/core/candidate.py` | 新增 `pre_generated_queries` / `suggested_action` 字段 |
| `src/pipeline/stages/reviewer.py` | 生成预查询 + 动作建议 |
| `src/services/reviews.py` | 暴露预查询 API |

**代码示例**：

```python
# src/knowledge/core/candidate.py
from typing import Literal
from dataclasses import dataclass

@dataclass
class KnowledgeCandidate:
    # ...existing fields (id, source_id, type, title, claims, evidence, status)...

    # 新增字段（需要在 status 之后，使用 field 默认值）
    pre_generated_queries: list[str] = field(default_factory=list)
    suggested_action: Literal["create_page", "deep_research", "skip", "merge"] = "create_page"
    action_reason: str = ""
```

**验收标准**：
- [ ] Review 项包含预生成搜索查询
- [ ] Review 项包含建议动作
- [ ] Web UI 显示预查询

---

#### 3.2.2 Dedup 完整实现

**类型**：强化模块

**现状**：`find_duplicates()` 返回空列表

**吸收来源**：Nash LLM 驱动 Dedup

**改造点**：

| 文件 | 改动 |
|------|------|
| `src/wiki/features/dedup.py` | 实现 `find_duplicates()` LLM 驱动 |
| `src/wiki/features/dedup_auto.py` | 增强 `merge_duplicate_group()` |

**代码示例**：

```python
# src/wiki/features/dedup.py
from dataclasses import dataclass
from ..core.types import WikiPage

@dataclass
class DuplicateGroup:
    slugs: list[str]
    reason: str
    confidence: Literal["high", "medium", "low"]

async def find_duplicates(
    pages: list[WikiPage],
) -> list[DuplicateGroup]:
    """LLM 识别重复页面"""
    llm = get_default_provider()

    # 构建摘要列表（处理空 body）
    summaries = []
    for p in pages:
        body_preview = (p.body or "")[:200]
        summaries.append(f"{p.id}: {p.title} - {body_preview}")
    
    prompt = f"""
    Analyze these wiki page summaries and identify groups that likely refer to the same entity/concept.
    
    Pages:
    {summaries}
    
    Return JSON: {{"groups": [{{"slugs": [...], "reason": "...", "confidence": "high|medium|low"}}]}}
    """
    
    response = await llm.complete(prompt)
    return parse_duplicate_groups(response)
```

**验收标准**：
- [ ] `find_duplicates()` 返回非空结果
- [ ] 合并操作正确更新 wikilink
- [ ] 备份可恢复

---

#### 3.2.3 源文件夹监控

**类型**：强化模块

**现状**：`FileSyncWatcher` 已移除

**吸收来源**：Nash 源文件夹自动监控

**新增文件**：

| 文件 | 功能 |
|------|------|
| `src/sync/source_watcher.py` | 源文件夹监控 |

**依赖**：

```toml
# pyproject.toml
[project.dependencies]
watchfiles = ">=0.20.0"
```

**代码示例**：

```python
# src/sync/source_watcher.py
import asyncio
from pathlib import Path
from watchfiles import awatch
from ..services.ingest import enqueue_source
from ..wiki.features.cascade_delete import cascade_delete

class SourceWatcher:
    def __init__(self, project_path: Path):
        self.project_path = project_path
        self.sources_path = project_path / "raw/sources"
        self.running = False

        # 确保目录存在
        self.sources_path.mkdir(parents=True, exist_ok=True)

    async def start(self):
        if not self.sources_path.exists():
            return
        self.running = True
        async for changes in awatch(self.sources_path):
            if not self.running:
                break
            
            for change_type, path in changes:
                if change_type == "added":
                    await self._handle_added(path)
                elif change_type == "deleted":
                    await self._handle_deleted(path)
                elif change_type == "modified":
                    await self._handle_modified(path)
    
    async def _handle_added(self, path: str):
        await enqueue_source(path, str(self.project_path))
    
    async def _handle_deleted(self, path: str):
        await cascade_delete(path, str(self.project_path))
    
    async def _handle_modified(self, path: str):
        # 重新 Ingest（内容可能变化）
        await enqueue_source(path, str(self.project_path), force=True)
    
    def stop(self):
        self.running = False
```

**验收标准**：
- [ ] 新文件自动入队
- [ ] 删除文件自动清理 Wiki
- [ ] 修改文件自动重处理

---

## 四、Phase 3：前端实现 + Agent 工具化

### 4.1 新增模块

#### 4.1.1 Web UI 实现

**类型**：新增模块

**现状**：`web/` 目录为空

**吸收来源**：Fork Nash React 前端，适配 FastAPI

**目录结构**：

```
web/
├── package.json
├── vite.config.ts
├── tsconfig.json
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── components/
│   │   ├── layout/
│   │   │   ├── AppLayout.tsx
│   │   │   ├── Sidebar.tsx
│   │   │   └── PreviewPanel.tsx
│   │   ├── chat/
│   │   │   ├── ChatPanel.tsx
│   │   │   └── ChatInput.tsx
│   │   ├── graph/
│   │   │   └── GraphView.tsx
│   │   └── search/
│   │       └── SearchView.tsx
│   ├── stores/
│   │   ├── wiki-store.ts
│   │   └── chat-store.ts
│   ├── lib/
│   │   └── api-client.ts
│   └── styles/
│       └── main.css
└── index.html
```

**技术选型**：
- React 19 + TypeScript + Vite
- Tailwind CSS（简化版，无 shadcn/ui 全套）
- Zustand 状态管理
- sigma.js 图谱可视化

**API 适配**：
- Nash: Tauri invoke
- ruflo-kb: FastAPI fetch

**验收标准**：
- [ ] 三栏布局可显示
- [ ] Wiki 树可浏览
- [ ] 搜索可执行
- [ ] 图谱可渲染

---

#### 4.1.2 图谱可视化

**类型**：新增模块

**现状**：无可视化

**吸收来源**：Nash sigma.js + graphology

**新增文件**：

| 文件 | 功能 |
|------|------|
| `web/src/components/graph/GraphView.tsx` | 图谱组件 |
| `web/src/lib/graph-utils.ts` | 图数据处理 |
| `src/services/graph.py` | 图谱数据 API |

**后端 API**：

```python
# src/services/graph.py
from dataclasses import dataclass
from typing import TypedDict

class GraphNode(TypedDict):
    id: str
    label: str
    type: str
    degree: int

class GraphEdge(TypedDict):
    source: str
    target: str
    weight: float
    type: str

@dataclass
class GraphData:
    nodes: list[GraphNode]
    edges: list[GraphEdge]

def export_graph(project_id: str) -> GraphData:
    """导出图谱数据供前端可视化"""
    pages = get_all_pages(project_id)
    
    nodes = [
        {"id": p.id, "label": p.title, "type": p.type, "degree": 0}
        for p in pages
    ]
    
    edges = []
    for p in pages:
        for r in p.relations:
            edges.append({
                "source": p.id,
                "target": r.target_id,  # Relation 字段名是 target_id
                "weight": r.weight or 1.0,
                "type": r.type,
            })
    
    # 计算度数
    degree_map = {}
    for e in edges:
        degree_map[e["source"]] = degree_map.get(e["source"], 0) + 1
        degree_map[e["target"]] = degree_map.get(e["target"], 0) + 1
    
    for n in nodes:
        n["degree"] = degree_map.get(n["id"], 0)
    
    return GraphData(nodes=nodes, edges=edges)
```

**前端组件**：

```tsx
// web/src/components/graph/GraphView.tsx
import { useEffect, useRef } from "react";
import Sigma from "sigma";
import Graph from "graphology";

interface GraphViewProps {
  data: GraphData;
}

export function GraphView({ data }: GraphViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  
  useEffect(() => {
    if (!containerRef.current) return;
    
    const graph = new Graph();
    
    // 添加节点
    for (const node of data.nodes) {
      graph.addNode(node.id, {
        label: node.label,
        size: Math.sqrt(node.degree) * 5,
        color: getColorByType(node.type),
      });
    }
    
    // 添加边
    for (const edge of data.edges) {
      graph.addEdge(edge.source, edge.target, {
        size: edge.weight,
      });
    }
    
    const renderer = new Sigma(graph, containerRef.current);
    
    return () => renderer.kill();
  }, [data]);
  
  return <div ref={containerRef} className="w-full h-full" />;
}
```

**验收标准**：
- [ ] 图谱可渲染
- [ ] 节点大小按度数
- [ ] 颜色按类型
- [ ] 可交互（缩放/拖拽）

---

#### 4.1.3 社区检测

**类型**：新增模块

**现状**：无社区检测

**吸收来源**：Nash Louvain 算法

**新增文件**：

| 文件 | 功能 |
|------|------|
| `src/wiki/features/community.py` | 社区检测 |
| `src/services/insights.py` | 知识缺口发现 |

**依赖**：

```toml
# pyproject.toml
[project.dependencies]
python-louvain = ">=0.16"  # 或 networkx 社区检测
```

**代码示例**：

```python
# src/wiki/features/community.py
import networkx as nx
from community import best_partition
from dataclasses import dataclass
from typing import Literal

@dataclass
class Community:
    id: int
    members: list[str]
    cohesion: float
    top_label: str

def detect_communities(pages: list[WikiPage]) -> list[Community]:
    """Louvain 社区检测"""
    G = nx.Graph()
    
    # 构建图
    for p in pages:
        G.add_node(p.id)
        for r in p.relations:
            G.add_edge(p.id, r.target)
    
    # 检测社区
    partition = best_partition(G)
    
    # 按社区分组
    communities = {}
    for node, comm_id in partition.items():
        if comm_id not in communities:
            communities[comm_id] = []
        communities[comm_id].append(node)
    
    # 计算凝聚度
    result = []
    for comm_id, members in communities.items():
        cohesion = compute_cohesion(G, members)
        top_label = get_top_page_label(pages, members)
        result.append(Community(
            id=comm_id,
            members=members,
            cohesion=cohesion,
            top_label=top_label,
        ))
    
    return result

def compute_cohesion(G: nx.Graph, members: list[str]) -> float:
    """计算社区凝聚度 = 内部边数 / 可能边数"""
    internal_edges = 0
    for i, n1 in enumerate(members):
        for n2 in members[i+1:]:
            if G.has_edge(n1, n2):
                internal_edges += 1
    
    n = len(members)
    possible_edges = n * (n - 1) / 2
    
    return internal_edges / possible_edges if possible_edges > 0 else 0
```

**验收标准**：
- [ ] 检测出知识社区
- [ ] 计算凝聚度
- [ ] 低凝聚度警告

---

#### 4.1.4 Agent 工具调用

**类型**：新增模块

**现状**：Agent 无工具调用机制

**吸收来源**：Nash Agent Tools

**新增文件**：

| 文件 | 功能 |
|------|------|
| `src/agent/tools.py` | 工具注册表 |
| `src/agent/router.py` | 意图路由 |
| `src/agent/session.py` | 会话管理 |
| `src/agent/cancel.py` | 取消机制 |

**目录结构**：

```
src/agent/
├── __init__.py
├── tools.py          # 工具注册
├── router.py         # 意图路由
├── session.py        # 会话管理
├── cancel.py         # 取消机制
└── types.py          # 类型定义
```

**代码示例**：

```python
# src/agent/tools.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

class ToolEffect(str, Enum):
    READ = "read"
    WRITE = "write"
    NETWORK = "network"
    PROCESS = "process"

@dataclass
class ToolSpec:
    name: str
    description: str
    effects: list[ToolEffect]
    parameters: dict[str, Any]

class AgentTool(ABC):
    @abstractmethod
    def spec(self) -> ToolSpec:
        ...
    
    @abstractmethod
    async def execute(self, **params) -> Any:
        ...

class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, AgentTool] = {}
    
    def register(self, tool: AgentTool):
        self._tools[tool.spec().name] = tool
    
    def specs(self) -> list[ToolSpec]:
        return [t.spec() for t in self._tools.values()]
    
    async def execute(self, name: str, **params) -> Any:
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"Unknown tool: {name}")
        return await tool.execute(**params)

# 内置工具实现
class WikiSearchTool(AgentTool):
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="wiki.search",
            description="Search wiki pages",
            effects=[ToolEffect.READ],
            parameters={
                "query": {"type": "string"},
                "top_k": {"type": "integer", "default": 10},
            },
        )
    
    async def execute(self, query: str, top_k: int = 10) -> list[dict]:
        from ..services.search import search
        results = await search(query, top_k=top_k)
        return [{"path": r["path"], "title": r["title"]} for r in results]

class WebSearchTool(AgentTool):
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="web.search",
            description="Search the web",
            effects=[ToolEffect.NETWORK],
            parameters={
                "query": {"type": "string"},
            },
        )
    
    async def execute(self, query: str) -> list[dict]:
        from ..searcher.web_search import get_web_search_provider
        provider = get_web_search_provider()
        results = await provider.search(query, max_results=10)
        return [{"title": r.title, "url": r.url} for r in results]
```

**验收标准**：
- [ ] 工具可注册
- [ ] LLM 可调用工具
- [ ] 权限控制生效

---

### 4.2 强化模块

#### 4.2.1 API 认证与限流

**类型**：强化模块

**现状**：无认证、无限流

**吸收来源**：Nash Token 认证 + 速率限制

**改造点**：

| 文件 | 改动 |
|------|------|
| `src/server/middleware/auth.py` | 新增认证中间件 |
| `src/server/middleware/ratelimit.py` | 新增限流中间件 |
| `src/server/app.py` | 挂载中间件 |

**代码示例**：

```python
# src/server/middleware/auth.py
from fastapi import Request, HTTPException
from functools import lru_cache
import secrets

API_TOKENS: dict[str, str] = {}  # token -> project_id

def generate_token() -> str:
    return secrets.token_urlsafe(32)

def verify_token(request: Request) -> str:
    token = request.headers.get("X-API-Token")
    if not token:
        raise HTTPException(401, "Missing API token")
    
    project_id = API_TOKENS.get(token)
    if not project_id:
        raise HTTPException(401, "Invalid API token")
    
    return project_id

# src/server/middleware/ratelimit.py
from fastapi import Request, HTTPException
from collections import deque
from datetime import datetime, timedelta

class RateLimiter:
    def __init__(self, max_requests: int = 120, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = timedelta(seconds=window_seconds)
        self.requests: deque = deque()
    
    def check(self) -> bool:
        now = datetime.now()
        
        # 清理过期请求
        while self.requests and (now - self.requests[0]) > self.window:
            self.requests.popleft()
        
        if len(self.requests) >= self.max_requests:
            return False
        
        self.requests.append(now)
        return True

limiter = RateLimiter()

async def rate_limit_middleware(request: Request, call_next):
    if not limiter.check():
        raise HTTPException(429, "Too many requests")
    return await call_next(request)
```

**验收标准**：
- [ ] Token 认证生效
- [ ] 速率限制生效
- [ ] 超限返回 429

---

## 五、Phase 4：可选增强

### 5.1 图片理解（可选）

**类型**：新增模块

**吸收来源**：Nash vision LLM

**新增文件**：

| 文件 | 功能 |
|------|------|
| `src/utils/vision.py` | 图片描述生成 |
| `src/pipeline/stages/image_captioner.py` | 图片处理阶段 |

**依赖**：需要支持 vision 的 LLM

---

### 5.2 技能系统（可选）

**类型**：新增模块

**吸收来源**：Nash Agent Skills

**新增文件**：

| 文件 | 功能 |
|------|------|
| `src/agent/skills.py` | 技能加载 |
| `src/agent/skill_types.py` | 技能类型定义 |

---

### 5.3 Chrome 扩展（可选）

**类型**：新增模块

**吸收来源**：Fork Nash Chrome 扩展

**目录**：
```
extension/
├── manifest.json
├── background.js
├── content.js
└── popup/
```

**改造**：API 端点指向 ruflo-kb 8765 端口

---

## 六、实施路线图

### 6.1 时间线

```
Week 1-2:  Phase 1 - 架构激活 + 基础增强
Week 3-6:  Phase 2 - 检索增强 + 网络集成
Month 2-3: Phase 3 - 前端实现 + Agent 工具化
Month 4+:  Phase 4 - 可选增强
```

### 6.2 依赖关系

```
Phase 1.1 (Candidate 接线)
    ↓
Phase 1.2 (KnowledgeObject 接线)
    ↓
Phase 2.1 (图扩展检索) ← 需要 Relation 数据
    ↓
Phase 2.3 (网络搜索) ← 需要 Provider 抽象
    ↓
Phase 2.4 (Deep Research) ← 需要网络搜索
    ↓
Phase 3.4 (Agent 工具化) ← 需要检索 + 网络
    ↓
Phase 3.1 (Web UI) ← 需要完整 API
```

### 6.3 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| 接线破坏现有功能 | Shadow 双跑模式，30 秒回滚 |
| 前端工作量大 | 先实现核心功能，迭代增强 |
| 网络搜索 Provider 不稳定 | 多 Provider 备份，降级策略 |
| LLM 成本增加 | 缓存 + 预算控制 + 用户可配置 |

---

## 七、验收标准总览

### 7.1 Phase 1 验收

- [ ] Candidate/Reviewer/Promoter 接线完成
- [ ] 两步法 Ingest 默认启用
- [ ] 增量缓存生效
- [ ] overview.md 自动更新
- [ ] EPUB/MOBI 解析可用

### 7.2 Phase 2 验收

- [ ] 图扩展检索召回率提升 > 15%
- [ ] Token 预算控制生效
- [ ] Tavily/SerpApi 搜索可用
- [ ] Deep Research 可执行
- [ ] Review 预生成查询

### 7.3 Phase 3 验收

- [ ] Web UI 三栏布局可用
- [ ] 图谱可视化可渲染
- [ ] 社区检测可用
- [ ] Agent 工具调用可用
- [ ] API 认证生效

---

## 八、总结

### 8.1 新增模块（13 个）

| 模块 | Phase | 来源 |
|------|-------|------|
| 图扩展检索 | Phase 2 | Nash |
| 预算控制 | Phase 2 | Nash |
| 网络搜索 | Phase 2 | Nash |
| Deep Research | Phase 2 | Nash |
| Web UI | Phase 3 | Nash |
| 图谱可视化 | Phase 3 | Nash |
| 社区检测 | Phase 3 | Nash |
| Agent 工具调用 | Phase 3 | Nash |
| Agent 会话管理 | Phase 3 | Nash |
| Agent 取消机制 | Phase 3 | Nash |
| 图片理解 | Phase 4 | Nash |
| 技能系统 | Phase 4 | Nash |
| Chrome 扩展 | Phase 4 | Nash |

### 8.2 强化模块（10 个）

| 模块 | Phase | 来源 |
|------|-------|------|
| 两步法强制执行 | Phase 1 | Nash |
| 增量缓存 | Phase 1 | Nash |
| overview.md | Phase 1 | Nash |
| EPUB/MOBI 解析 | Phase 1 | Nash |
| Review 增强 | Phase 2 | Nash |
| Dedup 实现 | Phase 2 | Nash |
| 源文件夹监控 | Phase 2 | Nash |
| API 认证 | Phase 3 | Nash |
| API 限流 | Phase 3 | Nash |
| 权限白名单完善 | Phase 1 | 自有修复 |

### 8.3 架构激活（3 个）

| 模块 | Phase |
|------|-------|
| Candidate/Reviewer/Promoter | Phase 1 |
| KnowledgeObject | Phase 1 |
| VersionManager | Phase 1 |

---

**最终目标**：打造一个**架构先进（Knowledge OS）+ 功能完整（检索增强 + 网络集成 + 可视化前端）**的知识库平台。