# V7 Stage 2 I5 TAIL_RESIDUE + lineage UNIQUE 修复 — 实施完成报告（2026-09-19）

## Plan + 实施路径

`docs/superpowers/plans/2026-09-19-v7-stage2-i5-lineage-unblock.md`（4 Task）

| 阶段 | 内容 | commit |
|---|---|---|
| 阶段 1 方案 + plan-audit | plan 草稿 + Round 1（致命 2 / 重大 5）+ Round 1 复审（3 新发现）+ Round 2 压力测试（PASS with P0 FIXES）+ 人工复核通过 | audit 文件未 commit（阶段 1 产物） |
| 阶段 2 Task 1 | Stage 2 TAIL_RESIDUE 状态 + boundary_confidence=1.0 | `101fde39` |
| 阶段 2 Task 2 | lineage helper + 4 处 executemany 修复 | `0c461a5f` |
| 阶段 2 Task 3 | 5 跑实测 5/5 PASS | — |
| 阶段 2 Task 4 | ADR-0015 + memory feedback + MEMORY.md 索引 | 本文件 + ADR + index |

## Task 1（commit `101fde39`）—— Stage 2 TAIL_RESIDUE

### 问题
- novel-wiki-v2 上 4/5 个 ASR 转录稿被 Stage 3 判 incomplete，无法产出页面
- Stage 2 invariant I5 严格 byte accounting 让 ASR 稿末尾留几十字节 → `status=degraded / boundary_confidence=0.5`
- Stage 3 LLM 把这两个**结构化信号**当硬否决条件，prompt 文字不生效（前置 commit `cdb274ed` 实测证明）

### 修复
- `invariants.py`: `InvariantReport` 新增 `i5_gap_at_tail: bool` + `i5_gap_bytes: int`（不影响 `all_pass` 计算）
- `segmentation.py`: 新增 `SegmentationStatus.TAIL_RESIDUE = "tail_residue"`；触发条件 = I5 不过 + 末尾 gap `<= MAX_TAIL_GAP_BYTES=1024` + I4 通过
- `build_structural_summary` 改 `boundary_confidence` 按 status 计算：SEGMENTED / SINGLE_EXPECTED / **TAIL_RESIDUE** → 1.0，其他 → 0.5

### 测试
- 5 个 invariants 测试（含 hasattr hard check 防接手 dev 漏改 — Round 2 P0 加固）
- 5 个 stage2 测试（含 1024 阈值边界 case）
- 1 个 completeness_checker 端到端断言（evidence pack 文本含 `status=tail_residue` + `boundary_confidence=1.0`）
- 既有 14 个 stage2 + 22 个既有 completeness_checker 测试不变回归
- 既有 `test_v7_extract_segmentation.py` 的 2 处 status 断言加 TAIL_RESIDUE 兼容

## Task 2（commit `0c461a5f`）—— lineage UNIQUE 修复

### 问题
- V7 bridge 成功后调 `commit_ingest` → `LineageStore.open` → `_recover_pending` 撞 `sqlite3.IntegrityError: UNIQUE constraint failed: artifact_sources.artifact_id, source_id`
- 根因：candidate 路径历史脏数据（kb-20260918145517 留下的 `pending_wiki_commits` 含重复 source_id）
- 单一 SQLite 撞 → 整个事务回滚 → 0 wiki 写入

### 修复
- 新增 helper `_safe_insert_artifact_sources(db, artifact_id, source_ids) -> list[tuple[source_id, error_msg]]`
  - `set()` 去重（防脏数据重复 source_id）
  - `INSERT OR IGNORE` 吞 UNIQUE（防御性记录）
  - 显式 catch FK 违反 → log warning + 错误列表（不抛）
  - 真正未知 IntegrityError → raise 让上层处理
- `_recover_pending` 重构：决策表（file 缺失 → 保留 / INSERT 成功 → DELETE / 部分失败 → DELETE + 写 recovery_errors.log / 异常 → 保留）；DELETE 移 try/except 外 + 条件性
- `recovery_errors.log` 写入包 try/except OSError（Round 2 P0 加固场景 2 磁盘满）
- 4 处 executemany 改用 helper：
  1. `_recover_pending`（line 148）：写 recovery_errors.log
  2. `_recover_book_releases`（line 197）：写 recovery_errors.log
  3. `record_book_release`（line 514）：errors 走 log warning
  4. `link_artifact`（line 609，**运行态写路径**）：FK 孤儿抛 `DataConsistencyError`（让 `commit_ingest` 失败让运维可见）

### 测试
- 6 个新 wiki_recovery 测试（含 log 写失败兜底 + 文件缺失保留 pending）
- 既有 `test_store_enables_foreign_keys` 断言从 `sqlite3.IntegrityError` 改为 `DataConsistencyError`
- 40 lineage 测试全绿；1188 pipeline 测试 = 10 failed（与改动前完全一致的已知基线 runbook §9 坑 6）

## Task 3 —— 5 跑实测 5/5 PASS

| # | 文件 | status | pages | llm |
|---|---|---|---|---|
| 1 | 视频-南派三叔1.md | ✓ succeeded | 2 | 5 |
| 2 | 写作十大技巧.md | ✓ succeeded | 2 | 4 |
| 3 | 小小说写作技巧1-2讲.md | ✓ succeeded | 2 | 4 |
| 4 | 人物形象写作技巧-1.md | ✓ succeeded | 2 | 4 |
| 5 | 02进阶/大纲写作技巧.md | ✓ succeeded | 2 | 4 |

**5 条判据全 PASS**（`scripts/verify_v7_ingest.py`）：
- 判据 1 succeeded + 有页面：5/5
- 判据 2 health H1/H2/H4/H5=0：✓
- 判据 3 wiki-quality --strict 无 error：✓
- 判据 4 幂等性：✓（source 文件 md5 未变）
- 判据 5 失败显式标记：✓（无静默成功）

**wiki/concepts/ 从 8 → 13 个新页面**（含之前 candidate 失败遗留的 `8471759c-大纲写作技巧-2c0627c4.md` 现在能写盘）
**pending_wiki_commits 表清空**（历史脏数据被自动清理；本次 5 跑没产生新脏数据）
**recovery_errors.log 未创建**（本次 5 跑 source_ids 都有效，无 FK 孤儿）

## ADR-0015 决策（`docs/adr/0015-v7-stage2-tail-residue-classification.md`）

- **Context**: 解释 I5 严格性 + ASR 烂尾特征 + LLM 信任结构化信号不信任 prompt 文字的发现
- **Decision**: 保留 I5 严格性 + 新增 TAIL_RESIDUE 状态 + boundary_confidence 按 status 算
- **Alternatives**: A(chosen) / B(改 I5 容差) / C(改 prompt，已 commit `cdb274ed` 但无效) / D(Stage 1 加 ASR 识别 deferred)
- **Consequences**: 含 Round 2 P0/P1 全部 9 个压力点的风险记录（MAX_TAIL_GAP_BYTES 跨项目不可移植、SQLite 版本约束、Stage 5 上游未排查）
- **Trigger to Revisit**: 阈值误判 / 项目级配置需求 / Stage 5 系统性产生重复 source_id

## dev-relay 流程复盘

阶段 1 阶段 1 路径（mattpocock 关闭 ponytail）→ 阶段 2 编码（ponytail full 开启）：

- 阶段 1 严格遵守 plan-audit 两轮 + 人工复核通过才进阶段 2
- 阶段 2 用 TDD per-task（write 测试 RED → 实施 GREEN → commit）保证不破坏既有契约
- 既有的 10 failed 测试与改动前完全一致（runbook §9 坑 6），证明零回归

## 后续 plan（不属本次）

按 Round 2 压力测试标记的 P1 / P2：

1. **MAX_TAIL_GAP_BYTES 通过 `quality_settings.json` 项目级配置覆盖**（方案 A 简化版）
2. **Stage 5 上游 source_ids 产生逻辑排查**（helper 让 FK 显式可见，但根因未修）
3. **SQLite 版本约束写入 requirements.lock**
4. **reviewer quota / 限流排查**（Round 2 场景 3 限流样本不足）

## 关联文档索引

- Plan: `docs/superpowers/plans/2026-09-19-v7-stage2-i5-lineage-unblock.md`
- Audits: `docs/superpowers/audits/2026-09-19-v7-stage2-i5-lineage-unblock-audit-{r1,r2}.md`
- ADR: `docs/adr/0015-v7-stage2-tail-residue-classification.md`
- 前置 memory: `.memory/feedback-v7-stage3-asr-prompt-fix-2026-09-19.md`（根因调研）
- Runbook: `docs/ops/handoff-v7-stage1-remote.md`（V7 Stage 1 灰度观察 runbook）

## V7 Stage 1 灰度状态

- Stage 3 prompt v1.2 + Stage 2 TAIL_RESIDUE + lineage UNIQUE 修复 = V7 在 novel-wiki-v2 上 5/5 PASS
- 等待：3 天观察期满用户决定是否进 Stage 2（改默认 `RUFLO_PIPELINE_MODE=candidate` → `v7`）
- 建议：如进入 Stage 2，建议**先做** quality_settings.json MAX_TAIL_GAP_BYTES 项目级配置（避免跨项目误判）