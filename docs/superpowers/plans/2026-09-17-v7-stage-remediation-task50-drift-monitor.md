# Plan: Task 50 — Reconciliation 长期 drift 监控

**Branch:** `codex/book-series-target`
**Status:** draft (master plan §5 第四批)
**Parent:** `docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan.md` §5 (Task 50)

## 0. 上下文

Task 48 落地 Stage 5 claim_support_ratio 指标采集 + 平均值 API。
Reconciliation 也需要 drift 监控：跨多次 ingest 的同概念 canonical_id / member count / 同 unresolved比例 漂移。

**Task 50 目标**：写一个 `ReconciliationDriftMonitor` 模块，定期读取 `canonical_concepts.json` + `decision_log.jsonl`，输出当前状态快照（active count / stale count / unresolved ratio / fp drift）。**无网络 / 无 LLM**。

## 1. Goal / Non-Goal

### 1.1 用户可见成果

1. `ReconciliationDriftMonitor(root)` 类：snapshot() 返回 ReconciliationDriftSnapshot
2. `ReconciliationDriftSnapshot` dataclass 含 active_canonical_count / stale_canonical_count / unresolved_decisions_recent / fingerprint_drift_detected
3. 4 个测试覆盖：empty / active-only / stale-detected / unresolved-ratio

### 1.2 Non-Goal

- **不**改 canonical registry / decision_log 持久化
- **不**调网络 / LLM
- **不**做主动告警（hook 是只读）

## 2. 模型

```python
@dataclass
class ReconciliationDriftSnapshot:
    active_canonical_count: int
    stale_canonical_count: int
    tombstoned_canonical_count: int
    unresolved_decisions_recent: int    # 最近 N decision_log 的 UNRESOLVED
    fingerprint_drift_detected: bool      # 任何 STALE
    current_fingerprint: str = ""
    taken_at_ms: int = 0
```

## 3. Files

- `src/reconciliation/drift_monitor.py`（新建）
- `tests/test_reconciliation/test_drift_monitor.py`（新建）

## 4. Tests

```python
def test_snapshot_with_empty_registry():
    """空 registry → 全 0"""

def test_snapshot_counts_active_and_stale_correctly():
    """3 ACTIVE + 2 STALE + 1 TOMBSTONED → 各 count 准确"""

def test_snapshot_detects_fingerprint_drift():
    """任何 STALE → fingerprint_drift_detected = True"""

def test_snapshot_counts_unresolved_decisions_recent():
    """最近 10 decision_log 中 UNRESOLVED 的计数"""

def test_snapshot_handles_missing_decision_log():
    """decision_log.jsonl 不存在 → unresolved_decisions_recent = 0"""
```

## 5. Implementation

```python
class ReconciliationDriftMonitor:
    def __init__(self, root: Path | str, *, current_fingerprint: str = ""): ...
    
    def snapshot(self, *, recent_decisions_limit: int = 10) -> ReconciliationDriftSnapshot: ...
```

## 6. Acceptance

- ✅ 5 个测试全绿
- ✅ 现有 38 reconciliation 测试 0 回归
- ✅ 不引入新依赖