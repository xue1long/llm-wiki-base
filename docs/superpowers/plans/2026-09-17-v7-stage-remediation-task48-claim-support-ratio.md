# Plan: Task 48 — Stage 5 claim_support_ratio 长期指标

**Branch:** `codex/book-series-target`
**Status:** draft (master plan §5 第四批)
**Parent:** `docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan.md` §5 (Task 48)

## 0. 上下文

Stage 5 产出大量 Claims（每个 slot × 每个 topic）。Master plan §3.2 要求 Stage 5 暴露
`metrics.claim_support_ratio = count(support==SUPPORTED) / max(1, total_claims)`。

现有 Stage 5A claim_extractor 不会持久化这个 ratio —— 每次跑只输出 FillResult.metrics。
**Task 48 目标**：把每次 ingest 的 claim_support_ratio 落到 `<.index/v7_metrics.jsonl`，
并提供读取 API（最近 N 次 ratio + 平均）。

## 1. Goal / Non-Goal

### 1.1 用户可见成果

1. `Stage5Metrics.record_run(ratio, *, run_id, topic_count)` 纯函数 append
2. `Stage5Metrics.read_recent(limit=10)` 读最近 N 次 ratio
3. `<.index/v7_metrics.jsonl` 持久化（append-only JSONL）
4. CLI hook：Task 31 reconcile_job.run + Stage 5 fill_slots_v2 调用

### 1.2 Non-Goal

- **不**改 FillResult / claim_extractor 内部（已有 metrics.claim_support_ratio）
- **不**做告警（Task 50 drift 监控的范围）
- **不**聚合 cross-stage 指标

## 2. 模型

```python
@dataclass
class Stage5MetricsEntry:
    timestamp_ms: int
    run_id: str
    topic_count: int
    claim_total: int
    claim_supported: int
    claim_support_ratio: float
    reviewer_verdicts_count: int
    clusterer_fingerprint: str = ""
```

## 3. Files

- `src/pipeline/v7_extract/stage5_metrics.py`（新建）
- `tests/test_pipeline/test_v7_extract_stage5_metrics.py`（新建）

## 4. Tests

```python
def test_metrics_record_run_appends_jsonl():
    """record_run → .index/v7_metrics.jsonl 多 1 行"""

def test_metrics_read_recent_returns_last_n():
    """3 条记录，read_recent(2) → 2 条"""

def test_metrics_aggregate_average_ratio():
    """多 ratio 的 arithmetic mean 准确"""

def test_metrics_record_zero_claim_topic_still_writes():
    """claim_total=0 → ratio=0.0（不是 NaN）"""
```

## 5. Implementation

```python
class Stage5Metrics:
    def __init__(self, root: Path | str): ...
    
    def record_run(self, entry: Stage5MetricsEntry) -> None: ...
    
    def read_recent(self, *, limit: int = 10) -> list[Stage5MetricsEntry]: ...
    
    def aggregate_average(self, *, limit: int = 10) -> float: ...

def metrics_path(root: Path | str) -> Path:
    return Path(root) / ".index" / "v7_metrics.jsonl"
```

## 6. Acceptance

- ✅ 4 个测试全绿
- ✅ append-only JSONL 持久化
- ✅ 现有 50+ v7_extract + 38 reconciliation 测试 0 回归
- ✅ 不引入新依赖