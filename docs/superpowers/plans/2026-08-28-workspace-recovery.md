# Workspace Recovery and Change Ownership Plan

## Scope

只处理工作区盘点、变更归属和 Git 安全；不修改业务代码，不处理 Wiki 全量生成物，不重排 WebUI。

## Tasks

### 1. Build an ownership ledger

- 记录 `git status --porcelain=v1 --untracked-files=all` 的计数和顶层分布。
- 用 `git diff --name-status`、`git diff --stat`、`git ls-files --others --exclude-standard` 分开统计 tracked/untracked。
- 按 KC、pipeline、Wiki 产物、WebUI、文档脚本、缓存/临时、unresolved 分组。
- 与 `.superpowers/sdd/progress.md`、近期提交、迁移报告和对应测试逐组对照。
- 输出“文件 → 功能 → 证据 → 提交边界”；不能证明归属的标为 unresolved。
- 将结果保存为 `ownership-ledger.md`，每行至少包含：`path | category | owner/evidence | decision(include/exclude/unresolved) | approved_at | rollback_boundary`。
- `decision` 未为 `include` 的文件不得暂存；ledger 本身也不得覆盖原有用户文件。

### 2. Verify write safety

- 检查 `.git/index.lock`，运行 `git status`、`git diff --check`。
- 若有权限/锁错误，只报告具体错误；不删除锁、不执行恢复性 Git 命令。
- 在任何写入前保存 `baseline-report.md`，包含 status 计数、顶层分布、index.lock 检查结果、命令退出码和失败输出摘要。

### 3. Isolate confirmed changes

- 仅对用户确认且属于同一功能边界的文件选择性 `git add`。
- 暂存后检查 `git diff --cached --name-only` 和 `git diff --cached --stat`，再跑定向测试。
- 每个边界单独提交；`knowledge/novel-wiki/`、WebUI、临时产物不得混入 KC 提交。
- 提交不是本阶段默认动作；只有用户明确授权且 staged manifest 与 ledger 一致时才提交。未授权时停在可复核的 staged/unstaged 状态。
- 不建立依赖整体 reset 的回滚；回滚边界必须是独立提交、独立备份或未发布 stage，并在 ledger 中标明。

## Completion gate

所有变更均已归属或明确 unresolved；Git index 可读写；没有删除/覆盖 raw source；源码、Wiki 产物和临时文件具备独立处置与回滚边界。否则停止，不进入 KC 主线。

## Exact verification

```powershell
$env:PYTHONPATH='.'
git status --porcelain=v1 --untracked-files=all
git diff --name-status
git diff --stat
git diff --check
python -m pytest tests/test_kc/ tests/test_collector/ -v --import-mode=importlib
```

每条命令记录退出码；测试失败必须归类为代码、接线、环境或生成物问题。
