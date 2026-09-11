# novel-wiki 写作知识库整改 Task 5 终验报告

日期：2026-09-11  
范围：`knowledge/novel-wiki` 的写作索引整改；raw 只读。  
结论类型：一次受限放行决定。

## 1. 前置门禁

Task 0–3 已完成。Task 4 的结果仅在写作索引范围成立：

| 检查项 | 结果 |
|---|---|
| `用途/可执行` 页面 | 15 页，均有用户确认记录 |
| 写作正例 | 15/15 Top-5 命中 |
| 负例拒答 | 5/5 abstain |
| 作者任务 | 4/4 在 1 次查询内找到可采用结果 |
| provenance | 每个采用结果均绑定 page path、page id、raw source |
| 写作索引 ready | `ready=true, pending=0, failed=0, scope=actionable` |
| 全库 ready | **不通过**：`pending=1206`，不纳入本次写作索引放行 |

证据文件：[`2026-09-11-writing-retrieval-report.md`](2026-09-11-writing-retrieval-report.md)、[`2026-09-11-writing-retrieval-run.json`](2026-09-11-writing-retrieval-run.json)、[`2026-09-11-writing-author-task-runs.yaml`](2026-09-11-writing-author-task-runs.yaml)。

## 2. Raw canary

在仓库外的临时项目副本 `.tmp-task5-canary` 中复制真实 raw，正式库未作为写入目标。执行器使用 `RUFLO_EXECUTOR_FAKE_GENERATE=1`，所以这里验证的是采集、门禁、原子落盘和状态机；不把 fake 生成内容当成语义质量证据。

| 类别 | raw 样本 | raw SHA256 | 生成页数 | 门禁/批状态 | 人工确认 |
|---|---|---|---:|---|---|
| 普通资料 | `raw/sources/02_进阶技巧/补充教程网络小说创作技巧.md` | `E7B1D4521D9B7A339D8B9FB3E28B8E8D79408B08931561C61FA80227A4AE345F` | 2 | PASS / `committed` | 来源可追溯、写入结果可检查；未批准为 `用途/可执行` |
| 可执行候选 | `raw/sources/01_新手入门/入门教程谈谈小说的矛盾冲突大高潮小高潮如何营造及小说节奏.md` | `188305D3400A2E142F802B0E43D8F91F079233B286833F30D5E5FA446A8E0C0B` | 2 | PASS / `committed` | 来源可追溯、写入结果可检查；未批准为 `用途/可执行` |
| 案例素材 | `raw/sources/02_进阶技巧/补充教程写作经验侦探小说创作指南与写法.md` | `986A698756F489840567A8F3F9EA75735C1A0874BD9FC397CFA66CC77C0B7F54` | 2 | PASS / `committed` | 来源可追溯、写入结果可检查；未批准为 `用途/可执行` |

canary 汇总：3/3 raw 为 `done`，6 个派生页，退出码 0。临时副本的 actionable readiness 为 `unavailable`（0 个可执行页），全页 readiness 为 `pending=6`；系统没有把“零可执行页”误报为 ready。

## 3. 写入失败与恢复演练

在独立临时项目 `.tmp-task5-failure` 中注入 `RUFLO_FLUSH_FAIL_PATHS=src-failure.md`：

| 阶段 | 证据 |
|---|---|
| 注入失败 | 退出码 4；批次和 raw 均为 `partial_commit` |
| 文件完整性 | 失败页采用 tmp + replace；失败的 source 页未落盘，已落盘的 concept 页不是撕裂文件 |
| raw 不变 | 失败前、失败后、续跑后 SHA256 均为 `EFC1C0211B9037462E4BDCB58B4380C8C815A238C19CE7CFDA6065807F4EE7BC` |
| 续跑 | 清除注入后 `--resume` 退出码 0；批次 `committed`，raw `done` |
| 恢复产物 | 续跑后 failure 样本对应派生页 2 个 |

演练中先发现并修复两项真实问题：空 LanceDB 表的 `DeleteResult` 不保证存在 `num_deleted_rows`；相对 `--root` 产生的失败路径会让 lineage reservation 无法清理。另将普通提交异常从“批次 committed”改为“批次 failed”，避免错误成功。对应回归已加入并通过。

## 4. 放行决定

**受限放行：允许继续使用当前 15 页写作索引并进行受控 canary；禁止扩大到 20、100 或全量摄取。**

理由只有两条：写入、失败可见化和续跑恢复已通过实测；全库仍有 1206 个 pending 页面，且 canary 使用 fake provider，不能把本报告当成全库语义质量证明。后续是否扩充范围，必须由真实作者使用记录和新的评测证据触发。

## 5. 本次代码变更与验证

- `src/vector/store.py`：兼容当前 LanceDB 删除返回值，空表清理安全返回。
- `src/orchestrator/batch_runner_internal/phases.py`：提交异常落状态并返回失败；修复相对路径 reservation 清理。
- 回归：向量存储与批执行器共 28 项通过；Task 5 新增/相关聚焦回归 3 项通过。

本报告只记录证据和边界，不把 fake canary 的生成内容、零 actionable 页面或小样本 Task 4 结果外推为全库质量结论。
