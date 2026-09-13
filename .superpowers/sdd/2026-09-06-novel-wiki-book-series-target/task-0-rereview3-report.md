# Task 0 Round 3 定向复审报告

## 结论

- **Spec compliance：PASS**
- **Task quality：FAIL**

复审范围：`task-0-brief.md`、`task-0-report.md`、`task-0-fix3-review-package.md`，并检查当前 `partition.py` 与基线测试。未修改实现，未派生子代理。

## 上轮 finding 核验

1. **全部候选不合格仍放行 Provider：已修复。** `blocked` 同时检查治理失败、空候选和不存在 `proceed` 候选；失败时返回 `rule_only`（`partition.py:221-231`）。入口无 provider/callback 参数，门禁结果不能自行调用 Provider。
2. **学习闭环过宽：已修复。** 闭环现在要求三类页面、候选内 `supports`/`required_by` 正向非自环边、至少 `max(6, min_reader_tasks)` 个任务，以及真实候选 page ID 且为 target task 的出口证据（`partition.py:137-178`）。
3. **关系解析率伪造：已修复。** 关系总数、悬空目标数和 `None`（无声明关系）均有确定性计算；taxonomy 命名空间仅按 `taxonomy/` 或 `taxonomy-` 前缀识别（`partition.py:131-136`）。
4. **三个候选及 merge/cancel：已修复。** 默认候选键与实际 taxonomy 合并，空候选可产生 `cancel`，指向另一候选页面可产生 `merge`（`partition.py:95-100,190-194`）。
5. **hard/soft 依赖不可审计：已修复。** 缺失 hard dependency 加入 block reason，hard/soft 依赖写入结果和每个候选（`partition.py:210-232`）。
6. **关键门槛测试不足：部分修复。** 新增了 fail-closed、`required_by`、无效出口、空 hash、任务下限和依赖测试；但测试质量仍有缺口，见下方 finding。
7. **重复率分母不明确：已修复。** 分母固定为有效 `content_sha256` 页面数，并同时输出全局及候选 `duplicate_denominator`（`partition.py:103-110,139-145,150,202`）。
8. **章节分块范围外：仍存在但不属于 fix3 回归。** `partition_pages`/`build_chapter_chunks` 仍在 Task 0 文件中；fix3 未新增其范围。该既有范围问题应继续由维护者决定，不影响本轮修复正确性。

## Findings

### Important — Task quality

fix3 报告声称覆盖 `taxonomyfoo` 和“5/6 task 下限”，但当前测试文件没有 `taxonomyfoo` 字符串；所谓下限测试给出的候选任务数实际为 2（`task_types=(learn_concept, reference)`），并未构造恰好 5 个任务再验证 6 的硬下限。实现中的 `max(6, ...)` 本身正确，但测试证据不足以支持报告的覆盖声明。建议补一个 5-task candidate 与 `taxonomyfoo` unresolved 的断言。

### Minor — 可审计依赖边界

`missing_hard` 以候选键集合判断存在，而 `_candidate_pages` 总是把默认 `book-a`、`book-b`、`book-c` 加入集合，即使候选为空（`partition.py:95-100,210-214`）。因此声明 `hard_reference_dependencies=("book-c",)` 时，空的默认候选会被视为存在。若 hard dependency 表示必须有实际页面的参考库，应改为按非空候选判断并补测试；若它只表示候选命名空间，该行为可接受，但报告应明确契约。

## 验证

实施报告记录命令：

`TEMP=.tmp-pytest TMP=.tmp-pytest TMPDIR=.tmp-pytest PYTHONPATH=. <bundled-python> -m pytest tests/test_kc/test_book_series_baseline.py tests/test_kc/test_book_wiki_scanner.py tests/test_kc/test_book_wiki_e2e.py -q` → 29 passed。

本复审环境没有可用的 `python`、`C:\Python314\python.exe` 或 Python312 解释器，无法独立重跑该命令；结论基于 fix3 diff、当前源码和测试静态核验。

## 最终判定

实现已满足本轮要求的 fail-closed、6 tasks 硬下限、真实 page ID/target task 出口、正向关系、命名空间判断和重复率审计字段，故 **spec compliance PASS**。由于报告宣称的两个边界测试并未真正覆盖，**task quality FAIL**；补齐测试后再转 PASS。
