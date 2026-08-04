# 吸收方案校验报告

> 校验日期：2026-08-04
> 修复日期：2026-08-04
> 目的：检查方案中的代码示例和设计是否符合现有代码结构

---

## 一、发现的 Bug

### ✅ Bug 1：Relation 字段名错误（已修复）

**位置**：§3.1.1 图扩展检索代码示例（第 945 行）

**问题**：
```python
# 方案中的代码（错误）
for r in p.relations:
    edges.append({
        "target": r.target,  # ❌ 错误：Relation 没有名为 target 的字段
    })
```

**正确写法**：
```python
# Relation 的实际定义（src/wiki/features/relations.py:51-56）
@dataclass
class Relation:
    target_id: str  # ← 字段名是 target_id
    type: str
    weight: float = 1.0
    context: str = ""

# 正确的代码
for r in p.relations:
    edges.append({
        "target": r.target_id,  # ✅ 正确
        "weight": r.weight,
        "type": r.type,
    })
```

**修复状态**：✅ 已修复 - 将 `r.target` 改为 `r.target_id`

---

### ✅ Bug 2：Relation.to_dict() 返回字段名不一致（已知晓）

**位置**：§3.1.1 图扩展检索代码示例

**问题**：
```python
# Relation.to_dict() 返回的是 "target" 而非 "target_id"
def to_dict(self) -> dict:
    return {"target": self.target_id, "type": self.type, ...}  # 注意：key 是 "target"
```

**影响**：如果从 JSON/dict 读取 Relation，key 是 `"target"`；如果是直接访问 Relation 对象，属性名是 `target_id`。

**修复状态**：✅ 方案代码已使用对象访问方式 `r.target_id`，避免了 dict key 问题

---

### ✅ Bug 3：Dedup 代码示例缺少类实例化（已修复）

**位置**：§3.2.2 Dedup 完整实现代码示例（第 714-746 行）

**问题**：
```python
# 方案中的代码（不完整）
async def find_duplicates(
    pages: list[WikiPage],
    llm_provider: LLMProvider,  # ← 参数名有问题
) -> list[DuplicateGroup]:
    summaries = [
        f"{p.id}: {p.title} - {p.body[:200]}"  # ← p.body 可能为 None
        for p in pages
    ]
```

**问题分析**：
1. `llm_provider` 参数：需要从外部传入，但方案没有说明如何获取
2. `p.body` 可能为空字符串，直接切片会报错

**修复状态**：✅ 已修复
```python
async def find_duplicates(
    pages: list[WikiPage],
) -> list[DuplicateGroup]:
    llm = get_default_provider()  # 获取默认 LLM Provider

    summaries = []
    for p in pages:
        body_preview = (p.body or "")[:200]  # 处理空值
        summaries.append(f"{p.id}: {p.title} - {body_preview}")
```

---

### ✅ Bug 4：Deep Research 中缺少 llm 属性（已修复）

**位置**：§3.1.4 Deep Research 代码示例（第 590-641 行）

**问题**：
```python
class DeepResearchService:
    def __init__(self, project_path: str, web_search_provider: str):
        self.project_path = project_path
        self.provider = get_web_search_provider(web_search_provider)
        # ← 缺少 self.llm 初始化

    async def _generate_queries(self, topic: str) -> list[str]:
        response = await self.llm.complete(prompt)  # ← self.llm 未定义
```

**修复状态**：✅ 已修复
```python
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
```

---

### ✅ Bug 5：KnowledgeCandidate 没有 sources 字段（已修复）

**位置**：§3.2.1 Review 系统增强代码示例（第 675-687 行）

**问题**：
```python
@dataclass
class KnowledgeCandidate:
    # ...existing fields...

    # 新增字段
    pre_generated_queries: list[str] = field(default_factory=list)
    suggested_action: Literal["create_page", "deep_research", "skip", "merge"] = "create_page"
```

**实际情况**：KnowledgeCandidate 现有字段（`src/knowledge/core/candidate.py`）：
```python
@dataclass
class KnowledgeCandidate:
    id: str
    source_id: str
    type: KnowledgeType
    title: str
    claims: list[dict]
    evidence: list[dict]
    status: CandidateStatus = CandidateStatus.PENDING
```

**问题**：
1. 没有 `sources` 字段，只有 `source_id`
2. 需要在 dataclass 中添加新字段，但要确保默认值正确

**修复状态**：✅ 已修复 - 明确字段顺序和默认值
```python
@dataclass
class KnowledgeCandidate:
    # ...existing fields (id, source_id, type, title, claims, evidence, status)...

    # 新增字段（需要在 status 之后，使用 field 默认值）
    pre_generated_queries: list[str] = field(default_factory=list)
    suggested_action: Literal["create_page", "deep_research", "skip", "merge"] = "create_page"
    action_reason: str = ""
```

---

### ✅ Bug 6：Watcher 监控路径可能不存在（已修复）

**位置**：§3.2.3 源文件夹监控代码示例（第 787-819 行）

**问题**：
```python
class SourceWatcher:
    def __init__(self, project_path: Path):
        self.sources_path = project_path / "raw/sources"
        # ← 可能不存在
```

**修复状态**：✅ 已修复
```python
class SourceWatcher:
    def __init__(self, project_path: Path):
        self.project_path = project_path
        self.sources_path = project_path / "raw/sources"

        # 确保目录存在
        self.sources_path.mkdir(parents=True, exist_ok=True)

    async def start(self):
        if not self.sources_path.exists():
            return
        # ...existing code
```

---

## 二、架构层面的检查

### ✅ 确认：ReviewerStage 和 CandidatePromoter 存在

**验证结果**：
```
src/pipeline/stages/
├── reviewer.py          # ✅ 存在，10046 bytes
└── candidate_promoter.py  # ✅ 存在，4049 bytes
```

**结论**：方案中"架构激活"的描述正确。

---

### ✅ 确认：Relation 有 weight 字段

**验证结果**：
```python
# src/wiki/features/relations.py:51-56
@dataclass
class Relation:
    target_id: str
    type: str
    weight: float = 1.0  # ✅ 存在
    context: str = ""
```

**结论**：图扩展检索可以依赖 weight 字段。

---

### ✅ 确认：VersionManager 存在

**验证结果**：
```
src/knowledge/core/version_manager.py  # ✅ 存在
```

---

### ✅ 确认：KnowledgeObject 有 lifecycle 字段

**验证结果**：
```python
# src/knowledge/core/object.py
class KnowledgeObject:
    lifecycle: LifecycleState  # ✅ 存在
```

---

## 三、依赖检查

### 🟡 需要新增的依赖

| 依赖 | Phase | 是否可选 | 说明 |
|------|-------|----------|------|
| `watchfiles` | Phase 2 | 必需 | 源文件夹监控 |
| `tavily-python` | Phase 2 | 可选 | 网络搜索，可替换 |
| `ebooklib` | Phase 1 | 必需 | EPUB 解析 |
| `mobi` | Phase 1 | 必需 | MOBI 解析 |
| `python-louvain` | Phase 3 | 必需 | 社区检测 |
| `networkx` | Phase 3 | 必需 | 图算法 |

**建议**：将网络搜索依赖设为 optional：
```toml
[project.optional-dependencies]
web-search = ["tavily-python>=0.3.0"]
ebook = ["ebooklib>=0.18", "mobi>=0.3"]
graph = ["python-louvain>=0.16", "networkx>=3.0"]
```

---

## 四、修复建议汇总

### 已修复（代码正确性问题）

| Bug | 文件 | 行号 | 修复内容 | 状态 |
|-----|------|------|----------|------|
| Bug 1 | 方案文档 | 945 | `r.target` → `r.target_id` | ✅ 已修复 |
| Bug 3 | 方案文档 | 714 | 添加空值处理 `p.body or ""` + 自动获取 LLM | ✅ 已修复 |
| Bug 4 | 方案文档 | 590 | 添加 `self.llm` 初始化 | ✅ 已修复 |
| Bug 5 | 方案文档 | 675 | 明确 KnowledgeCandidate 字段顺序 | ✅ 已修复 |
| Bug 6 | 方案文档 | 787 | 添加目录存在性检查 | ✅ 已修复 |

### 已知晓（设计决策）

| Bug | 说明 | 状态 |
|-----|------|------|
| Bug 2 | Relation.to_dict() 返回 `"target"` key，但方案使用对象访问方式 | ✅ 无问题 |

---

## 五、其他建议

### 5.1 增加 Shadow 模式说明

方案 §6.3 提到"Shadow 双跑模式"，但没有详细说明实现：

**建议补充**：
```python
# src/pipeline/ingest.py
async def run_ingest(..., shadow_mode: bool = False):
    if shadow_mode:
        # 同时运行新旧路径
        legacy_result = await run_ingest_legacy(...)
        new_result = await run_ingest_new(...)
        
        # 比较结果，写入报告
        await compare_and_report(legacy_result, new_result)
        
        # 默认返回 legacy 结果（安全）
        return legacy_result
    else:
        # 正常路径
        return await run_ingest_new(...)
```

### 5.2 增加回滚机制

方案提到"30 秒回滚"，但没有具体实现：

**建议补充**：
```python
# src/config.py
RUFLO_PIPELINE_ROLLBACK_TIMEOUT: int = 30  # seconds

# src/pipeline/service.py
class PipelineService:
    async def run_with_rollback(self, ...):
        start_time = time.time()
        try:
            result = await self.run_new_path(...)
            if time.time() - start_time > self.rollback_timeout:
                # 超时，切换回旧路径
                return await self.run_legacy_path(...)
            return result
        except Exception:
            # 失败，回滚到旧路径
            return await self.run_legacy_path(...)
```

---

## 六、结论

### 总体评价

方案设计**架构清晰**，吸收策略合理，代码示例**已全部修复**。

### 修复完成情况

| Bug 类型 | 数量 | 状态 |
|----------|------|------|
| 严重 Bug (字段名、初始化) | 2 | ✅ 已修复 |
| 中等问题 (空值、字段顺序) | 3 | ✅ 已修复 |
| 设计知晓 (dict key) | 1 | ✅ 无需修复 |

### 方案状态

**✅ 可执行** - 所有代码示例已验证并修复，可开始实施。

### 下一步

1. ✅ 方案文档 Bug 已修复
2. ✅ 校验报告已更新
3. 可选：补充 Shadow 模式和回滚机制的详细设计（已在方案 §6.3 提及框架）
4. 可选：确认依赖项可选性配置（已在方案中说明）