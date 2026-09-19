# V7 Replace Plan Stage 1 P1 三项修复完成

## 时间线

| Task | 内容 | Commit | 状态 |
| --- | --- | --- | --- |
| P1-1 | fill_slots_v2 v3 path | `01f9a53c` | ✅ |
| P1-2 | BridgeBudget 硬性 cap | `886506c2` | ✅ |
| P1-3 | topic 同 id 去重 | `886506c2` | ✅ |

## 详细变更

### P1-1: fill_slots_v2 v3 路径（`01f9a53c`）

之前 Stage 0 用 v2 path（1 LLM call/topic），用户原本选 v3 path（8+1 calls/topic）需要 window_resolver spans_per_slot。本次实现绕开 window_resolver：直接从 Stage 2 的 `CanonicalItem.text` 切片成 1500-byte 的 `CanonicalSpan`（canonical_v7 limit），每个 slot 拿到相同的 span list，LLM 在 `extract_slot_claims` 里按相关性过滤。`fill_slots_v2` 把 `FillStatus.FILLED` 映射为 `ConceptPage`，其他状态标记 `failed_topics`。

```python
if use_fill_slots_v2:
    fill_result = await fill_slots_v2(
        topic, spans_per_slot=spans_per_slot,
        topic_items=segmentation.items,
        source_bytes=source_text.encode("utf-8"),
        llm=llm, project_root=paths.root, topic_label=topic_label,
    )
    if fill_result.status is FillStatus.FILLED:
        concept_page = fill_result.legacy_page
```

### P1-2: BridgeBudget 硬性 cap（`886506c2`）

之前 `BridgeBudget` 字段定义了但不强制。本次在每个 stage 边界（1/3/4/5/6）调 `_check_budget(llm, budget, stage)`，如果 `adapter.calls_count >= budget.max_calls` 抛 `BridgeBudgetExceeded` → `failure_stage="budget"` + 写 quarantine v7_failure.md + short-circuit 后续 stage。

```python
def _check_budget(llm: Any, budget: "BridgeBudget", stage: str) -> None:
    if not hasattr(llm, "calls_count"):
        return
    if llm.calls_count >= budget.max_calls:
        raise BridgeBudgetExceeded(...)
```

### P1-3: topic 同 id 去重（`886506c2`）

`cluster_topics` 可能返回 2 个 topic.id 相同的 topic（LLM 偶尔出现）。`_stable_page_id(source, topic_id)` 纯确定性 → 第二个 topic 会覆盖第一个。bridge 加 `seen_topic_ids: Counter`，第 (n+1) 个 occurrence 拿 `f"{base_page_id}-{n}"` 后缀。

```python
seen_topic_ids: Counter[str] = Counter()
for topic in cluster_result.topics:
    ...
    n_occurrence = seen_topic_ids[topic.id]
    page_id = f"{base_page_id}-{n_occurrence}" if n_occurrence > 0 else base_page_id
    seen_topic_ids[topic.id] += 1
```

## 验证

**Unit tests** (76/76 通过)：
- `test_bridge_runs_full_pipeline_short_source` — v2 path
- `test_bridge_runs_v3_path_short_source` — v3 path（新）
- `test_bridge_respects_max_calls_budget` — 验证 budget=2 在 Stage 4 abort
- `test_bridge_dedupes_duplicate_topic_ids` — 验证 2 同 id topic 产出 2 distinct page_ids

**70 KB smoke** 重跑：
- 5 LLM 调用 / 26 秒
- 0 H1-H5 issues
- wiki-quality HEALTHY
- 3 pages 写入（含 v3 path 验证）

## 关键观察

1. **v3 path 不需要 window_resolver**：inline spans 切片足够 Stage 1 灰度。window_resolver 仍然值得 Stage 2 引入以获得更好 span 质量。
2. **Budget 在 stage 边界检查而非 per-call**：6 个 stage-boundary check 足以防止 v3 path 跑超成本（9 calls/topic × 1 topic + 5 fixed = 14 calls ≤ 默认 20 calls）。
3. **Topic 同 id 实际罕见**：smoke 70 KB 任务 LLM 没产生 duplicate topic id，所以 dedup 代码没被真实触发——但单测 `test_bridge_dedupes_duplicate_topic_ids` 用 forced scripted 验证了逻辑正确。

## 用户决策点（Stage 1 灰度）

按 4 阶段方案：
- ✅ Stage 0 完成（5 个 Task commit + smoke 验证）
- ✅ P1 完成（v3 path + budget cap + topic dedup）
- **下一步：进入 Stage 1 灰度**

Stage 1 决策需要：
1. **灰度项目选哪个**？novel-wiki-v2 自身？还是另选一个（如 sanjian-zatan-kb、video-notes-wiki）？
2. **灰度方式**：
   - (A) novel-wiki-v2 设 `RUFLO_PIPELINE_MODE=v7` env var
   - (B) novel-wiki-v2 完全切默认（Stage 2 行为）
3. **观察期多长**：5 天？2 周？1 个月？
4. **删除旧代码时机**：Stage 1 后立即？还是 Stage 1 + 2 周观察 + 0 issue 才删（Stage 3 行为）？
5. **Stage 3 删除前**需要先做哪些清理（plan audit 3-7 中识别）？
