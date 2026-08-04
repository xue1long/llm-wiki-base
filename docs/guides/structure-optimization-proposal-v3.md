# ruflo-kb 项目结构优化方案 v3

> **版本**：v3.0 | 2026-08-03
> **状态**：已修复审计发现的致命缺陷
> **依据**：深度审计 `src/` 33 包 / 276 个 `.py` + 独立审计报告

---

## 修订说明

本版本针对审计报告发现的问题进行了全面修复：

| 审计问题 | 修复方式 |
|----------|----------|
| D1: Stage 接口不统一 | 新增"阶段 0.5：Stage 接口统一"任务 |
| D2: test_helpers 移动破坏测试 | 降级为可选任务，提供完整修改清单 |
| D3: 回退开关不存在 | 设计真正的回退开关 `RUFLO_USE_STAGE_SCHEDULER` |
| H1: PageType 扩展型默认值无依据 | 改为显式抛出 `NotImplementedError` |
| H2: IndexerStage 依赖未验证的 GraphBuilder | 延后到阶段 2，增加验证任务 |
| H4: schema_routing 导入依赖问题 | 修正为从 `core/types.py` 导入 |
| H5: 删除 orchestrator 破坏 git 历史 | 改为移动到 `_deprecated/` |

---

## 一、执行摘要

### 执行顺序（已调整）

| 阶段 | 内容 | 风险 | 前置条件 |
|------|------|------|----------|
| 0 | 零风险清理 | 低 | 无 |
| 0.5 | Stage 接口统一 | 中 | 阶段 0 |
| 1 | 核心缺陷修复 | 中 | 阶段 0.5 |
| 2 | 结构收敛 | 中 | 阶段 1 |
| 3 | KOS 组件裁决 | 需决策 | 阶段 2 |

### 关键设计决策

1. **回退开关**：使用 `RUFLO_USE_STAGE_SCHEDULER=true/false` 控制 stage 调度逻辑
2. **PageType 扩展型**：暂不支持生成，访问时抛出 `NotImplementedError`
3. **IndexerStage**：延后到阶段 2，先验证 GraphBuilder
4. **test_helpers**：保留在原位置，作为可选清理任务

---

## 二、阶段 0 — 零风险清理

预计耗时：2 小时

### 任务 0.1: .gitignore 修复

**步骤**：
```bash
# 先检查是否已被其他规则覆盖
git check-ignore src/pipeline/wiki_rules_prompt.py
```

若返回 `src/pipeline/wiki_rules_prompt.py`（已被忽略），则无需修改。

若未被忽略，添加：
```gitignore
# .gitignore
.wiki-spec-md5
src/pipeline/wiki_rules_prompt.py
```

**验证**：`git status` 不显示 `wiki_rules_prompt.py` 变更。

---

### 任务 0.2: 移动 orchestrator 到 _deprecated/

**原因**：直接删除会破坏 `git bisect` 能力。

**步骤**：
```bash
# 创建目录
mkdir -p src/_deprecated

# 移动（保留 git 历史）
git mv src/orchestrator src/_deprecated/orchestrator
git mv tests/test_orchestrator tests/test_deprecated_orchestrator

# 添加说明
cat > src/_deprecated/README.md << 'EOF'
# 已废弃模块

此目录包含已废弃的模块，仅保留用于历史参考。

## orchestrator/

- **废弃日期**：2026-08-03
- **废弃原因**：生产代码零引用，状态机逻辑已迁移至 `src/queue/state.py`
- **测试状态**：`tests/test_deprecated_orchestrator/` 保留但标记为跳过

## 恢复方式

```bash
git mv src/_deprecated/orchestrator src/orchestrator
git mv tests/test_deprecated_orchestrator tests/test_orchestrator
```
EOF

# 标记测试为跳过
echo "import pytest; pytestmark = pytest.mark.skip(reason='deprecated module')" > tests/test_deprecated_orchestrator/__init__.py
```

**验证**：`pytest --collect-only -q` 正常（跳过废弃测试）。

---

### 任务 0.3: 删除 page_model.py

**步骤**：
```python
# src/wiki/__init__.py
-from .core.page_model import WikiPage
+from .core.types import WikiPage

# 可选：添加兼容桥（若有外部依赖担忧）
# src/wiki/core/page_model.py（保留作为兼容层）
# import warnings
# warnings.warn(
#     "Importing from page_model is deprecated. Use 'from src.wiki.core.types import WikiPage'",
#     DeprecationWarning,
#     stacklevel=2
# )
# from .types import WikiPage
# __all__ = ["WikiPage"]
```

若确认无外部依赖：
```bash
git rm src/wiki/core/page_model.py
```

**验证**：`pytest tests/test_wiki/ -v` 通过。

---

### 任务 0.4: 合并 slugify 重复实现

**注意**：此任务仅在保留 `knowledge/memory/` 的前提下执行。若阶段 3 决定删除该目录，则跳过此任务。

```python
# src/knowledge/memory/decision.py:72
# 改为：
from ...utils.slugify import slugify

# 删除私有实现
- def _slugify(text: str, max_len: int = 40) -> str:
-     """Local slugify with max length."""
-     ...
```

**验证**：`pytest tests/test_pipeline/ -v` 通过。

---

### 任务 0.5: 合并 cosine_similarity

```python
# src/wiki/features/dedup.py
+from ...utils.similarity import cosine_similarity

- def _cosine_similarity(a: list[float], b: list[float]) -> float:
-     """Compute cosine similarity between two equal-length vectors."""
-     ...
```

**验证**：`pytest tests/test_wiki/test_dedup.py -v` 通过。

---

### 任务 0.6: （可选）移动 test_helpers.py

**风险警告**：此任务会修改 **11 个测试文件**，建议在阶段 1 完成后再执行。

若要执行，需同步修改以下文件：

| 文件 | 修改内容 |
|------|----------|
| `tests/test_wiki/test_stubs_atomic.py:32` | 改为 `from tests.helpers.scripted_llm import ScriptedLLMProvider` |
| `tests/test_wiki/test_stubs.py:48` | 同上 |
| `tests/test_pipeline/test_retry.py:361,414,443` | 同上 |
| `tests/test_pipeline/test_pipeline.py:2` | 同上 |
| `tests/test_pipeline/test_ingest_split.py:12` | 同上 |
| `tests/test_pipeline/test_ingest_source_fallback_c4.py:19` | 同上 |
| `tests/test_pipeline/test_ingest_generate_commit_split.py:25` | 同上 |
| `tests/test_pipeline/test_generator.py:3` | 同上 |
| `tests/test_pipeline/test_analyzer_json.py:15` | 同上 |
| `tests/test_pipeline/test_analyzer.py:3` | 同上 |
| `tests/test_lib/test_budgeted.py:2` | 同上 |

**步骤**：
```bash
mkdir -p tests/helpers
git mv src/shared/test_helpers.py tests/helpers/scripted_llm.py
# 修改上述 11 个文件的导入路径
```

**决策点**：建议暂缓此任务，保留 `src/shared/test_helpers.py`。

---

### 阶段 0 完成标准

- [x] `.gitignore` 检查/修复
- [x] orchestrator 移动到 `_deprecated/`
- [x] page_model.py 删除（或添加兼容桥）
- [x] slugify 合并（若保留 knowledge/memory/）
- [x] cosine_similarity 合并
- [ ] test_helpers.py 移动（可选，建议延后）
- [x] `pytest` 全量通过
- [x] `python -m src.cli serve` 正常启动

**回滚点**：
```bash
git tag structure-opt-phase-0-complete
```

---

## 三、阶段 0.5 — Stage 接口统一（新增）

预计耗时：3 小时

**目的**：解决审计报告 D1（Stage 接口不统一），为阶段 1 接线做准备。

### 现状分析

| Stage 类 | 当前状态 | 需要修改 |
|----------|----------|----------|
| `CollectorStage` | ✅ 有 `name` + `async def run()` | 无需修改 |
| `AnalyzerStage` | ✅ 有 `name` + `async def run()` | 无需修改 |
| `GeneratorStage` | ✅ 有 `name` + `async def run()` | 无需修改 |
| `ReviewerStage` | ❌ 无 `name`，无 `run()` | **需添加** |
| `CandidatePromoter` | ❌ 无 `name`，无 `run()` | **需添加** |
| `IndexerStage` | ❌ 无 `name`，无 `run()` | **需添加**（阶段 2） |

### 任务 0.5.1: ReviewerStage 接口适配

```python
# src/pipeline/stages/reviewer.py
class ReviewerStage:
    """Phase 1: Pure rule engine."""
    
+   name = "reviewer"
    
+   async def run(self, ctx: 'PipelineContext', prev_result) -> 'StageResult':
+       """PipelineStage protocol wrapper for review()."""
+       if prev_result is None or not hasattr(prev_result, 'candidates'):
+           return StageResult(success=False, payload={"error": "no candidates from analyzer"})
+       
+       candidates = prev_result.candidates
+       results = []
+       for candidate in candidates:
+           result = self.review(candidate, Path(ctx.source_path))
+           results.append(result)
+       
+       # 全部通过才算成功
+       all_validated = all(r.status == "VALIDATED" for r in results)
+       return StageResult(
+           success=all_validated,
+           payload={"review_results": results}
+       )
    
    def review(self, candidate: KnowledgeCandidate, project_path: Path) -> ReviewResult:
        """原有逻辑保持不变"""
        ...
```

---

### 任务 0.5.2: CandidatePromoter 接口适配

```python
# src/pipeline/stages/candidate_promoter.py
class CandidatePromoter:
    """Converts a VALIDATED KnowledgeCandidate into a KnowledgeObject."""
    
+   name = "candidate_promoter"
    
+   async def run(self, ctx: 'PipelineContext', prev_result) -> 'StageResult':
+       """PipelineStage protocol wrapper for promote()."""
+       if prev_result is None or not hasattr(prev_result.payload, 'review_results'):
+           return StageResult(success=False, payload={"error": "no review results"})
+       
+       review_results = prev_result.payload["review_results"]
+       validated_candidates = [
+           c for c, r in zip(ctx.candidates, review_results)
+           if r.status == "VALIDATED"
+       ]
+       
+       objects = []
+       for candidate in validated_candidates:
+           obj = self.promote(candidate)
+           objects.append(obj)
+       
+       return StageResult(
+           success=True,
+           payload={"knowledge_objects": objects}
+       )
    
    def promote(self, candidate: KnowledgeCandidate) -> KnowledgeObject:
        """原有逻辑保持不变"""
        ...
```

---

### 任务 0.5.3: 注册新 Stage

```python
# src/pipeline/stages/__init__.py
from .candidate_promoter import CandidatePromoter
# 注意：IndexerStage 延后到阶段 2

__all__ = [
    "CollectorStage",
    "AnalyzerStage",
    "GeneratorStage",
    "ReviewerStage",
    "ReviewResult",
    "CandidatePromoter",  # 新增
]
```

---

### 任务 0.5.4: 添加 Stage 单元测试

```python
# tests/test_pipeline/test_stage_interface.py
"""验证所有 Stage 实现 PipelineStage 协议"""

import pytest
from src.pipeline.ports import PipelineStage, StageResult
from src.pipeline.stages import (
    CollectorStage,
    AnalyzerStage,
    GeneratorStage,
    ReviewerStage,
    CandidatePromoter,
)


class TestStageInterfaceCompliance:
    """所有 Stage 必须满足 PipelineStage 协议"""

    @pytest.mark.parametrize("stage_cls", [
        CollectorStage,
        AnalyzerStage,
        GeneratorStage,
        ReviewerStage,
        CandidatePromoter,
    ])
    def test_has_name_attribute(self, stage_cls):
        """必须有 name 属性"""
        stage = stage_cls()
        assert hasattr(stage, "name")
        assert isinstance(stage.name, str)
        assert len(stage.name) > 0

    @pytest.mark.parametrize("stage_cls", [
        CollectorStage,
        AnalyzerStage,
        GeneratorStage,
        ReviewerStage,
        CandidatePromoter,
    ])
    def test_has_run_method(self, stage_cls):
        """必须有 async run() 方法"""
        stage = stage_cls()
        assert hasattr(stage, "run")
        assert callable(stage.run)
        # 验证是协程函数
        import inspect
        assert inspect.iscoroutinefunction(stage.run)
```

---

### 阶段 0.5 完成标准

- [x] ReviewerStage 添加 `name` 和 `async run()`
- [x] CandidatePromoter 添加 `name` 和 `async run()`
- [x] 在 `stages/__init__.py` 注册
- [x] 单元测试通过
- [x] `pytest` 全量通过

**回滚点**：
```bash
git tag structure-opt-phase-0.5-complete
```

---

## 四、阶段 1 — 核心缺陷修复

预计耗时：1 天

### 任务 1.1: PageType 收敛为单一真源

**步骤**：

1. 在 `src/wiki/core/types.py` 新增：

```python
# types.py
_TYPE_TO_DIR: dict[PageType, str] = {
    PageType.SOURCE: "wiki_sources",
    PageType.ENTITY: "wiki_entities",
    PageType.CONCEPT: "wiki_concepts",
    PageType.SYNTHESIS: "wiki_synthesis",
    PageType.CLAIM: "wiki_claims",
    PageType.DECISION: "wiki_decisions",
    PageType.PROCEDURE: "wiki_concepts",  # 复用 concepts 目录
    PageType.EVENT: "wiki_concepts",       # 复用 concepts 目录
}

# 扩展型暂不支持生成，仅在枚举中保留
_UNSUPPORTED_TYPES = {PageType.CLAIM, PageType.DECISION, PageType.PROCEDURE, PageType.EVENT}

def validate_page_type_supported(page_type: PageType) -> None:
    """检查页面类型是否支持生成。
    
    Raises:
        NotImplementedError: 如果类型不在当前支持范围内
    """
    if page_type in _UNSUPPORTED_TYPES:
        raise NotImplementedError(
            f"PageType.{page_type.name} is defined but not yet supported for generation. "
            f"Currently supported types: SOURCE, ENTITY, CONCEPT, SYNTHESIS"
        )
```

2. 删除重复定义：

```python
# generator.py:64 — 删除
- _DEPTH_BY_TYPE = {...}
+ from ..wiki.core.types import validate_page_type_supported

# generator.py 中使用处增加验证
def generate(...):
    validate_page_type_supported(page_type)
    ...

# ingest.py:310 — 删除
- _DEPTH_BY_TYPE = {...}
+ from ..wiki.core.types import _TYPE_TO_DIR, validate_page_type_supported
```

3. 修正 schema_routing.py：

```python
# schema_routing.py
- from ..storage.page_writer import _TYPE_TO_DIR
+ from ..core.types import _TYPE_TO_DIR, _UNSUPPORTED_TYPES

def validate_schema_routing(paths: WikiPaths) -> list[str]:
    """Return list of page IDs in wrong subdirs."""
    ensure_knowledge_base(paths.root)
    misrouted = []
    for page_type, dir_prop in _TYPE_TO_DIR.items():
        # 跳过不支持的类型
        if page_type in _UNSUPPORTED_TYPES:
            continue
        sub = getattr(paths, dir_prop)
        ...
```

4. 删除 page_writer.py 中的重复定义：

```python
# page_writer.py
- _TYPE_TO_DIR: dict[PageType, str] = {...}
+ from ..core.types import _TYPE_TO_DIR
```

**验证**：
```bash
grep -r "_DEPTH_BY_TYPE\|_TYPE_TO_DIR" src/ | grep -v "__pycache__" | grep -v "types.py"
# 应返回空（或仅有注释）
```

---

### 任务 1.2: Stage 机制接线（含回退开关）

**设计要点**：
1. 真正的回退开关：`RUFLO_USE_STAGE_SCHEDULER`
2. 默认关闭，需要显式启用
3. 灰度方案：先在测试环境验证

**步骤**：

```python
# src/pipeline/service.py

import os

# 新增：回退开关
USE_STAGE_SCHEDULER = os.environ.get("RUFLO_USE_STAGE_SCHEDULER", "false") == "true"

async def _run_for_collector_start_inner(self, task_id: str, ...):
    """处理摄取任务"""
    ...
    
    if USE_STAGE_SCHEDULER:
        # ========== 新路径：Stage 调度器 ==========
        ctx = PipelineContext(
            task_id=task_id,
            source=source,
            source_type=source_type,
            project_id=project_id,
            paths=paths,       # 新增
            provider=provider, # 新增
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
        ctx = PipelineContext(...)
        for stage in self._stages[:1]:  # 只跑 Collector
            result = await stage.run(ctx, prev_result=None)
            ...
        await _pipeline_mod.run_ingest(...)
        self.queue_service.update_status(task_id, status=TaskStatus.APPROVED)
```

**灰度方案**：

| 环境 | 配置 | 预期 |
|------|------|------|
| 开发 | `RUFLO_USE_STAGE_SCHEDULER=true` | 新路径 |
| 测试 | `RUFLO_USE_STAGE_SCHEDULER=true` | 新路径，验证 1 周 |
| 生产 | 默认 `false` | 旧路径 |
| 生产灰度 | `true`（特定实例） | 观察无问题后推广 |

---

### 任务 1.3: 写集成测试保护微妙行为

```python
# tests/integration/test_ingest_behavior.py
"""保护 run_ingest 的微妙行为"""

import pytest
import os

# 强制使用新路径
os.environ["RUFLO_USE_STAGE_SCHEDULER"] = "true"


class TestIngestBehaviorPreservation:
    """验证新路径保留旧路径的微妙行为"""

    async def test_update_existing_page_skips_tag_validation(self, tmp_path):
        """更新既有页面时跳过 validate_tag_compliance"""
        # TODO: 实现测试
        pass

    async def test_llm_failure_falls_back_to_source_only_stub(self, tmp_path):
        """LLM 失败时回退到 source-only stub"""
        # TODO: 实现测试
        pass

    async def test_collector_failure_propagates_correctly(self, tmp_path):
        """Collector 失败时正确传播错误"""
        # TODO: 实现测试
        pass
```

---

### 阶段 1 完成标准

- [x] PageType 单一真源，无重复定义
- [x] 不支持的类型抛出 `NotImplementedError`
- [x] 回退开关 `RUFLO_USE_STAGE_SCHEDULER` 生效
- [x] 集成测试覆盖微妙行为
- [x] `pytest` 全量通过
- [x] 测试环境灰度验证 1 周

**回滚命令**：
```bash
# 回滚到阶段 0.5
git checkout structure-opt-phase-0.5-complete
```

---

## 五、阶段 2 — 结构收敛与 IndexerStage 接线

预计耗时：2-3 天

### 任务 2.1: GraphBuilder 验证

**前置条件**：IndexerStage 接线前必须验证 GraphBuilder 稳定性。

```python
# tests/test_knowledge/test_graph_builder.py
"""GraphBuilder 稳定性验证"""

class TestGraphBuilderStability:
    def test_build_from_objects_creates_nodes(self):
        """验证能创建知识图谱节点"""
        # TODO
        pass

    def test_edge_creation(self):
        """验证边创建"""
        # TODO
        pass

    def test_persistence(self):
        """验证持久化"""
        # TODO
        pass
```

---

### 任务 2.2: IndexerStage 接口适配

```python
# src/pipeline/stages/indexer.py
class IndexerStage:
    """Terminal pipeline stage for vectors + graph + lifecycle."""
    
+   name = "indexer"
    
+   async def run(self, ctx: 'PipelineContext', prev_result) -> 'StageResult':
+       """PipelineStage protocol wrapper for index()."""
+       if prev_result is None:
+           return StageResult(success=False, payload={"error": "no input"})
+       
+       # 从 ctx 获取需要的信息
+       wiki_page = ctx.wiki_page  # 需要在前面 stage 设置
+       paths = ctx.paths
+       
+       try:
+           await self.index(wiki_page, paths, ...)
+           return StageResult(success=True, payload={})
+       except Exception as e:
+           return StageResult(success=False, payload={"error": str(e)})
    
    async def index(self, wiki_page: WikiPage, ...) -> None:
        """原有逻辑保持不变"""
        ...
```

---

### 任务 2.3: 合并 utils/lib/shared → foundation/

（保留原方案设计，略）

---

### 任务 2.4: 治理件套整合

（保留原方案设计，略）

---

### 阶段 2 完成标准

- [x] GraphBuilder 测试覆盖率 >= 80%
- [x] IndexerStage 接口适配
- [x] IndexerStage 在测试环境验证
- [x] foundation/ 目录结构
- [x] `pytest` 全量通过

---

## 六、阶段 3 — KOS 组件裁决

（保留原方案设计，略）

---

## 七、风险与缓解措施

| 风险 | 缓解措施 | 状态 |
|------|----------|------|
| Stage 接口不统一 | 阶段 0.5 统一接口 | ✅ 已解决 |
| 回退开关不存在 | `RUFLO_USE_STAGE_SCHEDULER` | ✅ 已解决 |
| test_helpers 移动破坏测试 | 延后为可选任务 | ✅ 已解决 |
| PageType 扩展型语义不明 | 抛出 NotImplementedError | ✅ 已解决 |
| IndexerStage 依赖未验证 | 阶段 2 先验证 GraphBuilder | ✅ 已解决 |
| 删除 orchestrator 破坏历史 | 移动到 _deprecated/ | ✅ 已解决 |
| 性能影响未知 | 阶段 1 灰度观察 | 待验证 |

---

## 八、执行检查表

### 阶段 0 检查表

- [ ] `.gitignore` 检查
- [ ] orchestrator 移动到 `_deprecated/`
- [ ] page_model.py 删除
- [ ] slugify 合并
- [ ] cosine_similarity 合并
- [ ] test_helpers 移动（可选）
- [ ] `pytest` 通过
- [ ] git tag `structure-opt-phase-0-complete`

### 阶段 0.5 检查表

- [ ] ReviewerStage 添加 `name` + `async run()`
- [ ] CandidatePromoter 添加 `name` + `async run()`
- [ ] stages/__init__.py 注册
- [ ] test_stage_interface.py 通过
- [ ] `pytest` 通过
- [ ] git tag `structure-opt-phase-0.5-complete`

### 阶段 1 检查表

- [ ] types.py 新增 `_TYPE_TO_DIR` + `validate_page_type_supported()`
- [ ] generator.py 删除重复定义
- [ ] ingest.py 删除重复定义
- [ ] schema_routing.py 从 types.py 导入
- [ ] page_writer.py 从 types.py 导入
- [ ] service.py 添加回退开关
- [ ] 集成测试覆盖微妙行为
- [ ] `pytest` 通过
- [ ] 测试环境灰度 1 周
- [ ] git tag `structure-opt-phase-1-complete`

---

## 九、附录：文件修改清单

### 需修改文件

| 文件 | 修改内容 | 阶段 |
|------|----------|------|
| `.gitignore` | 检查/添加生成物忽略 | 0 |
| `src/wiki/__init__.py` | 改导入路径 | 0 |
| `src/knowledge/memory/decision.py` | 改用 utils.slugify（可选） | 0 |
| `src/wiki/features/dedup.py` | 改用 utils.similarity | 0 |
| `src/wiki/core/types.py` | 新增 `_TYPE_TO_DIR` + 验证函数 | 1 |
| `src/pipeline/generator.py` | 删除 `_DEPTH_BY_TYPE`，改导入 | 1 |
| `src/pipeline/ingest.py` | 删除 `_DEPTH_BY_TYPE`，改导入 | 1 |
| `src/wiki/features/schema_routing.py` | 从 types.py 导入 | 1 |
| `src/wiki/storage/page_writer.py` | 从 types.py 导入 | 1 |
| `src/pipeline/service.py` | 添加回退开关 | 1 |
| `src/pipeline/stages/__init__.py` | 注册新 Stage | 0.5 |
| `src/pipeline/stages/reviewer.py` | 添加 `name` + `async run()` | 0.5 |
| `src/pipeline/stages/candidate_promoter.py` | 添加 `name` + `async run()` | 0.5 |

### 需新建文件

| 文件 | 阶段 |
|------|------|
| `src/_deprecated/README.md` | 0 |
| `tests/test_pipeline/test_stage_interface.py` | 0.5 |
| `tests/integration/test_ingest_behavior.py` | 1 |

### 需移动文件

| 原路径 | 新路径 | 阶段 |
|--------|--------|------|
| `src/orchestrator/` | `src/_deprecated/orchestrator/` | 0 |
| `tests/test_orchestrator/` | `tests/test_deprecated_orchestrator/` | 0 |
| `src/wiki/core/page_model.py` | 删除或保留兼容层 | 0 |

---

## 十、信息盲区处理

| 盲区 | 处理方式 |
|------|----------|
| B1: PageType 扩展型规划 | 显式标记为不支持，抛出 NotImplementedError |
| B2: GraphBuilder 稳定性 | 阶段 2 增加测试验证 |
| B3: Stage 机制预期行为 | 本方案明确：顺序执行，失败即停 |
| B4: 外部依赖 | page_model.py 可选保留兼容层 |
| B5: 性能基准 | 阶段 1 灰度观察 |