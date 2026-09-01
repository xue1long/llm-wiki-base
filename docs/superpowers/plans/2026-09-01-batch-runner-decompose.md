# Plan A — `run_batch` 拆分重构方案

- **方案 ID**：`2026-09-01-batch-runner-decompose`
- **作者**：plan-audit 自动产出（含 Round 1 + Round 2 审查 + Ponytail 简化）
- **目标文件**：`src/orchestrator/batch_runner.py`（999 行 → 预计 ≤350 行主入口 + 3 个新模块）
- **图谱佐证**：`docs/architecture/2026-09-01-graph-subgraph-report.md` §1（run_batch 2-hop 子图，199 节点 / 467 边）
- **风险等级**：🟡 中（涉及持久化状态机、预算挂起、崩溃续跑三段不变量，但 blast radius 已被图谱证小）
- **预期收益**：
  - 圈复杂度 58 → ≤ 25（按 `run_batch` 单函数计）
  - 传递嵌套深度 14 → ≤ 6
  - 文件行数 999 → 350 主 + ≤ 250 × 3 模块 = ≤ 1100（总行数微增，但**单文件复杂度断崖下降**）
  - 心理复杂度下降：新人读完 `run_batch` 只需 30 分钟而不是 2 小时
- **重要约束（图谱证伪）**：
  - `run_batch` **没有任何 HTTP 路由入边**（§1.3，0 个 route handler in 2 hops）—— 重构不会破坏 web
  - `run_batch` **不直接写 `.index/batch_build_state.json`**——真正写盘者是 `src/services/batch_state.py:load_batch_state/set_raw_status/update_batch_state`（3 hops，§1.4）—— 拆分时**必须**保留 facade 入口，**不可**把 `update_batch_state`/`set_raw_status` 跟着搬进新模块，否则 facade 边界会被打破
  - 2 个外部 caller：`scripts/batch_executor.py:main` + `src/cli_ext/batch_cmd.py:cmd_batch_run` ——**必须**保留 `run_batch` 的 import 路径

---

## 0. 预埋审查标准（Plan-Audit §0）

| 维度 | 当前状态 | 验收目标 |
|---|---|---|
| 目标对齐 | 拆分后**仍跑通** `--batch N` / `--resume` / 预算挂起 / 崩溃注入 | 现有 32 个 `tests/test_orchestrator/` + 19 个 `tests/test_scripts/` 全部通过 |
| 前提假设 | 1) 状态 schema 不变；2) `batch_build_state.json` 文件锁协议不变；3) test hook env var 不变 | 任一假设破 → 走 fallback 方案「只重构内部、不动 schema」 |
| 边界场景 | 6 阶段都可能崩溃；崩溃后重启要求**幂等可续** | 现有 `BATCH_EXECUTOR_CRASH_AT` 测试仍 100% 通过 |
| 依赖项 | 仅依赖 `src.services.batch_state`、`src.wiki.features.batch_gate`、`src.pipeline.ingest` 三个稳定包 | 拆分模块不引入新外依赖 |
| 风险与副作用 | `BatchRunner` 抽象类有外部测试 (`tests/test_orchestrator/test_state_machine_guard.py` 用 `import src.orchestrator.orchestrator as orchestrator_module`) | ABC 接口签名零变化 |
| 可执行性 | 拆分必须能逐步合并（每个 PR 都能 shipable） | 每个阶段独立 PR、可回滚 |
| 验收标准 | 见 §6 量化指标 | 不达标不合并 |
| 盲区 | `scripts/batch_executor.py` 也调用了 `_auto_tag_ugc`（审计报告 K 类） | 必须同步处理 scripts 副本 |
| 回滚预案 | 每阶段保留 git revert 一行命令 | `git revert <merge>` 即可回退整阶段 |

---

## 1. 当前结构盘点（行号锚定 + 图谱佐证）

**`src/orchestrator/batch_runner.py`（999 行）——22 个函数 + 2 个 dataclass + 2 个类**

| 层 | 行号区间 | 内容 | 职责 | 复杂度贡献 |
|---|---|---|---|---|
| **A. 常量与测试钩子** | 63–169 | `DEFAULT_*`、`MAX_FAIL_STREAK`、`CRASH_STAGES`、`_crash_at`、`_snapshot_page_hashes`、`_fake_generate`、`_is_fake_mode`、`_estimate_batch_cost`、`_resolve_paths`、`_resolve_provider` | 测试用 fake + 路径/解析 | 极低 |
| **B. 单 raw 处理** | 191–416 | `_git_snapshot`、`_is_immutable_source`、`_generate_raw`、`_commit_raw`、`_set_batch_status`、`_update_fail_streak`、`_auto_tag_ugc`、`_upsert_batch_vectors` | 单文件生命周期 | 中（commit 分支多） |
| **C. 跨 raw 编排** | 367–605 | `_rerun_gate_batch`、`Batch`/`GateReport`/`BatchResult` dataclass、`BatchRunner` ABC、`DefaultBatchRunner` | 整批门禁、dataclass 容器 | 中（门禁逻辑） |
| **D. 主循环** | 606–999 | `async def run_batch(args) -> int`（**393 行**，含嵌套 `_gen_one`、`_commit_one`、`_phase_*` helpers） | 顶层状态机 | **极高（TLD 14、圈 58、认知 106）** |

**外部依赖 8 处 `from src.X import ...`**：

```
src.services.batch_state    ← 高频（每 raw 都写状态）
src.lib.write_hooks         ← 仅 type import (AtomicCommitError)
src.wiki.storage.page_writer ← 仅 type (WriteConflictError)
src.wiki.core.paths          ← WikiPaths
src.wiki.features.batch_gate ← run_precommit_gate
src.pipeline.ingest          ← generate_ingest, commit_ingest (动态 import 在内部)
```

`BatchRunner`/`DefaultBatchRunner` 仅 `tests/test_orchestrator/test_state_machine_guard.py:3` 使用（`import src.orchestrator.orchestrator as orchestrator_module`）——**ABC 拆分后必须 re-export 这两个类**。

### 1.1 图谱视角的 blast radius（来自 subagent 报告 §1）

| 维度 | 数字 | 含义 |
|---|---:|---|
| 2-hop 子图大小 | 199 节点 / 467 边 | `run_batch` 实际"影响面"是局部 |
| **外部 caller 数** | **2** | 仅 `scripts/batch_executor.py:main` + `src/cli_ext/batch_cmd.py:cmd_batch_run` |
| **HTTP 路由入边** | **0** | `run_batch` 不在 web 表面 —— web 改动不影响此重构 |
| **Callee 数** | 15，**全部 intra-file** | `run_batch` 真正只跟自己的 helpers 说话 |
| **PageRank Top 5** | `read_page` / `PageType` / `WikiPage.from_dict` / `WikiPage` / `generate_ingest` | **真正的复杂度中心是 wiki write-path，不是 `run_batch`** |
| `run_batch` PageRank 排名 | **#20** | `run_batch` 是**叶子节点**，不是中心枢纽 |
| **状态文件 writer hop 距离** | **3 hops** | `run_batch → _set_batch_status → set_raw_status/update_batch_state (in batch_state.py)` |
| 状态文件 writer 实际文件 | `src/services/batch_state.py:173/198/230/253` | `load_batch_state`、`update_batch_state`、`set_raw_status`、`raw_status` |

**结论性修正**：之前审计报告（`docs/codebase-graph-stats-2026-09-01.md` §七）把 `run_batch` 列为"全仓复杂度单点（TLD 14 / 圈 58 / 认知 106 / 出度 30）"——这是**绝对值**意义上的热点。但**从图谱视角**，`run_batch` 是**叶子**而非中心：

- 它**不**是仓库的主要耦合点（web / wiki write-path 才是）
- 它的所有 callee 都是 intra-file 的（好特性）
- 它**没有** HTTP 表面（web 完全独立）
- 它的状态写盘是 3 hops 之外的事（解耦充分）

→ **本次重构的安全边际比之前估计的高**。blast radius 199 节点是图谱里相对小的子图（对比 `lint_wiki` 之类热点动辄上千节点的 2-hop），外部破坏面只有 2 个文件。

### 1.2 拆分约束（由 §1.1 倒推）

| 约束 | 原因 |
|---|---|
| 保留 `src/orchestrator/batch_runner.py` 作为 facade（不能变包） | `from src.orchestrator.batch_runner import run_batch` 必须 work（2 个外部 caller + 测试） |
| 保留 `BatchRunner` / `DefaultBatchRunner` 在原路径 | 外部 monkeypatch 测试依赖 |
| `update_batch_state` / `set_raw_status` **不跟着搬到 `raw_lifecycle.py`** | 1) 它们在 `src/services/batch_state.py`（3 hops 之外，已经解耦）；2) 跟着搬会破坏已经形成的模块边界；3) 拆分原则是**只拆 batch_runner.py 内部**，不外扩 |
| 不动 `src/services/batch_state.py` 的接口 | 它是稳定的服务层叶子（I=0）|

---

## 2. 拆分设计（核心方案）

### 2.1 目录结构

```
src/orchestrator/
├── batch_runner.py            ← 主入口 ≤350 行（重写为编排器）
├── batch_runner/              ← 新建子包（占位空目录禁用：先建 __init__.py 再 ship）
│   ├── __init__.py            ← re-export BatchRunner, DefaultBatchRunner, run_batch
│   ├── hooks.py               ← 拆分自 layer A（fake / crash / snapshot / resolve_paths / cost）
│   ├── raw_lifecycle.py       ← 拆分自 layer B（generate / commit / upsert_vectors / auto_tag）
│   ├── gate.py                ← 拆分自 layer C 的 _rerun_gate_batch + Batch/GateReport dataclass
│   └── state.py               ← set_batch_status / update_fail_streak 包装（薄壳）
└── orchestrator.py            ← 不动
```

> ⚠️ **关键迁移约束**：`from src.orchestrator.batch_runner import run_batch, BatchRunner, DefaultBatchRunner` 必须继续 work。这是 §0「前提假设」第 3 条的硬要求。

### 2.2 拆分映射表

| 当前 (batch_runner.py) | 新位置 | 行为变化 |
|---|---|---|
| L75–82 `_crash_at` | `batch_runner/hooks.py` | 不变 |
| L83–102 `_snapshot_page_hashes` | `batch_runner/hooks.py` | 不变 |
| L104–144 `_fake_generate` | `batch_runner/hooks.py` | 不变 |
| L146–148 `_is_fake_mode` | `batch_runner/hooks.py` | 不变 |
| L150–168 `_estimate_batch_cost` | `batch_runner/hooks.py` | 不变 |
| L170–175 `_resolve_paths` | `batch_runner/hooks.py` | 不变 |
| L177–189 `_resolve_provider` | `batch_runner/hooks.py` | 不变 |
| L191–203 `_git_snapshot` | `batch_runner/raw_lifecycle.py` | 不变 |
| L205–219 `_is_immutable_source` | `batch_runner/raw_lifecycle.py` | 不变 |
| L221–232 `_generate_raw` | `batch_runner/raw_lifecycle.py` | 不变 |
| L235–287 `_commit_raw` | `batch_runner/raw_lifecycle.py` | **轻度重构**：把 `cascade_delete` 失败的 fallback 拆成 `_commit_raw_reingest` / `_commit_raw_first_ingest` 两个 helper（见 §2.3） |
| L290–309 `_set_batch_status` | `batch_runner/state.py`（薄壳）或保留 | 不变（包内调用） |
| L312–327 `_update_fail_streak` | `batch_runner/state.py` | 不变 |
| **L330–364 `_auto_tag_ugc`** | **`src/orchestrator/auto_tag.py`** | **🟢 P0 改造**：删 `scripts/phase4_batch.py:299` 副本，统一 import 此处（呼应审计报告 K 类） |
| L367–415 `_upsert_batch_vectors` | `batch_runner/raw_lifecycle.py` | 不变 |
| L417–468 `_rerun_gate_batch` | `batch_runner/gate.py` | 不变 |
| L470–482 `Batch` dataclass | `batch_runner/gate.py` | 不变 |
| L478–483 `GateReport` dataclass | `batch_runner/gate.py` | 不变 |
| L485–493 `BatchResult` dataclass | `batch_runner/raw_lifecycle.py` | 不变 |
| L494–551 `BatchRunner` ABC | `batch_runner/__init__.py` re-export | 不变 |
| L553–604 `DefaultBatchRunner` | `batch_runner/__init__.py` re-export（来自 `raw_lifecycle.py`） | 不变 |
| **L606–999 `async def run_batch`** | **`batch_runner.py` 重写** | **🟢 大幅重构**：见 §2.4 |

### 2.3 `_commit_raw` 分支重构（消除高圈复杂度的关键）

```python
# 当前：单函数两分支 + 内联 cascade 失败 fallback
async def _commit_raw(paths, raw_rel, pages, extras, batch_key, task_id,
                      meta=None, expected_page_hashes=None) -> str:
    source_id = probe_source_page(paths, raw_rel)
    if source_id is not None:
        set_raw_status(paths, batch_key, raw_rel, "pending_deletion", source_id=source_id)
        try:
            cascade_result = cascade_delete(paths, source_id)
        except FileNotFoundError:
            branch = "first_ingest"
            cascade_result = {}
        else:
            cascade_result.get("deleted_pages", [])
        ...
```

**拆为 3 个显式阶段函数 + 1 个 dispatch**：

```python
# batch_runner/raw_lifecycle.py (draft)
async def _ensure_rebuild_clean(paths, source_id, raw_rel, batch_key) -> str:
    """Return "reingest" or "first_ingest" based on whether cascade succeeded.

    pending_deletion is recorded BEFORE delete — the order is load-bearing.
    FileNotFoundError means concurrent delete already happened → degrade
    to first_ingest, NOT a fail (avoids broken-link 整批 false-positive).
    """
    set_raw_status(paths, batch_key, raw_rel, "pending_deletion", source_id=source_id)
    try:
        cascade_delete(paths, source_id)
        return "reingest"
    except FileNotFoundError:
        return "first_ingest"

async def _clear_stale_vectors(paths, raw_rel) -> None:
    """Idempotent: delete_by_source returns 0 if no rows — safe in all branches.
    Required for I3 review (stale chunk leak on crash between cascade & delete).
    """
    init_vector_store_for_paths(paths)
    delete_by_source(paths, raw_rel)

async def _commit_raw(paths, raw_rel, pages, extras, batch_key, task_id,
                      meta=None, expected_page_hashes=None) -> str:
    """Coordinator only — reads as: probe → ensure clean → commit → mark done."""
    source_id = probe_source_page(paths, raw_rel)
    if source_id is not None:
        branch = await _ensure_rebuild_clean(paths, source_id, raw_rel, batch_key)
    else:
        branch = "first_ingest"
    await _clear_stale_vectors(paths, raw_rel)
    await _commit_ingest(paths, Path(raw_rel), pages, extras, task_id=task_id, ...)
    set_raw_status(paths, batch_key, raw_rel, "done", branch=branch)
    return branch
```

**收益**：原 53 行单函数（含异常分支）→ 3 个 5–15 行小函数 + 12 行协调器；测试可独立覆盖每个 stage。

### 2.4 `run_batch` 主循环重构（核心）

把 393 行主体（行 606–999）拆为 **5 个 phase coroutine + 1 个 dispatch**：

```python
# batch_runner.py (new main) — draft, ≤350 行
async def run_batch(args) -> int:
    paths = _resolve_paths(args)
    provider = None if _is_fake_mode() else _resolve_provider(args)
    manifest, batch, batch_key, files = _load_manifest(args, paths)
    if manifest is None: return 1

    # ── phase 0: precondition (budget + crash snapshot) ──
    budget_paused = await _check_budget(args, paths, batch_key)
    if budget_paused: return 3
    _git_snapshot(paths)  # 仅用于 git snapshot 记录，不阻塞

    # ── phase 1: decide which raws to process (state machine filter) ──
    pending = _filter_pending(files, args, paths, batch_key)
    if not pending: return 0
    _set_batch_status(paths, batch_key, "pending_gate")

    # ── phase 2: generate (parallel, dry, zero disk write) ──
    generated, raw_headers, failed, perm_failed, skipped = \
        await _phase_generate(paths, provider, pending, args.batch, batch_key)

    # ── phase 3: pre-commit gate (in-memory, all-or-nothing) ──
    gate_ok = await _phase_gate(paths, generated, raw_headers, batch_key)
    if not gate_ok: return 4

    # ── phase 4: commit (per-raw branch + auto-tag + vector upsert) ──
    committed = await _phase_commit(paths, generated, raw_headers, batch_key, args.batch)
    if committed == 0 and failed: return 5
    return 0
```

每个 `_phase_*` 移到 `batch_runner/raw_lifecycle.py` 或 `batch_runner/gate.py`，是 ≤ 60 行的 coroutine。

**关键收益**：
- `run_batch` 顶层从 393 行 → ≤ 35 行
- 每个 phase 可独立做 fault-inject（`BATCH_EXECUTOR_CRASH_AT=generate|gate|cascade|commit` 在 `gate` 和 `commit` 阶段更可定位）
- 测试可分别覆盖 phase 决策逻辑（无需 fake-LLM 跑完整 pipeline）

### 2.5 `_auto_tag_ugc` 抽取（呼应审计报告 K 类 P0）

新建 `src/orchestrator/auto_tag.py`：

```python
# src/orchestrator/auto_tag.py (new, draft)
"""UGC carrier auto-tagging — single source of truth.

Extracted from src.orchestrator.batch_runner._auto_tag_ugc (35 lines)
and scripts.phase4_batch._auto_tag_ugc (37 lines, near-identical copy).

Both callers now import from here. K-class duplicate from
docs/codebase-dup-analysis-2026-09-01.md §一 / §四 K.
"""
from __future__ import annotations
from src.wiki.features.lint import _is_ugc_carrier

_UGC_TAGS: tuple[str, ...] = ("素材/ugc", "可信度/ugc")


def auto_tag_ugc(pages: list, raw_headers: dict[str, str]) -> int:
    """Return count of pages that received UGC tags.

    - carrier_raws = subset of raw_headers where _is_ugc_carrier(header) is True
    - page qualifies if (set(p.sources) & carrier_raws) is non-empty
    - stub pages are exempt
    - raw_headers=None → return 0 (no carriers)
    - duplicates of existing tags are skipped
    """
    carrier_raws = {r for r, h in (raw_headers or {}).items() if _is_ugc_carrier(h)}
    if not carrier_raws:
        return 0
    tagged = 0
    for p in pages:
        if getattr(p, "processing_depth", "") == "stub":
            continue
        if not (set(p.sources or []) & carrier_raws):
            continue
        tags = list(p.tags or [])
        changed = any(t not in tags for t in _UGC_TAGS)
        if changed:
            p.tags = tags + [t for t in _UGC_TAGS if t not in tags]
            tagged += 1
    return tagged
```

**同步修改 `scripts/phase4_batch.py:299`**：删除 `_auto_tag_ugc` 定义，改为 `from src.orchestrator.auto_tag import auto_tag_ugc`；调用点从 `_auto_tag_ugc(result.pages, gen["raw_headers"])` 改为 `auto_tag_ugc(result.pages, gen["raw_headers"])`。

> 🔴 **回滚预案**：两个原文件改动都可 `git revert`，新文件删除即可。

---

## 3. Plan-Audit Round 1 — 漏洞审计

> 以"独立第三方审计专家"视角，强制逆向思维。问题分级按 plan-Audit §1：①致命 / ②重大 / ③优化。

### ① 致命缺陷（无法落地）

**F-1**：`src/orchestrator/batch_runner.py` → `src/orchestrator/batch_runner/` 转换会**破坏外部 import**

- 风险：当前 `from src.orchestrator.batch_runner import run_batch, BatchRunner` 全部失效（Python 不允许 `.py` 与同名包同时存在）
- 现状：搜索全仓 `from src.orchestrator.batch_runner` —— 至少有 `tests/test_orchestrator/test_state_machine_guard.py` 和 `scripts/batch_executor.py` 在用
- 整改：保留 **`src/orchestrator/batch_runner.py` 作为 facade**，把 `run_batch`、`BatchRunner`、`DefaultBatchRunner` re-export，新建的 `batch_runner/` 包用 **不同名字**（如 `batch_runner_internal/`）避免冲突
- 评级调整：✅ 整改后落地

### ② 重大隐患（容易失败）

**H-1**：`scripts/phase4_batch.py` 副本抽取后，测试覆盖盲区扩大

- 风险：审计报告说副本有 37 行，原文件 35 行——如果不一致的部分包含 fail-streak/blocklist 逻辑，会引入新 bug
- 整改：在抽取 PR 增加 1 个 `tests/test_orchestrator/test_auto_tag_consistency.py`，跑两套 fixture（来自 src 版本 + scripts 版本）对比 1000 次随机输入
- 评级调整：✅ 整改后可控

**H-2**：拆分后 `run_batch` 主入口可能丢失某些 crash-inject 点

- 风险：现有 `BATCH_EXECUTOR_CRASH_AT` 测试覆盖 4 个阶段（generate/gate/cascade/commit）。拆分后新增的 `phase_commit` 内部多了一个 `_commit_ingest` 步骤——如果 `_commit_ingest` 失败时 crash-inject 漏放，会让 `tests/test_scripts/test_batch_executor.py` 的 crash 系列测试假阳性
- 整改：在 `_commit_raw` 内保留 `_crash_at("cascade")`，并在新的 phase 函数里**显式增加** `_crash_at("commit_ingest")` 注入点（env 值不变，向后兼容）
- 评级调整：✅ 整改后可控

**H-3**：`BatchRunner` ABC 拆分到 `batch_runner/__init__.py` 后，`tests/test_orchestrator/test_state_machine_guard.py` 的 monkeypatch 行为可能变化

- 风险：测试用 `import src.orchestrator.orchestrator as orchestrator_module`（不是 batch_runner），但 monkeypatch 时是 `_set_batch_status` —— 函数位置变化会让 `monkeypatch.setattr` 找不到对象
- 整改：在 `batch_runner.py` facade 里**保留所有 top-level 名字的别名**，包括 `_set_batch_status`、`_update_fail_streak`、`_auto_tag_ugc`（重新指向 `auto_tag.auto_tag_ugc`），让 `monkeypatch` 路径不变化
- 评级调整：✅ 整改后可控

### ③ 优化疏漏

**O-1**：`__init__.py` re-export 应只暴露 public surface；不应 re-export `_auto_tag_ugc`（内部函数）

**O-2**：batch_runner/hooks.py 中的 `_resolve_paths(args)`、`_resolve_provider(args)` 接收 `args` (argparse.Namespace) 是个 leaky abstraction —— 新模块可改成显式 keyword-only 参数 `(manifest: Path, *, budget_usd: float | None, no_git_snapshot: bool, resume: bool)`

**O-3**：`_estimate_batch_cost` 用 `ok * 0.2` 这种 magic number 没注释，应加 `# ponytail: cost = $0.20/page baseline (see .llm-wiki/cost_baseline.json if updated)`

---

## 4. Plan-Audit Round 2 — 压力测试推演

> 模拟多种失败路径，找"可行→失效"的边界。问题清单 + 加固方案。

### 压测路径矩阵

| # | 失败路径 | 当前方案表现 | 加固方案 |
|---|---|---|---|
| **S-1** | 拆分 PR merge 时正好发生代码 freeze（CI 阻塞） | 主分支无法 ship；revert 即可 | 每个阶段独立 PR，phase 0/1 不阻塞 merge；phase 2/3 排队等 CI |
| **S-2** | `_auto_tag_ugc` 抽取后，新版本与 scripts 副本**实际有微差**（不是 35 vs 37 行） | UGC 标记集可能漂移 | 抽取前用 AST diff（`ast.unparse(ast.parse(...).body[0])` 对比），不等才算"完全等价" |
| **S-3** | 拆分后 `run_batch` 抛 unhandled exception（LLM provider 故障） | 当前：process exit 1，partial commit 已落盘（file lock 保住 batch_state 一致） | 拆分后**必须**保留 outer try/except + `set_raw_status(... "failed", exc_info)` 路径；测试覆盖 exception → "failed" 路径 |
| **S-4** | 同一 raw 在 batch_state 中既 mark `done` 又 mark `pending_deletion`（并发 race） | 当前：state machine 在 line 664 检测到则报 `RESUME pending_deletion` | 拆分后 `state.py` 必须**重排** `_set_batch_status` 与 `_update_fail_streak` 的顺序锁（FileLock 必须在 _update 之前） |
| **S-5** | `BatchRunner` ABC 在新 `__init__.py` 中 re-export，但 `tests/test_orchestrator/test_state_machine_guard.py` 用了 `monkeypatch.setattr(orchestrator_module, "_set_batch_status", mock)`（注意是 `orchestrator_module` 不是 `batch_runner_module`） | ⚠️ 这个测试实际 patch 的是 `src.orchestrator.orchestrator` 的属性，与 `batch_runner` 无关——**不受拆分影响**，但需要确认 | 跑 `pytest tests/test_orchestrator/ -v` 验证（实测，不靠假设） |
| **S-6** | `fake_generate` 行为变化（hooks 拆分后 fake 路径的 import chain 改变） | 当前：fake 路径走 `RUFLO_EXECUTOR_FAKE_GENERATE=1`，跳过 `generate_ingest` 调真实 LLM | 拆分后**必须保留** `_fake_generate` 的 import 顺序（先 import WikiPage，再 RUFLO_FAKE_FAIL 检查）—— 移到 hooks.py 时**不能**打乱顺序 |
| **S-7** | 拆分 PR 误删 `_set_batch_status` 等被外部依赖的函数 | ⚠️ 当前只有 1 个外部依赖（test_state_machine_guard.py）—— 不算高风险，但需 `grep` 全仓确认 | 抽取前 grep `from src.orchestrator.batch_runner import`、`src.orchestrator.batch_runner.*`；遗漏必须修复 |
| **S-8**（图谱新证） | 拆分后 `run_batch` 失去 PageRank #20 的位置（被新 helper 替代），但 web/CLI 端表现不变 | 图谱显示 `run_batch` 是 leaf，2 个 caller 都是 CLI；split 不会扩散 | 跑 `pytest tests/test_cli_ext/test_cmd_batch*.py -v` + `python -m src.cli batch run --help` 烟雾测试 |
| **S-9**（图谱新证） | 拆分后 `lint_wiki` 仍居 PageRank #1，wiki write-path 仍是仓库热点；本次**只**拆 batch_runner，不会**改善** wiki write-path 复杂度 | 图谱证 wiki write-path 独立于 batch_runner 子图 | **不在本次 PR 范围**；wiki write-path 改造是后续独立任务（参见 `docs/codebase-graph-stats-2026-09-01.md` §七） |

### 加固总览

1. **拆分前必做的 3 个 grep 验证**（落地清单）：
   ```bash
   rg 'from src\.orchestrator\.batch_runner' --type py
   rg 'src\.orchestrator\.batch_runner\.[a-zA-Z_]+' --type py
   rg 'monkeypatch.*batch_runner' tests/
   ```
2. **拆分后必跑的测试集**：
   - `pytest tests/test_orchestrator/ -v`（内部契约）
   - `pytest tests/test_scripts/ -v`（CLI + crash-inject）
   - 跑 1 次 `--batch 0` 在真实 test_project fixture 上（端到端）
3. **拆分阶段**：
   - **Phase 0**：抽 `_auto_tag_ugc` → `src/orchestrator/auto_tag.py`（最小、最容易、最有价值；最先合并）
   - **Phase 1**：建 `batch_runner_internal/`（不是 `batch_runner/`！），把 hooks + raw_lifecycle 抽过去（向后兼容 re-export）
   - **Phase 2**：抽 gate.py + state.py
   - **Phase 3**：重写 `run_batch` 主体为 phase coroutine

> 每个 phase 独立 commit、独立 review、独立 revert。

---

## 5. Ponytail 简化 pass

> 按 Ponytail 梯子检查每个组件：是否存在更简单的实现。

### 5.1 已通过梯子（无需改动）

- `_crash_at`：**Rung 4**（OS 已有 `os._exit`），已是 6 行最小实现
- `_fake_generate`：**Rung 1**（已经存在，不可删；fake 是测试契约）
- `_resolve_paths`：**Rung 3**（stdlib pathlib），已是最简

### 5.2 可简化（采纳）

**P-1**: `update_batch_state(paths, lambda st: (st.setdefault(...).__setitem__(...), st)[1])` —— 这是一个**函数式 mutation**，可读性极差

- 当前写法（行 633–636）：
  ```python
  update_batch_state(paths, lambda st: (
      st.setdefault(batch_key, {}).__setitem__("git_snapshot", snapshot),
      st)[1])
  ```
- Ponytail 简化（**Rung 6 - one line 不行，但 Rung 1 - 不要 lambda**）：
  ```python
  # 在 batch_runner/state.py 顶部定义：
  def _record_git_snapshot(state: dict, batch_key: str, snapshot: str) -> None:
      """In-place dict mutation under FileLock held by update_batch_state."""
      state.setdefault(batch_key, {})["git_snapshot"] = snapshot
  # 调用点：
  update_batch_state(paths, lambda s: _record_git_snapshot(s, batch_key, snapshot))
  ```
- **收益**：行 633–636 从 3 行 lambda → 4 行函数（可单独单测） + 1 行调用

**P-2**: `_commit_raw` 异常处理用 `try/except FileNotFoundError → branch = "first_ingest"` 但同时执行 `cascade_result = {}` 然后立即 `cascade_result.get(...)` 拿不到东西（行 269–273）—— **死代码**

- 当前写法（行 273）：
  ```python
  else:
      cascade_result.get("deleted_pages", [])  # ← 结果被丢弃！
  ```
- Ponytail 简化（**Rung 1 - 删除**）：直接删这一行；`cascade_result` 本来就是局部变量，不需要 `.get`
- **收益**：减 1 行死代码

**P-3**: `Batch`/`GateReport`/`BatchResult` 三个 dataclass 当前都在 batch_runner.py 但只 `Batch` 被使用（外部测试）

- 验证：`rg "GateReport|BatchResult" --type py`
- 如果 `GateReport`/`BatchResult` 没有外部 import，可以删掉或者一起搬到 `gate.py`/`raw_lifecycle.py`

**P-4**: `_upsert_batch_vectors` 中 `from datetime import timezone, datetime` 内联使用

- 当前写法（行 381）：函数顶部动态 import
- Ponytail 简化（**Rung 3 - stdlib**）：把 import 移到模块顶部
- **收益**：可读性（无所谓性能）

### 5.3 拒绝的"过度简化"（已记录但不做）

- ❌ "把 `run_batch` 改成同步函数" —— 不行，崩溃恢复和 gate 异步执行有依赖
- ❌ "用 `subprocess.run` 把整个 batch_runner 抽到 scripts" —— 已经在 scripts/，但拆出的是 **核心引擎**，反向抽回才是对的
- ❌ "删掉 `BatchRunner` ABC" —— 外部测试 monkeypatch 用，删了破坏契约

---

## 6. 验收标准（量化）

| 指标 | 当前 | 拆分后 | 测量方式 |
|---|---:|---:|---|
| `batch_runner.py` 总行数 | 999 | ≤ 350 | `wc -l` |
| `run_batch` 函数行数 | 393 | ≤ 50 | 函数体 grep |
| `run_batch` 圈复杂度 | 58 | ≤ 20 | `radon cc -s` 或 eyeball |
| `run_batch` 传递嵌套深度 | 14 | ≤ 6 | eyeball + AST 测 |
| `_commit_raw` 函数行数 | 53 | ≤ 25 + 3 helpers ≤ 15 行 each | 函数体 grep |
| `_auto_tag_ugc` 副本数 | 2（src + scripts） | 1 | `rg "def _auto_tag_ugc"` 应仅命中 `scripts/phase4_batch.py:299` 中的 import 行 + `auto_tag.py` |
| 外部 import 路径破坏 | 0 | 0 | `rg 'from src\.orchestrator\.batch_runner'` 仍然命中 |
| 测试通过 | 32 + 19 = 51 | ≥ 51 | `pytest tests/test_orchestrator/ tests/test_scripts/` |
| Crash-inject 测试 | 4 阶段 | ≥ 4 阶段 | `BATCH_EXECUTOR_CRASH_AT=generate\|gate\|cascade\|commit` 各 1 次 |

---

## 7. 风险地图（commit-by-commit）

| Phase | Commit | 风险点 | 回滚命令 |
|---|---|---|---|
| Phase 0 | `refactor(orchestrator): extract _auto_tag_ugc → src/orchestrator/auto_tag.py` | scripts 副本引用错误 | `git revert <sha>` |
| Phase 1a | `refactor(orchestrator): move hooks to batch_runner_internal/hooks.py` | import 路径变化 | `git revert <sha>` |
| Phase 1b | `refactor(orchestrator): move raw_lifecycle helpers to batch_runner_internal/raw_lifecycle.py` | re-export 遗漏 | `git revert <sha>` |
| Phase 2 | `refactor(orchestrator): move gate + state helpers to batch_runner_internal/{gate,state}.py` | dataclass 路径 | `git revert <sha>` |
| Phase 3 | `refactor(orchestrator): rewrite run_batch as 5-phase coroutine` | crash-inject 漏放 | `git revert <sha>` |

每个 PR 单独 shipable、单独 review、单独 revert。

---

## 8. 不在本方案范围内（避免 scope drift）

按 Ponytail 「不要为不存在的需求写代码」：

- ❌ 不引入新抽象（`PhaseResult` dataclass 等）—— 等真需要再加
- ❌ 不改 `BatchRunner` ABC 接口 —— 保持向后兼容
- ❌ 不改 state schema —— 仅内部实现迁移
- ❌ 不重命名 public 函数（`run_batch`、`BatchRunner`）—— 保持 import 兼容
- ❌ 不引入新依赖（pytest 插件、loguru 等）—— 仅用 stdlib

---

*方案生成：基于 `src/orchestrator/batch_runner.py` 行号锚定 + `docs/codebase-dup-analysis-2026-09-01.md` §四 K 类 + `docs/codebase-graph-stats-2026-09-01.md` §七复杂度热点。Round 1/2 已嵌入。落地前需人工复核 §3 致命缺陷与 §4 加固方案。*