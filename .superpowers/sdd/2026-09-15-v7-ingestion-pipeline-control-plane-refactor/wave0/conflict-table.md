# 冲突表(Wave 0 P2 加固)

## 测试文件 import 依赖

| 测试文件 | 静态依赖(src/) | 运行时依赖 | 是否跨 lane 引用 |
|---|---|---|---|
| `tests/test_pipeline/test_v7_extract_slot_filler.py` | `slot_filler`, `topic_clusterer`, `failures` (via `filter_failed_topics`) | 无 | 不依赖 Luna-B 新接口 |
| `tests/test_pipeline/test_v7_extract_topic_clusterer.py` | `topic_clusterer`, `failures` | 无 | 不依赖 Luna-B 新接口 |
| `tests/test_pipeline/test_v7_extract_wiki_writer.py` | `wiki_writer`, `relation_extractor`, `audit_logger` | 需要 enqueue_failure | **依赖 Luna-B 新接口** (签名扩展后) |
| `tests/test_pipeline/test_v7_extract_failures.py` | `failures` | 无 | 不依赖 Luna-A |
| `tests/test_pipeline/test_v7_extract_prompts_*.py` | `prompts/*` | 无 | 不依赖 Luna-A/B |
| `tests/test_scripts/test_extract_pilot.py` | `extract_pilot` | 依赖 `failures.ExtractionResult` 改造(Wave 2) | 跨 lane,Wave 2 前不能跑 |
| `tests/test_scripts/test_extract_full.py` | `extract_full` | 依赖 `failures.ExtractionResult` 改造 + `wiki_writer.WriteReport` 扩展 | 跨 lane,Wave 3 后才能跑 |
| `tests/test_pipeline/test_v7_extract_legacy_fallback.py` | `__init__` + `_legacy_*` | 无 | 不依赖 Luna-A/B |
| `tests/test_scripts/test_review_queue_cli.py` | `scripts/review_queue_cli` + `failures` | 依赖 Luna-B 的 queue API | 依赖 Luna-B |

## 写集合(已确认)

| 文件 | 负责 lane | 备注 |
|---|---|---|
| `_page_id.py` (新) | Luna-A | H2 加固 |
| `slot_filler.py` | Luna-A | Stage 5 item_index 改造 |
| `fill_slots.toml` | Luna-A | prompt 改 |
| `extract_pilot.py` | Luna-A | 接入 `_page_id` + 改造 page 注入 |
| `topic_clusterer.py` | Luna-A | 仅在需要时复用 canonical item 映射 |
| `reviews_queue.py` | Luna-B | **不动**(用 `failures.py` 的 API) |
| `failures.py` | Luna-B | `enqueue_failure` 签名扩展 + 稳定 hash ID |
| `_queue_lock.py` (新) | 主 agent (Wave 0) | O1 加固 |
| `wiki_writer.py` | Luna-E (Wave 3) | `WriteReport.page_writes` + `dry_run` 字段 |
| `extract_full.py` | Luna-F (Wave 3) | source+md5 checkpoint |

## 测试依赖关系(关键)

- **Luna-A 的 slot_filler 测试** → 不依赖 Luna-B 接口 ✓
- **Luna-B 的 failures 测试** → 不依赖 Luna-A 接口 ✓
- **Luna-C 的 async 迁移测试** → 不依赖 Luna-A/B 接口 ✓
- **Wave 2 Luna-D 测试** → 依赖 Luna-A + Luna-B 的最终接口 — **必须在 Wave 1 合并后才能跑**
- **Wave 3 Luna-E Writer 测试** → 依赖 Luna-B 的 `enqueue_failure` 新签名 — **必须在 Wave 1 + 2 合并后才能跑**
- **Wave 3 Luna-F full runner 测试** → 依赖 Luna-E 的 `WriteReport` 扩展 — **必须在 Wave 3 Luna-E 完成后才能跑**

## Wave 0 主 agent 负责的事

- 创建 `_queue_lock.py` (O1 加固)
- 创建共享 fixture `tests/fixtures/v7_control_plane/`
- 创建 ledger + 当前文件
- **不写 src/pipeline/v7_extract/ 下任何 lane 写集合的文件** — 让 Luna-A/B/C 独占
- **不修改 extract_pilot.py / extract_full.py** — 让 Luna-A/Luna-F 独占
- 冲突裁决:`脚本身份契约优先 / queue schema 保持兼容 / P2 原则不破坏`(plan §6 写明)
