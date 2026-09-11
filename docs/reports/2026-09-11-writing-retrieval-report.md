# 写作检索首轮评测报告

## 结论

**Task 4：通过（限定在写作索引范围）。** 当前有 15 个经人工批准的 `用途/可执行` 页面，使用真实本地 embedding 完成 15 个正例、5 个负例和 4 个作者任务：正例 Top-5 命中 15/15，负例 abstain 5/5，作者任务 4/4 在 1 次查询内找到可采用答案。

这不是全库 Vector 发布通过。普通资料仍有 1206 个 pending 页面；它们被明确排除在默认写作索引之外，不能据此声称全库 `ready`。

## 评测边界和输入

| 项目 | 证据 | 结果 |
|---|---|---|
| 正例 | `docs/evaluation/writing_retrieval_cases.yaml` | 15 个真实写作问题 |
| 负例 | 同上 | 5 个应 abstain 问题 |
| 作者任务 | `docs/evaluation/writing_author_tasks.yaml` | 4 个任务定义 |
| 人工确认 | `.index/reviews_resolved.json` | 15 页均为 `user-confirmed / approved` |
| 写作向量 | `task4-actionable-body-256-20260911` | 15 页、33 chunk、512 维 |
| embedding | `thenlper/gte-small-zh` | 本地真实模型，max sequence length 256 |

案例由 Codex 按用户授权代行作者角色编写，绑定当前 Wiki 页面和 raw source；样本量小，只能证明首轮样本的可用性，不能外推普遍质量。

## 实际结果

| 运行 | 状态 | 正例 Top-5 | 负例 abstain | 向量状态 |
|---|---|---:|---:|---|
| `hybrid` 写作索引 | complete | 15/15 | 5/5 | `ready=true, pending=0, failed=0, scope=actionable` |
| 作者任务 | complete | 4/4 | — | 每个任务 1 次查询 |

完整逐案路径、commit、corpus hash 和向量诊断见 [`2026-09-11-writing-retrieval-run.json`](2026-09-11-writing-retrieval-run.json)；作者任务的实际耗时、采用页面和 provenance 见 [`2026-09-11-writing-author-task-runs.yaml`](2026-09-11-writing-author-task-runs.yaml)。

每个采用结果均记录了 `page_path`、`page_id` 和 `raw/sources/...` provenance。raw 共 1364 个文件，`用途/可执行` 迁移前后聚合 SHA256 均为 `086BEE78BC671E6984ACDC447E26097B6B77E95ED3B57E5294AEDD4AB7E3B6A1`。

## 本次整改

1. 默认写作 readiness 只检查已人工批准的可执行页面，普通资料 pending 不再阻塞写作索引；全库状态仍可通过 `scope=all` 看到。
2. Vector Top-K 先小倍数 overfetch，再按页面去重，避免同一页面的多个 chunk 挤占文档级 Top-5。
3. 对实时榜单、成功率/保证、预测和缺少正文上下文的请求执行显式 abstain。
4. 本地 provider 使用真实 `gte-small-zh`，向量只嵌入 body；`page_content_hash` 和 `vector_content_hash` 保持一致。

## 验证

定向回归测试：`9 passed`，覆盖页面去重、actionable readiness、abstain、现有服务搜索行为和 20 案例输入约束。

## 放行边界

Task 4 的写作价值验收已通过，可以进入 Task 5 的 canary。Task 5 仍必须继续记录全库 pending 状态、raw 不变和失败恢复；普通资料的 1206 个 pending 页面完成前，不得把系统描述为全库语义检索 ready。
