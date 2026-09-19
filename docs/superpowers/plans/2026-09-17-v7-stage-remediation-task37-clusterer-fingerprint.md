# Plan: Task 37 — Stage 4 clusterer_fingerprint 接入 source checkpoint

**Branch:** `codex/book-series-target`
**Status:** draft (master plan §5 第二批)
**Parent:** `docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan.md` §5 (Task 37)

## 0. 上下文

master plan §3.2 定义 pipeline_fingerprint = sha1(classifier_fp + segmenter_fp + checker_fp +
clusterer_fp + generator_fp + template_hashes)[:16]。

Task 22（commit `a84e1c11`）已落地 `_current_pipeline_fingerprint` 接受 4 个 stage
fingerprint 参数，但 **clusterer_fingerprint 未被接入**：
- `extract_full.py` 的 `_current_pipeline_fingerprint` 调用链中 clusterer_fp=""
- `topic_clusterer._compute_clusterer_fingerprint()` 已存在但未被 extract_full 拿

**Task 37 目标**：把 clusterer_fingerprint 接入 source checkpoint，让 Stage 4 prompt 升级
触发 source 重审。

## 1. Goal / Non-Goal

### 1.1 用户可见成果

1. `_current_pipeline_fingerprint` 在 extract_full 调用处传入真实 clusterer_fp（不再是 ""）
2. clusterer 升级（prompt 改 / 风险 pattern 改）→ source checkpoint 视 pipeline 升级 → 重审

### 1.2 Non-Goal

- **不**改 `_current_pipeline_fingerprint` 签名（已接受 `clusterer_fp` 参数）
- **不**改 `_source_can_skip` 双键逻辑（Task 22 已落地）
- **不**改 Stage 4 clusterer 内部（仅消费 `clusterer._compute_clusterer_fingerprint`）

## 2. Files

- `scripts/extract_full.py`（修改：找 `_current_pipeline_fingerprint` 调用点）
- `tests/test_scripts/test_extract_full.py`（追加测试）

## 3. Tests

```python
def test_current_pipeline_fingerprint_includes_clusterer():
    """clusterer_fp 改变 → pipeline_fingerprint 改变"""

def test_extract_full_calls_clusterer_fingerprint(tmp_path, monkeypatch):
    """extract_full 主流程调 clusterer_fingerprint（非空字符串）"""
```

## 4. Implementation

### 4.1 extract_full.py 改动

找到 `_current_pipeline_fingerprint(...)` 调用点（应在 `extract_one` 或 `_source_skip_decision` 里），
传入 `clusterer_fp=_compute_clusterer_fingerprint()`（来自 `topic_clusterer` 模块）。

如果调用点**没有**传入 clusterer_fp，**最小修复**：调用 `from src.pipeline.v7_extract.topic_clusterer import _compute_clusterer_fingerprint`，
传入当前值。

**不改** `_current_pipeline_fingerprint` 本身（已接受 clusterer_fp kwarg）。

## 5. Acceptance

- ✅ `_current_pipeline_fingerprint` 在 extract_full 调用时 clusterer_fp != ""
- ✅ clusterer 风险 pattern 改变 → 重新计算 clusterer_fingerprint → pipeline_fingerprint 改变
- ✅ existing fingerprint 测试 0 回归
- ✅ 不引入新依赖

## 6. Status

draft → in-progress → completed