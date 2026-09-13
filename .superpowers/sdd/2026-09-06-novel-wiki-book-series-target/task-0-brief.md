# Task 0：前置数据门与方案可否决报告

**Files:** `src/kc/views/book/wiki/scanner.py`、`partition.py`、新增 `docs/reports/2026-09-06-book-series-baseline.md`、新增基线测试。

**目标：** 在任何叙事 outline 或远程 Provider 调用前，基于当前 Wiki 快照生成可审计的书系基线。三本书只是候选，必须允许合并、降级为参考库或取消。

**必须满足：**

- 统计页面类型、重复率、来源覆盖率、关系解析率、预估字数和 reader task 候选。
- 按候选书计算 eligible 页数、章节密度和最小学习闭环。
- 每个候选 book 输出 `eligible_page_count`、`source_coverage`、`duplicate_rate`、`estimated_chars`、`reader_task_count`、`closure_status`、`decision`。
- 任一本书来源覆盖率低于 0.80、可归属页面少于 20 个或无法形成最小学习闭环时，decision 必须是 `merge`、`reference` 或 `cancel`，不得用 LLM 填充。
- 固化主读者画像、外发授权、预算上限、参考库 hard/soft 依赖和人工审批人；缺失时报告 `blocked`。
- 未通过数据门时只输出 `rule_only` 报告，不调用叙事 Provider。
- 使用确定性输入和快照 ID；重复运行相同快照应产生相同基线指标。

**测试要求：** 先写失败测试，覆盖通过、低覆盖、页面不足、无闭环、重复运行一致性、缺少授权/预算/审批人和“blocked 时不调用 provider”。运行 `PYTHONPATH=. pytest <new test> -q`，再运行相关已有 scanner/partition 测试。

**实现约束：** 复用现有 scanner/partition 和 Wiki 数据结构；不新增数据库或第三方依赖；报告不得包含 API key 或绝对路径。

**报告：** 写入 `.superpowers/sdd/2026-09-06-novel-wiki-book-series-target/task-0-report.md`，包含改动文件、测试命令与结果、基线示例、已知限制和是否阻塞后续任务。不要派生子代理；完成后提交一个逻辑 commit。
