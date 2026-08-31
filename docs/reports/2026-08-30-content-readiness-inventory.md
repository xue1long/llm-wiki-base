# Content readiness inventory and 15-sample pilot

执行日期：2026-08-30（Asia/Shanghai 记录日）
Policy：`content-policy-v1`  术语/审计版本：`content-readiness-v1`

## 保护范围

- 输入：`D:/5-Project/2026814/llm-wiki-base.bak.20260822/knowledge/novel-wiki-clean-staging`
- 保护目录：`D:/5-Project/2026814/llm-wiki-base.bak.20260822/knowledge/novel-wiki`
- inventory 与 pilot 报告：当前仓库 `docs/reports/`
- preflight 判定 staging 与保护目录不重叠；本次未读取、复制或修改保护目录。

## 全量 inventory

| 指标 | 数值 |
|---|---:|
| 源文件数 | 1343 |
| 唯一 source_id | 1343 |
| ready | 1204 |
| ready_with_warning | 122 |
| skip_no_content | 5 |
| quarantine_degraded | 0 |
| unsupported | 12 |

逐源记录见 [inventory JSON](2026-08-30-content-readiness-inventory.json)。每条记录含 source bytes/input text hash、format、extraction method、decision、reason codes 和 evidence capacity；inventory 不调用 provider。

## 分层 15 样本 pilot

选择使用 inventory stratum、固定 seed `20260830`；执行命令带 `--no-commit`，本轮只生成、不写 staging wiki/audit。

| 类别 | 数量 |
|---|---:|
| selected | 15 |
| accepted | 3 |
| skipped | 2 |
| rejected | 6 |
| needs_human_review | 0 |
| provider_error | 4 |

accepted evidence replay：`3/3`，`replay_failures=0`，`false_accepts=0`。4 个 provider error 均保留 `TruncatedResponseError / finish_reason=length` 原因链；证据绑定失败保留为 rejected，不通过模糊匹配放行。

逐源结果见 [pilot JSON](2026-08-30-content-readiness-pilot-15.json)，replay 结果见 [replay JSON](2026-08-30-content-readiness-pilot-15-replay.json)。

## 未关闭项

- 15 样本的 provider 稳定性仍是外部运行条件：本轮有 4 个响应因 token 截断进入 `provider_error`，不属于 readiness 证据误接收。
- 当前支持矩阵仍不覆盖 JSON 等未知格式；它们进入 `unsupported`，不会进入通用 Analyzer。
- 完整代码回归、graphify 和最终 release gate 由 Task 9 继续执行。
