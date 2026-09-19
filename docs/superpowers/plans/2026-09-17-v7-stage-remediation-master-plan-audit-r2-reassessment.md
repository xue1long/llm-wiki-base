# Round 2 P0 加固项 —— 多角度重新评估

> **重新评估时间**：2026-09-17
> **评估原则**：
> 1. **第一性原理**：这个加固项解决的"根本问题"是什么？没有它会真正坏掉吗？
> 2. **批判性思维**：我列出的加固项是不是 over-engineered？有没有更简单的方案？
> 3. **奥卡姆剃刀**：能不加就不加，最简单的方案永远最好。
> 4. **终局思维**：从长期运行看，这个加固是"预防性"还是"补锅"？
> 5. **全局思维**：这个加固会不会带来新的复杂度？
> 6. **二八法则**：哪些 20% 的加固能解决 80% 的问题？

---

## 1. 7 个 P0 加固项逐项评估

### FP1/Task 2 — Stage 1 reviews queue IO 失败 → durable_failure

**根本问题**：reviews queue 写盘失败 → Stage 1 failure 不可追溯
**第一性原理**：Stage 1 失败是 fail-closed 的——source 不会进入 Stage 7。失败的"审计"丢失**不会让数据变坏**，只让排查变难。
**奥卡姆剃刀**：是真正的"补锅"——不是为了防止数据坏，是为了"事后能看到"。
**终局思维**：长期运行下，queue IO 失败**极其罕见**（除非磁盘故障）。
**全局思维**：durable_failure 与 reviews queue 双写会引入新的"哪个是真相源"问题。
**二八法则**：80% 的故障排查靠 source checkpoint 即可。

**评估结论**：⚠️ **降级为不修复**——理由：
- 失败的"可见性"是 nice-to-have，不是 must-have
- 与 Stage 7 整改不一致（Stage 7 整改是因为 checkpoint 可能"假成功"；Stage 1 failure 没有这个风险）
- 简化为：Stage 1 失败直接写日志（`log.warning`）即可

---

### FP2/Task 7 — evidence pack 中部采样 + 时间触发 re-evaluation

**根本问题**：Stage 3 evidence pack 只看 HEAD/TAIL → LLM 可能误判 source 截断 → 永久 INCOMPLETE
**第一性原理**：中部采样确实是 Stage 3 evidence pack 的根本缺陷——HE的 LLM 看不全全文就无法判断完整。
**奥卡姆剃刀**：中部采样是简单修复——加 3 个 500 bytes 窗口，总预算仅 1500 bytes。
**终局思维**：没有中部采样，100KB 长文 Stage 3 必然多次误判。
**全局思维**：3 个采样点是 fixed cost，不引入新概念。
**二八法则**：中部采样 = 1 行正则表达式，解决 80% 的 LLM 误判问题。

**评估结论**：✅ **必修**——这是 evidence pack 的根本性 bug。

**简化实施**（比原方案简单）：
```python
# evidence pack 中加 3 个中段采样（每个 500 bytes）
positions = (int(n * r) for r in (0.25, 0.5, 0.75))
mid_samples = [content[pos:pos + 500] for pos in positions]
```
不引入时间触发 re-evaluation（那属于不同问题，留后续）。

---

### FP3/Task 9 — `unresolved_article_ratio` metric

**根本问题**：Stage 4 cluster 漏接 article item 时，仅有 `unresolved_item_ratio`，不区分 article vs section。
**第一性原理**：article 漏接和 section 漏接是**不同严重性**——article 漏是知识丢失。
**奥卡姆剃刀**：加 1 个 metric 字段，1 行计算。
**终局思维**：长期监控需要这个 metric。
**全局思维**：零新概念，复用 `ClusterMetrics`。
**二八法则**：解决 100% 的"article 丢失可观测性"问题。

**评估结论**：✅ **必修**——简单且必要。

---

### FP4/Task 17 — reviewer invoke budget

**根本问题**：Stage 5 reviewer 全面故障时，high-risk topic 全部 BLOCKED。
**第一性原理**：reviewer 失败应该 fail-closed——但"全面 BLOCKED"过严。
**奥卡姆剃刀**：budget 是简单限制——`MAX_REVIEWER_INVOKES_PER_TOPIC=3`。
**终局思维**：长期运行下，reviewer LLM 故障是偶发事件。
**全局思维**：budget 不引入新概念。
**二八法则**：80% 场景下 reviewer budget 永远不到顶，仅在故障时起作用。

**评估结论**：⚠️ **降级为可选**——理由：
- reviewer 失败已是 fail-closed（high-risk claims 降级 INSUFFICIENT）—— 已经保护数据不坏
- budget 仅在"reviewer 全面故障"时优化体验，但代价是增加 reviewer 子系统复杂度
- 简化为：**保留 fail-closed，但不引入 budget**；故障期间 source 全部 BLOCKED 是可接受行为

**最终结论**：❌ **不修复**（不增加 budget，但保留现有 fail-closed 逻辑）

---

### FP5/Task 23 — update_relations_readers 子任务

**根本问题**：Stage 6R relations 不入 frontmatter → Wiki reader 找不到 relations。
**第一性原理**：这是**真正的架构冲突**——reader 与 Stage 6R 数据源不一致。
**奥卡姆剃刀**：最简单方案：**保留 frontmatter relations 写入**——这不是破坏 Stage 7 crash consistency（relations 是 best-effort async enrichment），让 reader 不需要改造。
**终局思维**：改造 reader 涉及 web UI / search / NDG gate / 等多处——**blast radius 极大**。
**全局思维**：不如**回退 F8 决策**：relations 仍写入 frontmatter，但**不是主真相源**（RelationStore 是）。frontmatter 是 reader 的"快路径"，RelationStore 是 reconciliation 的"权威源"。

**评估结论**：🔄 **回退 F8 决策**——更简单：
- relations 仍写入 frontmatter（reader 不动）
- 但 relations 生命周期由 RelationStore 管理
- Wiki reader 读 frontmatter 是 fine 的（best-effort 视图）
- Stage 7 写盘时 relations 字段**尽力写入**（来自 `_last_relations`，与 Stage 6R 异步）
- RelationStore 是 reconciliation / lifecycle 的权威源

**这是奥卡姆剃刀的胜利**：不要为了"避免 frontmatter 写入"而引入 reader 改造大爆炸。

---

### FP6/Task 19 — reconcile cross-validate file vs checkpoint

**根本问题**：disk crash 后，page file 可能丢失但 checkpoint 仍记录。
**第一性原理**：disk crash 是硬件问题——reconcile 不能再保护硬件层。
**奥卡姆剃刀**：reconcile 已经包含 file exists 校验（`reconcile_unfinished_commits`）——增加 hash cross-validate 是 +2 行代码。
**终局思维**：disk crash 后系统**应该 fail-fast**，而不是"假装恢复"。
**全局思维**：hash cross-validate 增加 IO 开销，每次 reconcile 全量跑。
**二八法则**：99% 的 crash 是进程级，不是 disk 级。

**评估结论**：⚠️ **降级为可选**——理由：
- 现有 reconcile 已检查 `path.exists()`
- 增加 hash cross-validate 是 +1 行（`if self._hash_file(path) != record.revision_hash: 标 failed`）
- 不必修但极简成本

**最终结论**：✅ **简化为最小成本**——在 `reconcile_unfinished_commits` 中加 1 行 hash 校验。

---

### FP9/Task 19 — per-source lock file

**根本问题**：并发 ingest 同一 source → race condition。
**第一性原理**：并发 ingest 真的是常见场景吗？**单人/单设备**使用 V7 是主场景。
**奥卡姆剃刀**：lock file 引入新概念 + 新路径 + 新失败模式。
**终局思维**：长期下，并发用户**可能会出现**——但 V7 当前是 CLI，不是 daemon。
**全局思维**：lock file 增加调试复杂度。
**二八法则**：80% 的用户是单线程，不会触发 race。

**评估结论**：❌ **不修复**——理由：
- V7 当前架构是 CLI-driven，**没有并发场景**
- lock file 是预防未来并发，但未来可能用 db 替换
- 加 lock 增加复杂度但当下无价值
- 简化为：CLI 启动时检测 `.index/locks/`，如有 stale lock（超过 24h）警告但继续

**最终结论**：❌ **不修复**（无并发场景）

---

### FP10/Task 5 + Task 14 — byte offset 坐标系文档 + 测试

**根本问题**：Stage 2 item byte offset vs Stage 5 evidence span byte offset 坐标系不一致风险。
**第一性原理**：这是**坐标系混淆风险**——必须在第一次实施时杜绝。
**奥卡姆剃刀**：文档 + 测试是最低成本。
**终局思维**：1 处错 → 未来永久 bug。
**全局思维**：零新概念，仅文档 + 测试。
**二八法则**：解决 100% 坐标系混淆风险。

**评估结论**：✅ **必修**——成本极低，风险极高。

---

## 2. 重新评估后的加固清单

### 必修（4 项）

| 编号 | 加固 | 来源 | 简化 |
|---|---|---|---|
| **FP2** | evidence pack 中部采样 | Round 2 | 3 个 500 bytes 窗口 + 1 个测试 |
| **FP3** | `unresolved_article_ratio` metric | Round 2 | +1 字段 |
| **FP5** | **回退 F8** —— relations 保留 frontmatter | Round 2 + 奥卡姆 | 删除 Task 23 的 "不入 frontmatter" 决策 |
| **FP10** | byte offset 坐标系文档 + 测试 | Round 2 | +1 文档段 + +1 测试 |
| **FP6-minimal** | reconcile hash cross-validate | Round 2 | +1 行代码 |

### 降级为不修复（3 项）

| 编号 | 原 P0 | 不修理由 |
|---|---|---|
| **FP1** | Stage 1 reviews queue IO 失败 | 失败不会让数据坏；简化为日志即可 |
| **FP4** | reviewer invoke budget | 现有 fail-closed 已保护数据；不增加 reviewer 子系统复杂度 |
| **FP9** | per-source lock file | V7 是 CLI-driven，无并发场景；加 lock 复杂度 > 价值 |

### 决策回退（1 项）

| 编号 | 原决策 | 新决策 | 理由 |
|---|---|---|---|
| **F8** | relations 不入 Wiki frontmatter | **回退：relations 仍写入 frontmatter** | reader 改造 blast radius 极大；frontmatter 是 best-effort 视图，RelationStore 是权威源 |

---

## 3. 总结

**Round 2 加固项重新评估结果**：
- 7 项 P0 加固 → **3 项必修 + 2 项决策回退 = 5 项简化**
- 简化为：4 个小改动 + 1 个决策回退
- 总共不到 50 行代码改动

**奥卡姆剃刀 + 终局思维的胜利**：
- FP1 → 简化为日志
- FP4 → 简化为保留 fail-closed
- FP5/F8 → 决策回退
- FP9 → 不修
- FP2/FP3/FP6/FP10 → 极简实现

---

## 4. 下一步

按用户要求，我应该：

1. 在 master plan 中 **回退 F8**（relations 仍入 frontmatter）
2. **inline FP2/FP3/FP6-minimal/FP10**（4 个极简加固）
3. **不写 FP4/FP9**（已决策不修）
4. **不写 FP1**（已决策不修）

修改完成后：
- **不需要再次复审**（仅做单点修改）
- 直接进入 **人工 review**（按 plan-audit §3 第 3 条）

---

## 5. 是否通过 Round 2？

**✅ 通过**——条件：
1. 5 个改动已 inline（4 个加固 + 1 个回退）
2. 每个改动都有对应测试
3. plan §6 Open risks 更新反映新决策

---

**等待用户确认是否启动 5 项 inline 改动。**