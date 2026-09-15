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
- [x] Wave 2 Luna-D 已完成(Task 2 统一 `ExtractionResult`): `24c9bb24`
- [x] Wave 3 Task 3/4 已完成(Writer 集成 + source checkpoint): `c306b552` / `ac1ef971`
- [x] Wave 3 快照标签已打: `v7-control-plane-wave2` / `v7-control-plane-wave3`
- [ ] Wave 4 收尾仍待完成(Task 5 报告补齐、Task 6 文档提交、Task 7 最终验收)
- [ ] v3 实施的 `_legacy.py` placeholder 问题仍按 Wave 0 决策留在本计划范围外

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

### Wave 1 遗留 — `test_full_apply_writes_concepts` fixture 不一致(主会话发现并修复)

**测试**:`tests/test_scripts/test_extract_full.py::test_full_apply_writes_concepts`

**最初报告**:Luna-D 在 Wave 2 验收时把这个 fail 报成"pre-existing v3 T2.5 bug",
与 `test_content_filter` 混淆。Luna-D 引用了 Wave 1 ledger 的描述,**未独立验证**。

**主会话独立调查**(`git checkout 9e641367 --` + `8943f696 --` + `c56f08eb --` +
`b744293b --` 逐个跑测试):
| HEAD | 结果 |
|---|---|
| `9e641367`(Wave 0 准备) | ✅ PASS |
| `8943f696`(Luna-A: T1 provenance) | ❌ FAIL ← **回归引入点** |
| `c56f08eb`(Luna-B: T3 queue) | ❌ FAIL |
| `b744293b`(Luna-C: T0 async) | ❌ FAIL |

**真正的根因**:Luna-A 把 `slot_filler.py` 的 evidence 字段从 `item_id`(字符串)改为
`item_index`(整数,plan §4 Task 1 契约)。`test_full_apply_writes_concepts` 用
`fake.script("fill_slots", {"evidence": {"definition": {"item_id": "..."}}})`,
Luna-A 改造后 evidence 校验失败,page 被 `needs_review` 阻断,`wiki/concepts/*.md`
没生成。Luna-A 改了 `slot_filler.py` 但**没改这个测试的 fixture**,Luna-D 抄报告时
把它误归类为 pre-existing bug。

**Luna-D 的新测试同样受影响**:`test_full_summary_pages_counts_written_only` 用
同样的 buggy fixture,虽然不验证写盘所以 PASS,但仍是隐性 fixture bug。

**修复**:主会话 surgical 修复,把 `tests/test_scripts/test_extract_full.py` 的两处
fixture `item_id` 字符串改为 `item_index` 整数,符合 plan §4 Task 1 契约。修复后
全套 150 passed / 0 failed。

**Lesson for Wave 3**:
- subagent 报告 "pre-existing" 时,主 agent 必须**独立验证**(逐 commit checkout)。
- Luna-A 的 deviation #5 "旧 payload 测试改名" 范围应包括 `test_extract_full.py`
  的两个 fixture,但 Luna-A 没看到这两个测试,只改了 `test_v7_extract_slot_filler.py`。
- **Luna-E/F 改造 `wiki_writer.py` + `extract_full.py` 时**,需主动 audit
  `tests/test_scripts/test_extract_full.py` 的 fixture 是否仍匹配新契约。

### Wave 2(已完成，原占位)

- Luna-D: Task 2 unified ExtractionResult

### Wave 3(已完成，原占位)

- Luna-E: Task 3 Writer integration
- Luna-F: Task 4 source+md5 checkpoint

### Wave 4(待收尾，原占位)

- Luna-G: Task 5 smoke + report fields
- Luna-H: Task 6 docs + ADR
- Luna-I: final whole-branch review

## 当前核对 — 2026-09-15（以 HEAD `7c565c9b` 为准）

### 已落地提交与证据

| 范围 | 状态 | 提交/证据 |
|---|---|---|
| Wave 0 | ✅ 完成（A2 按用户决策保留为范围外风险） | `9e641367`；共享 fixture、`_queue_lock.py`、Stage 6 调研与启动条件记录已存在 |
| Wave 1 / Task 0 | ✅ 完成 | `b744293b`；stage4/5/7 测试迁移为 async；Wave 1 聚焦验收 `123 passed / 0 failed` |
| Wave 1 / Task 1 | ✅ 已实现 | `8943f696`；`_page_id.py`、`item_index` provenance、正式 `topic_id`；同名 topic 跨 source ID 隔离测试已落地 |
| Wave 1 / Task 3 queue core | ✅ 已实现 | `c56f08eb`；稳定 `v7fail-<12hex>` ID、sanitize、provider/prompt 标签 |
| Wave 2 / Task 2 | ✅ 已实现 | `24c9bb24`；五态 `ExtractionResult`、`legacy_status`、`to_dict()`、v3 兼容层；后续 Wave 3 验收记录累计 `169/172 passed` |
| Wave 3 / Task 3 | ✅ 已实现 | `c306b552`；Writer 返回 `page_writes`，四类 gate/技术失败入 queue，非法 page ID 不再击穿 batch；提交记录 `169 passed / 0 failed` |
| Wave 3 / Task 4 | ✅ 已实现（仍有加固缺口） | `ac1ef971`；source+md5 checkpoint v2、dry-run 标记、page outcome 三列；提交记录 `172 passed / 0 failed` |
| Wave 3 / Task 5 smoke | 🟡 自动化 smoke 已加入 | `7c565c9b`；新增 `test_v7_extract_apply_smoke.py`，覆盖 raw md5、写盘、checkpoint、二次 skip、queue 去重；ADR 记录目标累计 `173 passed / 0 failed` |
| Wave 3 标签 | ✅ | `v7-control-plane-wave2`、`v7-control-plane-wave3` 均存在 |

### 本次独立验证

- `python -m compileall -q src/pipeline/v7_extract scripts/extract_full.py scripts/extract_pilot.py`：✅ exit 0。
- `git diff --check`：✅ 无 diff 错误（仅有 plan 文件 LF/CRLF 提示）。
- `scripts/extract_full.py --help`：✅ `--checkpoint` / `--json-out` / `--markdown-out` 等参数存在，但 `--root` 仍为可选 default。
- 聚焦 pytest：⚠️ 未能重跑；当前 `C:\Python314` 与项目 `.venv` 均无 `pytest` 模块（`No module named pytest`）。上表的 passed 数字是对应提交中的验收记录，不是本次重跑结果。

### 尚未闭环 / 阻断完成定义的项目

1. **Task 3 / H4 未完成：** `scripts/extract_full.py:538` 与 `scripts/extract_pilot.py:439` 仍使用 `default=DEFAULT_ROOT`，未实现缺少 `--root` 时 exit 2。
2. **Wave 0 O1 未接入：** `_queue_lock.py` 已创建，但 `extract_full.py` 没有调用 `acquire_queue_lock` / `release_queue_lock`，且未见对应回归测试。
3. **Task 4 加固未完整：** checkpoint 损坏时只回退为空对象，没有按计划备份 `.json.corrupt`；`max_attempts`/source-level 永久 attempts、provider 变更告警、`pending_checkpoint` + `atexit` flush、旧 `completed_batches` 的安全重跑仍未形成完整实现/测试。
4. **Task 5 报告契约未完整：** `extract_full` 当前主要输出 `by_status` 与 `pages`，尚未直接提供计划要求的 `written`、`blocked`、`failed`、`incomplete`、`skipped`、`generated_pages` 等 summary 字段；真实 raw source + 实际 provider 的 CLI apply/二次运行记录也未形成 smoke artifact。
5. **Task 6 未完成提交：** Stage 6 说明已改入架构文档，ADR `docs/adr/0011-v7-ingestion-outcome-control-plane.md` 已创建但仍 untracked；实施计划未见修改，主计划中 Stage 6 与 excerpt 两个 checkbox 仍未勾选，且 `audit/`、`wave3/`、`wave4/` ledger 产物目录尚未建立。
6. **Task 7 未完成：** 尚无 `v7-control-plane-final` 标签、最终 whole-branch review、R2 review artifact 或本次计划专属 memory 条目。按计划完成定义，目前只能称为“控制面重构已部分实现”，不能启动 4918/1362 source 全量 apply。

### 已知范围外风险 / 规格差异

- `_legacy.py` 仍是 placeholder；这是 Wave 0 已确认的范围外问题，本计划采用 `V7_USE_V3_CONTROL_PLANE` 作为单一回退决策，不在本次修复。
- `_extract_items()` 对 heading source 仍生成 `relative#section-N`，而计划身份表描述的是 `relative#item-N`；当前测试 fixture 也锁定了 `section-N`，后续需单独决定是否统一命名。
- 工作树中以下 dirty files 未由本次台账更新触碰：`knowledge/novel-wiki/.index/batch_build_state.json`、`scripts/_batch_report.txt`；plan/architecture 文档改动及 ADR 仍需由后续 Task 6 统一整理提交。

### 下一步顺序

1. 先补齐 Task 3/4 的上述硬缺口与回归测试，并重新安装/准备 pytest 后重跑聚焦套件。
2. 完成 Task 5 summary 字段与真实单 source apply artifact；确认 report、queue、checkpoint、Wiki 文件四者一致。
3. 完成 Task 6 文档/ADR/ledger 提交，执行 R2 review 与最终 whole-branch review。
4. 仅在 Task 7 全部通过后打 `v7-control-plane-final`；在此前保持全量 apply 禁止状态。

## 计划文件

- 计划:`docs/superpowers/plans/2026-09-15-v7-ingestion-pipeline-control-plane-refactor.md`(749 行,plan-audit 整改后)
- 对照架构:`docs/superpowers/plans/2026-09-15-v7-pipeline-architecture-v3.md`
- 对照实施:`docs/superpowers/plans/2026-09-15-v7-pipeline-v3-implementation.md`
