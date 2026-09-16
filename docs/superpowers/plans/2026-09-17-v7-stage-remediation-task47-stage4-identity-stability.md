# Plan: Task 47 — Stage 4 identity stability test（rerun 同 source → 同一 topic_id）

**Branch:** `codex/book-series-target`
**Status:** draft (master plan §5 第四批)
**Parent:** `docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan.md` §5 (Task 47)

## 0. 上下文

Stage 4 cluster_topics 产出 `TopicCandidate.id` 与 `Topic.id`（Task 12 已脚本化）。
但 **determinism 至今没有专门的测试**——同名 source + 同 prompt 应产出同一 topic_id
的稳定性。

**Task 47 目标**：写一组 Stage 4 identity stability 测试，对同一 source 跑两次
cluster_topics，断言两次产出的 topic_id 完全一致（按 source_id + mapped_items）。

## 1. Goal / Non-Goal

### 1.1 用户可见成果

1. 测试 `tests/test_pipeline/test_v7_extract_topic_clusterer.py` 追加 ≥ 4 测试
2. 同一 source 不同 fake LLM 行为都产生稳定 topic_id
3. 不同 source 产出不同 topic_id
4. 跨升级 prompt fingerprint 漂移能被 detect

### 1.2 Non-Goal

- **不**改 cluster_topics 实现
- **不**改 TopicCandidate / Topic dataclass
- **不**调真实 LLM

## 2. Files

- `tests/test_pipeline/test_v7_extract_topic_clusterer.py`（追加测试）
- **无新源码**

## 3. Tests

```python
def test_topic_id_stable_across_repeated_runs():
    """同 source + 同 LLM script + 同 prompt → 两次 cluster_topics → topic_id 一致"""

def test_topic_id_differs_between_different_sources():
    """两个不同 source → topic_id 不同"""

def test_topic_id_stable_when_only_llm_response_unchanged():
    """FakeLLMClient.script 相同 → cluster_topics 2 次输出 topic_id 完全一致"""

def test_topic_id_changes_when_input_items_change():
    """items 集合不同 → topic_id 不同"""

def test_topic_id_format_remains_canonical():
    """topic_id 是 script hash 字符串格式（TopicCandidate.id 已知约束）"""
```

## 4. Implementation

**所有测试直接调用现有 `cluster_topics` 接口**。已有 `FakeLLMClient.script(...)` 
支持 script LLM 响应。**不需要新代码**——纯测试增量。

## 5. Acceptance

- ✅ 5 个测试全绿
- ✅ 现有 49 topic_clusterer 测试 0 回归
- ✅ 验证 task 12 的 script-generated topic_id 是真正 deterministic