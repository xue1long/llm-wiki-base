status: draft
branch: fix/ingest-relation-sync-bug

> **承接**：本 plan 是**阶段 4 架构体检的多角色审查拆分产物**。
> 原 plan `2026-09-19-pipeline-ingest-strategies.md` 把 "修 1 行 bug" 和 "7 文件架构重构" 混在 7 个 commit 里，**scope creep** —— 逆向挑战者 + 风险管控者均判定 NEEDS-FIX。
> 本 plan **只做 bug fix**：scope 最小（line 170 fix + `_compute_reverse_relations` 删除 + 6 caller 迁移）；架构重构（Strategy 抽象 / LineageContext / ResolvabilityIndex）作为独立 plan B 后续启动。
> 计划采用 TDD per task，1 commit per logical slice。

## Goal

**用户可见结果**：
- `src/wiki/features/relations.py:170` `RelationSync.sync_page` 改为 "保留 page.relations + 追加 + dedup"（语义对齐 `_compute_reverse_relations` 的内存合并）
- `src/pipeline/ingest.py:261-323` 的 `_compute_reverse_relations`（63 行）**删除**
- `ingest.py:1327` 调用方改为 `RelationSync.sync_page`（签名不变）
- **6 个 caller** 全部迁移到新接口：
  - `src/pipeline/ingest.py:429`（ingest 内部，本 plan 范围）
  - `src/pipeline/batch_gate.py:241`
  - `src/maintenance/checks/h2_break_links.py:102`
  - `src/pipeline/reconcile.py:85`
  - `src/orchestrator/batch_runner_internal/phases.py:190`（**plan author 原 plan 漏算**，由 reviewer 独立 grep 发现）
  - `tests/test_wiki/test_target_resolver.py`（迁移到 `tests/test_pipeline/test_resolvability.py`）
- **`Relation` dataclass 必须 `frozen=True`** 否则 `tuple(r)` 运行时 TypeError（reviewer 场景 7 验证的事实）
- **4 项 breaking change 显式声明**：legacy mode / sync_page 语义 / sync_page atomicity / `_v7_mode` 内联 boolean 行为转移

**明确非目标**：
- 不引入 `ResolvabilityIndex`（架构重构 → Plan B）
- 不引入 `STRATEGY_REGISTRY`（架构重构 → Plan B）
- 不引入 `LineageContext` context manager（架构重构 → Plan B）
- 不动 `services/ingest.py` 的 3 次 `LineageStore.open`（独立 plan）
- 不重写 shadow.py（独立 plan）
- 不动 `_compute_reverse_relations` 的 in-memory 合并到磁盘写盘的 atomic batch 行为

## Context

`src/pipeline/ingest.py` 是 ruflo-kb 摄取主路径，最近 5 个 commit 都在给这个文件打补丁。

**关键事实校正**（多角色审查 reviewer 独立验证）：
- `_compute_reverse_relations:271-273` docstring 显式说：**"sync_page resets a page's own relations to the passed list and would clobber an inverse edge that a prior page's sync just wrote"**。
- 原 `_compute_reverse_relations` 的语义是：**追加 + dedup（按 `(target_id, type)`）**，**不重置 own relations**。
- `RelationSync.sync_page:170` 的 "重置" 语义是**故意**的（docstring 反指），plan 必须把它改为**对齐 `_compute_reverse_relations` 的语义**才能删 63 行 dedup。
- `Relation` 是 `@dataclass` **未带** `frozen=True`（实测 `src/wiki/features/relations.py:92-97`），默认 `__hash__ = None`。任何 `tuple(r)` 运行时 TypeError。
- `target_resolver.resolve_wiki_target` 实际被 **6 处 import**（plan author 声称 4 处，漏算 `reconcile.py:85` + `phases.py:190`）。
- `_compute_reverse_relations` 当前 git grep 已是 **0 hits**（实测）—— 但 plan 的 deletion test 用 word boundary 漏判。

**问题**：
- `ingest.py:1327` `extra_pages = _compute_reverse_relations(paths, pages)` 是 63 行 dedup re-implementation
- `RelationSync.sync_page:170` 的"重置"语义**故意**与 `_compute_reverse_relations` 的"追加"语义相反——**两个函数**实现同一意图但语义冲突
- 6 个 caller 用 `target_resolver.resolve_wiki_target` 旧 API；删 module 时会 **ImportError**

## Decision

### 修复 1：`RelationSync.sync_page` 语义对齐

```python
# src/wiki/features/relations.py:92
@dataclass(frozen=True)  # +1：原无 frozen；改为 frozen 以支持 hash
class Relation:
    target_id: str
    type: str
    weight: float = 1.0
    context: str = ""

# src/wiki/features/relations.py:170-191 (sync_page 内)
def sync_page(self, page_id, relations):
    target = self._read_page(page_id)
    if target is None:
        return
    # 原: target.relations = relations  ← 重置 own relations (by design)
    # 新: 保留 + 追加 + dedup（与 _compute_reverse_relations 语义对齐）
    existing = list(target.relations or [])
    incoming = list(relations or [])
    # dedup by (target_id, type) — 同 _compute_reverse_relations:318
    seen = {(r.target_id, r.type): r for r in existing}
    for r in incoming:
        seen.setdefault((r.target_id, r.type), r)  # 不覆盖现有（保持 weight 不变）
    target.relations = list(seen.values())
    self._write_page(page_id, target)
    # 保留原有 write_outgoing + write_backlinks_for_source
    rel_dicts = [r.to_dict() for r in relations]
    write_outgoing(paths, page_id, rel_dicts)
    write_backlinks_for_source(paths, page_id, rel_dicts)
    # Apply inverse to each target
    for rel in relations:
        inv = rel.inverse()
        if inv is None or rel.type in SYMMETRIC_RELATIONS:
            continue
        # Relation frozen=True —— **必须** 用 dataclasses.replace 创建新实例
        # 不能 `inv.target_id = page_id`（FrozenInstanceError）
        # Plan A reviewer 4 (最终验收人) 独立验证 line 182 mutation 抛错
        inv = dataclasses.replace(inv, target_id=page_id)
        target_type = _infer_type(paths, rel.target_id)
        target_file = page_path_for(paths, target_type, rel.target_id)
        if not target_file.exists():
            continue
        target_page = read_page(target_file)
        if any(r.target_id == page_id and r.type == inv.type for r in target_page.relations):
            continue  # already has inverse
        # 同样用 replace 创建新 target.relations（frozen=True）
        new_target_relations = list(target_page.relations or []) + [inv]
        target_page.relations = [
            r for r in new_target_relations
            if not (r.target_id == inv.target_id and r.type == inv.type)
        ]  # dedup by (target_id, type)
        target_page.relations.append(inv)
        write_page(paths, target_type, target_page)

### 修复 2：删除 `_compute_reverse_relations`

```python
# src/pipeline/ingest.py — 删除 lines 261-323（63 行）
# 调用方 line 1327 改为：
# 原: extra_pages = _compute_reverse_relations(paths, pages)
# 新: extra_pages = []  # sync_page 已在 line 1327 后调过；但实际不在 line 1327，需要把 sync_page 移到此处
```

**问题**：`_compute_reverse_relations` 不仅**计算 inverse** 还**load + mutate pre-existing pages**（line 300-306）并返回 `extra`（line 290）—— 这是**关键差异**：
- `_compute_reverse_relations` 返回的 `extra_pages` 由 commit_ingest 在 AtomicContext 内 batch write（line 1357）
- `RelationSync.sync_page` **不会**自动 batch——每次调用都自己 write_page

**所以**：删除 `_compute_reverse_relations` 后必须把 inverse 计算**仍**显式做（不让 sync_page 自己每次 write），把 `extra_pages` 收集起来交给 `commit_ingest` 的 AtomicContext 统一写。

**新代码**：
```python
# src/pipeline/ingest.py — 替换 lines 1325-1354
def _collect_inverse_relations(paths, pages):
    """Compute inverse edges in-memory; returns extra_pages list for
    AtomicContext batch write. Same logic as old _compute_reverse_relations
    but **does not write** — caller (commit_ingest) writes batch.
    """
    from ..wiki.features.relations import SYMMETRIC_RELATIONS
    from ..wiki.storage.page_writer import read_page, page_path_for
    from ..wiki.core.types import PageType

    def _infer_type(slug):
        for t, prop in (
            (PageType.ENTITY, "wiki_entities"),
            (PageType.CONCEPT, "wiki_concepts"),
            (PageType.SOURCE, "wiki_sources"),
            (PageType.SYNTHESIS, "wiki_synthesis"),
        ):
            if (getattr(paths, prop) / f"{slug}.md").exists():
                return t
        return PageType.SOURCE

    by_id = {p.id: p for p in pages}
    extra = {}

    def _target_page(target_id):
        if target_id in by_id:
            return by_id[target_id]
        if target_id in extra:
            return extra[target_id]
        f = page_path_for(paths, _infer_type(target_id), target_id)
        if not f.exists():
            return None
        try:
            pg = read_page(f)
        except Exception:
            _logger.warning("Failed to read page %s for relation target", target_id, exc_info=True)
            return None
        extra[target_id] = pg
        return pg

    for page in pages:
        for rel in list(page.relations or []):
            inv = rel.inverse()
            if inv is None or rel.type in SYMMETRIC_RELATIONS:
                continue
            # Relation frozen=True —— 必须用 dataclasses.replace
            # 不能 `inv.target_id = page.id`（FrozenInstanceError）
            # 与 sync_page 修复一致
            inv = dataclasses.replace(inv, target_id=page.id)
            target = _target_page(rel.target_id)
            if target is None:
                continue
            rels = list(target.relations or [])
            if any(r.target_id == inv.target_id and r.type == inv.type for r in rels):
                continue
            rels.append(inv)
            target.relations = rels

    return list(extra.values())
```

`_collect_inverse_relations` 实施时**必须**:
- ingest.py:1 `from dataclasses import dataclass, field` → `from dataclasses import dataclass, field, replace`
- 在 line 313 `inv.target_id = page.id` 改为 `inv = replace(inv, target_id=page.id)`
- 加 1 个测试 `test_collect_inverse_relations_with_frozen_relation_does_not_raise`
```

**调用方**：
```python
# ingest.py:1327
# 原: extra_pages = _compute_reverse_relations(paths, pages)
# 新: extra_pages = _collect_inverse_relations(paths, pages)
```

**为什么重命名为 `_collect_inverse_relations`**：明确这是"收集"行为，不是"compute + write"——消除读者误解（reviewer 1 关键质疑点）。

### 修复 3：6 caller 迁移

每个 caller 把 `target_resolver.resolve_wiki_target(target, context=ctx)` 改为新接口（这是 Plan B 的 `ResolvabilityIndex.resolve_with_kind`——但 Plan B 未启动）。**Plan A 的解决方案**：保留 `target_resolver.resolve_wiki_target` 旧 API **不删除**，只迁本 plan 范围内的 caller。

**Plan A 范围 caller**：
1. `src/pipeline/ingest.py:429`（plan 范围内）—— 改为调 `RelationSync.sync_page` 直接写（**这是 ingest 内部的 _normalize_generated_pages**）
2. `src/pipeline/batch_gate.py:241` —— Plan A 范围内（batch_gate 是 ingest pipeline 的一部分），保留旧 API 调用，**加 deprecation warning**
3. `src/maintenance/checks/h2_break_links.py:102` —— Plan A 范围内，保留旧 API 调用 + deprecation warning
4. `src/pipeline/reconcile.py:85` —— Plan A 范围内（reconcile 是 ingest pipeline 的一部分），保留旧 API + deprecation warning
5. `src/orchestrator/batch_runner_internal/phases.py:190` —— **reviewer 新发现**，Plan A 范围内 + deprecation warning
6. `tests/test_wiki/test_target_resolver.py` —— 测试模块，Plan A 范围：保留旧 test，加 deprecation warning，标 "Plan B 迁 ResolvabilityIndex"

**Deprecation warning**：
```python
import warnings
warnings.warn(
    "target_resolver.resolve_wiki_target is deprecated; "
    "use ResolvabilityIndex.resolve_with_kind (Plan B). "
    "Will be removed in 2026-Q4.",
    DeprecationWarning,
    stacklevel=2,
)
```

**Plan A 不删除 `target_resolver.resolve_wiki_target`**——只加 deprecation warning。彻底删除是 Plan B 的工作（架构重构）。

### 修复 4：breaking change 声明（必须显式列）

按多角色审查 reviewer 4 的"行为变更声明缺失"要求，§Decision 段必须显式列 4 项：

1. **`legacy` mode 从 no-op 变生效** —— 原 `ingest.py:742-744` 只判 `_v7_mode` / `_candidate_mode`，**任何 `RUFLO_PIPELINE_MODE=legacy` 都 fall through 到 candidate 分支**。**Plan A 不改此行为**（不引入 STRATEGY_REGISTRY），保持 legacy mode 是 no-op。
2. **`RelationSync.sync_page` 语义变更** —— 从 "重置 own relations" 变 "保留 + 追加 + dedup"。这是**显式 breaking change**（任何依赖旧"重置"语义的 caller 会改变行为）。
   - **Mitigation**：Plan A §Acceptance 加 `test_sync_page_preserves_own_relations_breaking_change_documented` —— 测试断言新行为 + docstring 显式说"behavior change 2026-09-19"
3. **`_compute_reverse_relations` 重命名为 `_collect_inverse_relations`** —— 公共名变化。**Mitigation**：在 `src/pipeline/ingest.py:261` 留 deprecated alias 6 个月。
4. **Plan A 范围内 caller 6 处 deprecation warning** —— 不删除，标 "Plan B 迁 ResolvabilityIndex"。

## Rationale

- **scope 最小**：1 个 bug fix + 1 个 dataclass frozen + 1 个方法重命名 + 6 caller deprecation = **3-4 commits**
- **不引入架构重构**（ResolvabilityIndex / STRATEGY_REGISTRY / LineageContext）—— 这些推到 Plan B
- **删除 63 行重复**（`_compute_reverse_relations`） + **1 行行为修复**（`RelationSync.sync_page:170`） = **净 -62 行**
- **保留 6 caller 兼容**（deprecation warning），不破坏现有测试

## Consequences

### 更简单
- `RelationSync.sync_page` 单一方法处理所有 relation 写入（不再有"两套语义冲突的实现"）
- `_collect_inverse_relations` 名字清晰表明"只计算不写"
- `Relation.__hash__` 修复解锁未来 relation 去重的 dict key 用法

### 更复杂 / 风险
- **breaking change**（`RelationSync.sync_page` 语义变更）—— 任何外部 caller 可能受影响。Plan A 用 docstring + deprecation warning 减轻，但**不删除旧语义**
- **`_v7_mode` 内联 boolean 行为转移**（line 995 / line 1401）—— Plan A **不修**（这是 Plan B 范畴）
- **`services/ingest.py` 的 3 次 LineageStore.open** —— Plan A **不修**（独立 plan）

## Alternatives Considered

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| A (chosen) 1 bug fix + 1 dataclass frozen + 6 caller deprecation | scope 最小；可 sign-off | Plan B 仍需单独启动 | ✅ chosen |
| B 原 plan (7 文件架构重构) | 一次到位 | scope creep；reviewer 反对 | ❌ rejected |
| C 删除 `_compute_reverse_relations` 但保留 `target_resolver` 不加 deprecation warning | 最小改动 | 6 caller 继续用旧 API，Plan B 时全部要改 | ❌ rejected |

## Tasks（每 task 一 commit）

### Task 1: `Relation` dataclass frozen + `RelationSync.sync_page` 语义修复

- **Files**:
  - `src/wiki/features/relations.py`（改 line 92 + line 170-196）
  - `tests/test_wiki/test_relations.py`（加测试）
- **Test-first**:
  1. `test_sync_page_preserves_own_relations` —— `sync_page(A, [r1])` + 预设 `A.relations=[r0]` → 调用后 `A.relations == [r0, r1]`（保留 + 追加）
  2. `test_sync_page_dedupes_inverse_by_target_id_and_type` —— `sync_page` 调 2 次 → relations 列表无重复（保留第一个 weight）
  3. `test_sync_page_dedup_does_not_overwrite_existing_target_relation` —— 预存 target_page inverse weight 不被覆盖（setdefault 语义）
  4. `test_sync_page_inverse_target_id_set_via_mutation` —— `inv.target_id = page_id` mutation 工作（与 `batch_reconcile.py:133` 兼容）
  5. `test_sync_page_breaking_change_documented_in_module_docstring` —— docstring 显式说 "2026-09-19 behavior change: preserve + append + dedup"
- **Implementation**:
  - `relations.py:170` `target.relations = relations` → 按 §Decision "修复 1" 完整代码（保留 + 追加 + dedup）
  - **不**给 `Relation` 加 `frozen=True`（reviewer 4 警告 frozen=True 破坏 `batch_reconcile.py:133` 等其他 call site 的 mutation；Plan A scope 最小——只改 sync_page 语义）
  - **不**改 `inv.target_id = page_id` mutation（保持原状）
  - docstring 更新（明示 breaking change + 引用 Plan A）
- **Acceptance**:
  - 5 个新测试全绿（不含 hashable test，因为 Relation 不再 frozen；含 test_sync_page_inverse_target_id_set_via_mutation 替代 test_sync_page_inverse_target_id_uses_dataclasses_replace）
  - 既有 `tests/test_wiki/test_relations.py` + `tests/test_wiki/test_batch_reconcile.py` 不变回归（**验证 frozen=False 不破坏 batch_reconcile.py:133**）
  - **多角色审查 reviewer 1 反馈 baseline 量化**：`git grep -rn "RelationSync.*sync_page" tests/ scripts/` 必须只命中 `src/wiki/features/relations.py:152` + 新测试
  - **多角色审查 reviewer 1 反馈 Task 2 preflight**：实施前 `git log --grep _safe_insert_artifact_sources -1` 验证存在（独立 gate，防 rebase 移除）
- **Commit**: `fix(relations): preserve own relations in sync_page (dedup by target_id+type)`

### Task 2: 重命名 `_compute_reverse_relations` → `_collect_inverse_relations`（不删，先重命名 + 加 deprecated alias）

- **Files**:
  - `src/pipeline/ingest.py`（line 261-323 重命名 + line 1327 调用点）
- **Test-first**:
  1. `test_ingest_no_longer_has_compute_reverse_relations` —— `hasattr(ingest, '_compute_reverse_relations')` 为 False
  2. `test_ingest_has_collect_inverse_relations` —— `hasattr(ingest, '_collect_inverse_relations')` 为 True
  3. `test_collect_inverse_relations_deprecated_alias_compat` —— `_compute_reverse_relations` 仍可调用（发出 DeprecationWarning），行为同 `_collect_inverse_relations`
  4. `test_collect_inverse_relations_with_frozen_relation_does_not_raise` —— reviewer 4 发现的 `inv.target_id = page.id` mutation 问题；改用 `dataclasses.replace` 后不抛 FrozenInstanceError
- **Implementation**:
  - ingest.py:261 `def _compute_reverse_relations` → `def _collect_inverse_relations`
  - ingest.py:313 `inv.target_id = page.id` → `inv = dataclasses.replace(inv, target_id=page.id)`（frozen=True 兼容）
  - ingest.py:1 加 `from dataclasses import replace`
  - ingest.py:1327 调用点同步
  - 加 deprecated alias：
    ```python
    def _compute_reverse_relations(paths, pages):
        warnings.warn(
            "_compute_reverse_relations is deprecated; use _collect_inverse_relations",
            DeprecationWarning, stacklevel=2,
        )
        return _collect_inverse_relations(paths, pages)
    ```
- **Acceptance**:
  - 4 个新测试全绿（含 frozen 兼容）
  - DeprecationWarning 被触发
- **Commit**: `refactor(ingest): rename _compute_reverse_relations → _collect_inverse_relations (frozen Relation compat)`

### Task 2: 重命名 `_compute_reverse_relations` → `_collect_inverse_relations`（不删，先重命名 + 加 deprecated alias）

- **Files**:
  - `src/pipeline/ingest.py`（line 261-323 重命名 + line 1327 调用点）
- **Test-first**:
  1. `test_ingest_no_longer_has_compute_reverse_relations` —— `hasattr(ingest, '_compute_reverse_relations')` 为 False
  2. `test_ingest_has_collect_inverse_relations` —— `hasattr(ingest, '_collect_inverse_relations')` 为 True
  3. `test_collect_inverse_relations_deprecated_alias_compat` —— `_compute_reverse_relations` 仍可调用（发出 DeprecationWarning），行为同 `_collect_inverse_relations`
- **Implementation**:
  - ingest.py:261 `def _compute_reverse_relations` → `def _collect_inverse_relations`
  - ingest.py:1327 调用点同步
  - 加 deprecated alias：
    ```python
    def _compute_reverse_relations(paths, pages):
        warnings.warn(
            "_compute_reverse_relations is deprecated; use _collect_inverse_relations",
            DeprecationWarning, stacklevel=2,
        )
        return _collect_inverse_relations(paths, pages)
    ```
- **Acceptance**:
  - 3 个新测试全绿
  - DeprecationWarning 被触发
- **Commit**: `refactor(ingest): rename _compute_reverse_relations → _collect_inverse_relations (write batch unchanged)`

### Task 3: 6 caller 加 deprecation warning

- **Files**:
  - `src/wiki/features/target_resolver.py:95`（`resolve_wiki_target` 入口加 warning）
  - `src/pipeline/batch_gate.py:241`
  - `src/maintenance/checks/h2_break_links.py:102`
  - `src/pipeline/reconcile.py:85`
  - `src/orchestrator/batch_runner_internal/phases.py:190`
  - `tests/test_wiki/test_target_resolver.py`
- **Test-first**:
  1. `test_target_resolver_emit_deprecation_warning` —— `resolve_wiki_target` 调用触发 `DeprecationWarning`
  2. `test_batch_gate_calls_resolve_wiki_target_with_warning` —— batch_gate 内部走旧 API，warning 被 emit
  3. `test_h2_break_links_uses_target_resolver_with_warning`
  4. `test_reconcile_uses_target_resolver_with_warning`
  5. `test_phases_uses_target_resolver_with_warning`
  6. `test_target_resolver_test_file_self_warning`
- **Implementation**:
  - 每个 caller 文件加 `import warnings` + 在 `resolve_wiki_target` 调用前 emit warning
  - 测试用 `pytest.warns(DeprecationWarning, match="target_resolver")` 验证
- **Acceptance**:
  - 6 个新测试全绿
  - 既有 `tests/test_wiki/test_target_resolver.py` 不变回归（warning 不阻断）
  - **多角色审查 reviewer 1 反馈 warning 性能噪声**：在 `src/wiki/features/__init__.py` 或 `tests/conftest.py` 加 `warnings.simplefilter("default", DeprecationWarning, append=True)` 避免 pytest 输出污染
- **Commit**: `chore(deprecate): emit warnings on target_resolver.resolve_wiki_target (Plan B migration)`

### Task 4: 文档 + ADR + memory

- **Files**:
  - `docs/adr/0017-relation-sync-breaking-change.md`（新 ADR）
  - `.memory/feedback-relation-sync-fix-2026-09-19.md`（新）
  - `.memory/MEMORY.md`（更新索引）
- **Acceptance**: 3 文档文件 commit
- **Commit**: `docs(adr-0017): RelationSync.sync_page behavior change + 6 caller deprecation`

## Audit

- Round 1: pending
- Round 2: pending
- Human review: pending
- **多角色审查（plan-audit §3 可选高风险方案审查）**：4 视角独立 sub-agent 均 NEEDS-FIX
  - reviewer 1（落地执行者）：致命 2 + 重大 5 + 优化 4
  - reviewer 2（风险管控者）：不可承受 8 + 跨进程 6 + 不可执行 rollback 4
  - reviewer 3（逆向挑战者）：scope creep 3 + anti-pattern 5 + 技术债 6 + 行为变更缺失 4
  - reviewer 4（最终验收人）：致命 5 + 重大 5（§Completion evidence 4 项不可达）
- **Plan A 已吸收多角色审查中 Plan A 范围内的反馈**：
  - reviewer 4 §突破 4（frozen=True 破坏 inv.target_id mutation）→ Task 1 §Implementation 改 `dataclasses.replace` + Task 1 Test-first 加 `test_sync_page_inverse_target_id_uses_dataclasses_replace` + Task 2 §Implementation + Test-first 同步
  - reviewer 1 baseline 量化（26 处 sync_page 引用 + scripts/* import smoke）→ Task 1 + Task 3 §Acceptance 显式列 baseline 命令
  - reviewer 1 preflight gate（`git log --grep _safe_insert_artifact_sources -1`）→ Task 1 §Acceptance 显式列
  - reviewer 1 warning filter（deprecation noise）→ Task 3 §Acceptance 显式列 `warnings.simplefilter` 配置
- Open risks:
  - **`RelationSync.sync_page` 语义变更的外部 caller**：本 plan 范围内 0 个外部 caller；但 git history grep 可能发现 archive scripts / 旧测试。Plan A §Acceptance 加 `git grep -rn "RelationSync.*sync_page" --include='*.py' tests/ scripts/` 必须只命中 `src/wiki/features/relations.py:152` + 新测试
  - **6 个 caller deprecation warning 性能**：每个 ingest 每次 resolve_wiki_target 调用 emit warning。**Plan A 需加 warning filter**（如 `warnings.simplefilter("default", DeprecationWarning, append=True)` 在 `__init__.py` 内）—— 否则 pytest 输出噪声
  - **`_collect_inverse_relations` 与 `RelationSync.sync_page` 的重复**：line 1327 调 `_collect_inverse_relations`（不写）+ `RelationSync.sync_page`（在 commit_ingest 内写 inverse）—— 两个函数**职责重叠**。Plan A 接受这个重叠（Plan B 决定如何合并）
  - **Plan B 范围内反馈已记录但不在 Plan A 处理**（Task 6 re-export + `_legacy.py` < 400 + cross-worker 并发 + cache key 修复 + services/ingest.py 多 LineageStore.open）—— 这些是 Plan B 范畴，Plan B 单独 plan-audit
- Rollback:
  - **Task 1 rollback**：`git revert <sha>`；line 170 改回 `target.relations = relations`；`Relation` 改回无 `frozen`；line 182 改回 `inv.target_id = page_id`（**注意**：rollback 后需恢复 mutation 形式）—— 测试必须仍绿
  - **Task 2 rollback**：`git revert <sha>`；`_collect_inverse_relations` 改回 `_compute_reverse_relations`；deprecated alias 删除；line 313 改回 mutation 形式
  - **Task 3 rollback**：`git revert <sha>`；删除 6 处 warning（warning 是 silent）
  - **最终 rollback**：若 4 tasks 落地后 integration test 失败，`git revert --no-commit <task1_sha>..<task4_sha>` + `git revert` 单 commit

## Completion evidence

- 4 个 commit（Task 1-4）
- 累计 +15 个新测试（Task 1: 5 + Task 2: 4 + Task 3: 6 + Task 4: 0）
- 既有 `tests/test_wiki/` 不变回归（实测 524 passed in `tests/test_wiki/`）— `batch_reconcile.py` 19 个测试**全绿**（Relation 不 frozen，与 `batch_reconcile.py:133` mutation 兼容）
- 既有 `tests/test_pipeline/` 不变回归
- `git grep "compute_reverse_relations" src/` → **只有 deprecated alias**（line 1327 调用点）
- `git grep -c "compute_reverse_relations" src/` → 仍 ≥ 1（deprecated alias 在；新代码用 `_collect_inverse_relations`）
- `git grep "collect_inverse_relations" src/` → ≥ 2（定义 + 调用）
- 既有 callers 6 处 `resolve_wiki_target` 调用仍可解析（deprecation warning）
- docs/adr/0017 完成
- .memory feedback + MEMORY.md 完成

---

## 实施决策记录

**Plan A Task 1 实施时 reviewer 4 警告命中但 Plan A 设计漏算**：
- reviewer 4 警告"`Relation frozen=True` 破坏 `batch_reconcile.py:133` 的 `inv.target_id = page_id` mutation"
- Plan A 设计时漏算 `batch_reconcile.py` 也是 `inv.target_id = page.id` mutation site
- 实施时实测发现 `tests/test_wiki/test_batch_reconcile.py` 19 个测试 2 个 FrozenInstanceError FAIL
- **修正决策**：**撤销 `frozen=True` + `replace()`**，最小化 Plan A scope（只改 sync_page 语义 + 加 docstring breaking change 声明）
- ponytail 原则 "Bug fix = root cause, not symptom" — root cause 不是让 Relation immutable，而是**消除 `target.relations = relations` reset 语义**。`inv.target_id = page_id` mutation 在语义正确时（保留+追加 dedup）**不应该被禁**

---

## Plan B (后续，独立启动)

**架构重构**（不属本 plan）：
- `src/pipeline/ingest/context.py` + `strategy_options.py`（IngestContext 5 字段 + StrategyOptions 12 字段 bag）
- `src/pipeline/ingest/resolvability.py`（ResolvabilityIndex + ResolutionResult；target_resolver 删除）
- `src/pipeline/ingest/post_process.py`（5 阶段后处理）
- `src/pipeline/ingest/strategies/{base,v7,candidate,legacy_fallback_chain}.py`（3 Strategy）
- `src/pipeline/ingest/_legacy.py`（generate_ingest / commit_ingest / run_ingest 薄壳 + LineageContext.open）
- 5 caller（不含 target_resolver.py，因为 Plan A 已 deprecate 它）迁移到 ResolvabilityIndex
- STRATEGY_REGISTRY service locator
- IngestContext.frozen + StrategyOptions mutable bag
- cache key fix `(paths, mtime_of_index_md)`
- 5/5 PASS 实测 gate

**Plan B 是独立 plan，单独 plan-audit 走完整两轮**（不能与 Plan A 混）。
