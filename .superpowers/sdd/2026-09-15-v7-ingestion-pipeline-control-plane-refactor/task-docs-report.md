# Task 6 文档 / ADR 收尾报告

**日期**: 2026-09-15
**范围**: 仅文档、ADR 与本报告；未修改代码、任何 `progress.md`、raw、Wiki、
原始资料或其他既有脏文件。

## 修改文件

- `docs/superpowers/plans/2026-09-15-v7-pipeline-architecture-v3.md`
  - 修复 Stage 6 流程图的边框/缩进排版。
  - 将首轮必需链路明确为 Stage 1/2/3/4/5 → Stage 7 → durable source outcome。
  - 将 Stage 6 放到终局之后，定义为可选 best-effort 后处理。
  - 补充 Stage 5 excerpt、item provenance、Stage 6 失败边界和 C1-C4 验收。
- `docs/superpowers/plans/2026-09-15-v7-pipeline-v3-implementation.md`
  - 在不改 A1-A20 和既有 Phase/工作量语义的前提下，同步 Stage 5/6 约束。
  - 补充对应测试意图、文档交付、风险和 Definition of Done。
- `docs/adr/0011-v7-ingestion-outcome-control-plane.md`
  - 记录唯一 source outcome、Writer→queue→checkpoint→report 的持久化边界。
  - 记录 Stage 5 exact-match 降级、provenance 保留、Stage 6 best-effort 边界。
  - 区分历史提交证据与本轮实际检查，并记录可用/不可用的回滚手段。
- `.superpowers/sdd/2026-09-15-v7-ingestion-pipeline-control-plane-refactor/task-docs-report.md`
  - 记录本轮文件、判断、验证与待验证项。

## 关键判断

1. `source_text_excerpt` 适合人工定位，不适合作为 LLM paraphrase 的 literal
   substring 硬门；安全性继续由 canonical item provenance、evidence 完整性和
   页面级 source 闭环承担。
2. 当前 V7 `relation_extractor.py` 已实现且有独立测试，但 `scripts/` 没有
   `extract_relations()` 调用方。Stage 6 因此是可选后处理，而不是首轮
   source→concept 成功条件。
3. Stage 6 后续接入必须复用同一 page ID、queue、checkpoint 和 outcome 契约；
   其失败不能回写、降级或回滚已 durable 的首轮 outcome。
4. ADR 0011 编号检查结果为 0007、0008、0009、0010、0011；0011 是当前未跟踪
   草稿且没有另一个已提交文件占用，因此保留编号并完善现有内容。
5. 回滚以 `v7-control-plane-wave1/2/3` 标签和逐 Task commit 为当前可靠手段。
   文档计划中的 `V7_USE_V3_CONTROL_PLANE` 未在当前源码中检出，不能宣称为已
   验证的运行时开关；`V7_USE_V3=false` 的 legacy placeholder 也不作为安全回退。
6. 当前 Stage 2 的 canonical item ID 保留既有切片语义：heading 使用
   `#section-N`，编号条目使用 `#item-N`，未切片全文使用 source relative；
   Task 6 不借文档收尾暗改这项已落地行为。

## 验证与证据

- 完整阅读 Task 6 指定的控制面计划、brief、架构计划、实现计划和 ADR 0011。
- 只读调用关系检查：V7 `extract_relations()` 仅见实现与 Stage 6 测试，未见
  `scripts/` 调用方。
- 标签检查：`v7-control-plane-wave1`、`v7-control-plane-wave2`、
  `v7-control-plane-wave3` 均存在。
- 专属 ledger 记录：Wave 1 `123 passed`，Writer/Checkpoint 提交分别记录
  `169 passed`、`172 passed`，自动化 smoke 位于 commit `7c565c9b`；这些是历史
  证据，本轮未把它们描述为重新执行结果。
- 提交前执行 Markdown 定向检查、`git diff --check`、目标文件 diff 审阅和精确
  暂存范围检查；最终结果在本报告提交后补记于提交说明，不修改 progress ledger。

## 待验证项

- 当前环境缺少 pytest，Task 3/4/5/7 的实现缺口和完整测试复跑仍由主会话按专属
  ledger 处理；Task 6 不修改运行时代码。
- `V7_USE_V3_CONTROL_PLANE` 需要实现与回归后，才能升级为可用运行时回滚手段。
- Stage 6 真正接入时仍需新增后处理 outcome/幂等/失败恢复测试；本 Task 只锁定
  架构边界，不提前实现接线。
- 在真实 provider smoke、最终 whole-branch review 和 final tag 完成前，不得宣称
  控制面重构完成，也不得启动全量 apply。
