# LLM Wiki (Nash) vs ruflo-kb 功能对比与吸收建议

> 对比日期：2026-08-04
> 目的：识别 Nash 的 LLM Wiki 项目中值得吸收到 ruflo-kb 的功能特性

---

## 一、项目定位对比

| 维度 | ruflo-kb（本项目） | LLM Wiki (Nash) |
|------|-------------------|-----------------|
| **运行形态** | Python CLI + HTTP API | Tauri 桌面应用 |
| **用户界面** | CLI 为主，Web UI 未实现 | 完整桌面 GUI |
| **技术栈** | Python + FastAPI + LanceDB | Rust + React + Tauri |
| **架构成熟度** | 架构先进但接线未完成 | 生产级完整实现 |
| **知识层** | Knowledge OS 已建未接 | 简化但运行完整 |

**关键差异**：
- 本项目是**架构先进的半成品**（Knowledge OS 完整但未接线）
- Nash 项目是**功能完整的桌面应用**（架构简化但生产运行）

---

## 二、可吸收功能清单

### 🔴 P0 - 高优先级（显著提升用户体验）

#### 1. 两步链式思维 Ingest

**Nash 实现**：
```
Step 1 (分析): LLM 读取源文档 → 结构化分析
  - 关键实体、概念、论点
  - 与现有 Wiki 内容的连接
  - 与现有知识的矛盾
  - Wiki 结构建议

Step 2 (生成): LLM 基于分析 → 生成 Wiki 文件
  - 源文档摘要页
  - 实体页、概念页
  - 更新 index.md, log.md, overview.md
  - Review 项目
  - Deep Research 搜索查询
```

**本项目现状**：
- 有 `analyze()` + `generate()` 两步法
- 但默认走 `unified_generate()` 单步法绕过验证
- Analyzer 默认 markdown 模式，JSON 模式无人调用

**吸收建议**：
```python
# 改造 run_ingest() 强制走两步法
def run_ingest(...):
    # Step 1: 分析（JSON 模式）
    analysis = analyze(source_text, output_format="json")
    
    # Step 2: 生成（基于分析结果）
    pages = generate(analysis)
    
    # Step 3: 验证 + 写入
    validated = quality_gate(pages)
    commit_ingest(validated)
```

**收益**：提升生成质量，充分利用已有的 KnowledgeCandidate 层

---

#### 2. overview.md 自动更新

**Nash 实现**：
- 每次 Ingest 后重新生成全局摘要页
- 反映 Wiki 最新状态
- 作为 LLM 导航入口

**本项目现状**：
- 有 `wiki/` 目录结构
- 无 overview.md 自动维护

**吸收建议**：
```python
# 在 commit_ingest() 后触发
def update_overview(project_path: Path):
    """基于当前 Wiki 内容生成全局摘要"""
    pages = collect_all_pages(project_path)
    overview = llm_generate_overview(pages)
    write_page(project_path / "wiki/overview.md", overview)
```

---

#### 3. Deep Research 功能

**Nash 实现**：
- LLM 生成优化搜索主题
- 多查询网络搜索（Tavily/SerpApi/SearXNG）
- 自动 Ingest 结果
- 知识缺口检测 → 一键研究

**本项目现状**：
- 无网络搜索集成
- 无知识缺口主动发现

**吸收建议**：
```python
# 新增 src/services/research.py
class DeepResearchService:
    async def research(self, topic: str, provider: str = "tavily"):
        # 1. LLM 生成搜索查询
        queries = await self.generate_queries(topic)
        
        # 2. 网络搜索
        results = await self.web_search(queries, provider)
        
        # 3. 自动 Ingest
        for url in results:
            await ingest.enqueue_source(url)
        
        # 4. 生成研究页
        return await self.synthesize(topic, results)
```

**依赖**：需新增 Tavily/SerpApi SDK

---

#### 4. Review 系统增强

**Nash 实现**：
- 异步人机协作队列
- 预定义动作类型（Create Page / Deep Research / Skip）
- 搜索查询预生成
- 批量解决 API

**本项目现状**：
- 有 `reviews.json` 存储
- 有 `ReviewerStage` 代码但未接线
- 缺少预生成搜索查询

**吸收建议**：
```python
# 增强 KnowledgeCandidate
@dataclass
class KnowledgeCandidate:
    # ...existing fields...
    pre_generated_queries: list[str] = field(default_factory=list)
    suggested_action: Literal["create_page", "deep_research", "skip"] = "create_page"
```

---

### 🟡 P1 - 中优先级（增强系统能力）

#### 5. 知识图谱可视化

**Nash 实现**：
- sigma.js + graphology + ForceAtlas2
- 4-Signal 相关性模型
- 节点大小/颜色/边粗细可视化
- 悬停交互高亮

**本项目现状**：
- 有 `src/knowledge/graph/` 骨架
- 有 `Relation` 17 种类型
- 无可视化前端

**吸收建议**：
- Phase 1：实现 `graph_builder.py` 导出图数据 JSON
- Phase 2：在 Web UI 添加图谱页面
- Phase 3：实现相关性模型

```python
# 新增 src/services/graph.py
def export_graph(project_id: str) -> dict:
    """导出图谱数据供前端可视化"""
    pages = get_all_pages(project_id)
    nodes = [{"id": p.id, "label": p.title, "type": p.type} for p in pages]
    edges = []
    for p in pages:
        for r in p.relations:
            edges.append({"source": p.id, "target": r.target, "weight": r.weight})
    return {"nodes": nodes, "edges": edges}
```

---

#### 6. Louvain 社区检测

**Nash 实现**：
- 自动发现知识集群
- 凝聚度评分
- 低凝聚度集群警告

**吸收建议**：
```python
# 新增 src/wiki/features/community.py
from graphology_communities_louvain import louvain

def detect_communities(pages: list[WikiPage]) -> dict[str, int]:
    """检测知识社区"""
    graph = build_graph(pages)
    communities = louvain.assign(graph)
    return communities

def community_cohesion(pages: list[WikiPage], community_id: int) -> float:
    """计算社区凝聚度"""
    # 内部边数 / 可能边数
    ...
```

---

#### 7. Graph Insights

**Nash 实现**：
- 意外连接（跨社区边）
- 知识缺口（孤立页、稀疏社区、桥接节点）
- Deep Research 按钮

**吸收建议**：
```python
# 新增 src/services/insights.py
def find_knowledge_gaps(project_id: str) -> list[dict]:
    gaps = []
    
    # 孤立页面
    isolated = find_isolated_pages(project_id)
    gaps.extend({"type": "isolated", "page": p} for p in isolated)
    
    # 稀疏社区
    communities = detect_communities(project_id)
    for c in communities:
        if c.cohesion < 0.15:
            gaps.append({"type": "sparse_community", "community": c})
    
    # 桥接节点
    bridges = find_bridge_nodes(project_id)
    gaps.extend({"type": "bridge", "page": p} for p in bridges)
    
    return gaps
```

---

#### 8. 多格式文档解析增强

**Nash 实现**：
| 格式 | 方法 |
|------|------|
| PDF | pdfium-render + MinerU Cloud/Local |
| DOCX | docx-rs |
| PPTX | ZIP + XML |
| XLSX/XLS/ODS | calamine |
| EPUB/MOBI | epub + mobi 库 |
| 图片 | vision LLM 描述 |

**本项目现状**：
- PDF: pypdf（基础）
- DOCX: python-docx
- XLSX: openpyxl
- 无 EPUB/MOBI 支持
- 无图片理解

**吸收建议**：
```python
# 扩展 SourceType
class SourceType(str, Enum):
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    HTML = "html"
    MD = "md"
    TXT = "txt"
    URL = "url"
    EPUB = "epub"  # 新增
    MOBI = "mobi"  # 新增
    IMAGE = "image"  # 新增

# 新增 src/utils/extract/ebook.py
def extract_epub(path: Path) -> str:
    import epub
    book = epub.open_epub(path)
    return "\n\n".join(chapter.content for chapter in book.chapters)
```

---

#### 9. 源文件夹自动监控

**Nash 实现**：
- 监控 `raw/sources/` 外部变更
- 自动同步 Ingest/Delete
- 防止状态漂移

**本项目现状**：
- 有 `FileSyncWatcher` 但已移除
- 无自动监控

**吸收建议**：
```python
# 新增 src/sync/source_watcher.py
from watchfiles import watch

class SourceWatcher:
    def __init__(self, project_path: Path, queue: QueueService):
        self.path = project_path / "raw/sources"
        self.queue = queue
    
    async def start(self):
        async for changes in watch(self.path):
            for change_type, path in changes:
                if change_type == "added":
                    await self.queue.enqueue(path)
                elif change_type == "deleted":
                    await self.cascade_delete(path)
```

---

### 🟢 P2 - 低优先级（可选增强）

#### 10. Chrome Web Clipper

**Nash 实现**：
- Manifest V3 扩展
- Readability.js + Turndown.js
- 自动 Ingest

**吸收建议**：
- 可复用 Nash 的扩展代码
- 修改 API 端点指向本项目的 8765 端口
- 低优先级：本项目用户可通过 URL Ingest 代替

---

#### 11. Agent Skills 系统

**Nash 实现**：
- 扫描 `SKILL.md` 文件
- `/skill` 命令激活
- 工具权限控制

**本项目现状**：
- 无技能系统
- Agent 运行时未实现

**评估**：
- 本项目已有多 Agent 架构（Orchestrator/Librarian/Processor）
- 技能系统可作为 Agent 扩展机制
- 需先完成 Knowledge OS 接线

---

#### 12. 思考过程显示

**Nash 实现**：
- 显示 LLM `<tool_call>...` 思考块
- 折叠展示

**吸收建议**：
- 在 Web UI 聊天界面实现
- 解析响应中的思考块

---

#### 13. Mermaid 图表渲染

**Nash 实现**：
- 内联渲染 Mermaid 代码块
- 错误卡片代替原始输出

**吸收建议**：
- 在 Web UI Markdown 渲染中集成 mermaid.js

---

## 三、架构借鉴

### 1. 前端架构

**Nash 的前端设计**：
```
三栏布局：
┌──────────┬────────────────────┬──────────┐
│ Wiki 树  │      聊天/检索      │   预览   │
│ 文件树   │                     │   编辑   │
└──────────┴────────────────────┴──────────┘
         │                        │
         └──────── 图标侧栏 ────────┘
```

**借鉴建议**：
- 本项目 `web/` 目录为空
- 可复用 Nash 的 React 组件结构
- 适配 FastAPI 后端

---

### 2. 检索流水线

**Nash 的 4-Phase 检索**：
```
Phase 1: 分词搜索
Phase 1.5: 向量语义搜索（可选）
Phase 2: 图扩展（相关性模型）
Phase 3: 预算控制
Phase 4: 上下文组装
```

**本项目现状**：
- 向量 + 关键词 + RRF
- 无图扩展阶段

**借鉴建议**：
- 在 `hybrid_search()` 后增加图扩展
- 利用已有的 `Relation` 数据

```python
def hybrid_search_with_graph(query: str, top_k: int) -> list[SearchResult]:
    # 原有混合检索
    results = hybrid_search(query, top_k)
    
    # 图扩展（2-hop）
    expanded = set()
    for r in results[:10]:  # 取 Top 10 作为种子
        neighbors = find_neighbors(r.path, max_depth=2)
        expanded.update(neighbors)
    
    # 合并 + 重排序
    return merge_and_rerank(results, expanded)
```

---

### 3. 增量缓存

**Nash 实现**：
- SHA256 源文档哈希
- 未修改文件跳过 Ingest
- Token 节省

**本项目现状**：
- 有幂等性缓存（md5，TTL 7天）
- 但无内容变更检测

**借鉴建议**：
```python
# 在 enqueue_source 时计算哈希
def enqueue_source(source: str, project_id: str):
    content = read_source(source)
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    
    # 检查是否已处理过相同内容
    existing = get_existing_page_by_source_hash(project_id, content_hash)
    if existing:
        log(f"Skipping unchanged source: {source}")
        return
```

---

## 四、不建议吸收的功能

| 功能 | 原因 |
|------|------|
| Tauri 桌面框架 | 本项目定位为 CLI + Web，无桌面 GUI 需求 |
| Milkdown 编辑器 | 本项目以 Markdown 文件为真相源，编辑可选 |
| 多 LLM Provider UI | 本项目已有 Provider Registry，只需 Web UI |
| 系统托盘 | CLI 项目无此需求 |

---

## 五、实施优先级排序

### 阶段 1（短期，1-2 周）

| 功能 | 工作量 | 收益 |
|------|--------|------|
| 两步法 Ingest 强制 | 小 | 高（质量控制） |
| overview.md 自动更新 | 小 | 中（导航体验） |
| EPUB/MOBI 解析 | 小 | 中（格式覆盖） |
| 增量缓存增强 | 小 | 中（Token 节省） |

### 阶段 2（中期，2-4 周）

| 功能 | 工作量 | 收益 |
|------|--------|------|
| Deep Research | 中 | 高（知识扩展） |
| Review 系统增强 | 中 | 高（人机协作） |
| 图谱可视化 API | 中 | 高（可观测性） |
| 社区检测 | 中 | 中（知识发现） |

### 阶段 3（长期，1-2 月）

| 功能 | 工作量 | 收益 |
|------|--------|------|
| Web UI 实现 | 大 | 高（用户体验） |
| Graph Insights | 中 | 中（知识缺口） |
| Chrome 扩展 | 中 | 中（摄取便捷） |
| 图扩展检索 | 中 | 中（召回提升） |

---

## 六、关键洞察

### 1. 架构互补性

- **本项目优势**：Knowledge OS 架构完整、治理层丰富、多 Agent 设计
- **Nash 优势**：生产级实现、用户体验完整、可视化前端

**结论**：本项目吸收 Nash 的**前端能力**和**用户交互设计**，保持架构优势。

### 2. 演进策略

```
当前状态（Knowledge OS 已建未接）
    ↓
Phase 1: 接线 + 基础增强（两步法、overview、缓存）
    ↓
Phase 2: 功能扩展（Deep Research、图谱、Review）
    ↓
Phase 3: 前端完善（Web UI、可视化）
    ↓
目标状态（架构先进 + 体验完整）
```

### 3. 复用建议

| Nash 组件 | 复用方式 |
|-----------|----------|
| 前端组件 | Fork React 代码，适配 FastAPI |
| 图谱可视化 | 直接复用 sigma.js + graphology |
| 检索流水线 | Python 重写，复用算法逻辑 |
| Chrome 扩展 | 修改 API 端点配置 |

---

## 七、总结

本项目（ruflo-kb）具有**架构先进性**，Nash 的项目具有**实现完整性**。

**核心吸收方向**：
1. **用户交互层**：Web UI、图谱可视化、Review 界面
2. **检索增强**：图扩展、社区检测、知识缺口发现
3. **功能补全**：Deep Research、多格式解析、增量缓存
4. **体验优化**：overview.md、两步法强制、预生成查询

**保持优势**：
- Knowledge OS 架构（Candidate/Reviewer/Promoter）
- 多 Agent 协作
- 治理层（QualityGate/Lint/Heat/Dedup）
- 服务层设计

**最终目标**：打造一个**架构先进且体验完整**的知识库平台。