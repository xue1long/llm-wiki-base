# V7 Replace Plan 选择综合决策（grilling 后）

## 6 框架打分

| 维度 | A: 立即全量 | B: 灰度 + 删除 | C: opt-in 保留 | D: 更多 pre-work |
| --- | --- | --- | --- | --- |
| 第一性原理 | 假设 V7 在生产能跑 | 唯一直接验证假设 | 不验证 | 不验证 |
| 批判性思维 | 9 个未验证假设（v3 成本、限速、F5/F9 audit bug） | 1 个假设（1 周够长） | 假设用户会用 opt-in | 假设 pre-work 边际收益 > 0 |
| 奥卡姆剃刀 | 8 文件改 1 commit，难回滚 | 7 步逐步，每步可逆 | 看起来简单实际复杂 | 看似简单但延迟价值 |
| 终局思维 | 不可逆操作前无验证 | 不可逆操作在验证后 | 双路径永存 | 风险永存 |
| 全局思维 | 消除所有回滚路径 | 保留所有回滚路径 | 制造两个真相 | 延迟风险检测 |
| 二八法则 | 直接做 20% 工作（删除） | 先做 80%（bridge）+ 后做 20% | 20% 工作散开 | 80% 工作未启动 |

**B 是 6 个框架中胜出 4 个，A 胜出 0 个**

## 真正的决策问题

不是"选 A/B/C/D"——是"什么时机做哪些 Task"。

**重新组织 v2 plan 为 4 阶段**：

### Stage 0（Day 0）— 风险检测
**只做一件事**：用 v3 path + FakeLLMClient + novel-wiki-v2 单文件，跑 Task 4 bridge 测试 + Task 6 e2e smoke（70 KB 音频转录）。

**目的**：在 0 用户影响下，确认 V7 能跑过这个已知会触发 V7 Stage 5/Stage 7 闸门的最坏案例。
**成功标志**：70 KB smoke test succeeded；V7 写出 4-8 个 concept 页 + 1 个 source stub；cost < 0.5 USD；wiki-quality HEALTHY。
**失败标志**：任何 wiki-quality 失败 / cost 超预算 / WikiWriter 抛异常。
**决策点**：失败 → 回到 v2 plan 修复；通过 → 进 Stage 1。

### Stage 1（Day 1-3）— 灰度切换
**做 Task 1-4**：bridge + adapter + segmentation 抽出 + page_adapter + bridge.py + 测试。
**不修改** ingest.py 主体（只加 `_v7_mode` 分支，`RUFLO_PIPELINE_MODE=v7` 才走）。
**让 novel-wiki-v2 项目设 `RUFLO_PIPELINE_MODE=v7` 环境变量**（per-project config）。
**同时**：让 video-notes-wiki 项目也设（如果存在）。

**目的**：2 个生产项目跑 V7 5-7 天，监控：H1/H2/H4/H5 / wiki-quality / cost / 失败率 / 用户反馈。
**成功标志**：2 项目连续 5 天无 lint 报错 / cost 在预算内 / 无 S3 同 id 覆盖问题。
**失败标志**：任何 production-level 问题。
**决策点**：失败 → 回滚到候选路径；通过 → 进 Stage 2。

### Stage 2（Day 8-10）— 默认切换
**修改 `ingest.py`**：把候选路径默认改为 V7 bridge（不再 env var 切换，而是 ingest.py 直接调 bridge）。
**保留候选代码**（候选路径作为 fallback，env var `RUFLO_PIPELINE_MODE=candidate` 显式调用）。

**目的**：V7 成为默认；候选是显式 opt-in。
**成功标志**：其他 20 个项目一周内无异常 / 新摄取任务自动走 V7。
**决策点**：通过 → 进 Stage 3。

### Stage 3（Day 15+）— 删除旧代码
**做 Task 5/5a**：删除候选路径 + 旧 unified + shadow + tests。

**目的**：代码库收敛。
**触发条件**：Stage 2 成功后 30 天观察期无回滚需求。
**回滚路径**：保留 git history + ADR-0014 解释 + 测试 stub（来自 Task 1-4）。

## 关键决策修正（基于批判性思维）

1. **删除旧代码必须在 Stage 3 而不是 Stage 1**：不可逆操作前必须有足够 production 数据
2. **Stage 0 单测是必须**：70 KB 任务是已知的 worst case
3. **bridge 切换必须保留 env var**：rollback 必须 < 1 minute
4. **Stage 1 跑 2 个项目而不是 1 个**：避免 single-project 偏差（如 novel-wiki-v2 特有 ASR 噪声问题）
5. **每个 Stage 独立用户确认才能进下一阶段**

## 关于用户原始选项的最终判断

**不推荐 A**（立即全量）：6 框架中 0 个支持，不可逆操作前无验证。
**不推荐 C**（opt-in 保留）：永远两路径 = 永远代码负担 + 永远用户困惑。
**不推荐 D**（更多 pre-work）：边际收益递减，机会成本高（V7 已 smoke-tested）。
**推荐 B**（灰度 + 延迟删除）：6 框架中胜出最多，符合 80/20，符合第一性原理，符合终局思维。

**但 B 的具体形态**必须是 4 阶段（Stage 0/1/2/3），不是简单的"先小范围再全量"——Stage 0 是独立的安全网，Stage 3 是独立的 cleanup commit。

## 用户应做的下一步

1. **批准 Stage 0**：实施 Task 1-4 + Task 6 的 smoke 部分（约 4-6 小时工作）
2. **同步批准 Stage 1 的环境变量切换**：在 novel-wiki-v2 设 `RUFLO_PIPELINE_MODE=v7`，在 video-notes-wiki 设同
3. **明确 Stage 3 的触发条件**：30 天观察期 + 0 production issue

## 实施动作（Stage 0）

按 plan v2 的 Task 1-4 + Task 6 实施（不变），但 ingest.py **不修改**，只新增 bridge + adapter + page_adapter + segmentation 扩展。
Stage 0 完成后，**人工跑** 70 KB smoke curl，**确认 succeeded 后才进 Stage 1**。
Stage 1 由用户在两个生产项目上手动设 env var，**不修改代码**。
Stage 2 才修改 ingest.py 默认。
Stage 3 才执行 Task 5/5a。

每个 Stage 独立 commit + 用户确认 + 单独 review。
