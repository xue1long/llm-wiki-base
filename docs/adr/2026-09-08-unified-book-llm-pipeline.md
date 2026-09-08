# ADR: Unified Wiki-to-Book LLM compilation pipeline

- **状态**: accepted
- **日期**: 2026-09-08
- **触发**: 让所有项目使用同一条可追溯的 Wiki-to-Book 编译流程，同时允许每个项目定义自己的 Book 编辑要求。
- **关联**: [`2026-09-08-unified-book-llm-pipeline`](../superpowers/plans/2026-09-08-unified-book-llm-pipeline.md)

## Context（背景）

不同项目可能需要不同的读者、文风、章节组织和内容密度，但编译流程不能因项目不同而分叉。项目规则也不能绕过来源、授权、质量门或发布保护。

本决策只覆盖 Wiki → Book 的 `book build-from-wiki`。现有 Knowledge Core → Book 的 legacy `book build` 不在本次范围内。

## Decision（决策）

每个项目根目录提供一份人可编辑的 `book.rules.md`，作为该项目的 Book 编辑说明。新项目初始化时只生成中性模板，不猜测项目风格，也不自动创建或授权 `.llm-wiki/policy.json`。

规则职责限定为：

- 目标读者和 Book 用途
- 文风、详细程度和章节组织偏好
- 术语和去重偏好

系统始终拥有更高优先级，负责来源、结构、提示词边界、授权、预算、质量检查、血缘和发布。项目规则不能改变这些行为，也不是可执行 DSL、Prompt 模板或文件操作脚本。

编译开始时读取一次规则文件，形成本次构建的快照并计算哈希。预览和发布结果记录规则哈希、规则快照、Wiki 快照和模型信息，保证结果可追溯。

编译分为三个明确阶段：计划预览不调用 LLM；内容预览调用 LLM 但不发布；正式发布调用 LLM，只有完整生成并通过系统检查后才切换当前 Book。失败不得覆盖旧版本。

发布事实以 `CURRENT.json` 和 release manifest 为准。新 release 必须先完整写入并通过检查，`CURRENT.json` 最后原子切换。SQLite lineage 只做审计记录，不决定当前 Book 是否已发布，也不引入新的发布状态机或数据库迁移。

如果 `CURRENT.json` 切换前失败，结果为 `failed` 且旧指针保持不变；如果指针已切换但 lineage 写入失败，结果为 `published_with_audit_warning`，不能报告为普通 `failed`。

## Rationale（理由）

- 统一流程避免每个项目维护一套 Book 编译器。
- 项目规则文件能表达实例差异，且比配置 DSL 更容易审阅和维护。
- 系统硬规则与项目编辑意图分离，降低提示词注入和误配置风险。
- 快照与哈希让规则变更可追踪，不依赖人工记忆版本号。

## Consequences（后果）

- 新项目会多一个需要填写的 `book.rules.md`，模板本身不代表已配置具体风格。
- 既有项目必须显式补充并审核自己的规则文件；迁移不会自动猜测编辑意图或授权外部 LLM。
- 规则修改后必须重新预览，正式发布才会使用新的规则快照。
- plan manifest 的 `chapter_files` 只列出实际生成的文件；计划中的章节使用独立字段。
- 个人版不引入人工审批流、规则继承、规则 DSL、独立回滚服务或复杂事务协调。

### Trigger to Revisit（重审触发条件）

- 同一项目的不同 Book 已稳定需要互相冲突的编辑规则。
- 项目规则文件开始承载机器控制语义，而不再只是编辑说明。
- 现有规则快照不足以重现发布结果。

## Alternatives Considered（备选方案）

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| 全局固定 Prompt | 实现简单 | 无法满足不同项目的 Book 需求 | ❌ 不采用 |
| 每项目 JSON/DSL 配置 | 机器约束强 | 引入 schema、继承和执行语义，复杂度高 | ❌ 第一版不采用 |
| 每项目 `book.rules.md` + 系统硬规则 | 易读、可追踪、能表达差异 | 需要系统做生成后硬校验 | ✅ 采用 |

## References（参考）

- [`2026-09-08-unified-book-llm-pipeline.md`](../superpowers/plans/2026-09-08-unified-book-llm-pipeline.md)
- [`2026-09-06-unified-book-editorial-state.md`](2026-09-06-unified-book-editorial-state.md)
- [`2026-09-07-book-lineage-publication.md`](2026-09-07-book-lineage-publication.md)

## Implementation Notes（实施笔记）

- 新项目初始化生成 `<project_root>/book.rules.md` 中性模板。
- 既有项目需人工创建和审核该文件；缺失、为空或不可读时，LLM 编译 fail-closed。
- 本 ADR 不改变 legacy `book build`，也不自动写入 `.llm-wiki/policy.json`。
- 固定回归测试和真实预览用于验证规则变化；固定测试不替代人工验收。
