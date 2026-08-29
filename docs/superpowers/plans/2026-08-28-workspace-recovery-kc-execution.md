# Workspace Recovery and Knowledge Core Master Plan

## Objective

在不破坏既有用户改动、raw source 和 Wiki 产物的前提下，先恢复变更归属，再闭合 Knowledge Core（KC）正式主路径，最后统一 claim-level evidence 生命周期。

## Execution order

1. [Workspace recovery](2026-08-28-workspace-recovery.md)：只读盘点、归属、Git 写入安全。
2. [KC mainline](2026-08-28-kc-mainline.md)：建立真实的 candidate 主路径和发布闭包。
3. [Evidence lifecycle](2026-08-28-evidence-lifecycle.md)：统一 claim、evidence、状态、存储和下游消费。

每个子方案独立验收；前一方案未通过，不进入下一方案。生成 Wiki、WebUI、临时文件另行处理，不混入 KC 源码提交。

每阶段必须产出可审计记录：`ownership-ledger.md`、`baseline-report.md`、`integration-report.md`、`evidence-report.md`。记录文件只描述本次范围，不覆盖既有报告。提交不是默认动作，须在对应边界得到明确授权。

## Non-negotiable constraints

- 禁止 `git reset --hard`、`git clean`、`git checkout --`、未经确认的 `git stash -u`。
- 禁止 `git add .`、`git add -A`；只能按已确认边界选择性暂存。
- 未确认归属的文件只读检查；不删除、不恢复、不覆盖。
- Git index 出现权限或锁错误时立即停止写入，不自行删除锁文件。
- 所有正式 KC 写入必须经过现有 review、projection、atomic writer 和 commit boundary。
- 所有入口必须复核：HTTP ingest、programmatic `run_ingest`、queue worker、CLI/MCP、shadow/legacy；未列入正式主路径的入口必须明确为兼容或禁止路径。
- 任何测试、暂存或提交都必须保存命令、退出码、失败分类和受影响路径；不能只报告“测试通过”。

## Global acceptance

- 每个变更都有归属、证据和独立回滚边界。
- 正式 ingest 可达 `candidate → review → projection → commit`。
- claim 能回到 evidence 和 canonical source block；`anchored`、`structurally_verified`、`entailed`、`unsupported`、`needs_human_review` 不混淆。
- review/strict failure 不产生 Wiki、index、vector 正式写入。
- 写入采用 `validate → stage → publish`：只有 publish manifest 成功后正式目录可见；跨存储无法做到单事务时，必须有可验证的未发布状态和补偿记录。
- legacy/unified 不绕过发布闭包；Wiki 产物、源码、WebUI、临时产物可分别回滚。

## Stop conditions

无法确认文件归属、Git index 不可写、candidate caller 不可达、状态源冲突、测试失败无法分类，或需要批量删除/覆盖用户数据时，暂停并报告，不继续猜测。
