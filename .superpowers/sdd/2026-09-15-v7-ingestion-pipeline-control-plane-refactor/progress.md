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
- [ ] **当前待办:** Wave 0 commit 落地(`git add` + `git commit`)
- [ ] **当前待办:** v3 实施的 `_legacy.py` placeholder 问题已记录到 Wave 0 ledger(本次不修)

## 后续 Wave 占位

### Wave 1(待启动)

- Luna-A: Task 1 provenance + `_page_id.py`
- Luna-B: Task 3 queue core + `enqueue_failure` 稳定 hash ID
- Luna-C: Task 0 async test migration

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
