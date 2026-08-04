# ruflo-kb 项目结构优化方案 v4

> **版本**：v4.0 | 2026-08-03
> **状态**：已修复影响审核发现的 5 个高风险问题
> **变更日志**：修复 Stage 接口适配逻辑错误、增加 CommitStage、暂缓 slugify 合并

---

## 修订说明（v3 → v4）

| 问题 ID | 描述 | 修复方式 |
|---------|------|----------|
| R1 | `_slugify` 签名/实现不一致 | **暂缓任务**，待阶段 3 决策 |
| R2 | `ReviewerStage.run()` 检查逻辑错误 | 修正为检查 `payload` 结构 |
| R3 | `CandidatePromoter.run()` 字典检查错误 | 用 `in` 检查而非 `hasattr` |
| R4 | `ctx.candidates` 属性不存在 | 修正数据来源，从 `ctx.analysis_result` 获取 |
| R5 | 新路径缺少写盘逻辑 | **新增 CommitStage** |

---

## 一、阶段 0 — 零风险清理

预计耗时：2 小时

### 任务 0.1: .gitignore 修复

（保持不变）

```bash
git check-ignore src/pipeline/wiki_rules_prompt.py
```

若未被忽略，添加：
```gitignore
src/pipeline/wiki_rules_prompt.py
```

---

### 任务 0.2: 移动 orchestrator 到 _deprecated/

（保持不变）

```bash
mkdir -p src/_deprecated
git mv src/orchestrator src/_deprecated/orchestrator
git mv tests/test_orchestrator tests/test_deprecated_orchestrator
```

---

### 任务 0.3: 删除 page_model.py（含兼容层）

**修正**：保留兼容层以防外部依赖。

```python
# src/wiki/core/page_model.py（保留作为兼容层）
"""Deprecated: Import WikiPage from src.wiki.core.types instead.

This module exists for backwards compatibility with external code that may
import WikiPage from this path. It will be removed in a future version.
"""
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

**验证**：
```bash
# 验证兼容层工作
python -c "from src.wiki.core.page_model import WikiPage; print('OK')"
# 应打印 OK 并显示 DeprecationWarning
```

---

### 任务 0.4: 合并 cosine_similarity

（保持不变，风险低）

```python
# src/wiki/features/dedup.py
+from ...utils.similarity import cosine_similarity

- def _cosine_similarity(a: list[float], b: list[float]) -> float:
-     ...
```

---

### 任务 0.5: （暂缓）合并 slugify

**修正**：根据影响审核 R1，两个函数签名和实现不一致，暂缓此任务。

**原因**：
1. `decision._slugify(text, max_len=40)` 有截断参数
2. `utils.slugify(text)` 无截断参数
3. 实现逻辑不同（正则 vs run-based）

**决策**：等待阶段 3 决定是否删除 `knowledge/memory/`。若保留，再评估合并方案。

---

### 任务 0.6: （可选）移动 test_helpers.py

（保持不变，建议延后）

---

## 二、阶段 0.5 — Stage 接口统一（已修正）

预计耗时：3 小时

### 任务 0.5.1: ReviewerStage 接口适配（已修正）

```python
# src/pipeline/stages/reviewer.py
from __future__ import annotations
from pathlib import Path
from ..ports import PipelineContext, StageResult
from ...knowledge.core.candidate import KnowledgeCandidate


class ReviewerStage:
    """Phase 1: Pure rule engine. Validates KnowledgeCandidate before promotion."""
    
    name = "reviewer"
    
    async def run(self, ctx: PipelineContext, prev_result) -> StageResult:
        """PipelineStage protocol wrapper for review().
        
        Expected prev_result.payload structure:
            - If from AnalyzerStage: KnowledgeCandidate object
            - If from other stage: may vary
        
        Returns:
            StageResult with payload={"review_result": ReviewResult, "candidate": KnowledgeCandidate}
        """
        if prev_result is None:
            return StageResult(success=False, payload={"error": "no prev_result"})
        
        # 修正：prev_result.payload 是 KnowledgeCandidate（来自 AnalyzerStage）
        # 或者是 dict（如果其他 stage 传入）
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
        
        # 调用原有的 review 方法
        project_path = Path(ctx.source_path) if ctx.source_path else Path(ctx.source)
        result = self.review(candidate, project_path)
        
        # 返回包含 review 结果的 StageResult
        return StageResult(
            success=(result.status == "VALIDATED"),
            payload={
                "review_result": result,
                "candidate": candidate,
            }
        )
    
    def review(self, candidate: KnowledgeCandidate, project_path: Path) -> ReviewResult:
        """原有逻辑保持不变"""
        # ...（现有代码）
```

---

### 任务 0.5.2: CandidatePromoter 接口适配（已修正）

```python
# src/pipeline/stages/candidate_promoter.py
from __future__ import annotations
from ..ports import PipelineContext, StageResult
from ...knowledge.core.candidate import KnowledgeCandidate, CandidateStatus
from ...knowledge.core.object import KnowledgeObject, LifecycleState, Provenance, VersionRef


class CandidatePromoter:
    """Converts a VALIDATED KnowledgeCandidate into a KnowledgeObject."""
    
    name = "candidate_promoter"
    
    async def run(self, ctx: PipelineContext, prev_result) -> StageResult:
        """PipelineStage protocol wrapper for promote().
        
        Expected prev_result.payload structure (from ReviewerStage):
            {
                "review_result": ReviewResult,
                "candidate": KnowledgeCandidate
            }
        
        Returns:
            StageResult with payload={"knowledge_object": KnowledgeObject}
        """
        if prev_result is None:
            return StageResult(success=False, payload={"error": "no prev_result"})
        
        # 修正：用 dict 成员检查而非 hasattr
        payload = prev_result.payload
        if not isinstance(payload, dict):
            return StageResult(success=False, payload={"error": "payload is not a dict"})
        
        if "review_result" not in payload or "candidate" not in payload:
            return StageResult(
                success=False, 
                payload={"error": "payload missing review_result or candidate"}
            )
        
        review_result = payload["review_result"]
        candidate = payload["candidate"]
        
        # 只处理 VALIDATED 的 candidate
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
    
    def promote(self, candidate: KnowledgeCandidate) -> KnowledgeObject:
        """原有逻辑保持不变"""
        # ...（现有代码）
```

---

### 任务 0.5.3: GeneratorStage 适配（已修正）

**问题**：现有 GeneratorStage 只渲染页面，不写盘。需要修正以接收 KnowledgeObject。

```python
# src/pipeline/stages/generator.py（修正版）
from __future__ import annotations
from ..ports import PipelineContext, StageResult
from .. import generator as _generator_module


class GeneratorStage:
    """Renders WikiPage from KnowledgeObject."""
    
    name = "generator"
    
    async def run(self, ctx: PipelineContext, prev_result) -> StageResult:
        """Render WikiPage(s) from KnowledgeObject.
        
        Expected prev_result.payload structure (from CandidatePromoter):
            {
                "knowledge_object": KnowledgeObject,
                "candidate": KnowledgeCandidate
            }
        """
        if prev_result is None:
            return StageResult(success=False, payload={"error": "no prev_result"})
        
        payload = prev_result.payload
        if not isinstance(payload, dict) or "knowledge_object" not in payload:
            return StageResult(success=False, payload={"error": "no knowledge_object in payload"})
        
        ko = payload["knowledge_object"]
        candidate = payload.get("candidate")
        
        # 调用 generate_from_knowledge_object
        pages = await _generator_module.generate_from_knowledge_object(
            ko=ko,
            candidate=candidate,
            paths=ctx.paths,
            existing_wiki_index="",  # 可从 ctx 获取
            provider=ctx.provider,
            source_slug_map={},  # 可从 ctx 获取
            source_text=ctx.source,  # 或从 collector_result 获取
        )
        
        return StageResult(
            success=True,
            payload={"pages": pages, "knowledge_object": ko}
        )
```

---

### 任务 0.5.4: CommitStage（新增，解决 R5）

**目的**：负责写盘、更新 index.md、向量嵌入。

```python
# src/pipeline/stages/committer.py（新文件）
"""CommitStage — writes WikiPage(s) to disk and updates index/log."""

from __future__ import annotations
import time
import logging
from ..ports import PipelineContext, StageResult
from ...wiki.storage.page_writer import write_page
from ...wiki.storage.ensure import ensure_knowledge_base
from ...wiki.features.indexer import append_to_index
from ...wiki.features.logger import append_to_log

_logger = logging.getLogger(__name__)


class CommitStage:
    """Terminal stage: persists WikiPage(s) to disk.
    
    Responsibilities:
    1. Write each WikiPage to the correct subdirectory
    2. Append to wiki/index.md (catalog)
    3. Append to wiki/log.md (audit trail)
    4. (Future) Vector embedding via IndexerStage
    """
    
    name = "committer"
    
    async def run(self, ctx: PipelineContext, prev_result) -> StageResult:
        """Write pages to disk.
        
        Expected prev_result.payload structure (from GeneratorStage):
            {
                "pages": list[WikiPage],
                "knowledge_object": KnowledgeObject
            }
        """
        if prev_result is None:
            return StageResult(success=False, payload={"error": "no prev_result"})
        
        payload = prev_result.payload
        if not isinstance(payload, dict) or "pages" not in payload:
            return StageResult(success=False, payload={"error": "no pages in payload"})
        
        pages = payload["pages"]
        if not pages:
            return StageResult(success=False, payload={"error": "empty pages list"})
        
        paths = ctx.paths
        if paths is None:
            return StageResult(success=False, payload={"error": "no paths in context"})
        
        # 确保目录存在
        ensure_knowledge_base(paths.root)
        
        written_ids = []
        errors = []
        
        for page in pages:
            try:
                # 写入页面
                write_page(page, paths)
                written_ids.append(page.id)
                
                # 追加到 index.md
                append_to_index(page, paths)
                
                _logger.info("Committed page %s to %s", page.id, page.type.value)
            except Exception as e:
                _logger.error("Failed to commit page %s: %s", page.id, e)
                errors.append({"page_id": page.id, "error": str(e)})
        
        # 追加到 log.md
        if written_ids:
            log_entry = {
                "timestamp": int(time.time() * 1000),
                "action": "ingest_commit",
                "pages": written_ids,
                "task_id": ctx.task_id,
            }
            append_to_log(log_entry, paths)
        
        if errors:
            return StageResult(
                success=len(written_ids) > 0,  # 部分成功也算成功
                payload={"written_ids": written_ids, "errors": errors}
            )
        
        return StageResult(
            success=True,
            payload={"written_ids": written_ids, "pages": pages}
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
from .committer import CommitStage  # 新增

__all__ = [
    "CollectorStage",
    "AnalyzerStage",
    "ReviewerStage",
    "ReviewResult",
    "CandidatePromoter",
    "GeneratorStage",
    "CommitStage",  # 新增
]
```

---

## 三、阶段 1 — 核心缺陷修复

### 任务 1.1: PageType 收敛为单一真源

（保持 v3 设计，略）

---

### 任务 1.2: Stage 机制接线（已修正）

**修正点**：
1. 在创建 ctx 之前获取 paths/provider
2. 增加完整的 stage 链：Collector → Analyzer → Reviewer → Promoter → Generator → Committer
3. 保留回退开关

```python
# src/pipeline/service.py
import os
from __future__ import annotations

USE_STAGE_SCHEDULER = os.environ.get("RUFLO_USE_STAGE_SCHEDULER", "false") == "true"


class PipelineService:
    def __init__(self, queue_service=None, max_concurrency: int = DEFAULT_MAX_CONCURRENCY) -> None:
        self._queue_service_factory = queue_service or get_default_queue_service
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self.runner = PipelineRunner(self._queue_service_factory())
        # 注册完整的 stage 链
        from .stages import (
            CollectorStage, AnalyzerStage, ReviewerStage,
            CandidatePromoter, GeneratorStage, CommitStage
        )
        self._stages: list[PipelineStage] = [
            CollectorStage(),
            AnalyzerStage(),
            ReviewerStage(),
            CandidatePromoter(),
            GeneratorStage(),
            CommitStage(),
        ]

    async def _run_for_collector_start_inner(self, task_id, source, source_type, project_id, folder_context=None):
        """处理摄取任务"""
        
        # 修正：先获取 paths 和 provider（在 try 块之前）
        import src.pipeline.pipeline as _pipeline_mod
        from pathlib import Path as _Path
        paths = _pipeline_mod._resolve_wiki_paths(project_id=project_id)
        provider = _pipeline_mod._get_provider(project_id=project_id)
        
        # 标记 RUNNING
        try:
            self.queue_service.update_status(task_id, status=TaskStatus.RUNNING)
        except Exception:
            ...
            return
        
        try:
            if USE_STAGE_SCHEDULER:
                # ========== 新路径：Stage 调度器 ==========
                ctx = PipelineContext(
                    task_id=task_id,
                    source=source,
                    source_type=source_type,
                    project_id=project_id,
                    paths=paths,
                    provider=provider,
                    source_path=source,  # 新增
                )
                
                prev_result = None
                for stage in self._stages:
                    _logger.info("Running stage %s for task %s", stage.name, task_id)
                    result = await stage.run(ctx, prev_result)
                    if not result.success:
                        self.queue_service.update_status(
                            task_id, status=TaskStatus.FAILED,
                            error=f"stage {stage.name} failed: {result.payload}",
                        )
                        return
                    prev_result = result
                
                self.queue_service.update_status(task_id, status=TaskStatus.APPROVED)
            else:
                # ========== 旧路径：保持不变 ==========
                ctx = PipelineContext(
                    task_id=task_id,
                    source=source,
                    source_type=source_type,
                    project_id=project_id,
                )
                
                # 只跑 Collector
                for stage in self._stages[:1]:
                    result = await stage.run(ctx, prev_result=None)
                    if not result.success:
                        self.queue_service.update_status(
                            task_id, status=TaskStatus.FAILED,
                            error=f"collector stage failed: {result.payload}",
                        )
                        return
                    ctx.collector_result = result.payload
                
                # 调用 run_ingest
                await _pipeline_mod.run_ingest(
                    paths=paths,
                    source_path=_Path(ctx.collector_result.raw_path),
                    source_text=ctx.collector_result.content,
                    provider=provider,
                    folder_context=folder_context or "",
                    task_id=task_id,
                )
                self.queue_service.update_status(task_id, status=TaskStatus.APPROVED)
                
        except Exception as exc:
            _logger.exception("ingest failed for %s", task_id)
            try:
                self.queue_service.update_status(task_id, status=TaskStatus.FAILED, error=str(exc))
            except Exception:
                _logger.exception("failed to update_status to FAILED for %s", task_id)
        finally:
            try:
                self.queue_service.release_in_flight(task_id)
            except Exception:
                _logger.exception("failed to release_in_flight %s", task_id)
```

---

### 任务 1.3: PipelineContext 扩展（新增）

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
    source_path: str = ""  # 新增：用于 ReviewerStage
```

---

## 四、文件修改清单

### 新增文件

| 文件 | 内容 |
|------|------|
| `src/pipeline/stages/committer.py` | CommitStage（写盘） |
| `tests/test_pipeline/test_stage_interface.py` | Stage 接口单元测试 |
| `tests/integration/test_ingest_behavior.py` | 集成测试 |

### 修改文件

| 文件 | 修改内容 |
|------|----------|
| `src/wiki/core/page_model.py` | 保留为兼容层 |
| `src/wiki/__init__.py` | 改从 types 导入 |
| `src/wiki/features/dedup.py` | 改用 utils.similarity |
| `src/pipeline/stages/reviewer.py` | 添加 `name` + `async run()`（已修正） |
| `src/pipeline/stages/candidate_promoter.py` | 添加 `name` + `async run()`（已修正） |
| `src/pipeline/stages/generator.py` | 修正接收 KnowledgeObject |
| `src/pipeline/stages/__init__.py` | 注册 CommitStage |
| `src/pipeline/service.py` | 添加回退开关 + 注册完整 stage 链 |
| `src/pipeline/ports.py` | 添加 source_path 字段 |

### 暂缓修改

| 文件 | 原因 |
|------|------|
| `src/knowledge/memory/decision.py` | 函数签名不一致，待阶段 3 决策 |

---

## 五、执行检查表（已更新）

### 阶段 0 检查表

- [ ] `.gitignore` 检查
- [ ] orchestrator 移动到 `_deprecated/`
- [ ] page_model.py 保留兼容层
- [ ] cosine_similarity 合并
- [ ] ~~slugify 合并~~（暂缓）
- [ ] `pytest` 通过

### 阶段 0.5 检查表

- [ ] ReviewerStage 添加 `name` + `async run()`（修正版）
- [ ] CandidatePromoter 添加 `name` + `async run()`（修正版）
- [ ] GeneratorStage 修正接收 KnowledgeObject
- [ ] **CommitStage 新建**（新增）
- [ ] stages/__init__.py 注册 CommitStage
- [ ] test_stage_interface.py 通过
- [ ] `pytest` 通过

### 阶段 1 检查表

- [ ] types.py 新增 `_TYPE_TO_DIR` + `validate_page_type_supported()`
- [ ] service.py 添加回退开关 + 注册完整 stage 链
- [ ] ports.py 添加 source_path 字段
- [ ] 集成测试覆盖微妙行为
- [ ] `pytest` 通过
- [ ] 测试环境灰度 1 周

---

## 六、风险与缓解措施（已更新）

| 风险 | 缓解措施 | 状态 |
|------|----------|------|
| R1: slugify 签名不一致 | 暂缓任务，待阶段 3 决策 | ✅ 已规避 |
| R2: ReviewerStage 检查逻辑错误 | 修正为检查 payload 结构 | ✅ 已修复 |
| R3: CandidatePromoter 字典检查错误 | 用 `in` 检查 | ✅ 已修复 |
| R4: ctx.candidates 不存在 | 从 prev_result.payload 正确获取 | ✅ 已修复 |
| R5: 新路径缺少写盘逻辑 | 新增 CommitStage | ✅ 已修复 |

---

## 七、附录：数据流图

```
┌─────────────────────────────────────────────────────────────────┐
│                     Stage 调度数据流                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  CollectorStage                                                   │
│  ├─ 输入: ctx                                                     │
│  └─ 输出: StageResult(payload=CollectorDonePayload)              │
│       ↓                                                           │
│  AnalyzerStage                                                    │
│  ├─ 输入: ctx (with collector_result)                            │
│  └─ 输出: StageResult(payload=KnowledgeCandidate)  ←─ 修正点     │
│       ↓                                                           │
│  ReviewerStage                                                    │
│  ├─ 输入: prev_result.payload = KnowledgeCandidate               │
│  └─ 输出: StageResult(payload={review_result, candidate})        │
│       ↓                                                           │
│  CandidatePromoter                                                │
│  ├─ 输入: prev_result.payload = {review_result, candidate}       │
│  └─ 输出: StageResult(payload={knowledge_object, candidate})     │
│       ↓                                                           │
│  GeneratorStage                                                   │
│  ├─ 输入: prev_result.payload = {knowledge_object, ...}          │
│  └─ 输出: StageResult(payload={pages, knowledge_object})         │
│       ↓                                                           │
│  CommitStage                                                      │
│  ├─ 输入: prev_result.payload = {pages, ...}                     │
│  └─ 输出: StageResult(payload={written_ids, pages})              │
│       ↓                                                           │
│  完成: task status = APPROVED                                     │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```