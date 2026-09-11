# 写作检索首轮评测报告

## 状态

**BLOCKED：缺少真实作者评测输入，未产生通过/不通过结论。**

本报告只记录评测门槛检查结果，不用合成数据冒充写作效果。

## 方案要求

| 项目 | 要求 | 当前证据 | 结论 |
|---|---|---|---|
| 正例 | 15 个真实写作问题 | 未发现 | 未满足 |
| 负例 | 5 个应拒答或 abstain 问题 | 未发现 | 未满足 |
| 标注 | expected actionable page、证据来源、是否 abstain | 未发现 | 未满足 |
| 作者任务 | 3–5 次真实作者任务 | 未发现 | 未满足 |
| 结果记录 | commit、corpus hash、mode、来源、采用原因 | 无对应运行记录 | 未满足 |

## 已排除的替代数据

- `docs/evaluation/retrieval_cases.json` 只有通用的 Fact/Definition/Legacy 示例，不是写作问题集。
- `docs/evaluation/kc_mvp_cases.yaml` 和 `docs/evaluation/agent_tasks/agent_tasks.yaml` 标明为 MVP/mock 评测，不能证明当前写作检索链路。
- 现有仓库命中内容只能证明存在写作素材，不能推导作者的真实查询、可采用判断或 abstain 标注。

## 闸门结论

Task 4 暂停在输入准备阶段。没有这些输入，任何 Top-5 命中率、负例拒答率或作者任务成功率都是不可证明的数字。

因此 Task 5 的 canary 和 go/no-go 不得执行；否则会把“代码已完成”误包装成“写作价值已验证”。

## 继续条件

补齐以下最小材料后继续：

1. 15 个正例、5 个负例；每条包含 `query`、`expected_page_id`、`evidence_source`、`should_abstain`。
2. 3–5 次作者任务；每次包含任务描述、查询次数、采用/拒绝结果、耗时和原因。
3. 指定一名熟悉目标题材和写作流程的评测作者，确认上述标注。
