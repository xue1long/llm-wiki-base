# Task 0 审查报告

## 结论

- **Spec compliance：FAIL**
- **Task quality：FAIL**

审查范围：`task-0-brief.md`、`task-0-report.md`、`task-0-review-package.md`，并核对了对应实现逻辑。未修改实现，未调用远程 LLM，未添加第三方依赖。

## Findings

### Critical

1. **数据门 fail-open，候选全部不合格时仍可放行 LLM。**

   `partition.py:evaluate_series_gate` 只把授权、预算、审批人缺失写入 `status=blocked`；候选的 `LOW_SOURCE_COVERAGE`、`INSUFFICIENT_PAGES`、`NO_LEARNING_CLOSURE` 只影响 `CandidateDecision.decision`。只要治理字段齐全，任何候选均不为 `proceed` 时仍返回 `status="ready"`、`generation_mode="llm_allowed"`。因此下游若按 `generation_mode` 调用叙事 Provider，会违反简报“未通过数据门时只输出 `rule_only`，不调用叙事 Provider”，确定性和 fail-closed 均不成立。

   简报依据：`任一本书来源覆盖率低于 0.80、可归属页面少于 20 个或无法形成最小学习闭环时...不得用 LLM 填充`、`未通过数据门时只输出 rule_only`。

### Important

2. **最小学习闭环判定过于宽松，不能证明前置—产出链。**

   当前只检查候选中是否出现 concept/entity/synthesis（及若干别名），然后标记 `closed`。它没有检查关系是否形成可达链、章节是否有出口产物，也没有实现原规格要求的“至少 6 个可执行 reader task”及“连续两章无可验证出口产物”门槛；`reader_task_count` 仅作为计数，不参与裁决。一个只有三类页面、没有任何关系或任务的候选会被判为闭环。

   原规格依据：每个候选至少 6 个可执行 reader task，且不存在连续两章无可验证出口产物；每个候选须至少有一条前置—产出学习链。

3. **关系解析率不是实际指标。**

   `relation_parse_rate = 1.0 if relation_count else 1.0` 对所有输入恒为 1.0。扫描器在遇到坏关系时直接拒绝整个快照，因此无法报告“声明关系数”和“成功解析数”的分母；实施报告也承认该限制。这样无法满足可审计的关系解析率统计，且没有对空关系、悬空目标或解析失败进行门控。

4. **候选书契约未真正落实为三个候选及可否决结果。**

   候选完全按 `primary_taxonomy` 动态分组，没有固定/校验三个候选 book，也没有为缺失候选生成 `cancel` 或为跨候选页面生成 `merge`。由于分组结果总是非空 tuple，表达式 `reference if candidate_pages else cancel` 实际上永远不会产生 `cancel`；`merge` 也不会产生。实现只覆盖了“降级参考库”这一种否决路径。

5. **治理依赖被接收但没有进入可审计结果。**

   `GovernanceConfig` 有 `hard_reference_dependencies` 和 `soft_reference_dependencies`，但 `SeriesGateResult`/`CandidateDecision` 不输出它们，也不检查 hard 依赖是否满足。它们只进入 fingerprint，不能证明“参考库 hard/soft 依赖已固化”或阻断 hard 依赖缺失的后续发布。

6. **测试没有覆盖关键 fail-closed 和完整门槛。**

   只有 4 个测试；缺少“治理完整但所有候选均 reference/cancel 时必须 rule_only”“至少 6 个 reader task”“连续章节出口产物”“关系解析失败/悬空关系”“三个候选及 merge/cancel”“hard 依赖缺失”和实际 provider 不被调用的测试。现有测试只断言单个弱候选的 `decision != proceed`，无法发现第 1 项 Critical。

### Minor

7. **重复率分母没有被冻结或明确记录。**

   `_duplicate_rate` 的分子只统计非空 `content_sha256` 的重复页，但分母使用全部 `len(pages)`；如果快照含空 hash，重复率会被无哈希页面稀释。生产 scanner 当前总会填 raw hash，但简报/计划要求冻结统计分母，报告没有说明这一前提，也没有测试空 hash 情形。

8. **范围外预先加入章节分块实现。**

   `partition.py` 同时新增 `partition_pages` 和 `build_chapter_chunks`（约 70 行），属于后续页面归属/章节编译能力；Task 0 只要求基线数据门。它们没有被门禁使用，也没有对应测试，增加了未请求的 API 和维护面。

## 审查判定

上述 Critical 使“未通过数据门不得调用叙事 Provider”无法由结果契约保证；Important 项使闭环、关系指标、候选裁决和治理依赖不完整。因此 spec compliance 与 task quality 均为 FAIL。
