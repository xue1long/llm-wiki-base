# Plan: Task 40 — Stage 7 queue projection repair job

**Branch:** `codex/book-series-target`
**Status:** draft (master plan §5 第二批)
**Parent:** `docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan.md` §5 (Task 40)

## 0. 上下文

Task 21 落地 `durable_failure.jsonl` + `queue_projection_pending.jsonl` 显式分工。
当 `reviews_queue.json` 写入失败时，wiki_writer 把投影任务 append 到 pending log。

**Task 40 目标**：写一个 repair 函数，扫描 pending log，重投影每条到 reviews_queue。
失败仍写回 pending log（避免数据丢失）；成功后从 pending log 删除（truncate + rewrite）。

## 1. Goal / Non-Goal

### 1.1 用户可见成果

1. `repair_queue_projections(root)` 函数读 pending log → 重投影到 reviews_queue
2. 成功条目从 pending log 删除（rewrite without success entries）
3. 失败条目保留在 pending log（不丢知识）

### 1.2 Non-Goal

- **不**改 wiki_writer 的 `_record_queue_projection_pending` 写入逻辑
- **不**改 durable_failure 路径
- **不**做并行 / 后台调度（同步函数，CLI / startup hook 调用）

## 2. Files

- `src/pipeline/v7_extract/wiki_writer.py`（追加 `repair_queue_projections` 类方法或顶层函数）
- `tests/test_pipeline/test_v7_extract_stage7.py`（追加 3 测试）

## 3. Tests

```python
def test_repair_queue_projections_replays_pending(tmp_path):
    """3 条 pending → 全部 re-project 到 reviews_queue → pending 文件清空"""

def test_repair_queue_projections_keeps_still_failing(tmp_path):
    """2 条 pending，其中 1 条 replay 仍 fail → 留在 pending"""

def test_repair_queue_projections_handles_missing_pending_file(tmp_path):
    """pending 文件不存在 → 返回 0，no-op"""
```

## 4. Implementation

```python
def repair_queue_projections(root: Path | str) -> int:
    """扫描 .index/queue_projection_pending.jsonl，重投影到 reviews_queue。
    
    Returns: count of successfully repaired entries (now in reviews_queue).
    
    Best-effort: re-projection 失败保留原条目在 pending。Never raises.
    """
```

## 5. Acceptance

- ✅ 3 pending → 全部 re-project → pending 清空
- ✅ 部分失败保留在 pending
- ✅ 无 pending 文件 → no-op
- ✅ 现有 18 个 stage7 测试 0 回归
- ✅ 不引入新依赖