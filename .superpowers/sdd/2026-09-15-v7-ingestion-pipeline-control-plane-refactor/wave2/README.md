# Wave 2 启动上下文

> 本目录给 Wave 2 Luna-D 提供完整上下文。

## 全局上下文(Luna-D 必读)

- 计划文件:`docs/superpowers/plans/2026-09-15-v7-ingestion-pipeline-control-plane-refactor.md`
- Wave 0 产出:`.superpowers/sdd/2026-09-15-v7-ingestion-pipeline-control-plane-refactor/wave0/`
- Wave 1 ledger:`.superpowers/sdd/2026-09-15-v7-ingestion-pipeline-control-plane-refactor/wave1/`
- 当前 commit:`caa61dd0`(Wave 1 完成 + pre-existing bug 详细记录)
- tag:`v7-control-plane-wave1` 已打

## Wave 1 已落地的关键事实(Luna-D 必须遵守)

| 文件 | Wave 1 状态 |
|---|---|
| `src/pipeline/v7_extract/_page_id.py` | Luna-A 创建,提供 `_stable_page_id(relative, topic_title)` + `validate_page_id` |
| `src/pipeline/v7_extract/slot_filler.py` | Luna-A 改造,Stage 5 接受 `item_index` 整数,`_payload_to_page()` 映射到 canonical `topic.item_ids[index]` |
| `src/pipeline/v7_extract/failures.py` | Luna-B 改造,`enqueue_failure(source_id, stage, *, page_id="", topic_id="", reason, content_hash="", prompt_kind="", provider="", payload=None, queue_path=...)`,返回 sha1 稳定 `v7fail-<12hex>` ID |
| `scripts/extract_pilot.py` | Luna-A 改造,`_extract_one()` 接入 `_page_id`,`page.topic_id = topic.id` 正式字段,异常路径加 `failure_stage` + 截断 reason,保留 `error` 字段向后兼容 |
| `ConceptPage` | Luna-A 扩展 `topic_id: str \| None = None` 字段 |
| `tests/test_pipeline/test_v7_extract_*.py` | Luna-A/B/C 扩展或新增(76/34/13 = 123 passed) |

## Wave 2 — Luna-D 任务范围

### 修改文件

- 🟡 `src/pipeline/v7_extract/failures.py`(扩展 `ExtractionResult` 五态 + `legacy_status` + `to_dict()` 统一序列化 + `from_v3_status` 工厂)
- 🟡 `scripts/extract_pilot.py`(`_extract_one()` 返回 `ExtractionResult` 而非 dict)
- 🟡 `scripts/extract_full.py`(消费 `ExtractionResult` 而非 dict)

### 测试文件

- 🟡 `tests/test_pipeline/test_v7_extract_failures.py`(扩展 `ExtractionResult` 五态测试 + `legacy_status` 映射测试)
- 🟡 `tests/test_scripts/test_extract_pilot.py`(`_extract_one` 返回 `ExtractionResult` 而非 dict 的回归测试)
- 🟡 `tests/test_scripts/test_extract_full.py`(`run_full` 消费 `ExtractionResult` 的回归测试)

### 绝对不允许碰

- Luna-A 的 `_page_id.py` / `slot_filler.py` / `topic_clusterer.py` / `fill_slots.toml`
- Luna-B 的 `enqueue_failure` 签名(已被 Luna-B 改造为稳定 sha1 ID,Luna-D 必须保持兼容)
- `src/pipeline/v7_extract/wiki_writer.py`(Wave 3 Luna-E)
- `src/pipeline/v7_extract/_legacy.py` / `__init__.py`(v3 实施)
- `src/pipeline/v7_extract/_queue_lock.py`(Wave 0 O1 加固)
- Luna-A/B/C 已扩展过的测试文件(`test_v7_extract_slot_filler.py` / `test_v7_extract_page_id.py` / `test_v7_extract_failures_idempotency.py` / `test_v7_extract_stage4.py` / `test_v7_extract_stage5.py` / `test_v7_extract_stage7.py`)

## Wave 2 验收标准

```powershell
$env:PYTHONPATH = "."
python -m pytest tests/test_pipeline/test_v7_extract_failures.py \
                   tests/test_pipeline/test_v7_extract_page_id.py \
                   tests/test_pipeline/test_v7_extract_slot_filler.py \
                   tests/test_pipeline/test_v7_extract_topic_clusterer.py \
                   tests/test_pipeline/test_v7_extract_stage4.py \
                   tests/test_pipeline/test_v7_extract_stage5.py \
                   tests/test_pipeline/test_v7_extract_stage7.py \
                   tests/test_scripts/test_extract_pilot.py \
                   tests/test_scripts/test_extract_full.py \
                   --import-mode=importlib -q
python -m compileall -q src/pipeline/v7_extract scripts/extract_full.py scripts/extract_pilot.py
git diff --check
```

## 关键约束(plan §2.2.1 映射表)

五态 ↔ v3 三态:

| v3 `ExtractionStatus` | 本次 `status` | `legacy_status` |
|---|---|---|
| `OK` | `written` | `ok` |
| `OK` + 部分 page blocked | `written` | `ok` |
| `NEEDS_REVIEW`(全部 page) | `blocked` | `needs_review` |
| `INCOMPLETE` | `incomplete` | `incomplete` |
| (新增) | `failed` | `needs_review` |
| (新增) | `skipped` | `ok`(若 skip 命中 written) / `needs_review`(若 skip 命中 blocked) |

**LLM schema 不合规** 归 `failed`;**缺失 evidence** 永远走 `blocked`。

## Wave 2 完成 → Wave 3 准备

Wave 2 Luna-D 完成 + 验收后:
1. 主会话跑 Wave 2 全套验证
2. `git tag v7-control-plane-wave2`
3. 更新 ledger(progress.md)Wave 2 section
4. 进入 Wave 3(Luna-E 串行 Task 3 Writer 集成,然后 Luna-F 串行 Task 4 source checkpoint)
