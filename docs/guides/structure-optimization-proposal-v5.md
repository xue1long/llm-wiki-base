# ruflo-kb 项目结构优化方案 v5

> **版本**：v5.0 | 2026-08-03
> **状态**：已根据复核报告修正
> **变更日志**：补充 `knowledge/memory/` 使用分析、修正阶段 3 决策指引

---

## 修订说明（v4 → v5）

| 修正点 | 内容 |
|--------|------|
| 补充发现 | `knowledge/memory/` 被 MCP memory API 设计使用，不是纯粹死代码 |
| 修正阶段 3 | 明确 KOS 组件的决策选项：接线 / 标记 experimental / 删除 |
| 补充建议 | `utils.slugify` 可扩展支持 `max_len` 参数，统一两个实现 |
| 确认判断 | slugify 合并和 test_helpers 移动的"暂缓/不建议"判断正确 |

---

## 一、阶段 0 — 零风险清理

### 任务 0.1: .gitignore 修复（可选执行）

```bash
git check-ignore src/pipeline/wiki_rules_prompt.py
```

若未被忽略，添加：
```gitignore
src/pipeline/wiki_rules_prompt.py
```

---

### 任务 0.2: 移动 orchestrator 到 _deprecated/（可选执行）

```bash
mkdir -p src/_deprecated
git mv src/orchestrator src/_deprecated/orchestrator
git mv tests/test_orchestrator tests/test_deprecated_orchestrator
```

**注意**：等待阶段 1 验证通过后再执行。

---

### 任务 0.3: page_model.py 兼容层（可选执行）

保留兼容层以防外部依赖：

```python
# src/wiki/core/page_model.py
"""Deprecated: Import WikiPage from src.wiki.core.types instead."""
import warnings
warnings.warn(
    "Importing from 'src.wiki.core.page_model' is deprecated. "
    "Use 'from src.wiki.core.types import WikiPage' instead.",
    DeprecationWarning,
    stacklevel=2
)
from .types import WikiPage
__all__ = ["WikiPage"]
```

```python
# src/wiki/__init__.py
-from .core.page_model import WikiPage
+from .core.types import WikiPage
```

---

### 任务 0.4: 合并 cosine_similarity（可选执行，建议执行）

```python
# src/wiki/features/dedup.py
+from ...utils.similarity import cosine_similarity

- def _cosine_similarity(a: list[float], b: list[float]) -> float:
-     ...
```

**风险**：低。两个实现逻辑一致，只差空列表处理细节。

---

### 任务 0.5: slugify 统一（**暂缓**）

#### 暂缓原因

1. **签名差异**：`decision._slugify(text, max_len=40)` 有截断参数，`utils.slugify(text)` 无
2. **实现差异**：正则替换 vs run-based 处理
3. **用途关键**：用于生成决策页面 ID，是持久化数据
4. **风险 > 收益**：合并可能破坏已有数据一致性

#### 后续决策路径

| 场景 | 建议操作 |
|------|----------|
| 保留 `knowledge/memory/` | 扩展 `utils.slugify` 支持 `max_len` 参数，统一实现 |
| 删除 `knowledge/memory/` | 无需处理，随目录删除 |
| 接线 MCP memory API | 必须保留 `_slugify` 或统一 |

---

### 任务 0.6: 移动 test_helpers.py（**不建议执行**）

#### 不建议原因

1. **成本**：需修改 11 个测试文件 + 4 处文档示例
2. **收益**：仅为"代码位置更合理"
3. **收益/成本比**：≈ 0.1

#### 建议

保留 `src/shared/test_helpers.py` 在原位置，不做任何修改。

---

## 二、阶段 0.5 — Stage 接口统一（必须执行）

### 任务 0.5.1: ReviewerStage 接口适配

```python
# src/pipeline/stages/reviewer.py
class ReviewerStage:
    name = "reviewer"
    
    async def run(self, ctx: PipelineContext, prev_result) -> StageResult:
        if prev_result is None:
            return StageResult(success=False, payload={"error": "no prev_result"})
        
        # 修正：检查 payload 类型
        candidate = None
        if isinstance(prev_result.payload, KnowledgeCandidate):
            candidate = prev_result.payload
        elif isinstance(prev_result.payload, dict) and "candidate" in prev_result.payload:
            candidate = prev_result.payload["candidate"]
        
        if candidate is None:
            return StageResult(
                success=False, 
                payload={"error": "prev_result.payload is not a KnowledgeCandidate"}
            )
        
        project_path = Path(ctx.source_path) if ctx.source_path else Path(ctx.source)
        result = self.review(candidate, project_path)
        
        return StageResult(
            success=(result.status == "VALIDATED"),
            payload={"review_result": result, "candidate": candidate}
        )
```

---

### 任务 0.5.2: CandidatePromoter 接口适配

```python
# src/pipeline/stages/candidate_promoter.py
class CandidatePromoter:
    name = "candidate_promoter"
    
    async def run(self, ctx: PipelineContext, prev_result) -> StageResult:
        if prev_result is None:
            return StageResult(success=False, payload={"error": "no prev_result"})
        
        payload = prev_result.payload
        if not isinstance(payload, dict):
            return StageResult(success=False, payload={"error": "payload is not a dict"})
        
        # 修正：用 in 检查而非 hasattr
        if "review_result" not in payload or "candidate" not in payload:
            return StageResult(
                success=False, 
                payload={"error": "payload missing review_result or candidate"}
            )
        
        review_result = payload["review_result"]
        candidate = payload["candidate"]
        
        if review_result.status != "VALIDATED":
            return StageResult(
                success=False,
                payload={"error": f"candidate not validated: {review_result.status}"}
            )
        
        try:
            ko = self.promote(candidate)
            return StageResult(
                success=True,
                payload={"knowledge_object": ko, "candidate": candidate}
            )
        except ValueError as e:
            return StageResult(success=False, payload={"error": str(e)})
```

---

### 任务 0.5.3: GeneratorStage 修正

```python
# src/pipeline/stages/generator.py
class GeneratorStage:
    name = "generator"
    
    async def run(self, ctx: PipelineContext, prev_result) -> StageResult:
        if prev_result is None:
            return StageResult(success=False, payload={"error": "no prev_result"})
        
        payload = prev_result.payload
        if not isinstance(payload, dict) or "knowledge_object" not in payload:
            return StageResult(success=False, payload={"error": "no knowledge_object in payload"})
        
        ko = payload["knowledge_object"]
        candidate = payload.get("candidate")
        
        pages = await _generator_module.generate_from_knowledge_object(
            ko=ko,
            candidate=candidate,
            paths=ctx.paths,
            existing_wiki_index="",
            provider=ctx.provider,
            source_slug_map={},
            source_text=ctx.source,
        )
        
        return StageResult(success=True, payload={"pages": pages, "knowledge_object": ko})
```

---

### 任务 0.5.4: CommitStage 新建（关键）

```python
# src/pipeline/stages/committer.py（新文件）
"""CommitStage — writes WikiPage(s) to disk and updates index/log."""

class CommitStage:
    name = "committer"
    
    async def run(self, ctx: PipelineContext, prev_result) -> StageResult:
        if prev_result is None:
            return StageResult(success=False, payload={"error": "no prev_result"})
        
        payload = prev_result.payload
        if not isinstance(payload, dict) or "pages" not in payload:
            return StageResult(success=False, payload={"error": "no pages in payload"})
        
        pages = payload["pages"]
        paths = ctx.paths
        
        ensure_knowledge_base(paths.root)
        
        written_ids = []
        errors = []
        
        for page in pages:
            try:
                write_page(page, paths)
                append_to_index(page, paths)
                written_ids.append(page.id)
            except Exception as e:
                errors.append({"page_id": page.id, "error": str(e)})
        
        if written_ids:
            append_to_log({
                "timestamp": int(time.time() * 1000),
                "action": "ingest_commit",
                "pages": written_ids,
                "task_id": ctx.task_id,
            }, paths)
        
        return StageResult(
            success=len(written_ids) > 0,
            payload={"written_ids": written_ids, "errors": errors}
        )
```

---

### 任务 0.5.5: 注册所有 Stage

```python
# src/pipeline/stages/__init__.py
from .collector import CollectorStage
from .analyzer import AnalyzerStage
from .reviewer import ReviewerStage, ReviewResult
from .candidate_promoter import CandidatePromoter
from .generator import GeneratorStage
from .committer import CommitStage

__all__ = [
    "CollectorStage",
    "AnalyzerStage",
    "ReviewerStage",
    "ReviewResult",
    "CandidatePromoter",
    "GeneratorStage",
    "CommitStage",
]
```

---

## 三、阶段 1 — 核心缺陷修复（必须执行）

### 任务 1.1: PageType 收敛为单一真源

（保持 v4 设计）

### 任务 1.2: Stage 机制接线

（保持 v4 设计）

### 任务 1.3: PipelineContext 扩展

```python
# src/pipeline/ports.py
@dataclass
class PipelineContext:
    task_id: str
    source: str
    source_type: SourceType
    project_id: str | None = None
    paths: Any = None
    provider: Any = None
    model: str = "gpt-4o-mini"
    collector_result: Any = None
    analysis_result: Any = None
    folder_context: str = ""
    source_path: str = ""  # 新增
```

---

## 四、阶段 2 — 结构收敛（可选执行）

（保持 v4 设计，略）

---

## 五、阶段 3 — KOS 组件裁决（已修正）

### 重要发现

`knowledge/memory/` **不是纯粹死代码**：

```python
# src/mcp_server/memory_tools.py:373
decision_recorder: Optional ``DecisionRecorder`` instance.
```

MCP memory API 设计中使用了 `DecisionRecorder`，该类定义在 `knowledge/memory/decision.py`。

### 决策选项

| 选项 | 操作 | 影响分析 |
|------|------|----------|
| **A: 接线 MCP memory API** | 保留 `knowledge/memory/`，在 MCP 服务器启动时注入 `DecisionRecorder` | ✅ 推荐：保留 API 完整性 |
| **B: 标记为 experimental** | 移动到 `knowledge/experimental/memory/`，文档说明"未完全接线" | ⚠️ 中立：明确状态 |
| **C: 删除** | 删除 `knowledge/memory/`，移除 MCP memory API 相关参数 | ❌ 不推荐：破坏 API 设计 |

### 推荐方案：选项 A（接线）

#### 任务 3.1: 在 MCP 服务器中注入 DecisionRecorder

```python
# src/mcp_server/main.py
from ..knowledge.memory.decision import DecisionRecorder

def start_server():
    ...
    wiki_paths = WikiPaths(project_root)
    
    # 接线 DecisionRecorder
    decision_recorder = DecisionRecorder(wiki_paths)
    
    register_memory_tools(
        server,
        memory_retrieval=memory_retrieval,  # 可能为 None
        decision_recorder=decision_recorder,
        wiki_paths=wiki_paths,
    )
```

#### 任务 3.2: slugify 统一（如果保留 knowledge/memory/）

如果选择接线 MCP memory API，需要统一 slugify 实现：

```python
# src/utils/slugify.py（扩展）
def slugify(text, max_len: int | None = None) -> str:
    """Return a deterministic CJK-friendly slug for ``text``.
    
    Args:
        text: Input string
        max_len: Optional maximum length (truncates if exceeded)
    """
    if text is None:
        return ""
    text = unicodedata.normalize("NFC", text).strip()
    if not text:
        return ""
    
    # ... existing run-based logic ...
    result = out.strip("-")
    
    # 新增：截断支持（兼容 decision._slugify 行为）
    if max_len is not None and len(result) > max_len:
        result = result[:max_len].rstrip("-")
    
    return result or "decision"
```

然后修改 `decision.py`：

```python
# src/knowledge/memory/decision.py
-from ._slugify import _slugify
+from ...utils.slugify import slugify as _slugify

# 或直接使用
slug = slugify(question, max_len=40)
```

---

## 六、任务优先级分类

### 必须执行（阶段 0.5 + 阶段 1）

| 任务 | 优先级 | 耗时 |
|------|--------|------|
| ReviewerStage 接口适配 | P0 | 30 分钟 |
| CandidatePromoter 接口适配 | P0 | 30 分钟 |
| GeneratorStage 修正 | P0 | 30 分钟 |
| **CommitStage 新建** | P0 | 1 小时 |
| 注册所有 Stage | P0 | 10 分钟 |
| PipelineContext 扩展 | P0 | 10 分钟 |
| PageType 收敛 | P0 | 1 小时 |
| Stage 机制接线 | P0 | 1 小时 |

**总耗时**：约 4-5 小时

---

### 可选执行（阶段 0）

| 任务 | 建议 | 耗时 |
|------|------|------|
| .gitignore 修复 | ✅ 建议 | 5 分钟 |
| cosine_similarity 合并 | ✅ 建议 | 15 分钟 |
| orchestrator 移动 | ✅ 建议（阶段 1 验证后） | 20 分钟 |
| page_model.py 兼容层 | ⚠️ 若有外部依赖则必须 | 15 分钟 |

---

### 不建议执行

| 任务 | 原因 |
|------|------|
| slugify 合并 | 函数语义不同，用于持久化数据 ID，风险 > 收益（**暂缓，待阶段 3 决策**） |
| test_helpers.py 移动 | 成本高（15+ 文件），收益低（仅为位置合理） |

---

## 七、文件修改清单

### 必须新建

| 文件 | 内容 |
|------|------|
| `src/pipeline/stages/committer.py` | CommitStage |
| `tests/test_pipeline/test_stage_interface.py` | Stage 接口测试 |

### 必须修改

| 文件 | 内容 |
|------|------|
| `src/pipeline/stages/reviewer.py` | 添加 name + async run() |
| `src/pipeline/stages/candidate_promoter.py` | 添加 name + async run() |
| `src/pipeline/stages/generator.py` | 修正接收 KnowledgeObject |
| `src/pipeline/stages/__init__.py` | 注册 CommitStage |
| `src/pipeline/service.py` | 回退开关 + stage 链 |
| `src/pipeline/ports.py` | 添加 source_path |
| `src/wiki/core/types.py` | 新增 _TYPE_TO_DIR |

### 可选修改

| 文件 | 内容 |
|------|------|
| `.gitignore` | 检查/添加 |
| `src/wiki/features/dedup.py` | 合并 cosine_similarity |
| `src/wiki/__init__.py` | 改导入 |
| `src/wiki/core/page_model.py` | 兼容层 |

### 暂缓修改

| 文件 | 原因 |
|------|------|
| `src/knowledge/memory/decision.py` | 等待阶段 3 决策 |

---

## 八、执行检查表

### 阶段 0.5（必须）

- [ ] ReviewerStage 添加 name + async run()
- [ ] CandidatePromoter 添加 name + async run()
- [ ] GeneratorStage 修正
- [ ] CommitStage 新建
- [ ] stages/__init__.py 注册
- [ ] pytest 通过

### 阶段 1（必须）

- [ ] types.py 新增 _TYPE_TO_DIR
- [ ] service.py 回退开关
- [ ] ports.py 扩展
- [ ] pytest 通过
- [ ] 测试环境验证

### 阶段 0（可选）

- [ ] .gitignore 检查
- [ ] cosine_similarity 合并
- [ ] orchestrator 移动（阶段 1 验证后）
- [ ] page_model.py 兼容层（若有外部依赖）

### 阶段 3（产品决策）

- [ ] 确认 MCP memory API 是否接线
- [ ] 若接线：保留 knowledge/memory/ + 统一 slugify
- [ ] 若不接线：移动到 experimental/

---

## 九、数据流图

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Stage 调度数据流                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  CollectorStage                                                      │
│      ↓ payload: CollectorDonePayload                                 │
│  AnalyzerStage                                                       │
│      ↓ payload: KnowledgeCandidate                                   │
│  ReviewerStage                                                       │
│      ↓ payload: {review_result, candidate}                           │
│  CandidatePromoter                                                   │
│      ↓ payload: {knowledge_object, candidate}                        │
│  GeneratorStage                                                      │
│      ↓ payload: {pages, knowledge_object}                            │
│  CommitStage                                                         │
│      ↓ payload: {written_ids, errors}                                │
│  完成: task status = APPROVED                                        │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```