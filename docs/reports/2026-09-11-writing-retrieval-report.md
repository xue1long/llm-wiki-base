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
| 结果记录 | commit、corpus hash、mode、来源、采用原因 | 无对应运行记录 | 未满足 |

## 已排除的替代数据

- `docs/evaluation/retrieval_cases.json` 只有通用的 Fact/Definition/Legacy 示例，不是写作问题集。
- `docs/evaluation/kc_mvp_cases.yaml` 和 `docs/evaluation/agent_tasks/agent_tasks.yaml` 标明为 MVP/mock 评测，不能证明当前写作检索链路。
- 现有仓库命中内容只能证明存在写作素材，不能推导作者的真实查询、可采用判断或 abstain 标注。

## 闸门结论

Task 4 已从“缺少输入”推进到“待运行”阶段。当前仍没有 Top-5 命中率、负例拒答率或作者任务成功率，这些数字必须由固定 corpus 和 commit 下的真实运行产生。

Task 5 仍不得执行；否则会把“案例已准备”误包装成“写作价值已验证”。

## 继续条件

继续运行前还需完成以下最小动作：

1. 由作者/审核人确认案例中的 expected page 和 abstain 标注。
2. 在相同 corpus 下分别运行整改前后检索，并记录 commit、hash、mode、Top-5 和 provenance。
3. 实际完成 3–5 个任务，补充查询次数、耗时、采用/拒绝结果和原因。
