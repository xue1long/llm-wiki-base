# ruflo-kb 项目结构优化方案 v2

> **版本**：v2.0 | 2026-08-03
> **依据**：深度审计 `src/` 33 包 / 276 个 `.py`，所有结论附 `文件:行号` 证据
> **目标**：消除"架构先进但接线未完成"的现状，收敛为单一、可维护的结构

---

## 一、执行摘要（最该先做的 5 件事）

| 优先级 | 任务 | 代码行数 | 风险 | 收益 |
|--------|------|----------|------|------|
| 1 | PageType 收敛为单一真源 | ~50 行 | 低 | 高：消除 4 处矛盾定义 |
| 2 | 删除死代码（orchestrator + 重复实现） | ~3000 行 | 低 | 中：减少认知负担 |
| 3 | .gitignore 修复（生成物误判） | 2 行 | 极低 | 高：防止 spec sync 混乱 |
| 4 | Stage 机制接线 | ~100 行 | 中 | 高：让 stages/ 抽象生效 |
| 5 | KOS 组件裁决 | 争议 | 需产品决策 | 取决于产品规划 |

---

## 二、现状问题清单（按优先级）

### 🔴 P0 — 功能缺陷 / 数据不一致

#### P0-1: PageType 定义矛盾（最紧急）

**现象**：`PageType` 在 4 处定义，相互矛盾：

| 位置 | 定义 | 问题 |
|------|------|------|
| `src/wiki/core/types.py:10-18` | 8 类（SOURCE/ENTITY/CONCEPT/SYNTHESIS + CLAIM/DECISION/PROCEDURE/EVENT） | **完整定义** |
| `src/pipeline/generator.py:64` | `_DEPTH_BY_TYPE` 仅 4 类 | 逐字重复 |
| `src/pipeline/ingest.py:310` | `_DEPTH_BY_TYPE` 仅 4 类 | 与 generator.py 孪生 |
| `src/wiki/features/schema_routing.py:8` | `_TYPE_TO_DIR` 仅 4 类 | 独立副本 |
| `src/wiki/storage/page_writer.py:12` | `_TYPE_TO_DIR` 8 类 | 正确引用 |

**影响**：
- `claim/decision/procedure/event` 四类被 `generator.py` 和 `ingest.py` 静默忽略
- `schema_routing.py` 的校验只检查 4 类目录，其余 4 类页面漏检
- 新开发者无法判断"到底支持几类页面"

**证据**：
```python
# types.py:10-18 — 8 类
class PageType(str, Enum):
    SOURCE = "source"
    ENTITY = "entity"
    CONCEPT = "concept"
    SYNTHESIS = "synthesis"
    CLAIM = "claim"        # ← 被 generator/ingest 忽略
    DECISION = "decision"  # ← 被 generator/ingest 忽略
    PROCEDURE = "procedure"  # ← 被 generator/ingest 忽略
    EVENT = "event"        # ← 被 generator/ingest 忽略

# generator.py:64-69 — 仅 4 类
_DEPTH_BY_TYPE: dict[PageType, str] = {
    PageType.SOURCE: "source",
    PageType.ENTITY: "entity",
    PageType.CONCEPT: "concept",
    PageType.SYNTHESIS: "synthesis",
    # claim/decision/procedure/event 缺失
}

# schema_routing.py:8-13 — 独立副本，仅 4 类
_TYPE_TO_DIR = {
    PageType.SOURCE: "wiki_sources",
    ...
}
```

#### P0-2: Stage 机制被绕过

**现象**：`PipelineService` 只跑 `CollectorStage`，然后手工调旧 `run_ingest()`：

```python
# service.py:107
for stage in self._stages[:1]:  # only CollectorStage
    result = await stage.run(ctx, prev_result=None)
    ...
# service.py:128
await _pipeline_mod.run_ingest(...)  # 跳过 stages/ 抽象
```

**影响**：
- `stages/reviewer.py`、`stages/candidate_promoter.py`、`stages/indexer.py` 有代码但**生产零调用**
- `stages/__init__.py:7-14` 未登记 `CandidatePromoter` 和 `Indexer`
- 整个 `PipelineRunner.run_stages` 抽象失效

#### P0-3: .gitignore 漏配生成物

**现象**：
```gitignore
# .gitignore:26 — 正确忽略基线
.wiki-spec-md5

# 但未忽略生成物
pipeline/wiki_rules_prompt.py  # ← 新克隆误判 spec 已变更
```

**影响**：新开发者克隆仓库后，`git status` 显示生成物有变更，误导判断。

---

### 🟡 P1 — 重复实现 / 冗余代码

#### P1-1: slugify 三处实现

| 位置 | 用途 | 问题 |
|------|------|------|
| `src/utils/slugify.py:105` | 通用 slugify | ✅ 正确位置 |
| `src/knowledge/memory/decision.py:72` | `_slugify()` 私有副本 | 重复实现 |
| `src/wiki/features/relations.py:71` | 运行时导入复用 | 正确引用 |

**建议**：`decision.py:72` 改为 `from ...utils.slugify import slugify`。

#### P1-2: cosine_similarity 两处实现

| 位置 | 用途 | 问题 |
|------|------|------|
| `src/utils/similarity.py:4` | 通用 cosine | ✅ 正确位置 |
| `src/wiki/features/dedup.py:29` | `_cosine_similarity()` 私有副本 | 重复实现 |

**注意**：`utils/similarity.py:4` 当前**零引用**，应让 `dedup.py` 复用而非删除。

#### P1-3: 死代码 — orchestrator/

| 指标 | 数值 |
|------|------|
| 生产代码引用 | 0 处 |
| 测试代码引用 | 5 个测试文件 |
| 总行数 | ~600 行 |

**证据**：
```
tests/test_orchestrator/test_router.py
tests/test_orchestrator/test_audit_error_path.py
tests/test_orchestrator/test_router_suffix.py
tests/test_orchestrator/test_state_machine_guard.py
tests/test_orchestrator/__init__.py
```

**删除方案**：同步删除 `src/orchestrator/` 和 `tests/test_orchestrator/`。

#### P1-4: 死代码 — knowledge 子包

| 目录 | 行数 | 生产引用 | 备注 |
|------|------|----------|------|
| `knowledge/storage/` | ~400 | 0 | 事件存储抽象 |
| `knowledge/evolution/` | ~390 | 0 | 演进调度 |
| `knowledge/memory/` | ~634 | 0 | 记忆检索 |
| `knowledge/provenance/` | ~200 | 0 | 来源追溯 |
| **合计** | ~1624 | — | 需产品决策 |

**状态**：代码完整、有测试，但未接入主链路。`mcp_server/main.py:127` 的 `memory_retrieval` 留 `None`。

#### P1-5: 死代码 — 其他

| 文件 | 行数 | 引用 | 备注 |
|------|------|------|------|
| `src/wiki/core/page_model.py` | 10 | 1 处（`wiki/__init__.py:18`） | 冗余桥接 |
| `src/shared/test_helpers.py` | ~60 | 0（仅在 tests/） | 应移入 tests/ |
| `src/utils/similarity.py` | ~20 | 0 | 待 dedup.py 复用后激活 |

---

### 🟢 P2 — 架构异味

#### P2-1: 基础层反向依赖领域层

```python
# lib/project.py:13
from ..wiki.core.paths import WikiPaths  # ← 基础层依赖领域层

# maintenance/cache_cleanup.py:14
from ..wiki.core.paths import WikiPaths   # ← 同上
```

**问题**：`lib/` 和 `maintenance/` 定位为基础设施工具，不应依赖 `wiki/` 领域模型。

**建议**：路径常量上提到 `foundation/path.py`（阶段 2 任务）。

#### P2-2: ndg_gate 定位模糊

| 指标 | 数值 |
|------|------|
| 文件大小 | 450 行 |
| 生产引用 | 2 处（scripts/） |
| 测试引用 | 3 处 |

**问题**：
- 文档描述为"batch-level structural checks"
- 但未实现 `PipelineStage` 协议，无法嵌入摄取流程
- 与 `lint.py` 有代码耦合

**建议**：阶段 2 统一治理件套时整合。

---

## 三、目标结构

```
src/
├── cli/                  # 合并 cli.py + cli_ext/（阶段 2）
├── api/                  # 现 server/
├── mcp/
├── foundation/           # 合并 utils + lib + shared（阶段 2）
│   ├── text.py
│   ├── path.py           # WikiPaths 常量上提
│   ├── io.py
│   ├── idempotency.py
│   └── llm/
├── llm/                  # provider 注册表
├── vision/  research/
├── vector/  searcher/
├── pipeline/
│   ├── stages/           # 全部 stage 统一调度
│   └── governance/       # 合并质量治理（阶段 2）
├── wiki/
│   └── core/types.py     # PageType 单一真源
├── knowledge/
│   ├── core/             # ✅ 已接线
│   ├── lifecycle/        # ✅ 已接线
│   └── experimental/     # 未接线组件移入
├── schemas/
├── services/
└── (删除) orchestrator/
```

---

## 四、分阶段迁移方案

### 阶段 0 — 零风险清理（不动行为，立即可做）

预计耗时：2 小时

#### 任务 0.1: .gitignore 修复

```diff
 # .gitignore
 .wiki-spec-md5
+src/pipeline/wiki_rules_prompt.py
```

**验证**：新克隆后 `git status` 干净。

#### 任务 0.2: 删除 orchestrator + 测试

```bash
git rm -r src/orchestrator/
git rm -r tests/test_orchestrator/
```

**验证**：`pytest --collect-only -q` 正常。

#### 任务 0.3: 删除 page_model.py 冗余桥

```diff
# src/wiki/__init__.py
-from .core.page_model import WikiPage
+from .core.types import WikiPage
```

```bash
git rm src/wiki/core/page_model.py
```

#### 任务 0.4: 合并 slugify 重复实现

```python
# src/knowledge/memory/decision.py
-from ._slugify import _slugify
+from ...utils.slugify import slugify as _slugify
```

#### 任务 0.5: 合并 cosine_similarity

```python
# src/wiki/features/dedup.py
-from . import _cosine_similarity
+from ...utils.similarity import cosine_similarity
```

#### 任务 0.6: 移动 test_helpers.py

```bash
git mv src/shared/test_helpers.py tests/helpers/scripted_llm.py
# 更新测试文件导入路径
```

**阶段 0 完成标准**：
- ✅ `pytest` 全量通过
- ✅ `python -m src.cli serve` 正常启动
- ✅ 新克隆 `git status` 无误判变更

---

### 阶段 1 — 核心缺陷修复（需保护现有行为）

预计耗时：1 天

#### 任务 1.1: PageType 收敛为单一真源

**步骤**：

1. 在 `src/wiki/core/types.py` 新增派生常量：

```python
# types.py（新增）
_DEPTH_BY_TYPE: dict[PageType, str] = {
    PageType.SOURCE: "source",
    PageType.ENTITY: "entity",
    PageType.CONCEPT: "concept",
    PageType.SYNTHESIS: "synthesis",
    # 四类扩展型暂用 concept 深度
    PageType.CLAIM: "concept",
    PageType.DECISION: "concept",
    PageType.PROCEDURE: "concept",
    PageType.EVENT: "concept",
}
```

2. 删除重复定义：

```python
# generator.py:64 — 删除
- _DEPTH_BY_TYPE = {...}

# ingest.py:310 — 删除
- _DEPTH_BY_TYPE = {...}

# 两处改为：
from ..wiki.core.types import _DEPTH_BY_TYPE
```

3. 统一 `_TYPE_TO_DIR`：

```python
# schema_routing.py:8 — 删除副本
- _TYPE_TO_DIR = {...}
+ from ..storage.page_writer import _TYPE_TO_DIR
```

**验证**：
```bash
grep -r "_DEPTH_BY_TYPE\|_TYPE_TO_DIR" src/ | grep -v "__pycache__" | grep -v "types.py\|page_writer.py"
# 应返回空
```

#### 任务 1.2: Stage 机制接线

**前置条件**：写集成测试保护 `run_ingest` 微妙行为：
- 更新既有页面跳过 `validate_tag_compliance`
- LLM 失败回退 source-only stub

**步骤**：

1. 补齐 `PipelineContext`：

```python
# service.py:103
ctx = PipelineContext(
    task_id=task_id,
    source=source,
    source_type=source_type,
    project_id=project_id,
+   paths=paths,      # 新增
+   provider=provider, # 新增
)
```

2. 注册缺失的 stage：

```python
# stages/__init__.py
from .candidate_promoter import CandidatePromoterStage
from .indexer import IndexerStage

__all__ = [
    ...,
    "CandidatePromoterStage",
    "IndexerStage",
]
```

3. 修改调度逻辑（保守方案）：

```python
# service.py:107
-for stage in self._stages[:1]:
-    result = await stage.run(ctx, prev_result=None)
-...
-await _pipeline_mod.run_ingest(...)

# 改为：
for stage in self._stages:  # 跑全部已注册 stage
    result = await stage.run(ctx, prev_result)
    if not result.success:
        ...
    prev_result = result
```

**风险控制**：
- 设置环境变量 `RUFLO_PIPELINE_MODE=legacy` 可回退旧路径
- 灰度观察 1 周

**阶段 1 完成标准**：
- ✅ PageType 单一真源，无重复定义
- ✅ Stage 机制生效，`stages/__init__.py` 全部注册
- ✅ `pytest` 全量通过
- ✅ 实际摄取流程正常产出 wiki 页面

---

### 阶段 2 — 结构收敛（中风险）

预计耗时：2-3 天

#### 任务 2.1: 合并 utils/lib/shared → foundation/

```
src/foundation/
├── __init__.py
├── text.py        # 来自 utils/text.py
├── path.py        # WikiPaths 常量上提
├── io.py          # 来自 utils/path.py
├── idempotency.py # 来自 utils/idempotency.py
├── slugify.py     # 来自 utils/slugify.py
├── similarity.py  # 来自 utils/similarity.py
└── llm/
    ├── context_budget.py
    ├── budgeted.py
    └── write_hooks.py
```

**难点**：消除 `lib/project.py` 和 `maintenance/cache_cleanup.py` 对 `wiki.core.paths` 的反向依赖。

**方案**：
- `WikiPaths` 类保留在 `wiki/core/paths.py`
- 仅路径常量（如 `WIKI_SOURCES_DIR`）上提到 `foundation/path.py`
- 或：接受基础层对领域层的依赖，显式文档说明

#### 任务 2.2: 治理件套整合

将 `wiki/features/{dedup,lint,heat,ndg_gate}` 统一到 `pipeline/governance/`，实现 `PipelineStage` 协议。

#### 任务 2.3: CLI 整合

合并 `cli.py` + `cli_ext/` 为 `cli/` 包，统一子命令注册。

---

### 阶段 3 — KOS 组件裁决（需产品决策）

预计耗时：视决策而定

#### 选项 A：接线 KOS

1. `knowledge/storage/` → 接入摄取流程的事件记录
2. `knowledge/evolution/` → 注入页面生命周期钩子
3. `knowledge/memory/` → 修 `mcp_server:127` 的 `memory_retrieval`
4. 注册 `ClaimExtractor` / `Indexer` stage

#### 选项 B：标记为实验性

```bash
mkdir -p src/knowledge/experimental
git mv src/knowledge/storage src/knowledge/experimental/
git mv src/knowledge/evolution src/knowledge/experimental/
git mv src/knowledge/memory src/knowledge/experimental/
git mv src/knowledge/provenance src/knowledge/experimental/
```

在 `knowledge/experimental/README.md` 说明：
> 此目录包含 KOS Phase 1 设计的组件，尚未接入主链路。待产品规划确认后接线或移除。

---

## 五、风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| 阶段 1 破坏摄取行为 | 先写集成测试覆盖边界条件；设 `RUFLO_PIPELINE_MODE` 回退开关 |
| PageType 扩展型产品未规划 | 显式文档说明"暂时仅生成 4 类"；`_DEPTH_BY_TYPE` 注释 `# 扩展型暂用 concept` |
| KOS 取舍争议大 | 阶段 3 需产品参与决策；阶段 0-2 不触碰 |
| 重构引入回归 | 每阶段独立 PR；全量测试 + 手动摄取验证 |

---

## 六、与现有文档关系

| 文档 | 关系 |
|------|------|
| `2026-08-02-ingest-pipeline-completion.md` | 本方案的子集（聚焦摄取接线），本方案补齐全局结构问题 |
| `module-map.md` | 进度跟踪底图（接线状态图例） |
| `wiki-spec.md` | PageType 定义必须与 spec 一致 |
| `evaluations/*.md` | 问题证据可交叉印证 |

---

## 七、执行检查表

### 阶段 0 检查表

- [ ] `.gitignore` 添加 `src/pipeline/wiki_rules_prompt.py`
- [ ] `git rm -r src/orchestrator/ tests/test_orchestrator/`
- [ ] `git rm src/wiki/core/page_model.py` + 更新导入
- [ ] `decision.py` 改用 `utils.slugify`
- [ ] `dedup.py` 改用 `utils.similarity.cosine_similarity`
- [ ] `git mv src/shared/test_helpers.py tests/helpers/`
- [ ] `pytest` 全量通过
- [ ] 新克隆验证干净

### 阶段 1 检查表

- [ ] `types.py` 新增 `_DEPTH_BY_TYPE`
- [ ] `generator.py` / `ingest.py` 删除重复定义
- [ ] `schema_routing.py` 复用 `page_writer._TYPE_TO_DIR`
- [ ] 写摄取行为集成测试
- [ ] 补齐 `PipelineContext.paths/provider`
- [ ] 注册 `CandidatePromoterStage` / `IndexerStage`
- [ ] 修改 `service.py` 跑全部 stage
- [ ] 设置回退开关
- [ ] `pytest` 全量通过
- [ ] 实际摄取验证

### 阶段 2 检查表

- [ ] `foundation/` 目录结构
- [ ] 消除反向依赖或显式文档
- [ ] `pipeline/governance/` 整合
- [ ] `cli/` 整合
- [ ] `pytest` 全量通过

### 阶段 3 检查表

- [ ] 产品决策记录
- [ ] 接线或移入 experimental/
- [ ] 文档更新
- [ ] `pytest` 全量通过

---

## 附录：关键文件清单

### 需修改文件

| 文件 | 修改内容 | 阶段 |
|------|----------|------|
| `.gitignore` | 添加生成物忽略 | 0 |
| `src/wiki/core/types.py` | 新增 `_DEPTH_BY_TYPE` | 1 |
| `src/pipeline/generator.py` | 删除 `_DEPTH_BY_TYPE`，改导入 | 1 |
| `src/pipeline/ingest.py` | 删除 `_DEPTH_BY_TYPE`，改导入 | 1 |
| `src/wiki/features/schema_routing.py` | 删除 `_TYPE_TO_DIR`，改导入 | 1 |
| `src/pipeline/service.py` | 补 ctx 字段 + 跑全部 stage | 1 |
| `src/pipeline/stages/__init__.py` | 注册缺失 stage | 1 |
| `src/knowledge/memory/decision.py` | 改用 utils.slugify | 0 |
| `src/wiki/features/dedup.py` | 改用 utils.similarity | 0 |

### 需删除文件

| 文件/目录 | 阶段 |
|-----------|------|
| `src/orchestrator/` | 0 |
| `tests/test_orchestrator/` | 0 |
| `src/wiki/core/page_model.py` | 0 |
| `src/shared/test_helpers.py` | 0 |

### 需新建文件

| 文件 | 阶段 |
|------|------|
| `tests/helpers/scripted_llm.py` | 0 |
| `tests/integration/test_ingest_behavior.py` | 1 |