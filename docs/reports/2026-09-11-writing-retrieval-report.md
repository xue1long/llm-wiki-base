# 写作检索首轮评测报告

## 状态

**PARTIAL：作者案例和任务输入已补齐，尚未运行检索和作者盲测，未产生通过/不通过结论。**

本报告只记录评测门槛检查结果。案例由 Codex 按用户授权代行作者角色编写，已绑定当前语料中的真实页面和来源；仍需人工确认并完成运行记录，不能把案例准备冒充成检索效果。

## 方案要求

| 项目 | 要求 | 当前证据 | 结论 |
|---|---|---|---|
| 正例 | 15 个真实写作问题 | `docs/evaluation/writing_retrieval_cases.yaml` | 已补齐，待确认 |
| 负例 | 5 个应拒答或 abstain 问题 | 同上 | 已补齐，待确认 |
| 标注 | expected actionable page、证据来源、是否 abstain | 同上 | 已补齐，待确认 |
| 作者任务 | 3–5 次真实作者任务 | `docs/evaluation/writing_author_tasks.yaml` | 4 个任务定义已补齐，待运行 |

## 已完成的人工确认与迁移

- 用户确认了 15 个正例页面，并批准批量授予 `用途/可执行`。
- 审核记录写入现有 `.index/reviews_resolved.json`，reviewer 为 `user-confirmed`。
- 迁移 dry-run 计划 15 页，apply 成功 15 页。
- raw 文件 1364 个；迁移前后聚合 SHA256 均为 `086BEE78BC671E6984ACDC447E26097B6B77E95ED3B57E5294AEDD4AB7E3B6A1`。
- 严格 Frontmatter 检查结果为 `P0=0`。

## 实际运行结果

| 运行 | commit | corpus hash | 状态 | 正例 Top-5 | 负例 abstain |
|---|---|---|---|---:|---:|
| `hybrid` 默认写作检索 | 见 `2026-09-11-writing-retrieval-run.json` | `dddfc134e9a65f6aa5968a7f8678c231bb743a382c43fe5508d7367e99068f3a` | blocked: pending=1221 | 0/15 | 5/5* |
| `keyword` 显式诊断回退 | 见 `2026-09-11-writing-keyword-run.json` | 同上 | complete | 0/15 | 5/5 |

`*` 默认检索因 ready 闸门阻断，5/5 是保护性空结果，不能计入质量验收。keyword 运行使用完整自然语言问题，而当前关键词实现要求正文出现连续查询串，因此结果不能替代语义检索验收。

作者任务执行记录见 `2026-09-11-writing-author-task-runs.yaml`。4 个任务均在 ready 闸门前停止，未伪造查询次数、耗时或采用结论。
| 结果记录 | commit、corpus hash、mode、来源、采用原因 | 无对应运行记录 | 未满足 |

## 已排除的替代数据

- `docs/evaluation/retrieval_cases.json` 只有通用的 Fact/Definition/Legacy 示例，不是写作问题集。
- `docs/evaluation/kc_mvp_cases.yaml` 和 `docs/evaluation/agent_tasks/agent_tasks.yaml` 标明为 MVP/mock 评测，不能证明当前写作检索链路。
- 现有仓库命中内容只能证明存在写作素材，不能推导作者的真实查询、可采用判断或 abstain 标注。

## 闸门结论

Task 4 已完成案例、标签和运行器准备，并完成一次真实运行；结果为默认写作检索被 `pending=1221` 阻断，未通过业务验收。keyword 诊断回退也未命中 15 个完整自然语言问题，说明它不能替代语义检索。

Task 5 仍不得执行；否则会把“案例已准备”误包装成“写作价值已验证”。

## 继续条件

继续运行前还需完成以下最小动作：

1. 完成 Vector 发布并使 `ready=true`、`pending=0`、`failed=0`、模型和 hash 一致。
2. 在相同 corpus 下重跑整改前后检索，并记录 commit、hash、mode、Top-5 和 provenance。
3. 实际完成 3–5 个任务，补充查询次数、耗时、采用/拒绝结果和原因。
