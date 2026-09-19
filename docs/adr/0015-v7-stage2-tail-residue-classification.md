# ADR: V7 Stage 2 用 TAIL_RESIDUE 显式分类替代"改 I5 容差"

- **状态**: accepted
- **日期**: 2026-09-19
- **触发**: V7 在 novel-wiki-v2 上 4/5 个 ASR 转录稿被 Stage 3 判 incomplete，无法产出页面；Stage 3 prompt v1.2 ASR 例外条款（commit `cdb274ed`）实测证明不生效——LLM 把 Stage 2 结构化信号当硬否决条件。
- **关联**: `docs/superpowers/plans/2026-09-19-v7-stage2-i5-lineage-unblock.md` Task 1；plan-audit 两轮 + 人工复核通过

## Context

V7 7 阶段摄取管线在 novel-wiki-v2 上表现：

- 218 个 raw 全部为 ASR 转录稿（音频转录文字）
- Stage 2 deterministic splitter 切完后**末尾常留几十字节**（ASR 错误字符 / 标点 / 无效段落）
- Stage 2 invariant **I5 严格 byte accounting** 要求 `sum(item spans) == source bytes`，**末尾 gap → I5 不过**（`byte_accounting = 0.9995~1.0`）
- `invariants.all_pass = False` → `SegmentationStatus.DEGRADED` → `boundary_confidence = 0.5`（硬编码）
- Stage 3 LLM 看到 `status=degraded + boundary_confidence=0.5` 判 incomplete（即便 prompt 文字说 ASR 例外）
- 结果：**V7 在 novel-wiki-v2 上几乎不出页面**

## Decision

1. **保留 I5 严格性** —— 不放宽 `total == source_bytes` 的契约（设计原则是 byte-perfect 精确性）
2. **`InvariantReport` 新增两个描述性字段** `i5_gap_at_tail: bool` + `i5_gap_bytes: int`（不影响 `all_pass` 计算）
3. **`SegmentationStatus` 新增 `TAIL_RESIDUE = "tail_residue"`** —— 触发条件：I5 不过 + 末尾小 gap（`<= MAX_TAIL_GAP_BYTES = 1024`）+ I4 通过
4. **`build_structural_summary` 的 `boundary_confidence` 改为按 status 计算** —— TAIL_RESIDUE / SEGMENTED / SINGLE_EXPECTED → 1.0；其他（DEGRADED / FAILED / UNCERTAIN）→ 0.5
5. **不修改 Stage 3 prompt** —— ASR 例外 v1.2 已保留作为 LLM 软指引，但**真正的硬信号**靠 Stage 2 status + `boundary_confidence`

## Rationale

- **源头修复**：status + boundary_confidence 是 Stage 3 LLM 实际阅读的硬信号；改 prompt 只影响 LLM 软指引（实测证明无效）
- **保留 I5 契约**：I5 严格性是 Stage 5 `CanonicalSpan` / Stage 7 `revision_hash` byte-anchored 协调的基础；放宽 byte accounting 会污染下游 byte offset 坐标系
- **新增 TAIL_RESIDUE 而非复用 DEGRADED**：语义清晰，Stage 3/Stage 7 消费者可明确判断"自然结束" vs "真分段 bug"
- **1KB 阈值是经验值**：ASR 烂尾特征是几十字节；真分段 bug 通常 gap 远大于此。后续按项目调整可通过 `quality_settings.json` 覆盖（**待实现**）

## Consequences

### 更简单
- Stage 3 LLM 看到 `status=tail_residue + boundary_confidence=1.0` → 判 complete（5 跑实测 5/5 PASS）
- 解决了 novel-wiki-v2 上 V7 "几乎不出页面" 的系统性问题
- I5 严格性保留——下游 byte offset 协调未受影响

### 更复杂 / 风险
- **MAX_TAIL_GAP_BYTES = 1024 是经验值**，跨项目不可移植（Round 2 场景 8 压力点）。后续 plan 实现 `quality_settings.json` 项目级配置覆盖
- **Stage 5 上游 source_ids 产生逻辑未排查**（Round 2 场景 7 压力点）。lineage 修复了运行态 FK 显式抛 DataConsistencyError，但**没排查 Stage 5 是否系统性产生重复 source_id**；后续 plan 单独处理
- **SQLite 版本约束**：helper 依赖 SQLite ≥ 3.6.19（`INSERT OR IGNORE` 对 FK 行为正确抑制）；老 SQLite dev box 可能静默腐败。需在 `requirements.lock` 标注

### Trigger to Revisit

- 阈值 1024 实测发现误判（如某项目 ASR 文件末尾有 2KB HTML 标题残值被误分类）→ 改阈值或按比例式 `gap_ratio < 0.005`
- 跨项目复现显示 threshold 不一致 → 实现 `quality_settings.json` 项目级配置
- Stage 5 上游确认产生重复 source_id → helper 改 log + 抛 warning（不抛 DataConsistencyError，因为是上游问题）

## Alternatives Considered

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **A. Stage 2 用 TAIL_RESIDUE**（**chosen**）| 源头修复；信号清晰；保留 I5 严格性 | 需新增 status + 字段；阈值需调 | ✅ chosen |
| **B. 改 I5 容差**（如 `byte_accounting >= 0.999`）| 一行代码；简单 | 破坏 I5 byte-perfect 设计；下游 byte offset 坐标系被污染；阈值魔数 | ❌ rejected |
| **C. Stage 3 prompt 教 LLM 忽略信号**（已 commit `cdb274ed` v1.2）| 无代码改动；纯 prompt | 实测证明 LLM 不遵守——它把结构化信号当硬条件 | ❌ rejected（已落地但效果为零） |
| **D. Stage 1 加 ASR 识别**（is_asr_transcript: bool 信号）| 信号明确 | 改 Stage 1 prompt + Stage 2 信号 + Stage 3 prompt；改动面 = 3 个 prompt；投入 4-6 小时 | ⏸ deferred（与本 ADR 互补可叠加，但当前方案已足够解决 novel-wiki-v2 问题） |

## References

- `docs/superpowers/plans/2026-09-19-v7-stage2-i5-lineage-unblock.md` Task 1
- `docs/superpowers/audits/2026-09-19-v7-stage2-i5-lineage-unblock-audit-r1.md`（致命 2 / 重大 5 / 优化 6 / 盲区 7）
- `docs/superpowers/audits/2026-09-19-v7-stage2-i5-lineage-unblock-audit-r2.md`（PASS with P0 FIXES）
- `.memory/feedback-v7-stage3-asr-prompt-fix-2026-09-19.md`（前置：Stage 3 prompt 修复不生效的根因调研）

## Implementation Notes

- **实施 commit**: `101fde39 fix(v7-stage2): TAIL_RESIDUE status for end-of-source deterministic gaps`
- **测试**: 5 个新 invariants 测试 + 5 个新 stage2 测试（含 1024 阈值边界）+ 1 个新 completeness_checker 端到端断言 = 11 个新测试全绿；24 个既有 stage2 + invariants 测试不变回归
- **5 跑实测**（Task 3）: novel-wiki-v2 5/5 PASS，wiki/concepts/ 从 8 → 13 个页面，pending_wiki_commits 表清空
- **未来改进入口**: `quality_settings.json` 项目级配置覆盖 `MAX_TAIL_GAP_BYTES`（建议独立 plan）