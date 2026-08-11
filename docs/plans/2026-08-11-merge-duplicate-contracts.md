# 合并重复契约（wiki 版死代码清理）Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 删除 `src/wiki/core/types.py` 中三处与 `src/types.py` / `src/events/events.py` **重名但未被使用**的契约定义，并同步收敛门面导出，消除"同名双定义"陷阱，让契约回到单一来源。

**Architecture:** 这是一次**死代码清理 + 门面收敛**，不是语义重构。经全量 AST + grep 核实，wiki 版 `TaskStatus` / `KnowledgeTask` / `EventName` 在全项目中**零真实消费者**（无任何 `from src.wiki import ... TaskStatus/KnowledgeTask/EventName`、无 `from ..core.types import ... TaskStatus/KnowledgeTask`、无 `import *`、无反射访问）。真正被使用的是 `src/types.py` 与 `src/events/events.py` 的版本。因此只需删除定义 + 从 `wiki/core/__init__.py`、`wiki/__init__.py` 的 import/`__all__` 中摘掉对应名字，全项目行为不变。

**Tech Stack:** Python 3.11+（项目要求），纯静态导入图整改。无运行时行为变化。

---

## ⚠️ 重要更正（来自架构审计复核）

在 2026-08-11 的架构报告里，我曾判定"类型契约双份定义且字段冲突"是**运行时隐患**（拿到 wiki 版 `TaskStatus` 的代码无法表达 `WAITING_REVIEW`/`DEAD_LETTER` 状态）。复核后发现该判断**过度严重**：

- wiki 版 `TaskStatus`（6 态）、`KnowledgeTask`（缺 `project_id`/`wiki_pages`）、`EventName` **虽然被定义并 re-export 进了 `wiki/__all__`**，但**任何代码都没有真正引用它们**。它们是历史遗留的死代码。
- 全项目实际使用的是 `src/types.py::TaskStatus`（9 态）和 `src/events/events.py::EventName`。
- 因此这**不是"两套契约在同进程流转"的实时冲突**，而是"门面里躺着残缺定义"的**潜在陷阱**（IDE 自动补全会推荐 `from src.wiki import TaskStatus`，新人静默拿到 6 态版本）——风险等级从"运行时 bug"降为"整洁度 / 可维护性"。

结论：方案风险很低，本质是删除未引用的定义。完成它之后，再提"禁止跨模块穿透"那 215 处整改时，新人就不会撞上这些陷阱。

---

## 红线（与历次优化一致）

1. **不碰摄取核心**：`pipeline/collector.py`、`pipeline/generator.py`、`pipeline/librarian.py`、`pipeline/service.py` 的 ingest 逻辑字节级不变。本次改动完全在 `wiki/core/types.py` + 两个 `wiki/__init__.py`，不触及上述文件。
2. **不改任何成功路径的字段结构**：`src/types.py::KnowledgeTask` / `TaskStatus` 保持原样（它是 9 态、带 `project_id` 的那份，被 queue/service 等 19 处真实使用）。
3. **删定义 ≠ 删功能**：只删"定义了却没人用"的符号；凡真实使用的符号一律保留。
4. 改动保持**纯减法**：不新增抽象层、不引入兼容桥。

---

## 事实依据（已核实）

| 符号（wiki 版位置） | 全项目真实来源 | wiki 版消费者 |
|---|---|---|
| `TaskStatus` `src/wiki/core/types.py:47-53`（6 态，缺 WAITING_REVIEW/TIMEOUT/DEAD_LETTER） | `src/types.py:6-15`（9 态） | **零** |
| `KnowledgeTask` `src/wiki/core/types.py:124-136`（缺 `project_id`/`raw_path`/`note_path`/`knowledge_path`，多 `wiki_pages`/`folder_context`） | `src/types.py:21-38`（含 `project_id`） | **零** |
| `EventName` `src/wiki/core/types.py:36-44`（8 常量，缺 `INGEST_STAGE`/`TASK_DEAD_LETTER`） | `src/events/events.py`（`EventName` 10 常量，被 orchestrator/queue/service 真实使用） | **零** |

删除安全性已确认：
- 生产代码（`src/`）中无任何 `from src.wiki.core.types import TaskStatus/KnowledgeTask/EventName` 或 `from src.wiki import TaskStatus/KnowledgeTask/EventName` 引用
- 无 `import *`、无 `__all__` 断言、无反射访问
- **唯一下游消费者是 `tests/test_wiki/test_types.py`**，它直接从 `src.wiki.core.types` 导入三个符号并建有 5 个测试函数。删除死定义时需同步迁移该文件到规范来源 `src.types` / `src.events.events`。

被 wiki 门面**保留**的真实符号（不动）：`PageType`、`WikiPage`、`ReviewItem`、`make_review_item`、`WikiPaths`、`ID_PATTERN` / `generate_page_id` / `is_valid_id`、`Relation*`、`SlugAliasRegistry`、`page_path_for*`、`read_page`/`write_page`/`PageNotFoundError`/`ensure_knowledge_base`/`atomic_pipeline_op` 等。

---

## Task 1: 删除 wiki/core/types.py 的三个死定义

**Files:**
- Modify: `src/wiki/core/types.py`（删 `EventName` 类块、`TaskStatus` 类块、`KnowledgeTask` 类块；其余 `PageType`/`WikiPage`/`ReviewItem`/`make_review_item`/关系桥 `__getattr__` 全部保留）

**Step 1: 删除 `EventName` 类定义**（`src/wiki/core/types.py:36-44`）

删除以下整块：
```python
class EventName:
    TASK_CREATED = "task:created"
    TASK_STATUS_CHANGED = "task:status:changed"
    COLLECTOR_DONE = "collector:done"
    ANALYZER_DONE = "analyzer:done"
    GENERATOR_DONE = "generator:done"
    QUALITY_JUDGED = "quality:judged"
    LIBRARIAN_DONE = "librarian:done"
    REVIEW_RESOLVED = "review:resolved"
```

**Step 2: 删除 `TaskStatus` 类定义**（`src/wiki/core/types.py:47-53`）

删除以下整块：
```python
class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"
    ARCHIVED = "archived"
```

**Step 3: 删除 `KnowledgeTask` 类定义**（`src/wiki/core/types.py:124-136`）

删除以下整块（注意保留其后的 `ReviewItem` 定义）：
```python
@dataclass
class KnowledgeTask:
    id: str
    source: str
    source_type: str
    status: TaskStatus
    task_hash: str
    created_at: int
    updated_at: int
    retry_count: int = 0
    error: Optional[str] = None
    wiki_pages: list[str] = field(default_factory=list)
    folder_context: str = ""
```

**Step 4: 编译校验该文件**
Run: `python -m py_compile src/wiki/core/types.py`
Expected: 无报错（注意 `Optional` 仍被 `ReviewItem` 使用，故 `from typing import TYPE_CHECKING, Optional` 保留）。

**Step 5: 迁移测试文件（唯一下游消费者）**
Modify: `tests/test_wiki/test_types.py`
- 删除 import 行中的 `EventName, TaskStatus, KnowledgeTask`
- 删除 `test_event_name_constants`、`test_task_status_enum`、`test_knowledge_task_defaults` 三个测试函数
- 保留 `PageType`、`WikiPage`、`ReviewItem`、`make_review_item` 的导入和测试

**Step 6: 确认无残留引用**
Run: `grep -rn "core.types import.*TaskStatus\|core.types import.*KnowledgeTask\|core.types import.*EventName" src tests 2>/dev/null | grep -v __pycache__`
Expected: 没有任何输出。

**Step 7: Commit**
```
git add src/wiki/core/types.py tests/test_wiki/test_types.py
git commit -m "refactor(wiki): drop dead TaskStatus/KnowledgeTask/EventName duplicates"
```

---

## Task 2: 收敛 wiki/core 门面

**Files:**
- Modify: `src/wiki/core/__init__.py:5-22`（import 块 + `__all__`）

**Step 1: 从 import 块移除三个名字**

原块：
```python
from .types import (
    EventName,
    KnowledgeTask,
    PageType,
    ReviewItem,
    TaskStatus,
    WikiPage,
    make_review_item,
)
```
改为：
```python
from .types import (
    PageType,
    ReviewItem,
    WikiPage,
    make_review_item,
)
```

**Step 2: 从 `__all__` 移除三个名字**

原 `__all__`：
```python
__all__ = [
    "EventName",
    "KnowledgeTask",
    "PageType",
    "ReviewItem",
    "TaskStatus",
    "WikiPage",
    "WikiPaths",
    "make_review_item",
    "ID_PATTERN",
    "generate_page_id",
    "is_valid_id",
]
```
改为：
```python
__all__ = [
    "PageType",
    "ReviewItem",
    "WikiPage",
    "WikiPaths",
    "make_review_item",
    "ID_PATTERN",
    "generate_page_id",
    "is_valid_id",
]
```

**Step 3: 编译校验**
Run: `python -m py_compile src/wiki/core/__init__.py`
Expected: 无报错。

**Step 4: Commit**
```
git add src/wiki/core/__init__.py
git commit -m "refactor(wiki/core): stop re-exporting dead TaskStatus/KnowledgeTask/EventName"
```

---

## Task 3: 收敛 wiki 顶层门面

**Files:**
- Modify: `src/wiki/__init__.py:18-24`（import 块）+ `src/wiki/__init__.py:46-56`（`__all__`，具体行见文件现状）

**Step 1: 从 import 块移除三个名字**

原块（`src/wiki/__init__.py` 约 18-24 行）：
```python
from .core.types import (
    EventName,
    KnowledgeTask,
    PageType,
    ReviewItem,
    TaskStatus,
    make_review_item,
)
```
改为：
```python
from .core.types import (
    PageType,
    ReviewItem,
    TaskStatus_DUMMY,   # ← 不保留；见下
    make_review_item,
)
```
> **注意**：实际不写 `TaskStatus_DUMMY`。正确改法是直接删掉 `EventName`、`KnowledgeTask`、`TaskStatus` 三行，结果：
```python
from .core.types import (
    PageType,
    ReviewItem,
    make_review_item,
)
```

**Step 2: 从 `__all__` 移除三个名字**

从顶层 `__all__` 中删去 `"EventName"`、`"TaskStatus"`、`"KnowledgeTask"` 三项（保留 `"PageType"` / `"WikiPage"` / `"ReviewItem"` / `"make_review_item"` / `"WikiPaths"` 等）。

**Step 3: 编译校验**
Run: `python -m py_compile src/wiki/__init__.py`
Expected: 无报错。

**Step 4: Commit**
```
git add src/wiki/__init__.py
git commit -m "refactor(wiki): drop dead TaskStatus/KnowledgeTask/EventName from public facade"
```

---

## Task 4: 全量回归与一致性验证

**Step 1: 门面一致性——确认 wiki 不再导出自相矛盾的符号**
Run:
```
python -c "import src.wiki as w; assert not hasattr(w,'TaskStatus'), 'TaskStatus still exported'; assert not hasattr(w,'KnowledgeTask'), 'KnowledgeTask still exported'; assert not hasattr(w,'EventName'), 'EventName still exported'; print('OK: wiki facade clean')"
```
Expected: `OK: wiki facade clean`

**Step 2: 真实来源仍可用——确认 src.types / events 不受影响**
Run:
```
python -c "from src.types import TaskStatus, KnowledgeTask, SourceType; from src.events.events import EventName; assert 'waiting_review' in [s.value for s in TaskStatus]; assert 'dead_letter' in [s.value for s in TaskStatus]; assert 'project_id' in KnowledgeTask.__dataclass_fields__; assert hasattr(EventName,'INGEST_STAGE'); print('OK: canonical contracts intact')"
```
Expected: `OK: canonical contracts intact`

**Step 3: 全项目 import 图自检（轻量，不跑完整 pytest）**
Run: `python -m py_compile $(find src -name '*.py' -not -path '*__pycache__*')`
Expected: 无报错。

**Step 4: 搜索无悬空引用**
Run:
```
grep -rn "from src.wiki import.*\(TaskStatus\|KnowledgeTask\|EventName\)\|from src.wiki.core import.*\(TaskStatus\|KnowledgeTask\)\|wiki.core.types import.*\(TaskStatus\|KnowledgeTask\|EventName\)" src tests 2>/dev/null | grep -v __pycache__
```
Expected: 无任何输出。

**Step 5: 建议本机完整回归（沙箱离线无法跑）**
Run: `uv run pytest -q`
Expected: 全绿（873 测试基线）。重点看 `tests/test_wiki/test_types.py`（已迁移，应通过）、`tests/test_queue/`、`tests/test_pipeline/`、`tests/test_orchestrator/`、`tests/test_e2e/`——这些直接消费 `src.types` 的契约。

**Step 6: Commit（若 Step 5 通过，合并前述 commit 或补 commit）**
```
git add -A && git commit -m "test: confirm contract merge keeps full suite green"
```

---

## 收尾说明

- 本方案**不修复**"禁止跨模块穿透"（281 处）那条——那是独立的、更大的整洁度整改，本方案只拔除其中"同名双定义陷阱"这一根因隐患，使后续穿透整改更安全。
- 若日后希望 **wiki 版 `EventName` 也收敛为统一来源**，可在 Task 3 之后追加：`wiki/__init__.py` 里 `from .core.types import ...` 改为 `from ..events.events import EventName` 并保留在 `__all__`。因当前 wiki 版 `EventName` 零消费者，本次直接删除即可，无需做这个 re-export（保持纯减法）。
- 全部改动在 `src/wiki/` 内，与摄取核心（`pipeline/*`）零耦合，符合红线。
