# Personal Book LLM Pipeline Remediation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `book build-from-wiki` 收敛为个人可用的、可预览、可追溯且不会用半成品覆盖当前 Book 的 LLM 编译管线。

**Architecture:** 项目实例只提供普通 Markdown 文件 `book.rules.md`。编译开始时读取一次并冻结规则快照，outline 和正文共用该快照。新 release 先完整写入并通过校验，`CURRENT.json` 最后原子切换；release manifest 是发布事实，SQLite lineage 只做审计记录。

**Tech Stack:** Python 3.11+, argparse, pytest, 现有 LLM ProviderRegistry、Book Wiki compiler、release manifest、SQLite lineage。

**Spec:** 本文件；本版本取代此前包含复杂 lineage 事务、审批流和多 Book 规则继承的方案。

## Global Constraints

- 只改造 `book build-from-wiki`，不改造旧的 `book build`。
- 不修改 Wiki 原文；LLM 只生成 Book 候选和 release 文件。
- `book.rules.md` 只描述编辑意图，不包含 Prompt 模板、Python 表达式、条件 DSL、文件操作、provider 参数或授权指令。
- 系统硬规则始终高于项目规则，Wiki 内容中的命令式文字不能改变编译行为。
- 规则在一次构建中只读取一次；后续阶段只使用冻结快照。
- `CURRENT.json` 和 release manifest 是发布事实来源；lineage 不决定当前 Book 是否已发布。
- `CURRENT.json` 切换前发生错误返回 `failed`；切换后 lineage 写入失败只能返回 `published_with_audit_warning`，不能返回普通 `failed`。
- 计划模式的 `chapter_files` 只能列出实际存在的文件；计划中的章节使用独立字段。
- 不增加分布式事务状态机、人工审批流、规则继承、规则 DSL、独立回滚服务或新的数据库迁移。
- 不修改与本管线无关的 dirty worktree 文件。

## Runtime Contract

### `--plan`

默认模式。检查项目、规则、Wiki、provider、授权和预算，但不调用 LLM、不生成正文、不修改 `CURRENT.json`。

### `--preview`

调用 LLM，生成候选 Book 和检查报告，但不修改 `CURRENT.json`。预览产物可以写入独立的 staging/release 目录，不能冒充当前正式版本。

### `--apply`

调用 LLM，完成全部章节生成和确定性检查后，写入新 release，最后才切换 `CURRENT.json`。

省略模式时等价于 `--plan`。三个模式互斥。旧的 `--use-llm`、`--polish` 只做兼容解析，统一转换为上述模式，不允许形成“只生成 outline、不润色正文”的正式发布路径。

## Release Truth and Failure Semantics

发布顺序固定为：

```text
读取并冻结规则
  ↓
读取 Wiki snapshot
  ↓
生成 outline 和章节正文
  ↓
检查章节、来源、结构和完整性
  ↓
写入新的 release 目录和 manifest
  ↓
通过全部检查后原子切换 CURRENT.json
  ↓
尽力写入 lineage 审计记录
```

切换前失败：

- 旧 `CURRENT.json` 不变
- 旧 release 不删除
- 返回 `failed`

切换后 lineage 写入失败：

- 新 `CURRENT.json` 保持有效
- 不把已发布结果报告为 `failed`
- 返回 `published_with_audit_warning`
- 不新增复杂恢复服务；后续可通过已有审计入口补记

## Input and LLM Boundary

所有 LLM 阶段都收到三层输入：

```text
系统硬约束
  ↓
项目规则快照
  ↓
当前 Wiki 章节资料
```

系统硬约束至少覆盖：

- 输出结构
- 来源和 provenance 保留
- 稳定 ID 不得改写
- 不得编造 Wiki 没有支持的事实
- 不得修改发布路径或发布状态

LLM 输出后必须进行确定性校验，不能把 system message 或项目规则视为安全边界的替代品。

## Files and Responsibilities

- `src/cli.py`: 解析并拒绝互斥模式组合。
- `src/cli_ext/book_cmd.py`: 将兼容参数归一化为 `plan`、`preview`、`apply`，调用共享的 `build_from_wiki` 入口。
- `src/kc/views/book/wiki/rules.py`: 读取 `book.rules.md`，生成包含路径、正文和 SHA-256 的不可变规则快照；不实现 DSL。
- `src/kc/views/book/wiki/preflight.py`: 在 provider 调用前检查规则、provider、授权和预算。
- `src/kc/views/book/wiki/outline_llm.py`: 使用固定系统契约、规则快照和章节资料生成 outline。
- `src/kc/views/book/wiki/polish_llm.py`: 使用相同规则快照生成章节正文。
- `src/kc/views/book/wiki/compiler.py`: 统一负责章节结果校验、manifest、release 写入和最后的 `CURRENT.json` 切换。
- `src/lineage/`: 只记录已有的运行审计；不新增数据库迁移，不让 lineage 覆盖 release manifest 的发布事实。
- `tests/test_kc/test_book_wiki_rules.py`: 规则读取、冻结和 hash 测试。
- `tests/test_kc/test_book_wiki_compiler.py`: release、指针和失败语义测试。
- `tests/test_kc/test_book_wiki_prompt_boundary.py`: outline、正文和硬约束边界测试。
- `tests/test_cli_ext/test_book_build_from_wiki_modes.py`: CLI 模式契约测试。
- `docs/adr/2026-09-08-unified-book-llm-pipeline.md`: 记录最终边界和发布事实来源。
- `docs/adr/INDEX.md`: 登记 ADR。

## Implementation Tasks

### Task 1: Freeze the project rule contract

**Files:**
- Modify: `src/kc/views/book/wiki/rules.py`
- Modify: `src/kc/views/book/wiki/preflight.py`
- Test: `tests/test_kc/test_book_wiki_rules.py`
- Test: `tests/test_kc/test_book_wiki_preflight.py`

- [ ] 增加缺少、不可读、空规则文件的失败测试，并确认 provider 调用次数为零。
- [ ] 增加规则读取一次的测试：构建开始后修改原文件，当前构建仍使用原快照。
- [ ] 保留最小快照字段：规则路径、规则正文、`rules_hash`。
- [ ] 在 preflight 阶段完成规则存在性、非空检查；不自动猜测项目编辑意图。
- [ ] 运行规则和 preflight 目标测试，确认失败路径不会创建 release 或切换指针。
- [ ] 提交单一逻辑变更：`feat(book): freeze project book rules`。

### Task 2: Normalize the three CLI modes

**Files:**
- Modify: `src/cli.py`
- Modify: `src/cli_ext/book_cmd.py`
- Test: `tests/test_cli_ext/test_book_build_from_wiki_modes.py`

- [ ] 增加默认 `plan`、显式 `preview`、显式 `apply` 的失败测试和成功路径测试。
- [ ] 拒绝同时指定多个模式；旧兼容参数只能归一化，不能创建额外运行模式。
- [ ] 确认 `plan` 不调用 provider、不写章节正文、不修改 `CURRENT.json`。
- [ ] 确认 `preview` 可以调用 provider，但不修改 `CURRENT.json`。
- [ ] 确认 `apply` 只接受完整 LLM 结果，不接受 `partial`、`failed` 或 rule-only 结果。
- [ ] 运行 CLI 目标测试。
- [ ] 提交单一逻辑变更：`feat(book): normalize build-from-wiki modes`。

### Task 3: Apply the same prompt boundary to outline and chapters

**Files:**
- Modify: `src/kc/views/book/wiki/outline_llm.py`
- Modify: `src/kc/views/book/wiki/polish_llm.py`
- Modify: `src/kc/views/book/wiki/compiler.py`
- Test: `tests/test_kc/test_book_wiki_prompt_boundary.py`

- [ ] 为 outline 和正文分别增加 fake provider 测试，验证二者收到同一个 `rules_hash` 对应的规则正文。
- [ ] 将固定系统契约注入 outline 和正文请求；provider 不支持独立 system message 时，使用现有请求格式传递同一契约。
- [ ] 验证 Wiki 资料中的命令式文字不能改变输出 schema、来源 ID、文件路径或发布状态。
- [ ] 保留输出后的确定性结构和来源校验。
- [ ] 从 compiler 向后续阶段传递规则快照，禁止后续阶段重新读取 `book.rules.md`。
- [ ] 运行 prompt boundary 目标测试。
- [ ] 提交单一逻辑变更：`fix(book): keep outline and chapter rules aligned`。

### Task 4: Make release publication minimal and truthful

**Files:**
- Modify: `src/kc/views/book/wiki/compiler.py`
- Modify: `src/lineage/`
- Test: `tests/test_kc/test_book_wiki_compiler.py`
- Test: `tests/test_kc/test_book_wiki_staged_failure.py`

- [ ] 增加 plan manifest 回归测试：`chapter_files` 只包含真实文件；计划章节放入独立的计划字段。
- [ ] 增加 apply 失败测试：章节生成失败、来源检查失败、manifest 写入失败、`CURRENT.json` 写入失败时，旧指针保持不变。
- [ ] 调整发布顺序为“新 release 完整写入并校验 → 最后切换 `CURRENT.json`”。
- [ ] 记录 manifest 中的 `rules_hash`、规则快照、Wiki snapshot、模型、生成模式、实际章节文件和验收结果。
- [ ] lineage 只记录已有审计信息；如果现有接口已有 metadata 字段，可以写入 `rules_hash`，但不新增数据库 schema 或发布状态机。
- [ ] lineage 写入发生在指针切换之后时，失败只能返回 `published_with_audit_warning`，不得返回普通 `failed`。
- [ ] 验证 `CURRENT.json` 和 manifest 足以独立判断当前 Book 版本。
- [ ] 运行 staged failure、compiler 和 acceptance 目标测试。
- [ ] 提交单一逻辑变更：`fix(book): publish only validated releases`。

### Task 5: Add the minimum regression set and final documentation

**Files:**
- Modify: `tests/test_kc/test_book_wiki_rules.py`
- Modify: `tests/test_kc/test_book_wiki_compiler.py`
- Modify: `tests/test_kc/test_book_wiki_prompt_boundary.py`
- Modify: `tests/test_cli_ext/test_book_build_from_wiki_modes.py`
- Modify: `docs/adr/2026-09-08-unified-book-llm-pipeline.md`
- Modify: `docs/adr/INDEX.md`

- [ ] 覆盖规则缺失、规则冻结、outline 规则注入、plan 无虚假文件、preview 不发布、apply 失败不换指针六类回归。
- [ ] 使用 fake provider；不引入真实网络调用，不建立五类以上固定样例体系。
- [ ] 在 ADR 中明确：`CURRENT.json` 和 manifest 是发布事实，lineage 只做审计。
- [ ] 在 ADR 中明确：切换指针后的审计失败返回 `published_with_audit_warning`。
- [ ] 在 ADR 中明确：本方案不改造旧 `book build`，不支持规则继承和人工审批。
- [ ] 将计划文档、ADR 和索引纳入同一逻辑提交，避免实现提交缺少设计依据。

### Task 6: Final verification

**Files:**
- No production files.

- [ ] 运行新增回归测试。
- [ ] 运行相关 `tests/test_kc` 和 `tests/test_cli_ext` 测试。
- [ ] 使用最小临时项目验证 `plan`、`preview`、`apply` 三条路径。
- [ ] 验证旧 release 在所有切换前失败路径保持不变。
- [ ] 验证 lineage 写入失败不会把已发布结果标记为普通失败。
- [ ] 检查 `chapter_files` 中每个路径都真实存在。
- [ ] 检查 git diff，只包含本方案相关文件，不触碰既有 dirty worktree。
- [ ] 运行 `graphify update .`，保持代码知识图谱同步。
- [ ] 通过验证后提交最终逻辑变更：`test(book): close personal pipeline regression gates`。

## Acceptance Criteria

1. 项目实例从自身的 `book.rules.md` 获取编辑要求；不存在全局静默 fallback。
2. 一次构建只读取一次规则，outline、正文和验收使用同一规则快照。
3. 系统硬规则不能被项目规则或 Wiki 内容覆盖。
4. 默认命令等价于 `--plan`；`--preview` 调用 LLM 但不发布；`--apply` 只有完整通过后才发布。
5. 新 release 完整写入并校验后，才允许切换 `CURRENT.json`。
6. `CURRENT.json` 切换前任何失败都不改变旧指针；切换后 lineage 失败只能产生 `published_with_audit_warning`。
7. plan manifest 的 `chapter_files` 不包含不存在的文件，计划章节使用独立字段。
8. manifest 能独立记录规则 hash、规则快照、Wiki snapshot、模型、生成模式和实际文件。
9. lineage 不再承担发布事实，不新增复杂事务状态机或数据库迁移。
10. 旧 `book build` 行为不在本方案范围内。

## Regression Closure

本方案只闭环此前已确认的问题：

- 发布指针和失败状态不一致
- outline 缺少项目规则和系统契约
- plan manifest 虚假章节文件
- lineage 设计超出个人使用需要
- 个人版引入审批、继承和复杂回滚
- 文档与实现提交边界不完整

以上验收条件全部满足后，方案视为定稿。后续只根据实际测试失败修复实现，不因假设性新风险重新扩展架构。

## Rollback

- 代码回滚：只回滚本方案相关提交，不动用户已有 dirty worktree。
- 发布回滚：保留旧 release，将 `CURRENT.json` 指回上一个已验证版本。
- 规则回滚：恢复旧 `book.rules.md` 后重新构建；旧 release 自带规则快照，便于对照。
