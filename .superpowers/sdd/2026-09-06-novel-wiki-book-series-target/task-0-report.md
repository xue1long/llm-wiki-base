# Task 0：书系基线与前置数据门报告

状态：VERIFIED（实现、定向测试和相关回归测试通过）。

## 改动文件

- `src/kc/views/book/wiki/partition.py`：新增 `ReaderProfile`、`GovernanceConfig`、基线指标/候选裁决数据结构及纯规则入口 `evaluate_series_gate`。候选按 snapshot taxonomy 稳定分组；统计页类型、重复率、来源覆盖率、关系数/解析率、估算字数和 reader task 候选；页面数、来源覆盖率或最小学习闭环不足时只返回 `proceed` 以外的裁决。
- `src/kc/views/book/wiki/scanner.py`：从扫描边界导出基线入口，保持 scanner 的 Wiki 快照契约。
- `src/kc/views/book/wiki/__init__.py`：导出基线公共类型和入口。
- `tests/test_kc/test_book_series_baseline.py`：覆盖 ready、低覆盖/页面不足、治理缺失 blocked、重复运行一致性。

## 基线示例

输入为 `snapshot_id=snap-1` 的三个页面（concept/entity/synthesis），每页 10 字符且有一个 source，治理配置为授权、预算 100、审批人 `editor`：

```json
{
  "total_pages": 3,
  "source_coverage": 1.0,
  "duplicate_rate": 0.0,
  "estimated_chars": 30,
  "candidate": {
    "eligible_page_count": 3,
    "closure_status": "closed",
    "decision": "reference"
  },
  "status": "ready",
  "generation_mode": "llm_allowed"
}
```

该示例因页面数小于默认 20，候选会被降级为 `reference`；系统不会用 Provider 补齐页面。缺少授权、预算上限或审批人时，结果为 `status=blocked`、`generation_mode=rule_only`，并列出缺失字段。

## 测试命令与结果

- `TEMP=.tmp-pytest TMP=.tmp-pytest TMPDIR=.tmp-pytest PYTHONPATH=. <bundled-python> -m pytest tests/test_kc/test_book_series_baseline.py -q`：通过，4 passed。
- `TEMP=.tmp-pytest TMP=.tmp-pytest TMPDIR=.tmp-pytest PYTHONPATH=. <bundled-python> -m pytest tests/test_kc/test_book_wiki_scanner.py tests/test_kc/test_book_wiki_e2e.py -q`：通过，17 passed。
- `git diff --check`：通过（仅已有工作树 CRLF 提示）。

未调用远程 LLM，未添加第三方依赖。

## 已知限制

- 当前 `PageRecord` 只保留 scanner 已成功解析的结构化 relations；因此 relation parse rate 对扫描成功快照固定为 `1.0`，坏 frontmatter 由 scanner fail-closed 拒绝。若后续需要展示“原始关系声明/解析失败数”，应在 scanner 快照中增加显式计数。
- 候选按 `primary_taxonomy` 分组；没有 taxonomy 的页面归入 `unassigned`。候选合并仅留给后续任务，Task 0 不做语义判断。
- 书系候选页面数默认门槛为 20，可由 `ReaderProfile` 固定调整；任务入口没有 provider 参数，因此无法绕过规则门。

## 后续阻塞状态

实现和验证不阻塞后续任务。后续任务消费 `SeriesGateResult` 时必须保留 `rule_only` 和 `blocked` 状态，不得在门禁失败时调用叙事 Provider。

## 审查修复记录

- 所有候选均未 `proceed` 时，结果强制 `status=blocked`、`generation_mode=rule_only`，并记录 `no_retained_candidate`。
- 闭环增加最小 reader task 数（默认 6）和候选内前置页面到出口页面的结构化 relation 边；仅有页面类型不再闭环。
- 关系指标按结构化关系总数与悬空目标计数计算；无关系时为 `None`（未知），不再恒定伪造 1.0。
- 默认输出 `book-a`、`book-b`、`book-c` 三个候选；空候选产生 `cancel`，跨候选关系产生 `merge`，满足门槛才 `proceed`。
- hard/soft reference dependencies 进入候选和结果，缺失 hard dependency 会阻断；soft 缺失可审计但不阻断。
- 新增回归覆盖 fail-closed、reader task/关系闭环、三候选裁决和依赖字段；`test_book_series_baseline.py`、scanner、e2e 共 21 passed。
