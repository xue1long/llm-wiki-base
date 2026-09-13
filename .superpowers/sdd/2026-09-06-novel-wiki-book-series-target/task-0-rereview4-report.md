# Task 0 scoped re-review Round 4

审查范围：`981c90ad..5cd19a4e`，对照 `task-0-brief.md`、`task-0-report.md` 和 `task-0-fix4-review-package.md`。

## 结论

- **Spec compliance：PASS**
- **Task quality：PASS**
- 本轮没有遗留 finding，也没有发现由 fix4 引入的新回归。

## 三项 finding 复核

### 1. `taxonomyfoo` 实测：已修复

`partition.py` 只把 `taxonomy/` 与 `taxonomy-` 前缀视为命名空间目标；`taxonomyfoo` 不匹配前缀，因此计入 unresolved。新增测试实际构造 `supports -> taxonomyfoo`，并断言：`relation_count=1`、`relation_unresolved_count=1`、`relation_parse_rate=0.0`。该 finding 已闭合。

### 2. 恰好 5/6 reader task 硬下限：已修复

新增 boundary fixture 实际生成 5 和 6 个符合 profile 的 task。5 task 结果为 `reader_task_count=5`、`closure_status=incomplete`，包含 `INSUFFICIENT_READER_TASKS`；6 task 结果为 `reader_task_count=6`、`closure_status=closed`、`decision=proceed`，并保留 `edge:p1:required_by->p3`。实现入口仍使用 `max(6, reader_profile.min_reader_tasks)`，因此传入 1 不能绕过硬下限。该 finding 已闭合。

### 3. 空默认候选不能满足 hard dependency：已修复

实现现在只把 `_candidate_pages(...)` 中有页面的候选加入 dependency 满足集合。默认空 `book-c` 不再满足 `hard_reference_dependencies=("book-c",)`，结果包含候选级和全局 hard dependency 记录及 `hard_reference_dependencies` block reason；加入一个 `book-c` 页面后该缺失依赖清空。该 finding 已闭合。

## 回归与声明核验

实际执行：

```powershell
$py='C:\Users\HP\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$tmp=(Resolve-Path -LiteralPath '.tmp-pytest').Path
$env:TEMP=$tmp; $env:TMP=$tmp; $env:TMPDIR=$tmp; $env:PYTHONPATH='.'
& $py -m pytest tests/test_kc/test_book_series_baseline.py tests/test_kc/test_book_wiki_scanner.py tests/test_kc/test_book_wiki_e2e.py -q
```

结果：**31 passed in 1.38s**。与实施报告声明一致。`git diff --check 981c90ad..5cd19a4e` 无输出；fix4 diff 仅涉及 hard dependency 空候选判定及对应回归测试/报告更新。未发现 provider 参数、远程调用、第三方依赖或旧功能删除等越界变化。

## 限制

本轮未重复执行报告中已知不可用的 `graphify update .`：launcher 指向不存在的 Python 3.12，bundled Python 又缺少 `graphify` 模块；这不影响本轮代码和测试结论。
