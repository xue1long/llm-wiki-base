# 方案 v3 影响范围审核报告

> **审核身份**：独立审核专家
> **审核日期**：2026-08-03
> **审核目标**：评估方案执行后对其他模块的影响，识别潜在 bug

---

## 一、任务级别影响分析

### 任务 0.3: 删除 page_model.py

**直接影响**：
- `src/wiki/__init__.py:18` — 改为从 `core.types` 导入

**潜在风险分析**：

| 风险点 | 现状 | 方案后状态 | 风险等级 |
|--------|------|------------|----------|
| 外部代码 `from src.wiki.core.page_model import WikiPage` | 可行 | ❌ 会失败 | **中** |

**发现的问题**：

方案只考虑了 `src/wiki/__init__.py:18` 这一处导入，但**未检查是否有外部代码**直接导入 `src.wiki.core.page_model`。

**证据**：
```
# 内部导入情况（已列出）
src/wiki/__init__.py:18:from .core.page_model import WikiPage  # 方案已处理

# 但外部项目可能存在的导入（未检查）
from src.wiki.core.page_model import WikiPage  # ← 直接导入路径
```

**整改建议**：
1. 方案应提供**兼容层**而非直接删除：
   ```python
   # src/wiki/core/page_model.py（保留）
   """Deprecated: Use 'from src.wiki.core.types import WikiPage' instead."""
   import warnings
   from .types import WikiPage
   __all__ = ["WikiPage"]
   ```
2. 或在删除前搜索所有可能的外部引用

---

### 任务 0.4: 合并 slugify

**直接影响**：
- `src/knowledge/memory/decision.py:72` — 改用 `utils.slugify`

**潜在风险分析**：

| 风险点 | 现状 | 方案后状态 | 风险等级 |
|--------|------|------------|----------|
| `_slugify` 函数签名差异 | `def _slugify(text: str, max_len: int = 40)` | `def slugify(text)` 无 `max_len` 参数 | **高** |

**发现的问题**：

方案未检查两个函数的签名和语义是否一致。

**证据**：
```python
# decision.py:72 — 私有实现
def _slugify(text: str, max_len: int = 40) -> str:
    """Create a valid page-ID slug from arbitrary text."""
    slug = re.sub(r"\s+", "-", text.strip().lower())
    slug = re.sub(r"[^a-z0-9\-一-鿿]", "", slug)  # CJK 支持
    ...

# utils/slugify.py:105 — 公共实现
def slugify(text) -> str:
    """Return a deterministic CJK-friendly slug for ``text``."""
    # 不同的实现逻辑
    runs = _split_runs(text)
    ...
```

**关键差异**：
1. `decision._slugify` 有 `max_len` 参数，`utils.slugify` 无
2. 实现逻辑不同（正则 vs run-based）
3. 可能产生不同的输出结果

**风险后果**：
- 更改后 `DecisionRecorder.record_decision` 产生的 slug 可能与历史不一致
- 可能破坏已有的 decision 页面 ID

**整改建议**：
1. **暂缓此任务**，等待阶段 3 明确是否删除 `knowledge/memory/`
2. 若必须合并，需验证两个函数的输出是否一致

---

### 任务 0.5: 合并 cosine_similarity

**直接影响**：
- `src/wiki/features/dedup.py:29` — 改用 `utils.similarity.cosine_similarity`

**潜在风险分析**：

| 风险点 | 现状 | 方案后状态 | 风险等级 |
|--------|------|------------|----------|
| 函数签名一致 | ✅ 都是 `(list[float], list[float]) -> float` | ✅ 一致 | 低 |
| 实现逻辑一致 | ✅ 都计算余弦相似度 | ✅ 一致 | 低 |

**验证结果**：

```python
# dedup.py:29-38
def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)

# utils/similarity.py:4-16
def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot_product = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot_product / (norm_a * norm_b)
```

**差异**：
- `dedup._cosine_similarity` 检查 `not a or not b`（处理空列表）
- `utils.cosine_similarity` 只检查 `len(a) != len(b)`

**风险后果**：
- 如果传入空列表 `[]`，`utils.cosine_similarity` 可能返回不同结果（但不影响正确性，因为 `len([]) == len([])` 会进入后续计算）

**整改建议**：
- 合并是安全的，但建议统一空列表处理逻辑

---

### 任务 0.5.1/0.5.2: ReviewerStage/CandidatePromoter 接口适配

**直接影响**：
- 添加 `name` 属性
- 添加 `async def run()` 方法

**潜在风险分析**：

#### 风险点 1：ReviewerStage.run() 的参数假设

方案中 `ReviewerStage.run()` 实现：
```python
async def run(self, ctx: 'PipelineContext', prev_result) -> 'StageResult':
    if prev_result is None or not hasattr(prev_result, 'candidates'):
        return StageResult(success=False, payload={"error": "no candidates from analyzer"})
    
    candidates = prev_result.candidates  # ← 假设 prev_result 有 candidates 属性
```

**问题**：方案假设 `prev_result` 有 `candidates` 属性，但：

```python
# analyzer.py:25 的返回
return StageResult(success=True, payload=analysis)
```

`StageResult.payload` 是 `analysis` 对象，**不一定有 `candidates` 属性**。

**风险后果**：
- `ReviewerStage.run()` 可能因为找不到 `candidates` 而总是返回失败

**整改建议**：
1. 检查 `analysis` 对象的结构
2. 或从 `payload` 中正确提取 candidates

#### 风险点 2：CandidatePromoter.run() 的参数假设

方案中 `CandidatePromoter.run()` 实现：
```python
async def run(self, ctx: 'PipelineContext', prev_result) -> 'StageResult':
    if prev_result is None or not hasattr(prev_result.payload, 'review_results'):
        ...
    review_results = prev_result.payload["review_results"]  # ← payload 是字典
```

但 `ReviewerStage.run()` 返回：
```python
return StageResult(success=True, payload={"review_results": results})
```

**问题**：`prev_result.payload` 是字典 `{"review_results": results}`，而非对象。`hasattr(prev_result.payload, 'review_results')` 永远为 `False`（字典没有属性）。

**风险后果**：
- `CandidatePromoter.run()` 的检查逻辑**永远失败**

**整改建议**：
```python
# 修正检查逻辑
if prev_result is None:
    return StageResult(success=False, payload={"error": "no prev_result"})
if not isinstance(prev_result.payload, dict) or "review_results" not in prev_result.payload:
    return StageResult(success=False, payload={"error": "no review_results"})
```

#### 风险点 3：ctx.candidates 从何而来？

方案中 `CandidatePromoter.run()` 使用：
```python
validated_candidates = [
    c for c, r in zip(ctx.candidates, review_results)  # ← ctx.candidates 从哪来？
    if r.status == "VALIDATED"
]
```

**问题**：`PipelineContext` 当前定义中**没有 `candidates` 属性**。

```python
# ports.py:15-35
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
    source_path: str = ""
    # 没有 candidates 属性
```

**风险后果**：
- `ctx.candidates` 会抛出 `AttributeError`

**整改建议**：
方案必须在 `PipelineContext` 中添加 `candidates` 属性，或修正数据来源

---

### 任务 1.1: PageType 收敛为单一真源

**直接影响**：
- `src/wiki/core/types.py` — 新增 `_TYPE_TO_DIR` 和 `validate_page_type_supported()`
- `src/pipeline/generator.py` — 删除 `_DEPTH_BY_TYPE`
- `src/pipeline/ingest.py` — 删除 `_DEPTH_BY_TYPE`
- `src/wiki/features/schema_routing.py` — 从 types 导入
- `src/wiki/storage/page_writer.py` — 从 types 导入

**潜在风险分析**：

#### 风险点 1：validate_page_type_supported() 的调用位置

方案在 generator 中：
```python
def generate(...):
    validate_page_type_supported(page_type)
    ...
```

**问题**：这会在每次生成页面时检查，但如果 LLM 返回了 CLAIM/DECISION/PROCEDURE/EVENT 类型呢？

```python
# generator.py 中 LLM 返回解析
page_type = PageType(p.get("type", "concept"))  # ← 如果 LLM 返回 "claim"
```

**风险后果**：
- 如果 LLM 返回扩展类型（虽目前不会），会抛出 `NotImplementedError`
- 这可能是预期行为，但应明确记录

#### 风险点 2：schema_routing.py 跳过不支持的类型

方案：
```python
def validate_schema_routing(paths: WikiPaths) -> list[str]:
    for page_type, dir_prop in _TYPE_TO_DIR.items():
        if page_type in _UNSUPPORTED_TYPES:
            continue  # 跳过
        ...
```

**问题**：如果磁盘上**已经存在** claim/decision 类型的页面呢？

**风险后果**：
- 已存在的扩展类型页面不会被检查路由正确性
- 这可能是有意为之（允许历史数据），但应明确

#### 风险点 3：page_writer.py 的 CLAIM/DECISION 目录

现有 `types.py` 和 `page_writer.py` 都定义了：
```python
PageType.CLAIM: "wiki_claims",
PageType.DECISION: "wiki_decisions",
```

但 WikiPaths 是否有这些属性？

**整改建议**：
检查 `WikiPaths` 类是否定义了 `wiki_claims` 和 `wiki_decisions` 属性

---

### 任务 1.2: Stage 机制接线

**直接影响**：
- `src/pipeline/service.py` — 添加回退开关和新路径

**潜在风险分析**：

#### 风险点 1：ctx.paths 和 ctx.provider 的来源

方案：
```python
ctx = PipelineContext(
    task_id=task_id,
    source=source,
    source_type=source_type,
    project_id=project_id,
    paths=paths,       # 新增
    provider=provider, # 新增
)
```

**问题**：在 `service.py` 中，`paths` 和 `provider` 是在 `try` 块内部通过晚期导入获取的：

```python
# service.py:122-125（现有代码）
import src.pipeline.pipeline as _pipeline_mod
from pathlib import Path as _Path
paths = _pipeline_mod._resolve_wiki_paths(project_id=project_id)
provider = _pipeline_mod._get_provider(project_id=project_id)
```

方案需要在创建 `ctx` 之前就获取 `paths` 和 `provider`，这需要**移动代码位置**。

**风险后果**：
- 如果移动不当，可能破坏现有逻辑

#### 风险点 2：新路径缺少写盘逻辑

方案的新路径：
```python
for stage in self._stages:
    result = await stage.run(ctx, prev_result)
    ...
self.queue_service.update_status(task_id, status=TaskStatus.APPROVED)
```

**问题**：旧路径 `run_ingest()` 包含：
- 写入 wiki 页面文件
- 更新 index.md
- 写入 log.md
- 向量嵌入

新路径只跑 stage，**没有写盘逻辑**。

**风险后果**：
- 新路径不会产生任何持久化输出
- 需要在 GeneratorStage 后增加 CommitStage

---

## 二、跨模块依赖影响

### 2.1 knowledge/core/adapter.py 对扩展类型的依赖

```python
# adapter.py:26-30
_PAGETYPE_TO_KNOWLEDGETYPE: dict[PageType, KnowledgeType] = {
    ...
    PageType.CLAIM: KnowledgeType.CLAIM,
    PageType.DECISION: KnowledgeType.DECISION,
    PageType.PROCEDURE: KnowledgeType.PROCEDURE,
    PageType.EVENT: KnowledgeType.EVENT,
}
```

**影响分析**：
- adapter 会正常转换扩展类型
- 但如果 generator 抛出 `NotImplementedError`，这个转换永远不会被调用
- **无冲突**

### 2.2 knowledge/memory/decision.py 的 _slugify

**影响分析**：
- 这是一个**死代码区域**（生产零引用）
- 建议暂缓合并，待阶段 3 决策

### 2.3 pipeline/ingest.py 对 ReviewerStage 和 CandidatePromoter 的现有使用

```python
# ingest.py:598-599, 732-733
from .stages.reviewer import ReviewerStage
_reviewer = ReviewerStage()

# ingest.py:778-779
from .stages.candidate_promoter import CandidatePromoter
promoter = CandidatePromoter()
```

**影响分析**：
- `ingest.py` 直接实例化并调用 `review()` 和 `promote()` 方法
- 方案添加的 `run()` 方法**不影响现有使用**
- **无冲突**

---

## 三、发现的问题汇总

### 🔴 高风险问题

| ID | 问题 | 位置 | 后果 | 整改建议 |
|----|------|------|------|----------|
| R1 | `_slugify` 签名/实现不一致 | 任务 0.4 | 可能产生不同的 slug | 暂缓，或验证输出一致性 |
| R2 | `ReviewerStage.run()` 假设 `prev_result.candidates` 不存在 | 任务 0.5.1 | 检查逻辑错误 | 修正为检查 `payload` 结构 |
| R3 | `CandidatePromoter.run()` 字典属性检查错误 | 任务 0.5.2 | 检查逻辑永远失败 | 用 `in` 检查而非 `hasattr` |
| R4 | `ctx.candidates` 属性不存在 | 任务 0.5.2 | `AttributeError` | 在 PipelineContext 添加属性 |
| R5 | 新路径缺少写盘逻辑 | 任务 1.2 | 不产生持久化输出 | 增加 CommitStage |

### 🟡 中风险问题

| ID | 问题 | 位置 | 后果 | 整改建议 |
|----|------|------|------|----------|
| M1 | 外部代码可能直接导入 page_model | 任务 0.3 | 外部依赖失败 | 保留兼容层 |
| M2 | `ctx.paths/provider` 获取时机需调整 | 任务 1.2 | 变量未定义 | 移动代码位置 |
| M3 | WikiPaths 可能缺少扩展类型目录属性 | 任务 1.1 | `AttributeError` | 检查并补充 |

### 🟢 低风险问题

| ID | 问题 | 位置 | 后果 | 整改建议 |
|----|------|------|------|----------|
| L1 | cosine_similarity 空列表处理差异 | 任务 0.5 | 边缘情况行为不同 | 统一处理逻辑 |

---

## 四、整改优先级

### 必须修复（阻塞执行）

1. **R2/R3/R4**：Stage 接口适配中的逻辑错误 — 会导致代码无法运行
2. **R5**：新路径缺少写盘逻辑 — 会导致数据丢失

### 建议修复（影响正确性）

3. **M2**：`ctx.paths/provider` 获取时机
4. **R1**：slugify 签名差异（或暂缓任务）

### 可选修复（改进健壮性）

5. **M1**：page_model 兼容层
6. **M3**：WikiPaths 扩展目录检查
7. **L1**：cosine_similarity 统一

---

## 五、审计结论

**方案状态**：⚠️ **需修正后执行**

**原因**：
- 阶段 0.5 的 Stage 接口适配代码存在**多处逻辑错误**
- 阶段 1.2 的新路径**缺少关键的写盘逻辑**
- 这些错误会导致代码运行失败或数据丢失

**整改要求**：
1. 修正 R2-R5 四个高风险问题
2. 补充 CommitStage 设计
3. 验证 M3（WikiPaths 目录属性）
4. 重新提交审核