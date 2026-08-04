# 结构优化方案 v2 — 独立审计报告

> **审计身份**：第三方独立审计专家
> **审计原则**：不美化、不掩饰、不假设、不放过
> **审计日期**：2026-08-03

---

## 一、致命缺陷（方案无法落地）

### D1: Stage 机制接线方案存在根本性架构错误

**漏洞位置**：任务 1.2 "Stage 机制接线"

**问题描述**：
方案提出让 `service.py` 改为跑全部已注册 stage：

```python
# 方案建议
for stage in self._stages:  # 跑全部已注册 stage
    result = await stage.run(ctx, prev_result)
```

**事实核查**：

经审计，现有 stage 类**接口不统一**：

| Stage 类 | 是否实现 `PipelineStage` 协议 | 是否有 `async def run()` | 备注 |
|----------|------------------------------|---------------------------|------|
| `CollectorStage` | ✅ | ✅ | 正常 |
| `AnalyzerStage` | ✅ | ✅ | 正常 |
| `GeneratorStage` | ✅ | ✅ | 正常 |
| `ReviewerStage` | ❌ | ❌ | 只有 `def review()` |
| `CandidatePromoter` | ❌ | ❌ | 只有 `def promote()` |
| `IndexerStage` | ❌ | ❌ | 只有 `async def index()` |

**证据**：
```python
# reviewer.py:73 — 同步方法，非 async run()
def review(self, candidate: KnowledgeCandidate, project_path: Path) -> ReviewResult:

# candidate_promoter.py:27 — 同步方法，非 async run()
def promote(self, candidate: KnowledgeCandidate) -> KnowledgeObject:

# indexer.py:70 — 异步方法但签名是 index()，非 run()
async def index(self, wiki_page: WikiPage, ...) -> None:
```

**风险后果**：
- 方案声称"跑全部已注册 stage"，但 3 个核心 stage **根本无法被 `run()` 调用**
- 直接执行会导致 `AttributeError: 'ReviewerStage' object has no attribute 'run'`
- **方案步骤 3 在技术层面不可执行**

**整改建议**：
1. 方案必须增加"Stage 接口统一"作为任务 1.2 的前置任务
2. 明确三种改造路径之一：
   - 路径 A：为 `ReviewerStage`/`CandidatePromoter`/`IndexerStage` 添加 `async def run()` 包装方法
   - 路径 B：修改 `PipelineStage` 协议，支持多种方法签名
   - 路径 C：放弃统一 stage 调度，维持现状

---

### D2: test_helpers.py 移动方案会破坏 11+ 个测试文件

**漏洞位置**：任务 0.6 "移动 test_helpers.py"

**问题描述**：
方案建议：
```bash
git mv src/shared/test_helpers.py tests/helpers/scripted_llm.py
```

**事实核查**：

经审计，`test_helpers.py` 被 **13 处代码引用**：

| 引用位置 | 数量 |
|----------|------|
| 生产代码 | 0 |
| 测试代码 | 11 |
| 文档代码块 | 4（plans/*.md 中的示例代码） |

**具体引用点**：
```
tests/test_wiki/test_stubs_atomic.py:32
tests/test_wiki/test_stubs.py:48
tests/test_pipeline/test_retry.py:361, 414, 443
tests/test_pipeline/test_pipeline.py:2
tests/test_pipeline/test_ingest_split.py:12
tests/test_pipeline/test_ingest_source_fallback_c4.py:19
tests/test_pipeline/test_ingest_generate_commit_split.py:25
tests/test_pipeline/test_generator.py:3
tests/test_pipeline/test_analyzer_json.py:15
tests/test_pipeline/test_analyzer.py:3
tests/test_lib/test_budgeted.py:2
```

**风险后果**：
- 方案声称"零风险清理"，但此任务会**立即破坏 11 个测试文件的导入**
- 方案未提及需要同步修改这 11 个文件的导入路径
- 执行 `pytest` 会立即失败，不符合"阶段 0 完成标准：pytest 全量通过"

**整改建议**：
1. 任务 0.6 必须明确列出所有需修改的测试文件
2. 或改为：先复制到 `tests/helpers/`，更新所有导入后，再删除原文件
3. 文档中的示例代码也需要同步更新（4 处）

---

### D3: "回退开关"机制不存在，方案承诺无法兑现

**漏洞位置**：任务 1.2 "风险控制"

**问题描述**：
方案声称：
> 设置环境变量 `RUFLO_PIPELINE_MODE=legacy` 可回退旧路径

**事实核查**：

经审计 `src/pipeline/ingest.py:581`：
```python
_pipeline_mode = __import__("os").environ.get("RUFLO_PIPELINE_MODE", "candidate")

if _pipeline_mode == "candidate":
    # 新路径：json analyzer → Reviewer → Promoter
    ...
else:
    # legacy 路径（markdown analyzer）
    ...
```

**问题**：
1. `RUFLO_PIPELINE_MODE=legacy` 控制的是 **analyzer 输出格式**（json vs markdown），**不是** stage 调度逻辑
2. `service.py:107` 的 `for stage in self._stages[:1]` **硬编码只跑 Collector**，无任何环境变量控制
3. 方案提出的 stage 接线改造**没有回退开关设计**

**风险后果**：
- 一旦接线失败，无法通过环境变量切回旧路径
- 方案承诺的"灰度观察 1 周"无法实现（没有灰度开关）
- **生产环境会直接崩溃**

**整改建议**：
1. 方案必须设计真正的回退机制：
   ```python
   # service.py 建议实现
   USE_STAGE_SCHEDULER = os.environ.get("RUFLO_USE_STAGE_SCHEDULER", "false") == "true"
   
   if USE_STAGE_SCHEDULER:
       for stage in self._stages:
           result = await stage.run(ctx, prev_result)
   else:
       # 现有逻辑
       for stage in self._stages[:1]:
           ...
       await run_ingest(...)
   ```
2. 明确灰度方案：先在测试环境设 `RUFLO_USE_STAGE_SCHEDULER=true`

---

## 二、重大隐患（容易失败）

### H1: PageType 扩展型默认值为 "concept" 无数据支撑

**漏洞位置**：任务 1.1，第 309-320 行

**问题描述**：
方案为 claim/decision/procedure/event 设置：
```python
PageType.CLAIM: "concept",
PageType.DECISION: "concept",
PageType.PROCEDURE: "concept",
PageType.EVENT: "concept",
```

**隐含假设**：
- 假设这四类页面适合用 `processing_depth="concept"` 处理
- 假设这四类页面会被生成（虽然目前不生成）

**事实核查**：
1. `types.py:21-30` 显示 `PageType.PROCEDURE` 和 `PageType.EVENT` 映射到 `wiki_concepts` 目录
2. 但 LLM prompt（generator.py）**根本没有这四类的生成逻辑**
3. 没有任何文档说明这四类的 `processing_depth` 应该是什么

**风险后果**：
- 静默引入语义不确定的默认值
- 未来如果真的生成这四类页面，可能产生错误的处理深度

**整改建议**：
1. 方案应明确标注：`# TODO: 待产品确认这四类的 processing_depth`
2. 或显式报错：`if page.type in {CLAIM, DECISION, ...}: raise NotImplementedError`

---

### H2: IndexerStage 依赖未接线的 GraphBuilder

**漏洞位置**：`src/pipeline/stages/indexer.py:17-23`

**问题描述**：
方案声称要让 `IndexerStage` 进入生产调度，但：

**事实核查**：
```python
# indexer.py:17-23 导入
from src.knowledge.graph.builder import (
    GraphBuilder,
    GraphNode,
    GraphEdge,
    NodeType,
    EdgeType,
)
```

经审计，`knowledge/graph/` 目录：
- 生产引用：**仅 1 处**（`indexer.py` 自身）
- 测试引用：0
- 其他代码：`knowledge/storage/event_store.py` 引用（但该文件也是死代码）

**风险后果**：
- `IndexerStage` 依赖的 `GraphBuilder` **本身未被验证**
- 一旦接线，可能引入未知 bug
- 方案未评估 `GraphBuilder` 的稳定性

**整改建议**：
1. 方案必须增加 `GraphBuilder` 单独测试/验证任务
2. 或明确：IndexerStage 接线在"阶段 2 或更晚"

---

### H3: decision.py 改造会引入循环导入风险

**漏洞位置**：任务 0.4

**问题描述**：
方案建议：
```python
# src/knowledge/memory/decision.py
-from ._slugify import _slugify
+from ...utils.slugify import slugify as _slugify
```

**事实核查**：
- `knowledge/memory/` 当前是**死代码区域**（生产零引用）
- `utils/slugify.py` 当前**零引用**
- 跨三层目录的相对导入 `...utils.slugify` 在复杂导入场景下易出错

**风险后果**：
- 如果 `utils/slugify.py` 有意外的导入依赖，可能引发循环导入
- 修改死代码引入新依赖，增加认知负担

**整改建议**：
1. 既然是死代码，优先级应该是"删除 knowledge/memory/"而非"重构导入"
2. 或明确：此任务仅在保留 knowledge/memory/ 的前提下执行

---

### H4: schema_routing.py 导入 page_writer 会引入依赖

**漏洞位置**：任务 1.1，第 339-342 行

**问题描述**：
方案建议：
```python
# schema_routing.py:8 — 删除副本
-from ..core.types import PageType
-_TYPE_TO_DIR = {...}
+from ..storage.page_writer import _TYPE_TO_DIR
```

**事实核查**：
- `schema_routing.py` 当前只依赖 `core/types.py`（纯类型定义）
- 改为导入 `storage/page_writer.py` 会引入**整个写入层依赖**

**风险后果**：
- 违反"类型检查不应依赖实现层"的原则
- 可能在某些导入场景（如类型检查工具）引入意外依赖

**整改建议**：
1. 正确做法：`page_writer._TYPE_TO_DIR` 应上提到 `core/types.py`
2. `schema_routing.py` 应从 `core/types.py` 导入，而非 `storage/page_writer.py`

---

### H5: 阶段 0 删除 orchestrator 可能破坏 git 历史

**漏洞位置**：任务 0.2

**问题描述**：
方案建议直接 `git rm -r src/orchestrator/`，但：

**事实核查**：
- `orchestrator/` 包含状态机逻辑（`state_machine.py`）
- 可能有分支依赖这个历史代码进行 git bisect
- 删除后无法轻易恢复（除非 reflog）

**风险后果**：
- 历史提交的 `git bisect` 会因文件不存在而失败
- 如果需要回溯某个历史版本调试，会非常困难

**整改建议**：
1. 使用 `git mv src/orchestrator/ src/_deprecated/orchestrator/` 保留历史
2. 添加 `src/_deprecated/README.md` 说明"此目录为历史参考，生产不使用"
3. 阶段 3 或更晚再真正删除

---

## 三、优化疏漏

### O1: 方案未覆盖 .gitignore 已有配置的验证

**漏洞位置**：任务 0.1

**问题描述**：
方案建议添加 `src/pipeline/wiki_rules_prompt.py` 到 `.gitignore`，但：

**事实核查**：
- `.gitignore:26` 已有 `.wiki-spec-md5`
- 方案未验证 `wiki_rules_prompt.py` 是否**真的未被忽略**

**整改建议**：
1. 先执行 `git check-ignore src/pipeline/wiki_rules_prompt.py` 确认当前状态
2. 如果已被其他规则覆盖，则无需额外添加

---

### O2: page_model.py 删除方案不完整

**漏洞位置**：任务 0.3

**问题描述**：
方案只修改了 `wiki/__init__.py:18`，但：

**事实核查**：
- `page_model.py` 的注释说明它"提供 page-model layer"
- 删除后，`from src.wiki.core.page_model import WikiPage` 的外部代码会如何？
- 方案未检查是否有外部项目依赖此路径

**整改建议**：
1. 增加 `sys.modules` 兼容桥（如果担心外部依赖）：
   ```python
   # wiki/core/page_model.py（临时保留）
   import warnings
   warnings.warn(
       "Importing from page_model is deprecated. Use from ..types import WikiPage",
       DeprecationWarning
   )
   from .types import WikiPage
   ```
2. 或确认无外部依赖后直接删除

---

### O3: 阶段划分不合理

**漏洞位置**：四阶段设计

**问题描述**：

| 阶段 | 声称风险 | 实际风险 |
|------|----------|----------|
| 阶段 0 | "零风险" | 任务 0.6 会破坏 11+ 测试文件（**高风险**） |
| 阶段 1 | "需保护现有行为" | Stage 接口不统一，**根本无法执行**（**致命风险**） |

**整改建议**：
1. 任务 0.6 降级为"阶段 1 可选任务"或增加完整导入路径修改清单
2. 任务 1.2 前置"Stage 接口统一"任务，并标记为"阶段 1.5"
3. 重新评估各阶段风险等级

---

### O4: 缺少回滚方案

**漏洞位置**：全方案

**问题描述**：
方案提到"每阶段独立 PR"，但：

**事实核查**：
- 没有回滚脚本或回滚检查点
- 一旦某个阶段出问题，如何回退？

**整改建议**：
每个阶段应包含：
1. `git tag structure-optimization-phase-N-start` 作为回滚点
2. 明确的回滚命令：
   ```bash
   # 回滚阶段 1
   git checkout structure-optimization-phase-0-end
   ```

---

### O5: 缺少性能影响评估

**漏洞位置**：任务 1.2

**问题描述**：
方案要让"全部 stage"参与调度，但：

**事实核查**：
- 当前只跑 1 个 stage（Collector）
- 改为跑全部（假设 6 个）会增加多少延迟？
- `IndexerStage.index()` 包含向量 embedding + 图构建，是**重操作**

**风险后果**：
- 摄取延迟可能从秒级变为分钟级
- 方案未评估性能影响

**整改建议**：
1. 增加"性能基准测试"任务
2. 或明确：IndexerStage 接线在"阶段 2"，且需异步化

---

## 四、信息盲区

### B1: PageType 四类扩展型的产品规划

**缺失信息**：
- CLAIM/DECISION/PROCEDURE/EVENT 是否在产品路线图上？
- 如果是，何时需要支持？
- 如果否，为何保留在枚举中？

**影响**：无法判断 `_DEPTH_BY_TYPE` 的正确默认值

---

### B2: GraphBuilder 的稳定性

**缺失信息**：
- `knowledge/graph/builder.py` 的测试覆盖率？
- 是否经过生产验证？
- 有无已知 bug？

**影响**：无法评估 IndexerStage 接线的风险

---

### B3: Stage 机制的预期行为

**缺失信息**：
- 方案声称"让 stages/ 抽象生效"，但具体期望是什么？
- 所有 stage 顺序执行？并行执行？条件执行？
- 失败重试策略？

**影响**：无法设计正确的调度逻辑

---

### B4: 外部依赖分析

**缺失信息**：
- 是否有外部项目 `pip install` 此项目？
- 是否有外部代码导入 `src.wiki.core.page_model`？

**影响**：无法评估删除 page_model.py 的兼容性风险

---

### B5: 性能基准

**缺失信息**：
- 当前摄取一个 PDF 平均耗时？
- 新 stage 调度后预期耗时？

**影响**：无法评估改造对用户体验的影响

---

## 五、审计结论

### 致命缺陷汇总

| ID | 问题 | 阻塞原因 |
|----|------|----------|
| D1 | Stage 接口不统一 | 方案步骤无法执行 |
| D2 | test_helpers 移动会破坏测试 | 不满足"零风险"前提 |
| D3 | 回退开关不存在 | 生产安全无法保障 |

### 建议执行顺序

1. **立即暂停** 阶段 0 任务 0.6（移动 test_helpers）
2. **重新设计** 阶段 1 任务 1.2：
   - 前置：统一 Stage 接口
   - 设计：真正的回退开关
3. **补充调研**：
   - PageType 四类扩展型的产品规划
   - GraphBuilder 的稳定性评估
4. **修订方案** 后再考虑执行

### 最终裁定

**方案状态**：❌ **不可执行**

**原因**：存在 3 个致命缺陷，方案声称的"零风险"和"可回退"均不成立。

**整改要求**：
1. 修复 D1-D3 后重新提交审计
2. 补充信息盲区 B1-B5 的调研结果
3. 重新评估阶段划分和风险等级