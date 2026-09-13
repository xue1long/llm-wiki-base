# Task 0 Round 2 scoped re-review

## 结论

**FAIL / 仍需修复。** Round 2 关闭了上轮“任意关系即闭环”的主要问题，也实现了无章节出口证据时的 fail-closed；但 6-task 下限仍不是硬下限，且关系 taxonomy 前缀与 duplicate denominator 的审计语义仍有缺口。定向测试无法在本环境执行：`python` 与 `C:\Python314\python.exe` 均不存在。

审查依据：`task-0-brief.md`、`task-0-report.md`、`task-0-fix2-review-package.md`，并核对当前 `src/kc/views/book/wiki/{model,partition,scanner}.py` 与 `tests/test_kc/test_book_series_baseline.py`。未修改实现。

## Findings

### Important

1. **6 个 reader task 不是不可降低的下限。**

   `ReaderProfile.min_reader_tasks` 默认值为 6，但 `evaluate_series_gate()` 直接使用调用方传入的值；现有回归仍显式构造 `min_reader_tasks=1` 和 `min_reader_tasks=2`。因此一个只包含 1 或 2 个可执行 task 的候选可以在其它条件满足时 `closed/proceed`。若“6 tasks 下限”是 Task 0 的硬门槛，应在入口将阈值钳制为至少 6，或拒绝低于 6 的 profile；至少应有 5-task 失败、6-task 成功的测试。当前测试只断言完整样例有 19 个 task，未验证边界。

2. **章节出口证据只是非空 caller token，未证明候选章节出口。**

   `chapter_known = bool(reader_profile.chapter_exit_evidence)` 会把任意非空字符串元组当作章节出口证据。没有证据时状态为 `unknown`，并加入 `CHAPTER_EXIT_UNKNOWN`，整体会因无 `proceed` 返回 `blocked/rule_only`，这一部分已满足 fail-closed。可是有证据时没有验证证据是否对应候选、章节、出口产物或连续章节；因此 `chapter_exit_evidence=("x",)` 即可参与 `closed`。如果 Task 0 的契约只允许“无章节数据时未知”，需明确标注这是调用方已验证的 opaque evidence；否则仍缺少可审计的出口语义。现有测试没有覆盖“无证据时 closure_status=unknown”或错误/无关证据。

### Minor

3. **taxonomy 目标前缀判断过宽。**

   `relation_unresolved` 使用 `not target.startswith("taxonomy")`，所以 `taxonomyfoo`、`taxonomyXYZ` 等普通 page id 会被当成已解析的 taxonomy namespace 目标。scanner 实际只识别 `taxonomy/` 和 `taxonomy-`；门禁应使用这两个明确前缀（或共享一个 namespace helper）。应增加 `taxonomyfoo` 的回归测试，确认它计入 unresolved 并降低 `relation_parse_rate`。

4. **duplicate rate 的分母仍与分子口径不一致。**

   `_duplicate_rate()` 只把非空 `content_sha256` 放入 hash 计数，却始终用全部 `len(pages)` 作分母。含空 hash 的 snapshot 会稀释 duplicate rate；本轮报告明确把该问题留作后续，但 Task 0 要求基线可审计，当前仍未冻结“全部页面”还是“有 hash 页面”的统计契约，也没有空 hash 测试。

5. **关系方向覆盖不完整。**

   实现接受 `supports` 与 `required_by`，并要求 relation owner 为 source task、target 为 target task，故正向 `source -> target` 和 self/reverse 的基本规则已落地。测试只覆盖 `supports` 的正向样例以及 self/reverse，未验证 `required_by` 的正向语义，也未验证 target task 显式为 `example/application/explanation/method` 的边界。建议补一个 `required_by` 正向和 source/target 任务反转失败用例。

## 已关闭项

- 治理字段完整但无合格候选时现在确实返回 `blocked` + `rule_only`。
- 闭环边不再接受任意 relation；只接受 `supports`/`required_by`、候选内目标、非自环、source-task 到 target-task。
- 无 relation 时 `relation_parse_rate is None`；悬空非 taxonomy 目标计入 unresolved。
- 默认 candidate taxonomy 并集会产生 `book-a`/`book-b`/`book-c`，空候选走 `cancel`，跨候选目标在未满足门槛时走 `merge`。
- hard dependency 缺失阻断，soft dependency 会返回并记录但不阻断。
- `evaluate_series_gate` 无 provider 参数，门禁失败时结果保持 `rule_only`。

## Verification

尝试运行：

```text
$env:PYTHONPATH='.'; python -m pytest --import-mode=importlib tests/test_kc/test_book_series_baseline.py -q
python: The term 'python' is not recognized ...

$env:PYTHONPATH='.'; & 'C:\Python314\python.exe' -m pytest ...
The term 'C:\Python314\python.exe' is not recognized ...
```

因此本轮没有新的运行时测试证据；结论基于源码、diff 和测试内容静态复核。

## 判定

Task 0 暂不通过。先修复硬性 6-task 下限，并补齐章节未知、5/6 task、`required_by`、taxonomy 前缀和空 hash denominator 回归后再复审。
