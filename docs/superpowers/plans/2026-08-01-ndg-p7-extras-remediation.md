# NDG P7 extras 语义修正 — 落地方案（挂靠 R1-2 / R2-2）

> **依据**：batch 0（2026-08-01）门禁验证暴露 P7 误报 6 例（夔/猰貐/穷奇/共工/白虎/中国神话人物）；
> 独立第三方审计指出原 P7 修正方案有致命缺陷（漏 B6、方向与 R1-2 相反、来源假设未验证）。
> 本方案是**修正后的落地方案**，挂靠 `2026-08-01-ingestion-gate-ndg-remediation.md` 的
> R1-2（extras 归 reconcile 管理）与 R2-2（commit 循环重写），不引入独立补丁。
>
> 本计划立项时不写代码，遵守 CLAUDE.md：TDD-per-task + 一次一 commit + per-task reviewer。

---

## 审计结论 → 本方案回应

| 审计发现 | 本方案处置 |
|---|---|
| F1 漏改 B6，P7 放行后 B6 再拦 | B6 只检查批页 `result.pages`，extras 移出覆盖保护 |
| F2 "命中批页→blocker" 与 R1-2 方向相反 | 删除该分支；命中批页的 extra 由 R1-2 折入批页（A3 根治） |
| F3 P7 无来源信息，判定靠猜 | P7 改为**内容校验**：`extra.body == 磁盘 body`（仅 relations 差异）→ 放行 |
| M1 跨批 A3 复发 | R1-2 折入批页 + extras 单独 commit，写回顺序确定（extras 最后、内容已校验） |
| M2 reconcile 折叠 body 冲突未定义 | R1-2 定义：同 id extras 仅当 body 相同才折叠 relations；body 不同 → 保留首个 + warning |
| M4 extras 写回无独立审计 | R2-2 B9：extras `commit_ingest(event="reverse-relation")` |
| 信息盲区 | 已补齐（见下） |

**已确认的信息盲区**：
1. extra 来源唯一：`_compute_reverse_relations`（`ingest.py:1073`），body 从磁盘 `read_page` 读入 → 与磁盘 body 一致（仅 relations 不同）。✅
2. `reconcile_batch` 当前把 extras 原样 append 到 `result.pages` 末尾（`batch_reconcile.py:251-253`），phase4 用 `len(all_extra)` 切片切出——脆弱假设，R1-2 一并移除。✅
3. `append_to_index` 按 slug 去重幂等（`indexer.py`），但 `write_page` 覆盖磁盘页 body。✅
4. phase4_batch 单进程串行批，无批间并发；但 archive 可能独立跑（约束见 R2-2）。✅

---

## 执行顺序（依赖硬约束）

```
R1-2a  ReconcileResult 分离 extras + 命中批页折入 + body 冲突规则
R1-2b  phase4_batch 删预去重 + 删 len(all_extra) 切片，用 result.pages/result.extras
P7     ndg_gate P7 改内容校验（extra.body == 磁盘 body）
B6     phase4_batch B6 只查 result.pages（extras 移出）
R2-2a  extras 单独 commit（event="reverse-relation"）
R2-2b  B6 后置验证 + batch 0 实测
```

---

## R1-2a — ReconcileResult 分离 extras + 折入

- **Files**：`src/wiki/features/batch_reconcile.py`
- **Tests**（`tests/test_wiki/test_batch_reconcile.py` 扩展）：
  - 两个同 id extra（body 相同）→ 保留一个、relations 并集（B2 回归）。
  - 两个同 id extra（body 不同）→ 保留首个 + warning，不静默折叠（M2 约束）。
  - extra 的 `(id,type)` 命中合并后批页 → **extra 丢弃、relations 折入批页**、合并计 1（A3 回归：批页新内容存活）。
  - 无碰撞 extra → 保留在 `result.extras`，**不混入 `result.pages`**。
  - `result.pages` 只含批页；`result.extras` 只含保留的 extra。
- **Implementation guidance**：
  - `ReconcileResult` 增 `extras: list[WikiPage] = field(default_factory=list)`。
  - 合并后：建 `batch_by_id = {(p.id, p.type): p}`；遍历 `extra_pages`——
    - 命中批页 → 用 `_fold_relations(batch_page, extra.relations)`（按 `(target_id, type)` 去重、weight 高者胜，复用现有合并逻辑）→ `merged.append(...)`；
    - 未命中 → 同 id extras **仅 body 相同才折叠 relations**（body 不同保留首个 + `_log` warning），留一个进 `extras`。
  - **移除** `Step 3: append extra_pages (unmerged)`（`:251-253`）。
- **Commit**：`fix(wiki): ReconcileResult 分离 extras + 命中批页折入（A3/B2/M2）`

---

## R1-2b — phase4_batch 删预去重 + 删切片

- **Files**：`scripts/phase4_batch.py`
- **Tests**：`tests/test_wiki/test_phase4_batch.py` 新增（monkeypatch `reconcile_batch`）——
  断言 gate 收 `result.pages`、`result.extras` 分别传参，不再用 `len(all_extra)` 切片。
- **Implementation guidance**：
  - 删除 `:298-305` 的 `_deduped_extra` 预去重（归 reconcile 管）。
  - 删除 `:333-334` 的 `_batch_page_count`/`_gate_extras` 切片；直接用 `result.pages` / `result.extras`。
  - `run_ndg_gate(result.pages, extra_pages=result.extras, ...)`。
- **Commit**：`refactor(scripts): phase4_batch 用 result.pages/result.extras，删脆弱切片`

---

## P7 — ndg_gate 内容校验

- **Files**：`src/wiki/features/ndg_gate.py`
- **Tests**（`tests/test_wiki/test_ndg_gate.py`）：
  - extra 命中磁盘非 stub 且 `extra.body == 磁盘 body`（仅 relations 差异）→ **放行**（batch 0 场景）。
  - extra 命中磁盘非 stub 且 `extra.body != 磁盘 body` → blocker（真覆盖）。
  - extra 命中磁盘 stub → 放行（stub 升级，保持现状）。
  - extra 命中批页 → 不再由 P7 处理（R1-2 已折入），P7 不拦。
- **Implementation guidance**：
  - `_check_p7_extra_pages` 读取磁盘页，比对 `ep.body == existing.body`（**仅允许 relations 差异**，body 必须逐字节一致）。
  - body 一致 → 放行（反向边更新是预期）；body 不一致 → blocker（除非 `--allow-overwrite`）。
  - 命中批页的 extra：R1-2 已折入，正常到 P7 的都是残留 extra，此分支不再需要。
- **Commit**：`fix(wiki): P7 改内容校验——extra.body==磁盘 body 放行，真覆盖仍拦`

---

## B6 — phase4_batch 覆盖保护只查批页

- **Files**：`scripts/phase4_batch.py`
- **Tests**：构造含 extras 的批 → B6 只对 `result.pages`（批页）报覆盖，extras 不报。
- **Implementation guidance**：`_check_overwrite_protection(result.pages, ...)`——**只传批页**，extras 移出（它们由 P7 内容校验 + R1-2 管理）。
- **Commit**：`fix(scripts): B6 覆盖保护只查批页——extras 移出（与 P7 一致）`

---

## R2-2a — extras 单独 commit

- **Files**：`scripts/phase4_batch.py`
- **Tests**：monkeypatch `commit_ingest`——断言 extras 用 `event="reverse-relation"` 单独调用一次。
- **Implementation guidance**：commit 循环后，`if result.extras: await commit_ingest(paths, Path("(batch-reconcile)"), [], result.extras, task_id, event="reverse-relation")`。
- **Commit**：`feat(scripts): extras 单独 commit——reverse-relation 独立审计事件（B9）`

---

## R2-2b — batch 0 实测

- 前置：R1-2a/b + P7 + B6 + R2-2a 全绿。
- 重跑 `phase4_batch.py --batch 0`：预期 P7 6 例全部因 body 一致放行，批 commit 落盘。
- 验收：wiki 页数增加、batch_build_state `batch_0.status="committed"`、`extras` 以 `reverse-relation` 事件记录。
- **并发约束**：批跑期间不并行 `archive`/`batch_build`（避免磁盘页竞态，E4）。文档化。

---

## 验收总目标

- A3 场景（extra 命中批页）→ 折入批页，批页新内容存活。
- B2 场景（同 id extras）→ relations 并集，不丢边。
- batch 0 场景（extra.body==磁盘 body）→ P7 放行，批通过。
- 真覆盖（extra.body != 磁盘 body）→ 仍被拦（P7/B6 兜底）。
- extras 写回有独立 `reverse-relation` 审计事件。
- 全部测试通过（test_wiki / test_pipeline / test_scripts）。
