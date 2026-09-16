# Plan: Task 49 — Stage 7 fault injection 完整覆盖（6 crash points）

**Branch:** `codex/book-series-target`
**Status:** draft (master plan §5 第四批)
**Parent:** `docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan.md` §5 (Task 49)

## 0. 上下文

Task 32 落地 1 个 Stage 7 crash recovery 测试（`test_e2e_crash_during_publish_recovers_via_manifest`）。
但 `CommitPhase` 9 态机（Task 19）有 6 个明确 crash point，每个 phase transition 都可能崩。
**Task 49 目标**：补全 6 个 crash point 的故障注入测试，覆盖每个 phase transition。

## 1. Goal / Non-Goal

### 1.1 用户可见成果

`tests/test_integration/test_v7_e2e_remediation.py` 追加 5 个新测试，
覆盖 6 个 crash points（PREPARED/PUBLISHING/INDEXING/CHECKPOINTING/FINALIZING + queue_projection）：

1. `test_e2e_crash_before_publish_manifest_prepared` — crash after PREPARED
2. `test_e2e_crash_during_publish_recovers_via_manifest`（已存在，Task 32）
3. `test_e2e_crash_during_indexing_recovers` — crash mid-INDEXING
4. `test_e2e_crash_during_checkpointing_recovers` — crash mid-CHECKPOINTING
5. `test_e2e_crash_before_finalizing_recovers` — crash between checkpoint write and COMMIT
6. `test_e2e_durable_failure_io_failure_pending_log_written` — durable_failure.jsonl 写失败 → queue_projection_pending 兜底

### 1.2 Non-Goal

- **不**改 WikiWriter / commit_manifest 实现
- **不**改 page 内容
- **不**做真实磁盘故障注入（用 monkeypatch 替代 IO 失败）

## 2. Files

- `tests/test_integration/test_v7_e2e_remediation.py`（追加测试）
- **无新源码**

## 3. Tests

每个测试 monkeypatch `WikiWriter._atomic_write` 在指定 phase 抛 OSError，
然后调 `reconcile_unfinished_commits()`，断言恢复正确。

### 测试 1 — PREPARED 阶段崩

```python
def test_e2e_crash_before_publish_manifest_prepared(tmp_path, monkeypatch):
    """commit_and_index 在 PREPARED 阶段崩（write manifest 成功前）。
    reconcile_unfinished_commits → manifest 仍 PREPARED，page 未写 → 整体需要重跑。
    """
```

### 测试 3 — INDEXING 阶段崩

```python
def test_e2e_crash_during_indexing_recovers(tmp_path, monkeypatch):
    """page 已写，index.md append 期间崩。
    reconcile → page 已存在 + hash 匹配 → COMMITTED。
    """
```

### 测试 4 — CHECKPOINTING 阶段崩

```python
def test_e2e_crash_during_checkpointing_recovers(tmp_path, monkeypatch):
    """page 已写 + index 已 append，checkpoint.json 写期间崩。
    reconcile → page 在 disk + hash 匹配 → COMMITTED，retry checkpoint 写。
    """
```

### 测试 5 — FINALIZING 阶段崩

```python
def test_e2e_crash_before_finalizing_recovers(tmp_path, monkeypatch):
    """checkpoint 写完，manifest.phase=COMMITTED 标记前崩。
    reconcile → manifest.phase → COMMITTED（幂等）。"""
```

### 测试 6 — durable_failure IO 失败

```python
def test_e2e_durable_failure_io_failure_pending_log_written(tmp_path, monkeypatch):
    """durable_failure.jsonl 写失败 → queue_projection_pending.jsonl 兜底。
    """
```

## 4. Implementation

复用 Task 32 现有 `ScriptedLLM` + monkeypatch 模式。**无新源码**——纯测试增量。

## 5. Acceptance

- ✅ 5 个新测试 + 已有 1 个 crash 测试 = 6 个 crash points 全覆盖
- ✅ 现有 8 个 E2E 测试 0 回归
- ✅ 每个 crash point 都有显式 invariant 断言（page 文件存在 / durable_failure 写入 / manifest phase 正确）