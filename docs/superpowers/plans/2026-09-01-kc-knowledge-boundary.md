# Plan B — `src/kc` ↔ `src/knowledge` 边界重构方案

- **方案 ID**：`2026-09-01-kc-knowledge-boundary`
- **关联 ADR**：`docs/adr/0007-knowledge-candidate-ownership.md`（见附录 A）
- **风险等级**：🟡 中-高（领域模型重构，所有 kc 调用点必须审一遍）
- **目标**：让 `knowledge` 成为 `kc` 的**唯一领域类型 owner**；消除三个 `KnowledgeMode` 值空间不一致
- **预期收益**：
  - 跨包双向依赖从 **5 + 1 = 6** 处 → **0**
  - 单一 source of truth：`KnowledgeMode` 来自 `src.knowledge.core.candidate`
  - KC 退化为「适配器 + 编译器 + 完整性 Gates」三层，**不再持有领域 enum**
  - 测试覆盖更容易（KC 的领域逻辑依赖 knowledge 的稳定 schema）

---

## 0. 预埋审查标准（Plan-Audit §0）

| 维度 | 评估 |
|---|---|
| 目标对齐 | 消除 `kc → knowledge` 与 `knowledge → kc` 双向耦合；保留所有行为不变 |
| 前提假设 | 1) `KnowledgeObject` 是知识系统的"领域根"——稳定；2) `KnowledgeMode` 应为 3 值 enum 而非 2 值；3) `mode_extension.py` 的 re-export 仅为兼容层，可删 | 
| 边界场景 | 1) KC 测试 fixture 用本地 KnowledgeMode；2) book views 用了 2 值 KnowledgeMode；3) LLM 输出 JSON 走 fail-closed 路径 |
| 依赖项 | `src.knowledge.core.candidate`、`src.knowledge.core.object` 必须保持 backward-compat |
| 风险与副作用 | `src/kc/views/book/contract.py:302` 把 `KnowledgeMode` 重新赋给 2 值 set —— 改值空间会破坏 5 个测试 |
| 可执行性 | 分 4 个独立 commit，每个可 revert |
| 验收标准 | 见 §6 |
| 盲区 | 1) `src/knowledge/__init__.py` 几乎是空文件，重构后**应做公开 API 白名单**；2) `kc/contracts/mode.py` 行 88–158 里的 `parse_llm_output_with_mode` 是 KC 的核心算法，应整体迁到 knowledge 或在 kc 内部封装 |
| 回滚预案 | 4 个 commit 独立 revert |

---

## 1. 当前耦合现状（精确盘点 + 图谱佐证）

**图谱佐证**：`docs/architecture/2026-09-01-graph-subgraph-report.md` §2（kc↔knowledge 子图，37 边 / 24 distinct tuples / Tarjan SCC = 0 / 0 模块反向对）。

### 1.1 模块级依赖矩阵（grep + 图谱双重核验）

**grep 结果**：

```
src/kc → src/knowledge           (5 文件，全部依赖领域类型)
  ├─ kc/mainline.py:16-17         from src.knowledge.core.{candidate, object}
  ├─ kc/compiler/compile.py:5     from src.knowledge.core.object
  ├─ kc/backup/drill.py:25        from src.knowledge.core.object
  ├─ kc/backup/core_snapshot.py:26-27  from src.knowledge.core.{object, version_manager}
  └─ kc/adapters/wiki_projection.py:3  from src.knowledge.core.object

src/knowledge → src/kc           (1 文件，反向依赖的"接缝")
  └─ knowledge/core/mode_extension.py:22  from src.kc.contracts.mode (re-export)
```

**图谱量化**（subagent §2）：

| 维度 | 数字 | 含义 |
|---|---:|---|
| `kc → knowledge` 边数 | **33** | 主流向 |
| `knowledge → kc` 边数 | **4** | 仅 `mode_extension → mode`（3 `imports` + 1 `imports_from`） |
| 去重 distinct tuples | **24** | `(direction, src_module, tgt_module, relation)` |
| 参与耦合的源模块数 | **11** | kc 侧 + knowledge 侧 |
| Tarjan SCC（含两侧的环） | **0** | **无循环依赖**（与 codebase-memory-MCP 报告一致） |
| "A→B AND B→A" 模块对 | **0** | 没有任何反向模块对 |

→ 整个跨包耦合是一个 **DAG**：`kc → knowledge` 主干（33 边）+ 一个孤立的反向叶子边（`mode_extension → mode`，4 边，且 `mode` **不**反向 import `mode_extension`）。这是 **单向叶子反向依赖**，不是 SCC，不是循环——原方案 §1.1 措辞"循环"应降级为"单一反向接缝"。

### 1.2 `KnowledgeMode` 值空间的两处定义（一处业务约束 + 一处别名陷阱）

| 位置 | 定义 | 取值 | 性质 |
|---|---|---|---|
| `src/kc/contracts/mode.py:22` | `KnowledgeMode = Literal["observed","synthesized","unknown"]` | **3 值** | 领域类型，fail-closed 默认 "unknown" |
| `src/knowledge/core/candidate.py:76` | `knowledge_mode: Literal["observed","synthesized","unknown"] = "unknown"` | **3 值** | ✅ 与 kc 一致（src of truth） |
| `src/kc/views/book/contract.py:76` | `_ALLOWED_KNOWLEDGE_MODES: frozenset = frozenset({"observed","synthesized"})` | **2 值** | **业务约束**（book view 不渲染 "unknown"——"unknown" 应走 fail-closed 路径，不应进入 book view） |
| `src/kc/views/book/contract.py:302` | `KnowledgeMode = _ALLOWED_KNOWLEDGE_MODES`（type-ignored） | **2 值别名** | ⚠️ **这是 bug**：line 302 把 `KnowledgeMode` 这个名字重新定义为 2 值 frozenset，**shadow 了真正的 KnowledgeMode**，导致 `from src.kc.views.book.contract import KnowledgeMode` 拿到的是 frozenset，不是 Literal |

→ **同一概念，两套值空间**（领域层 3 值、book view 校验层 2 值）—— 后者是**有意业务约束**，但 line 302 的别名覆盖是**真 bug**：污染全局 `KnowledgeMode` 名字。

**修正后的修复方向**（替代原 §2.2 的"统一为 3 值"）：
- ✅ **保留** `_ALLOWED_KNOWLEDGE_MODES`（2 值）作为 book view 自己的业务校验常量
- ❌ **删除** line 302 的 `KnowledgeMode = _ALLOWED_KNOWLEDGE_MODES` 别名覆盖
- ❌ **删除** `mode_extension.py` shim（grep 已确认 0 外部 import）
- ✅ `src/kc/contracts/mode.py` 的 `KnowledgeMode` 改为 import 自 `src.knowledge.core.candidate`
- ✅ `src/knowledge/__init__.py` 加公开 API 白名单

**这样改之后**：book view 的 2 值校验保持不变，但 `KnowledgeMode` 这个名字始终指向 3 值 Literal——不再有 alias 陷阱。

### 1.3 耦合 hub 模块（subagent §2.5）

| 模块 | 跨包 import 边数 | 性质 |
|---|---:|---|
| `src/knowledge/core/object.py` | **19** | 核心领域 dataclass，最大 hub |
| `src/kc/backup/core_snapshot.py` | **14** | KC 的 backup 子模块，依赖 knowledge 持久化层 |
| `src/knowledge/core/version_manager.py` | **10** | 知识版本管理 |
| `src/kc/contracts/mode.py` | **8** | KnowledgeMode 定义 + LLM 解析算法（**5 hub 之一，不是辅助模块**） |
| `src/kc/compiler/compile.py` | **6** | KC 编译器入口 |

→ **整个跨包耦合 funnels through 5 个模块**——比 grep 的 5 文件更精细（`mode.py` 是 8 边的 hub，**不是** "路过的辅助模块"）。

### 1.4 文件大小对比（佐证"knowledge 是稳定内核"）

```
src/kc/        68 个 .py, 顶层 api.py 6338 行 + mainline.py 12199 行 + 14 个子包
src/knowledge/  34 个 .py, 顶层 kernel.py 12967 行 + 9 个子包, __init__.py 只有 1 行
```

→ knowledge 文件数只是 kc 的一半，但**承载核心领域类型**（`KnowledgeObject` / `KnowledgeCandidate` / `KnowledgeMode`）。

---

## 2. 边界重构设计（核心方案）

### 2.1 目标边界（前后对比）

```
BEFORE                                     AFTER
─────                                      ─────

src/kc ──depends on──> src/knowledge       src/kc ──depends on──> src/knowledge
       <──depends on──┘                              （无反向）
       (循环模式：re-export shim)
```

**核心原则**：knowledge 是**领域类型 owner**；kc 是**编译/适配器/Gates 层**；领域 enum 的真理在 knowledge。

### 2.2 `KnowledgeMode` 单一来源化（修正版）

**步骤 1：把 `src/kc/contracts/mode.py` 的 `KnowledgeMode` 定义改为 import**

```python
# src/kc/contracts/mode.py — AFTER refactor
"""Knowledge Mode LLM output parser (K-2 fail-closed truncation guard).

The ``KnowledgeMode`` *value space* lives in
``src.knowledge.core.candidate`` as a single source of truth.
This module owns only the *parse functions* that operate on LLM output.

Public API:
    KnowledgeMode                re-export (canonical 3-value Literal)
    detect_truncation(raw)       5-truncation detector
    parse_llm_output_with_mode(raw) → KnowledgeCandidate (with fail-closed)
"""
from __future__ import annotations
import json
from typing import Any

from src.knowledge.core.candidate import (
    CandidateStatus,
    KnowledgeCandidate,
    KnowledgeMode,        # ← import from canonical source (no longer redefined)
    KnowledgeType,
)


def parse_knowledge_mode(value: Any) -> KnowledgeMode:
    # ... (logic identical, only the type is imported not redefined)
```

**步骤 2：删除 `src/kc/views/book/contract.py:302` 的 alias 别名覆盖（保留 _ALLOWED_KNOWLEDGE_MODES 业务校验）**

```python
# src/kc/views/book/contract.py — AFTER refactor (only line 302 changes)
# DELETE line 302:  KnowledgeMode = _ALLOWED_KNOWLEDGE_MODES  # type: ignore[assignment]
# KEEP line 76:      _ALLOWED_KNOWLEDGE_MODES (2-value business rule for book view)
# KEEP line 271-276: book view's own validation rejects "unknown" (intentional)
#
# Now `from src.kc.views.book.contract import KnowledgeMode` no longer pollutes the
# global namespace. Code that needs the canonical 3-value type must use:
#   from src.knowledge.core.candidate import KnowledgeMode
#   # or via the public API:
#   from src.knowledge import KnowledgeMode
```

✅ **没有测试期望需要修改**：book view 的 `_ALLOWED_KNOWLEDGE_MODES` 校验保留，所有现有测试仍 pass。

**步骤 3：删除 `src/knowledge/core/mode_extension.py` 的 re-export shim**

```python
# src/knowledge/core/mode_extension.py — DELETED
# Reason: the 4 back-compat fields (knowledge_mode, failure_reason) are
# already in src/knowledge/core/candidate.py since C-4 commit.
# The mode_extension shim was transitional — the transition is done.
```

grep 已确认 0 个外部 import（`rg "from src\.knowledge\.core\.mode_extension" --type py` = 0 命中），删除安全。

### 2.3 `src/kc/mainline.py` 与 `src/knowledge.kernel` 的角色拆分

**当前**：
- `src/knowledge.kernel.KnowledgeKernel` 是"领域操作 facade"（create/update/transition_lifecycle/get_history/replay_object）
- `src/kc.mainline.py` 是"Reviewer→ Promoter 接缝"——走 `kc_api.candidate_to_payload` → `kc_api.compile_source`

**问题**：两者职责部分重叠（都涉及 KnowledgeObject 生命周期）

**方案**：明确分层
- `knowledge.kernel.KnowledgeKernel`：**持久化层 facade**（snapshot/version/lifecycle/replay）
- `kc.mainline.CandidateReviewer` / `CandidatePromoter`：**编译/适配层**（不直接管 persistence，走 `kc.publish` + `kc.integrity.gates`）

**`mainline.py` 拆 3 个类 → 各 ≤ 200 行**（Ponytail 建议）：
- `CandidateReviewer`（保留）
- `CandidatePromoter`（保留）
- `PublicationDriver`（新提取 —— 串接 Reviewer→ Promoter→ PublicationGate）

### 2.4 `src/knowledge/__init__.py` 做公开 API 白名单（呼应 `kc/__init__.py` 的样板）

**当前**：`src/knowledge/__init__.py` 只有 1 行 docstring。

**方案**：与 `kc/__init__.py` 对齐风格，给出 public API：

```python
# src/knowledge/__init__.py — AFTER refactor
"""Knowledge OS — core knowledge infrastructure.

Public API:
    KnowledgeObject, LifecycleState, KnowledgeType, Provenance
    KnowledgeCandidate, CandidateStatus, KnowledgeMode
    KnowledgeKernel — unified infrastructure facade for agent code
"""
from .core.candidate import (
    CandidateStatus,
    KnowledgeCandidate,
    KnowledgeMode,
)
from .core.object import (
    KnowledgeObject,
    KnowledgeType,
    LifecycleState,
    Provenance,
)
from .kernel import KnowledgeKernel

__all__ = [
    "CandidateStatus",
    "KnowledgeCandidate",
    "KnowledgeMode",
    "KnowledgeObject",
    "KnowledgeType",
    "LifecycleState",
    "Provenance",
    "KnowledgeKernel",
]
```

→ 让外部 import `from src.knowledge import KnowledgeMode` 与 `from src.knowledge import KnowledgeObject` 都 work（之前必须 `from src.knowledge.core.candidate import KnowledgeMode`）。

---

## 3. Plan-Audit Round 1 — 漏洞审计

### ① 致命缺陷

**F-1**：`KnowledgeMode` 值空间合并可能让生产数据 reject

- 场景：`book_view` 序列化"unknown"模式数据时，旧 contract 拒收 → 修改后 accept → 反序列化兼容性 ✅
- 但：如果有**已落盘的 wiki 页面**的 frontmatter 里写了 `knowledge_mode: unknown`，旧代码拒收 → 新代码 accept → 数据完整性 ✅
- 整改：增加 1 个 migration test，验证 legacy pages 不被新 contract 拒绝
- 评级：✅ 整改后可控

### ② 重大隐患

**H-1**：`mode_extension.py` 删除前必须 grep 验证外部 import

- 风险：可能有测试用 `from src.knowledge.core.mode_extension import KnowledgeMode`
- 整改：抽取前 `rg "from src\.knowledge\.core\.mode_extension" --type py`；若有，全部改为 `from src.knowledge.core.candidate import KnowledgeMode`

**H-2**：`src/kc/contracts/mode.py` 改 `KnowledgeMode` 来源后，`KnowledgeCandidate` 的 `knowledge_mode` 字段类型从 inline Literal 变为 import — 可能让 mypy / typeguard 报 cross-module alias

- 整改：在 `knowledge/core/candidate.py` 顶部显式 `KnowledgeMode = Literal["observed","synthesized","unknown"]`，加 `# noqa: A001` if needed

**H-3**（已撤销）：book view 的 5 个测试 fixture 期望值

- 风险：**不存在** —— 原方案 §2.2 误判了 `book/contract.py:302` 的语义
- 现状：`book_view` 拒绝 `"unknown"` 是**有意业务约束**（"unknown" 模式不应进入 book view——它应走 KC 的 fail-closed 状态机），不是 bug
- 修正后：book view 的 `_ALLOWED_KNOWLEDGE_MODES` 2值校验**保留**，line 302 别名覆盖**删除**；现有测试零改动
- 评级：✅ 已修正，无需整改

**H-4**：`kc/mainline.py` 拆分为 3 类后，外部 `CandidateReviewer` 用户可能依赖私有方法

- 风险：当前 `CandidateReviewer.review` 是 async method，但内部用 `try/except (ValueError, KeyError, TypeError)` —— 拆分时若把异常处理逻辑拆到 helper，外部 `await reviewer.review()` 的契约不变，但要 grep 验证
- 整改：`rg "CandidateReviewer" --type py`；只有 `tests/test_kc/test_default_mainline.py` 在用，安全

### ③ 优化疏漏

**O-1**：`KnowledgeKernel.replay_object`（行 207）有 `self.versions._load_version_data(...)` 使用 private method —— **违反封装**

- 整改：把 `_load_version_data` 改为 public `load_version_data`，或者在 `KnowledgeKernel` 中重写读取逻辑

**O-2**：`KnowledgeKernel.replay_core_from_events`（docstring 标记为 stub）—— 是 dead interface

- 整改：删除（YAGNI）；等真实需求出现再加

**O-3**：`PermissionEngine` 是 `kernel.py` 的内嵌类 —— 但被其他地方 import `KnowledgeKernel.permissions` 也无需要它

- 整改：保留（与 plan 文档绑定，未来会扩展）

---

## 4. Plan-Audit Round 2 — 压力测试推演

### 压测路径矩阵

| # | 失败路径 | 当前方案表现 | 加固方案 |
|---|---|---|---|
| **S-1** | `KnowledgeMode` 值空间从 3 值改 3 值（含 "unknown"），但 `kc/views/book/contract.py` 测试 fixture 写死 2 值期望 | 测试红 | 抽取 PR 同时更新 5 个测试 fixture：把"unknown"从 reject 改为 accept |
| **S-2** | 删除 `mode_extension.py` 后，外部 import `KnowledgeMode` 失败 | 启动时 ImportError（生产崩溃） | 抽取前 `rg` 验证；如有用方，迁移到 `src.knowledge` 直接 import |
| **S-3** | `kc/mainline.py` 拆 3 类后，`PublicationDriver` 串接 reviewer→ promoter→ publication_gate 的顺序错了 → 数据丢失 | 已有 `tests/test_kc/test_mainline.py` 覆盖；拆分后必须保持 pass | 拆分后跑端到端 `test_mainline.py -v`；任何红 = 不合并 |
| **S-4** | `kc/contracts/mode.py` 改 import 后，`parse_llm_output_with_mode` 的延迟 import（行 104）路径变了 — 可能触发 `ImportError` 在运行时不触发在测试时 | LLM 输出 fail-closed 静默失效（5 截断场景不再被捕获） | 增加 1 个 test: `test_truncation_fail_closed`，跑 5 种截断 fixture，每种都期望 `CandidateStatus.REJECTED` |
| **S-5** | `src/knowledge/__init__.py` 公开 API 变更后，旧 import 路径（`from src.knowledge.core.candidate import ...`）仍 work 但新增 `from src.knowledge import ...` 也 work — 但如果有 cyc import `from src.knowledge import KnowledgeCandidate` 在 kc 初始化路径上 | 启动时循环 import | 在 kc 入口用 `from src.knowledge.core.candidate import ...`（避免触发 `__init__.py` 的整包导入链） |
| **S-6** | `KnowledgeKernel.replay_object` 改了 `_load_version_data` 访问方式 → `tests/test_knowledge/test_version_manager.py` 失败 | 持久化层破坏 | 拆分后跑 `pytest tests/test_knowledge/ -v`；任何红 = 不合并 |

### 加固总览

**每个 commit 前必做的 4 件事**：
1. `rg "from src\.knowledge\.core\.mode_extension"` — 必须 0 命中
2. `rg "KnowledgeMode"` — 列出全部 12 个使用点，逐个确认值空间假设
3. `pytest tests/test_knowledge/ tests/test_kc/ -v` — 拆分前基线
4. 跑 `python -m src.cli project init <test_proj> && python -m src.cli health --project <id>` — 真实启动一次（`docs/environment/SKETUP.md` §4 警告：lifespan 不能在测试里发现）

---

## 5. Ponytail 简化 pass

### 5.1 已通过梯子

- `_load_version_data` 用 `_` 前缀说明这是 private API —— 但 `KnowledgeKernel` 用它 → 违反封装（P-1）
- `PermissionEngine` 仅 6 行 method → 已是最简

### 5.2 可简化（采纳）

**PP-1**: `src/knowledge/core/mode_extension.py` 整体删除（YAGNI）

- 当前 40 行文件，**纯 re-export**，没有任何新逻辑
- 整改：删除；如需保留兼容，加一行 `DeprecationWarning` 在 kc/contracts/mode.py 的 re-export 处

**PP-2**: `src/knowledge/kernel.py` 行 207 `self.versions._load_version_data(...)` → 改为 `self.versions.load_version_data(...)`（提升为 public）

- 当前：kernel 调用 version_manager 的 private 方法
- Ponytail：**Rung 1 - 不要调 private**；应该让 `_load_version_data` 升为 public `load_version_data`
- 收益：去掉 `# noqa: SLF001` 注释

**PP-3**: `KnowledgeKernel._extensions: dict = {}` 是占位字段，未使用

- 整改：删除（YAGNI）；等 Phase 2/3 真的接入再添加

### 5.3 拒绝的"过度简化"（已记录但不做）

- ❌ "把 `kc/mainline.py` 拆成 5 个 dataclass" —— 拆分到 3 个 class 已经足够（reviewer/promoter/driver）
- ❌ "把 `KnowledgeKernel` 改为 pure function" —— 它的状态（permissions、events、versions）是合理的 facade 设计

---

## 6. 验收标准（量化）

| 指标 | 当前 | 重构后 | 测量方式 |
|---|---:|---:|---|
| `kc → knowledge` 依赖文件数 | 5 | ≤ 5（不变；都是合法领域类型依赖） | `rg 'from src\.knowledge\.' src/kc/` |
| `knowledge → kc` 依赖文件数 | **1**（mode_extension re-export） | **0** | `rg 'from src\.kc\.' src/knowledge/` |
| `KnowledgeMode` 类型定义位置 | **2 处**（mode.py + candidate.py，都是 Literal 3 值） | **1 处**（candidate.py，mode.py import） | `rg 'KnowledgeMode\s*=\s*Literal' src/` |
| `KnowledgeMode` 别名覆盖 | **1 处**（book/contract.py:302 2 值 frozenset） | **0 处** | `rg 'KnowledgeMode\s*=\s*_ALLOWED' src/` |
| `_ALLOWED_KNOWLEDGE_MODES` 业务校验 | 存在（book view 2 值规则） | **保留**（不删除） | `rg '_ALLOWED_KNOWLEDGE_MODES' src/` |
| `mode_extension.py` 存在 | ✅ 40 行 re-export shim | ❌ 删除 | `ls src/knowledge/core/` |
| `src/knowledge/__init__.py` 行数 | 1 | ≥ 15（公开 API 白名单） | `wc -l src/knowledge/__init__.py` |
| `src/kc/mainline.py` 行数 | 12,199 | ≤ 8,000（拆 3 类后） | `wc -l src/kc/mainline.py` |
| book view 测试需更新 | 0 | **0**（删除 alias 不动校验逻辑） | `pytest tests/test_kc/views/book/ -v` |
| `tests/test_knowledge/` 通过 | ✅ | ✅ | `pytest tests/test_knowledge/ -v` |
| `python -m src.cli serve` 启动 | ✅ | ✅ | manual smoke test |

---

## 7. 风险地图（commit-by-commit）

| Phase | Commit | 风险点 | 回滚命令 |
|---|---|---|---|
| Phase 0 | `refactor(knowledge): delete mode_extension.py shim` | 外部 import 遗漏 | `git revert <sha>` |
| Phase 1 | `refactor(kc): align book/contract.py KnowledgeMode to 3-value` | book view 测试 fixture 期望值变了 | `git revert <sha>` + 修测试 |
| Phase 2 | `refactor(kc): make mode.py import KnowledgeMode from knowledge.core.candidate` | typeguard / 延迟 import 路径变化 | `git revert <sha>` |
| Phase 3 | `refactor(knowledge): add public API whitelist to __init__.py` | 循环 import（若 kc 用 `from src.knowledge import ...`） | kc 入口改回 `from src.knowledge.core.X import ...` |
| Phase 4 (optional) | `refactor(kc): split mainline.py into 3 classes` | review/promote/driver 串联顺序错 | `git revert <sha>` |

---

## 8. 不在本方案范围内（避免 scope drift）

按 Ponytail 「不要为不存在的需求写代码」：

- ❌ 不引入新的 `KnowledgeMode` 字段（如 `Mixed` 模式）—— 等 spec 真要再改
- ❌ 不把 `PermissionEngine` 提到独立模块 —— 当前 6 行内嵌合理
- ❌ 不重写 `LifecycleEngine` —— 不在边界重构的范围
- ❌ 不改 KnowledgeObject 的字段 schema —— 只动 enum 来源

---

## 附录 A — ADR 草案

```markdown
# ADR-0007: KnowledgeCandidate 领域类型 ownership 归属 src.knowledge

## Status
Proposed (2026-09-01)

## Context
src/kc 和 src/knowledge 在演进过程中,领域类型 `KnowledgeObject` /
`KnowledgeCandidate` / `KnowledgeMode` 同时出现在两个包中:

| 类型 | kc 中的位置 | knowledge 中的位置 |
|---|---|---|
| KnowledgeObject | (consumed via import) | core/object.py |
| KnowledgeCandidate | (consumed via import) | core/candidate.py |
| KnowledgeMode | contracts/mode.py (3-value) | core/candidate.py (3-value) |
|                  | views/book/contract.py:302 (2-value!) | |

`KnowledgeMode` 在 kc/views/book/contract.py 被重定义为 2 值,与
kc/contracts/mode.py 的 3 值不一致 —— 同一概念三种值空间,生产数据
可能因新 contract 校验失败而拒收 (book view 测试 fixture 期望
"unknown" 被拒,但 KC fail-closed 策略要求 "unknown" 合法)。

src/knowledge 是稳定的领域内核 (kernel.py 单一 facade,无 stateful 业务),
src/kc 是编译器/适配器/Gates 业务层,二者应该有清晰的单向依赖:

  src/kc ──depends on──> src/knowledge

而不是当前的"接缝式双向耦合"。

## Decision
1. **KnowledgeCandidate 系列类型 (KnowledgeMode / CandidateStatus /
   KnowledgeType) 全部 src/knowledge.core.candidate 为单一来源**。
3. **KnowledgeMode 值空间统一为 3 值 (observed / synthesized /
   unknown)**;book/contract.py 接受 "unknown",不再拒收。
4. **删除 src/knowledge/core/mode_extension.py** (40 行 re-export
   shim,纯过渡层,迁移已完成)。
5. **src/knowledge/__init__.py 增加公开 API 白名单**,与 src/kc/
   __init__.py 风格对齐。

## Consequences

### Positive
- 跨包耦合从 1 处反向 (knowledge→kc) → 0 处
- 同一概念三个值空间 → 一个值空间;消除生产数据拒收风险
- knowledge 与 kc 的角色清晰:knowledge = 领域内核,kc = 编译器/适配器
- knowledge 子包可独立测试,无需 import kc

### Negative
- 5 个 book/contract 测试 fixture 需更新 (从期望 reject 改为 accept)
- 部分 legacy import 路径 (`from src.knowledge.core.mode_extension
  import KnowledgeMode`) 被打破 — 需 grep + 全量替换

### Risks
- KC 算法 `parse_llm_output_with_mode` 跨包延迟 import 路径变化 → 需
  回归测试覆盖 5 种 LLM 截断 fail-closed 场景
- knowledge `__init__.py` 引入新公开 API → 需验证无 cyc import (kc
  入口必须用 `from src.knowledge.core.candidate import ...`)

## Alternatives Considered

### A. 保留 kc/contracts/mode.py 作为 KnowledgeMode 单一来源
- ❌ kc 是编译器层而非领域层;领域 enum 不应在 kc
- ❌ 与 kc/contracts/ 的纯 contracts (无领域类型) 定位冲突

### B. 把 knowledge 内核合并进 kc (反向吸收)
- ❌ 现有 100+ 文件依赖 knowledge;合并将是一次破坏性改动
- ❌ knowledge 的稳定性 (kernel.py 1 个 facade) 是它的最大价值

### C. 保持现状,只补文档
- ❌ 已有数据生产 reject 风险,不补代码无法消除
- ❌ mode_extension shim 已无存在价值,YAGNI
```

---

## 附录 B — 落地 Checklist（PR-by-PR）

- [ ] **PR 0**：删除 `src/knowledge/core/mode_extension.py`，grep 验证无外部 import
- [ ] **PR 1**：修改 `src/kc/views/book/contract.py` 的 `KnowledgeMode` 值为 3 值，更新 5 个测试 fixture
- [ ] **PR 2**：修改 `src/kc/contracts/mode.py` 让 `KnowledgeMode` 从 `src.knowledge.core.candidate` import
- [ ] **PR 3**：修改 `src/knowledge/__init__.py` 加公开 API 白名单
- [ ] **PR 4（可选）**：拆分 `src/kc/mainline.py` 为 3 个类（reviewer/promoter/driver）
- [ ] **最终**：跑 `pytest tests/test_knowledge/ tests/test_kc/ tests/test_scripts/ -v` 全绿 + `python -m src.cli serve` smoke test 通过
- [ ] **更新 `docs/agents/issue-tracker.md` 与 `.superpowers/sdd/progress.md`**

---

*方案生成：基于 `rg 'from src\.(kc|knowledge)\.' --type py` 的精确盘点 + `src/knowledge/core/mode_extension.py` 反向 re-export 实证 + `KnowledgeMode` 值空间三处定义冲突。Round 1/2 已嵌入。ADR-0007 草案见附录 A。*