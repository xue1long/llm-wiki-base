# V7 Stage 2 + lineage 解锁 — code-review 阶段 3 报告（2026-09-19）

**Review 范围**: `0fc893e7` → `eeab468a`（5 commits，17 文件，+2132 / -32 行）
**Spec**: `docs/superpowers/plans/2026-09-19-v7-stage2-i5-lineage-unblock.md`
**Standards**: AGENTS.md / CONTEXT.md / dev-relay / ponytail skill（已注入 + 直接 read）
**审查方法**: 双轴 parallel sub-agent（code-review skill Step 4）

---

## Standards 轴（sub-agent e100c0fe）

### V1: lineage/api.py 跨层 import 私有错误类 — **FIX**
- 位置: `src/lineage/api.py:758` `from ..lib.errors import DataConsistencyError`
- 违反: AGENTS.md "模块化永久约束：禁止跨模块导入 service/model/utils 内部文件"
- 修复: 在 `src/lineage/types.py` 加 `from src.lib.errors import DataConsistencyError` 并 re-export；lineage/api.py 改 `from .types import DataConsistencyError`
- 优先级: **立刻修**（直接违反 AGENTS.md 模块化永久约束 + dev-relay §3）

### V2: cdb274ed fast-track 绕过 plan-audit 两轮审查 — **ACCEPT with record**
- 违反: AGENTS.md + dev-relay §3 "方案在进入阶段 2 之前必须先过 plan-audit 两轮审查"
- 现实: commit 已落地不可逆；memory feedback 已显式承认"fast-track 修复实测无效"
- 处置: **接受既成事实**，在 ADR-0015 与本文件中**显式记录为反例**；后续 fast-track 改动须声明是 plan-audit 复审的 `## Round 0 紧急补丁` 而非新方案

### S1: Shotgun Surgery — **ACCEPT（judgment call）**
- 4 处 method body 仍复制 `recovery_log` fallback 8 行模板
- helper 已经最大努力去重 INSERT；再抽 `_append_recovery_log` 会跨入 "Speculative Generality" 反模式（ponytail 禁）
- 接受现状

### S2: Mysterious Name — **FIX with doc only**
- `_safe_insert_artifact_sources` 名过宽，实际只吞 FK + UNIQUE
- 改名 `_deduped_insert_artifact_sources` 会破坏 import 路径与测试 fixture
- 接受 docstring 补 "swallows only FK orphan + UNIQUE dup；raises other IntegrityError"（已有类似描述）

### S3: Speculative Generality (MAX_TAIL_GAP_BYTES) — **ACCEPT**
- ADR-0015 已 deferred quality_settings.json 项目级配置
- 接受 deferred（plan P1 已记录）

**Standards 轴 worst: V1**

---

## Spec 轴（sub-agent 948a9952）

### M1: 1025 边界 fixture 缺失 — **FIX**
- spec ref: plan:186-188 "构造 fixture `gap == 1025` 字节 → 断言 status=DEGRADED"
- 当前: `test_tail_residue_threshold_boundary_1024_includes_exact` 只测 1024
- 修复: 加 `test_tail_residue_threshold_boundary_1025_degrades` fixture（1025 bytes gap → status=DEGRADED）

### M2: "4 个新测试" 数量偏差 — **ACCEPT with note**
- spec ref: plan:191 "4 个新测试 + 阈值边界 2 条 = 6 个新测试"
- 实际: 12 条新测试（含 P0 加固 hasattr + 3 状态枚举）
- 处置: plan "4 + 2 = 6" 是 round 1 写时的初稿，**未与 P0 加固同步更新**；多出 6 条是功能增强不是 scope creep；下次 plan 写测试数量时按 P0/P1 同步

### M3: Stage 5 排查缺失 §Open risks 显式列条目 — **ACCEPT（轻微）**
- ADR-0015:51-52 已记录 "Stage 5 上游 source_ids 产生逻辑未排查… 后续 plan 单独处理"
- plan §Open risks 表只列了 "MAX_TAIL_GAP_BYTES 必须通过 quality_settings.json 覆盖"
- 处置: 接受（ADR 已 apply），下次 plan §Open risks 表格列出全部 deferred 排查项时再补

### C1: cdb274ed — **NOT CREEP**（spec 显式"保留"非目标）

### C2: book_releases 路径无回归测试 — **FIX**
- spec ref: plan §Test-first line 335-339 只列 4 条
- 当前: `_recover_book_releases` + `record_book_release` 改用 helper 但**无测试**
- 修复: 加 2 条测试覆盖 book_releases 路径（dirty data → recovery_errors.log；正常 release → 不写 log）

### C3: 4 处 "Plan: …" 引用 docstring — **ACCEPT**（dev-relay 惯例）

### W1: UNIQUE 异常分支死代码 — **FIX**
- `INSERT OR IGNORE` 已吞 UNIQUE，helper 内 `elif "UNIQUE constraint"` 永远不触发
- 修复: 加 `errors.append((sid, "UNIQUE violation"))` 的同时，给 SQLite 老版本/不同 PRAGMA 配置做防御记录——**保留代码但加注释说明**；或改为**显式测试**这条分支（用 SQL 触发 UNIQUE 后 verify helper 收到 errors）

### W2: link_artifact UNIQUE 静默吞 — **ACCEPT（spec 允许）**
- spec: "UNIQUE violation 不抛（运行态不应有 UNIQUE）"
- 实际: `INSERT OR IGNORE` 吞掉，无测试覆盖
- 处置: 与 W1 同一修复——加防御测试

### W3: Task 3 "整体 exit=0" 验收证据不完整 — **FIX**
- spec ref: plan:382 "python -X utf8 scripts/run_v7_5x.py 整体 **exit=0**"
- 当前: memory feedback 只记 per-file PASS，未记 run_v7_5x.py 退出码
- 修复: 重跑 `run_v7_5x.py` 并 capture exit code；补到 memory feedback

**Spec 轴 worst: W3**

---

## 总判定与下一步

| 轴 | Hard violations | Judgement calls | Missing | Scope creep | Looks wrong |
|---|---|---|---|---|---|
| Standards | 2（V1 FIX, V2 ACCEPT） | 3（ACCEPT 2, FIX doc 1） | — | — | — |
| Spec | — | — | 3（M1 FIX, M2/M3 ACCEPT） | 3（C1 NOT, C3 ACCEPT, C2 FIX） | 3（W1/W2 FIX test, W3 FIX） |

### 要修的项（共 7 项）

1. **V1**: lineage 跨层 import → `src/lineage/types.py` re-export
2. **S2**: helper docstring 加"只吞 FK + UNIQUE"说明
3. **M1**: 加 1025 字节 → DEGRADED 边界 fixture
4. **C2**: 加 book_releases 路径 2 条测试
5. **W1**: 加 helper UNIQUE 防御测试
6. **W2**: 加 link_artifact UNIQUE 防御测试
7. **W3**: 重跑 run_v7_5x.py 并 capture exit code

### 接受的项（共 4 项）

- **V2** (fast-track 记录反例) — 已 memory 记录
- **S1** (Shotgun Surgery) — judgement call
- **S3** (MAX_TAIL_GAP_BYTES deferred) — ADR 已记录
- **M2/M3** (数量偏差 + Stage 5 Open risks 表格不全) — 轻微，ADR 已 apply
- **C1/C3** (scope creep) — 都不是实质 creep

---

## 实施顺序

按依赖 + 风险排序：

1. **W3** 先做（成本最低、最具体）—— 重跑 `run_v7_5x.py` capture exit code，补 memory feedback
2. **V1**（最严重 hard violation）—— lineage re-export
3. **M1**（spec 明文要求）—— 1025 fixture
4. **W1 + W2**（测试覆盖）—— UNIQUE 防御测试
5. **C2**（测试覆盖）—— book_releases 路径测试
6. **S2**（最低风险）—— docstring 加说明

全部预计 < 30 分钟（测试 + 1 个 re-export + 几条 fixture）。

---

## 关联文档索引

- Plan: `docs/superpowers/plans/2026-09-19-v7-stage2-i5-lineage-unblock.md`
- Audit-r1: `docs/superpowers/audits/2026-09-19-v7-stage2-i5-lineage-unblock-audit-r1.md`
- Audit-r2: `docs/superpowers/audits/2026-09-19-v7-stage2-i5-lineage-unblock-audit-r2.md`
- ADR: `docs/adr/0015-v7-stage2-tail-residue-classification.md`
- 实施 memory: `.memory/feedback-v7-stage2-i5-lineage-fix-2026-09-19.md`
- 前置 memory: `.memory/feedback-v7-stage3-asr-prompt-fix-2026-09-19.md`

---

## FIX 实施结果（2026-09-19 收尾）

7 项 FIX 全部实施完成：

| # | finding | 实施 |
|---|---|---|
| **W3** | 整体 exit code 未留痕 | 重跑 `python -X utf8 scripts/run_v7_5x.py` → **5 PASS / 0 FAIL，EXIT_CODE=0**（见下方 evidence） |
| **V1** | lineage 跨层 import | `src/lineage/types.py` 加 `from ..lib.errors import DataConsistencyError` re-export；`api.py` 改 `from .types import DataConsistencyError`（`grep 'from ..lib.errors' src/lineage/api.py` → 0 命中） |
| **M1** | 1025 边界 fixture 缺失 | 新增 `_segment_with_exact_tail_gap()` helper 走**真实** `wrap_items_as_segmentation_result` 状态决策；`test_tail_residue_threshold_boundary_1024_includes_exact`（重写，去 placebo）+ `test_tail_residue_threshold_boundary_1025_degrades` |
| **W1** | UNIQUE 分支死代码 | **删除**该死分支（`INSERT OR IGNORE` 已吞 UNIQUE）；新增 `test_helper_silently_skips_row_already_linked` 证明跨调用 UNIQUE 静默吞（`errors == []`） |
| **W2** | link_artifact UNIQUE 无测试 | 随 W1 消解——helper 不再返回 UNIQUE errors，`link_artifact` 简化为 `if orphans:` 判定 |
| **C2** | book_releases 路径无测试 | 新增 `test_book_release_recovery_logs_orphan_source`（孤儿 → recovery_errors.log，不再崩）+ `test_record_book_release_links_sources_without_recovery_log`（正常路径不写 log） |
| **S2** | helper 名过宽 | docstring 重写：明确"只吞 FK violation，UNIQUE 不可能出现且不报告，其他 IntegrityError 传播" |

**验证**：
- `tests/test_lineage/` **41 → 43 passed**（+2：UNIQUE 静默 + book release ×2，实际 +3 减去合并）
- `tests/test_lineage/ + tests/test_pipeline/` = **1192 passed / 10 failed**
- 10 failed 与改动前完全一致（runbook §9 坑 6 已知基线）
- 零回归

### W3 evidence（run_v7_5x.py 整体退出码）

```
[1/5] 视频-南派三叔1.md          smoke exit=0  verify exit=0
[2/5] 写作十大技巧.md            smoke exit=0  verify exit=0
[3/5] 小小说写作技巧1-2讲.md      smoke exit=0  verify exit=0
[4/5] 人物形象写作技巧-1.md       smoke exit=0  verify exit=0   (pages=3, llm=5)
[5/5] 02进阶/大纲写作技巧.md      smoke exit=0  verify exit=0

汇总: 5 PASS / 0 FAIL / 0 UNKNOWN
EXIT_CODE=0
```

Spec §Task 3 Acceptance "python -X utf8 scripts/run_v7_5x.py 整体 exit=0" **已满足**。

### 接受未修的项（记录理由）

- **V2** fast-track 绕过 plan-audit：commit 已落地不可逆；已在本文档 + ADR-0015 显式记录为反例
- **S1** Shotgun Surgery（4 处 recovery_log fallback 模板）：judgement call；再抽 helper 会跨入 Speculative Generality（ponytail 禁）
- **S3** MAX_TAIL_GAP_BYTES hard-code：ADR-0015 已 deferred `quality_settings.json` 项目级配置
- **M2** 测试数量与 plan 文字偏差：plan "4+2=6" 是初稿，P0 加固未同步更新（实际更强）
- **M3** Stage 5 排查未列入 plan §Open risks 表格：ADR-0015 Consequences 已记录
- **C1/C3** scope creep：C1 是 pre-base fast-track；C3 是 dev-relay 惯例注释