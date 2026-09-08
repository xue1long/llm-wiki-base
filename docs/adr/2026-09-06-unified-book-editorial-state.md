# ADR: Book 以持久化编辑状态为权威，TutorialPath 作为阅读覆盖层

- **状态**: proposed
- **日期**: 2026-09-06
- **触发**: 将 Wiki 稳定编译为面向人阅读的个人知识书，并避免教程、正文和发布版本形成多套知识来源
- **关联**: `docs/superpowers/plans/2026-09-06-unified-knowledge-book-remediation.md`

## Context（背景）

项目原有 Book 编译器能够生成目录、章节 Markdown、manifest 和 `CURRENT.json`，但当前正文主要是规则聚合，LLM 润色只生成编排元数据。原有书系方案把教程建模为多本独立书，与“一个知识域的一本个人知识书”不一致。

多轮审计发现，问题不是缺少更多质量门，而是没有明确 Book 的权威编辑状态：页面取舍、章节归属、目录和稳定 ID 如果只存在于 staging 或每次由 LLM 重新推断，就无法保证重复构建一致，也无法沉淀个人判断。

因此需要明确四层职责：

```text
Wiki
  ↓
BookEditorialState
  ↓
BookCompiler
  ↓
BookRelease
  ↓
TutorialPath
```

## Decision（决策）

### 1. 权威来源分层

- **Wiki**：保存原子知识页面、来源、关系和搜索索引。
- **BookEditorialState**：保存某个知识域的页面裁决、章节归属、目录和稳定 ID；这是 Book 编译的正式输入，不是临时 staging 产物。
- **BookCompiler**：只把确定的编辑状态编译成规则版或 LLM 版章节正文，不决定页面最终归属。
- **BookRelease**：保存不可变的章节、manifest、来源摘要和生成元数据。
- **TutorialPath**：保存章节/小节的阅读顺序、任务和检查点，不保存章节正文。

### 2. 知识域与 Book 身份

新模型使用：

```text
project_id
domain_id
book_id
```

当前 `novel-wiki` 第一阶段视为一个知识域，并使用一个 canonical Book。旧 `series_id` 仅用于兼容旧 release，不再作为新正文内容容器。

### 3. BookEditorialState 的最小内容

```text
book-wiki/
  ├── book.json
  ├── editorial/
  │   ├── curation.json
  │   ├── outline.json
  │   └── paths.json
  ├── .releases/
  └── CURRENT.json
```

文件职责固定为：

- `book.json`：`domain_id`、`book_id`、版本策略和当前编辑状态；
- `editorial/curation.json`：页面裁决、primary owner、secondary references 和裁决理由；
- `editorial/outline.json`：卷、章、节、稳定 ID 和章节页面分配；
- `editorial/paths.json`：TutorialPath 的引用式定义；
- `.releases/`：不可变构建产物；
- `CURRENT.json`：当前正式 release 指针。

`editorial/` 是正式 Book 输入，不能放入 staging，也不能只存在于 release 内。每次构建记录 `editorial_revision` 和输入 hash。

第一阶段固定四个文件的 schema 版本：`book-v1`、`book-curation-v1`、`book-outline-v1`、`tutorial-path-v1`。当前 `novel-wiki` 的身份映射为 `domain_id=novel-wiki`、`book_id=novel-wiki-book`；旧 `series_id` 只进入兼容读取，不参与新构建的页面归属。

页面裁决至少支持：

```text
include
duplicate
conflict
exclude
unresolved
```

每个纳入页面必须有一个 `primary_chapter_id`；其他章节只能写入 `secondary_references[]`，只能生成引用或相关链接，不能复制正文。

章节 section 的最小状态为：

```text
normal
disputed
blocked
editorial
```

### 4. 编译边界

编译输入必须是：

```text
WikiSnapshot + BookEditorialState + canonical_outline
```

编译器负责：

- 规则聚合；
- LLM 章节/section 正文生成；
- section/page 级来源绑定；
- 正文结构校验；
- 生成 manifest。

编译器不负责：

- 临时决定页面归属；
- 自动裁决冲突；
- 创建第二套教程正文；
- 让标题变化重新生成稳定章节 ID。

第一阶段的正文策略是 `generated_only`：章节正文是绑定 snapshot 的生成产物，不提供人工直接覆盖层。个人的稳定编辑先沉淀在 `curation.json`、`outline.json` 和 `paths.json`；人工正文覆盖作为后续独立决策，不隐含在当前设计中。

### 5. 正文和来源范围

第一阶段只保证 section/page 级来源：

```text
Section.source_page_ids
```

标题、过渡句和任务说明可以标记为 `editorial` 或 `task`，不得伪装成直接来源事实。claim-level evidence、source fragment 和自动事实蕴含检查暂不纳入第一阶段。

### 6. 发布状态

将生成模式和发布状态分开：

```text
generation_mode: rule_only | llm
release_status: complete | partial | failed
book_freshness: fresh | stale | building | failed
```

`book_freshness` 描述当前 Book 相对于最新 Wiki 的状态，不等同于 release 状态。Wiki 变化后，Book 可以标记为 `stale`，但仍继续指向最后一个完整 CURRENT。

第一阶段通过比较当前 Wiki snapshot hash 与 CURRENT release 的 `wiki_snapshot_hash` 触发 `stale`，不引入事件系统。

发布规则：

| 模式 | 状态 | 是否写 release | 是否更新 CURRENT |
|---|---|---:|---:|
| rule_only | complete | 是 | 是 |
| llm | complete | 是 | 是 |
| llm | partial | 仅 preview/staging | 否 |
| 任意 | failed | 否 | 否 |

### 7. TutorialPath 约束

TutorialPath 只包含：

```text
path_id
title
goal
ordered chapter_id / section_id references
tasks
checkpoints
status
```

路径可以复用同一章节。章节拆分或合并时，第一阶段允许人工修复受影响路径，不建设完整 lineage 服务。

### 8. 发布安全

发布顺序固定为：

```text
snapshot
→ compile
→ validate
→ write immutable release
→ verify manifest and hashes
→ atomically update CURRENT
```

每个 release 必须记录三类 hash：

```text
wiki_snapshot_hash
editorial_state_hash
release_manifest_hash
```

全量扩展前必须设置 LLM 调用上限、输入/输出 token 上限、重试上限和最长运行时间；达到上限时只生成 partial/failed 结果，不更新 CURRENT。

Pilot 默认上限为：`max_llm_calls=3`、`max_input_tokens=60000`、`max_output_tokens=15000`、`max_retries=1`、`max_runtime_seconds=900`。全量构建必须提供经批准的显式配置。缺少 `external_authorized`、`budget_cap` 或 `approver` 时，不允许调用外部 Provider，只能执行 rule-only。

外部 Provider 调用前执行路径 allowlist、敏感字段、来源授权和 provider scope 检查。

## Rationale（理由）

- BookEditorialState 让个人的页面取舍、章节结构和目录真正沉淀下来。
- 编译器只负责转换，避免同时承担策展、规划和发布决策。
- TutorialPath 作为覆盖层，避免每条教程复制一套正文。
- section/page 级来源足以支持第一版可读性和基本追溯，避免过早建设 claim 图谱。
- 分离生成模式和发布状态，避免 rule-only、LLM partial 和 failed 混用。
- 继续复用现有 release/CURRENT/Reader，减少迁移范围。

## Consequences（后果）

### Positive

- 页面裁决、章节归属和稳定 ID 可以跨构建保留。
- 编辑状态有明确的项目内持久化位置，不依赖临时 staging。
- 同一章节可以被多个 TutorialPath 复用。
- LLM 失败不会污染旧版本。
- Book 的正文、目录和路径职责清晰。
- 不需要新增数据库、图数据库或搜索系统。

### Negative

- 需要维护 BookEditorialState 和 canonical outline。
- Wiki 更新后需要重新判断受影响章节。
- 第一阶段生成正文不支持人工直接覆盖；需要人工正文编辑时必须引入新的 override 层。
- 第一阶段不能自动完成 claim-level 事实验证。
- 章节拆分/合并暂时需要人工修复路径。
- rule-only 和 LLM release 需要在 UI 中明确区分。

### Trigger to Revisit（重审触发条件）

- 一个项目确实出现多个独立知识域，需要多个 Book。
- 个人人工编辑正文成为稳定需求。
- section/page 级来源不足以满足使用场景的可信度要求。
- 章节拆分/合并频繁发生，人工路径修复成本超过自动迁移成本。
- 全量构建成本或运行时间超过项目预算。
- 需要保存人工改写正文，并且 generated-only 无法满足需求。

## Alternatives Considered（备选方案）

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| Wiki 直接编译 Book | 实现简单 | 个人裁决和目录结构无法沉淀 | ❌ 拒绝 |
| 三本教程 + 一个参考库 | 阅读路径直观 | 正文重复，多书同步复杂，偏离原始目标 | ❌ 拒绝 |
| BookEditorialState + 一本文正文 + 多路径 | 权威关系清晰，复用现有 release | 需要新增持久化编辑状态 | ✅ 采用 |
| 多 Book/图数据库一开始全建 | 扩展性强 | 当前目标不需要，实施成本高 | ❌ 延后 |

## References（参考）

- `knowledge/novel-wiki/purpose.md`
- `src/kc/views/book/wiki/compiler.py`
- `src/kc/views/book/wiki/polish_llm.py`
- `docs/superpowers/plans/2026-09-06-unified-knowledge-book-remediation.md`
- `docs/reports/2026-09-06-book-series-baseline.md`

## Implementation Notes（实施笔记）

1. 先定义并持久化 BookEditorialState，不先扩展全量 LLM 编译。
2. 先用 10–30 个真实页面生成 2–3 个章节的 rule-only Book。
3. 目录和章节结构人工确认后，再接入 LLM section 正文。
4. 现有 `series_id` 只走兼容读取；新 release 使用 `domain_id/book_id`。
5. 旧 release 不重写，只通过读取适配器继续可读。
