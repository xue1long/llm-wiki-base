# Content Readiness Acceptance Report

执行日期：2026-08-31（Asia/Shanghai）

## 结论

内容可用性与证据就绪方案已完成实现。阻断决策保持 fail-closed；证据只接受可重放的 `source_id + block_id + canonical quote`。本次 pilot 的 provider 截断没有被伪装成业务成功，仍按 `provider_error` 保留。

## 验收证据

| 项目 | 结果 |
|---|---|
| clean staging inventory | `1343/1343` source 覆盖；`ready=1204`、`ready_with_warning=122`、`skip_no_content=5`、`unsupported=12`、`quarantine_degraded=0` |
| 固定 15 样本 pilot | `selected=15`；`accepted=3`、`skipped=2`、`rejected=6`、`needs_human_review=0`、`provider_error=4` |
| accepted evidence replay | `3/3` 通过；`replay_failures=0`；`false_accepts=0` |
| blocking path | `skip_no_content`/`unsupported` 记录 `analyzer_called=false`，不创建 KnowledgeObject |
| 保护目录 | `git diff --quiet -- knowledge/novel-wiki` 通过；原始目录无持久化改动 |
| 全量相关测试 | `tests/test_pipeline tests/test_kc tests/test_server`：`1299 passed, 43 warnings` |
| 回归修复测试 | collector URL + KC mainline：`13 passed` |
| 编译检查 | `python -m compileall -q src scripts` 通过 |
| 结构图谱 | `graphify update . --no-cluster`：`20631 nodes / 42738 edges`；官方无聚类模式通过 |

## 命令与报告

- Inventory：[`2026-08-30-content-readiness-inventory.json`](2026-08-30-content-readiness-inventory.json)
- Inventory 摘要：[`2026-08-30-content-readiness-inventory.md`](2026-08-30-content-readiness-inventory.md)
- Pilot：[`2026-08-30-content-readiness-pilot-15.json`](2026-08-30-content-readiness-pilot-15.json)
- Replay：[`2026-08-30-content-readiness-pilot-15-replay.json`](2026-08-30-content-readiness-pilot-15-replay.json)

## 仍需关注

15 样本中的 4 个 `provider_error` 均为 GLM5.2 `TruncatedResponseError`/`finish_reason=length`。这是 provider 输出容量问题，已分类、保留原始失败链，不能通过放宽证据校验解决；后续应在 provider 请求预算或模型服务稳定后单独复跑，不修改当前 provider 配置。

首次直接运行完整聚类模式无进度并被终止；在不清理用户保留临时目录的前提下，使用 graphify 官方 `--no-cluster` 完成结构更新。零节点提示仅涉及 JSON/配置文件，不影响 Python 代码图谱。

## 提交

- `10d44415 feat(kc): run content readiness inventory and pilot`
- `d9c67b64 fix(kc): harden staging writes on Windows`

未 push。既有 `docs/guides/wiki-spec.md`、`src/pipeline/wiki_rules_prompt.py`、`scripts/_batch_report.txt` 和临时目录均未纳入本次提交。
