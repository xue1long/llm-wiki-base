# Progress — V7 Control Plane Refactor

> Ledger 由 Wave 0 主 agent 创建,后续每个 Wave/Task 完成时由对应 agent
> 在本文件追加 commit hash + 验收证据 + 阻塞原因。

## Wave 0 — 主 agent 准备(2026-09-15)

### 已完成

| # | 动作 | 产物 |
|---|---|---|
| 0.1 | 记录 BASE | `b1657ed9e589afd23017b5fdf8b285fcbd90adc5` |
| 0.2 | 记录 dirty files | 仅整改后 plan(`docs/superpowers/plans/2026-09-15-v7-ingestion-pipeline-control-plane-refactor.md`) |
| 0.3 | A1-A7 启动前置条件核对 | `wave0/prerequisites.md` |
| 0.4 | H6 Stage 6 调研 | `wave0/stage6-investigation.md`(结论:Stage 6 已实现但 scripts 未调用,Task 6 只需改文档) |
| 0.5 | 冲突表(含 import 依赖) | `wave0/conflict-table.md` |
| 0.6 | 共享 fixture 设计 | `wave0/shared-fixture.md` |
| 0.7 | 共享 fixture 物理创建 | `tests/fixtures/v7_control_plane/{source_a.md, source_b.md, expected_ids.json}` |
| 0.8 | `_queue_lock.py` 创建 | `src/pipeline/v7_extract/_queue_lock.py`(O1 加固) |
| 0.9 | §1.5 微调(反映 `enqueue_failure` 已存在) | plan 文件已更新 |

### 阻塞项(待用户决策)

| 项 | 阻塞原因 | 候选解 |
|---|---|---|
| **A2** | `_legacy.py` 是 placeholder,`V7_USE_V3=false` 不可用 | (a) 仅 `V7_USE_V3_CONTROL_PLANE` 单一回退 / (b) 补 4 个 `_legacy_*.py` / (c) 修 `__init__.py` 静默退到 v3 |
| **H4** | `--root` 当前有 default(`knowledge/novel-wiki`),与"缺则 exit 2"冲突 | (i) 保留 default(用户友好) / (ii) 改 required(强制显式) |

### 决策落地(2026-09-15,用户确认)

| 项 | 决策 | plan 落地位置 |
|---|---|---|
| **A2** | **(a)** 仅 `V7_USE_V3_CONTROL_PLANE` 单一回退 | §1.5 已固化 |
| **H4** | **(ii)** 改 `required=True`,删除 `default` | Task 3 已固化 |

### Wave 1 启动条件(全部满足才能派发)

- [x] A2 决策落地 + plan §1.5 微调已完成
- [x] H4 决策落地(`--root` 改 required)
- [x] 共享 fixture 物理创建
- [x] `_queue_lock.py` 创建
- [x] **Wave 0 commit**(`9e641367`)
- [x] **Wave 1 启动文档 commit**(`09322aac`)
- [x] **Wave 1 三个 lane commit**(`8943f696` / `c56f08eb` / `b744293b`)
- [x] **Wave 1 全套验证**(123 passed / 0 failed)
- [x] **`git tag v7-control-plane-wave1` 已打**
- [ ] **当前待办:** Wave 2 Luna-D 派发(Task 2 统一 `ExtractionResult`)
- [ ] **当前待办:** v3 实施的 `_legacy.py` placeholder 问题记录在 Wave 0 ledger(本次不修)

## 后续 Wave 占位

### Wave 1(待启动)

- Luna-A: Task 1 provenance + `_page_id.py`
- Luna-B: Task 3 queue core + `enqueue_failure` 稳定 hash ID
- Luna-C: Task 0 async test migration

## Wave 1 — 完成(2026-09-15)

### 三个 lane 全部 commit

| Lane | Commit | 范围 | 主会话测试 |
|---|---|---|---|
| Luna-A | `8943f696` | `_page_id.py` + Stage 5 input contract + extract_pilot 接入 | 76 passed |
| Luna-B | `c56f08eb` | `enqueue_failure` 稳定 sha1 ID + 5 项 keyword 参数 + P12/D11 | 34 passed |
| Luna-C | `b744293b` | stage4/5/7 测试 sync → async 迁移 + fixture 升级 | 13 passed |

### Wave 1 全套验证

```
$env:PYTHONPATH = "."
python -m pytest tests/test_pipeline/test_v7_extract_page_id.py \
                   tests/test_pipeline/test_v7_extract_slot_filler.py \
                   tests/test_pipeline/test_v7_extract_topic_clusterer.py \
                   tests/test_pipeline/test_v7_extract_failures.py \
                   tests/test_pipeline/test_v7_extract_failures_idempotency.py \
                   tests/test_pipeline/test_v7_extract_stage4.py \
                   tests/test_pipeline/test_v7_extract_stage5.py \
                   tests/test_pipeline/test_v7_extract_stage7.py \
                   tests/test_scripts/test_extract_pilot.py \
                   --import-mode=importlib -q
→ 123 passed in 8.23s
```

### 编译与 diff check

- `python -m compileall -q src/pipeline/v7_extract scripts/extract_pilot.py` → exit 0
- `git diff --check` → exit 0

### Git tag

```
git tag -a v7-control-plane-wave1 -m "..."
→ v7-control-plane-wave1
```

作为 Wave 2 / Wave 3 失败的回滚快照点。

### Deviations 摘要

| Lane | 项 | 决议 |
|---|---|---|
| Luna-A | 6 项(包括 `ConceptPage.topic_id` 扩展、`_excerpt_in_source` 保留、5 个旧 payload 测试改名) | ✅ 全部接受 |
| Luna-B | 无 | ✅ |
| Luna-C | 3 项(stage4/5 schema 升级到 v3.1 item_indexes;stage7 fixture evidence 升级) | ✅ 全部接受 |

### Pre-existing failure(与 Wave 1 无关,已独立验证)

**测试**:`tests/test_pipeline/test_content_filter.py::test_writer_blocks_flagged_page_until_review_is_accepted`

**fail mode**(Wave 0 HEAD `9e641367` + Wave 1 HEAD `eb1a4a7d` 复现一致):
```
AttributeError: 'ConceptPage' object has no attribute 'topic_id'
src/pipeline/v7_extract/wiki_writer.py:88
```

**根因**:v3 实施 T2.5(Stage 7 P4 闸门)的遗留问题。`WikiWriter.commit_and_index` Guard A
直接访问 `page.topic_id`,但 `tests/test_pipeline/test_content_filter.py:72-77` 直接构造
`ConceptPage("sensitive", "待审概念", ...)` 时没有 `topic_id` 字段(因为 v3 Wave 0
`_extract_one()` 用 `__dict__` 注入,而测试 fixture 绕过了 `_extract_one()`)。

**Wave 0 复现**(主会话 `git stash + git checkout 9e641367 -- + pytest`)fail mode 与
Wave 1 完全相同,确认是 **v3 实施 T2.5 引入的 pre-existing bug**,不是 Wave 1 回归。

**修复候选**(留给后续 plan 处理,不修):
- 方案 A:让 `ConceptPage.topic_id` 默认 `""`(Wave 1 Luna-A 已默认 None,需改为 `""`)
- 方案 B:让 Guard A 用 `getattr(page, "topic_id", "")` 兼容(与 v3 `failures.filter_failed_topics`
  的 `getattr(p, "topic_id", None)` 模式一致,最优雅)
- 方案 C:修测试 fixture 显式构造带 `topic_id=""` 的 page

**本计划范围外**:plan §1.5 / §6 明确"不动 v3 实施的 _legacy.py / __init__.py",
"不重写 Stage 1/3/4/5 的语义"。修这个 bug 属于 v3 后续 task,**Wave 2 不动**。

### Wave 2(待 Wave 1 完成)

- Luna-D: Task 2 unified ExtractionResult

### Wave 3(待 Wave 2 完成)

- Luna-E: Task 3 Writer integration
- Luna-F: Task 4 source+md5 checkpoint

### Wave 4(待 Wave 3 完成)

- Luna-G: Task 5 smoke + report fields
- Luna-H: Task 6 docs + ADR
- Luna-I: final whole-branch review

## 计划文件

- 计划:`docs/superpowers/plans/2026-09-15-v7-ingestion-pipeline-control-plane-refactor.md`(749 行,plan-audit 整改后)
- 对照架构:`docs/superpowers/plans/2026-09-15-v7-pipeline-architecture-v3.md`
- 对照实施:`docs/superpowers/plans/2026-09-15-v7-pipeline-v3-implementation.md`
