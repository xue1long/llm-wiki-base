# Plan: novel-wiki 全量知识 Book 编译

status: planned
branch: codex/book-series-target

## Goal

将 `knowledge/novel-wiki` 的全部可编译知识页纳入一个可发布的 Wiki-to-Book release：

- 1255 个 `concepts`、`entities`、`synthesis` 页面全部覆盖；
- 463 个 `sources` 原始资料进入来源附录/索引和 provenance，不直接混入正文生成；
- 自动生成完整 volume/chapter 目录，预计约 179 个受上下文限制的章节块；
- 支持分批、断点续编、预算预估、失败恢复和 `preview -> apply-from`；
- 发布仍通过原子 `CURRENT.json`，partial/failed/stale release 不得成为当前版本；
- Book 发布与 LanceDB 更新保持独立。

## Explicit non-goals

- 不把 1718 个文件一次性发送给 LLM；
- 不让 LLM 决定丢弃页面、修改 page ID 或伪造 provenance；
- 不删除或覆盖现有 12 页 pilot release；
- 不在本计划中自动更新 LanceDB；
- 不把人工可读性/人工验收重新设为发布硬阻塞；保留风险抽样和报告记录。

## Design

### Scope contract

新增显式 `scope=full_knowledge` 编译范围。该范围从当前 Wiki snapshot 读取全部可编译页面，绕过现有 pilot 的持久化 `editorial/curation.json` 页面筛选，但不绕过：

- snapshot consistency；
- source allowlist / sensitivity gate；
- outline coverage validation；
- chapter provenance validation；
- LLM budget and external authorization；
- release acceptance and CURRENT atomic promotion。

`sources` 仍是 compiler 的证据边界。全量 Book 生成 `sources-index.md` 和 source manifest，记录相对路径、hash、所属知识页和引用关系；若未来要求将原始 sources 全文作为正文，需要另立 `full_raw_sources` 范围，不能隐式改变本计划语义。

### Pipeline

```text
freeze Wiki snapshot
  -> deterministic partition of all eligible pages
  -> deterministic volume/chapter outline
  -> budget manifest and batch plan
  -> batch chapter generation with compiler-owned IDs/provenance
  -> deterministic source appendix and indexes
  -> coverage/provenance/quality acceptance
  -> one candidate release
  -> preview
  -> apply-from same release
  -> optional independent vector reconcile
```

LLM 只负责章节正文和可选的标题/摘要润色。章节边界、page ownership、section IDs、source IDs 和发布状态由编译器控制。该分层方式符合大规模多文档总结的层级摘要实践；GraphRAG 的社区层级与 map-reduce 也采用先分层组织、再汇总的路线。

## Tasks

### Task 1: 建立全量范围接口与覆盖报告

- Files:
  - `src/kc/views/book/wiki/compiler.py`
  - `src/kc/views/book/wiki/model.py` 或新增 `src/kc/views/book/wiki/scope.py`
  - `src/cli_ext/book_cmd.py`
  - `src/cli.py`
- Test first:
  - full scope 不读取 pilot curation 作为页面过滤器；
  - snapshot 中所有 1255 个 eligible page ID 都进入 scope report；
  - scope report 明确 `eligible_pages=1255`、`source_files=463`、`excluded_pages=0` 或列出明确原因；
  - 默认 pilot 行为保持不变。
- Implementation:
  - 新增 `--scope pilot|full_knowledge`，默认 `pilot`；
  - manifest 增加 `scope_mode`、`eligible_page_count`、`covered_page_count`、`coverage_ratio`、`source_appendix_count`；
  - full scope 使用 snapshot 全量页面，不能通过 `book.json` 的旧 curation 缩减输入；
  - 允许输出到独立 staging 目录，但最终 candidate 仍使用标准 `book-wiki` promotion seam。
- Acceptance:
  - full scope 覆盖率计算为 100%；
  - pilot release 与 CURRENT 不变；
  - 未发生 LLM 调用即可完成 scope/plan dry-run。
- Status: pending

### Task 2: 生成确定性全量目录和 source appendix

- Files:
  - `src/kc/views/book/wiki/partition.py`
  - `src/kc/views/book/wiki/outline_validate.py`
  - `src/kc/views/book/wiki/compiler.py`
  - 新增 `src/kc/views/book/wiki/source_appendix.py`
- Test first:
  - 1255 个 page ID 恰好出现一次；
  - chapter chunk 不拆分页面或 content block；
  - 超长单页被隔离并标记，而不是静默丢弃；
  - appendix 能覆盖所有 463 个 source 文件并保留 hash/path/provenance；
  - outline snapshot ID 与 Wiki snapshot 一致。
- Implementation:
  - 沿用 `partition_pages` + `build_chapter_chunks` 的确定性分区；
  - 默认不增加 outline LLM 调用，章节标题用稳定规则生成；
  - 生成 volume index、chapter index、coverage ledger 和 `sources-index.md`；
  - 允许后续单独开启 outline naming，不影响 page assignment。
- Acceptance:
  - 当前数据集 plan-only 预计 1255 页、约 179 个 chapter chunk；
  - outline validation、page coverage、source appendix validation 全通过。
- Status: pending

### Task 3: 增加可恢复的 batch build 与预算 manifest

- Files:
  - `src/kc/views/book/wiki/compiler.py`
  - 新增 `src/kc/views/book/wiki/batch_state.py` 或最小复用现有 batch state
  - `src/kc/views/book/wiki/acceptance.py`
  - `src/cli_ext/book_cmd.py`
- Test first:
  - batch 中途 provider timeout 后可从最后一个 completed chapter 继续；
  - 重跑同一 snapshot/prompt hash 不重复调用已完成章节；
  - 任意 batch 失败都不会更新 CURRENT；
  - budget manifest 在首次 provider 调用前阻断不足预算；
  - 进程重启后状态仍可恢复，状态文件损坏则 fail-closed。
- Implementation:
  - 新增 `--batch-size`、`--resume`、`--budget-manifest`；
  - 每个 batch 记录 snapshot ID、page IDs、prompt hash、调用数、状态和失败原因；
  - 推荐 10～20 章/批次；batch 只是执行与恢复单位，最终仍只发布一个 candidate release；
  - 使用内容 identity + prompt hash 作为缓存键，避免 preview/apply 或重试重复生成。
- Acceptance:
  - 可模拟失败、恢复、重复执行和预算耗尽；
  - manifest 能报告 minimum/configured/actual calls；
  - partial batch 只能停留在 staging。
- Status: pending

### Task 4: 全量章节正文生成与质量门

- Files:
  - `src/kc/views/book/wiki/polish_llm.py`
  - `src/kc/views/book/wiki/polish_validate.py`
  - `src/kc/views/book/wiki/compiler.py`
  - `tests/test_kc/test_book_chapter_body.py`
- Test first:
  - 每章正文必须有 compiler-owned section ID 和 source page IDs；
  - MiniMax 的 object/list/string 变体都不能造成 provenance 猜测；
  - 单 section 长正文数组可受控合并，短标题数组和多 section 数组仍拒绝；
  - 任一章节失败时总体 release 为 partial，不得伪装 complete；
  - 章节正文、来源、章节数量和 coverage ledger 一致。
- Implementation:
  - 使用现有结构化章节 seam；
  - full scope 默认每 chunk 一个生成单元，避免逐页摘要重复；
  - 生成失败只允许确定性规则 fallback 作为诊断/预览产物，正式 LLM release 必须全部 complete；
  - 质量报告区分自动 gate、人工可读性抽样和人工内容验收，不修改确定性 acceptance report。
- Acceptance:
  - 179 个章节全部 `content_status=complete`；
  - `coverage_ratio=1.0`、`chapter_provenance=pass`、`release_status=complete`；
  - 人工抽样至少覆盖每个 volume 和高风险/长章节，结果记录但不作为硬阻塞。
- Status: pending

### Task 5: 发布、WebUI 和 vector 状态对接

- Files:
  - `src/kc/views/book/wiki/compiler.py`
  - `src/services/files.py`
  - `src/server/routes/files.py`
  - `web/js/views/book.js`
  - `docs/webui-buttons.md`
  - tests for files/routes/UI behavior
- Test first:
  - full candidate 通过 `--apply-from` 后 CURRENT 原子切换；
  - WebUI 读取全量 release 的 chapter count、volume、source appendix；
  - 旧 pilot release 可通过版本选择器回读；
  - Book 发布不改变 LanceDB 状态；
  - vector status/reconcile 单独报告 pending/update。
- Implementation:
  - WebUI 默认显示 full release，并显示 scope/coverage/appendix 状态；
  - 保留 pilot release 版本回读能力；
  - source appendix 作为只读目录展示，原始 source 内容仍走已有 Wiki 文件读取安全路径；
  - 同步更新按钮/API 映射文档。
- Acceptance:
  - WebUI 能阅读全量 Book；
  - `CURRENT.json` manifest hash 与 release 一致；
  - vector 未 reconcile 时 UI 明确显示未更新，而不是显示 Book 已同步向量。
- Status: pending

### Task 6: 真实全量 preview 与 apply

- Files:
  - no new implementation files; release evidence under `.index/book-wiki/`
- Preconditions:
  - Tasks 1～5 tests pass；
  - full scope budget manifest 已生成；
  - 明确外部 LLM provider、最大调用数、预算 cap、allowed paths；
  - 用户单独批准全量内容发送，不复用本次 4-call pilot 批准。
- Execution:
  - plan-only：确认 1255/1255 coverage、预计约 179 章；
  - preview：按 batch 执行并生成 candidate release；
  - 自动验收通过后，用 `--apply-from <preview_release_id>` promote；
  - 发布后单独运行 `vector status`，不自动 reconcile。
- Acceptance:
  - release `complete`；
  - automated acceptance `pass`；
  - `CURRENT.json` 指向 candidate；
  - Book 与 source appendix 可被 WebUI 读取；
  - LanceDB 状态单独记录。
- Status: pending

## Assumptions and failure impact

| Assumption | If false |
|---|---|
| “全量 Book”指全部 1255 个知识页，sources 作为附录/证据 | 若要求 sources 全文进正文，需要新增 `full_raw_sources` 范围和更大预算 |
| 179 个 chunk 的默认上下文上限可接受 | 需调整分区策略并重新估算调用数 |
| MiniMax 可稳定完成单 chunk 正文生成 | 需切换 provider 或增加缓存/结构化修复，不允许默默 rule fallback 发布 |
| 用户允许数百次外部 LLM 调用 | 只能先发布 rule-only/full index，不能完成 LLM Book |
| 现有 Wiki snapshot 无重复 ID/标题 | 先进入扫描阻塞，不能生成全量 release |

## Audit — Round 1: comprehensive vulnerability audit

### ① 致命缺陷

1. **全量边界未被机器化定义**：若只删除 curation 过滤，sources 是否纳入会产生歧义。后果是“全量”无法验收。整改：固定 `scope_mode`、eligible/appendix/excluded 三类计数，并写入 manifest。
2. **预算未前置估算**：179 章在一次重试策略下可能达到 358 次以上调用。后果是执行到中途耗尽预算，留下昂贵 partial。整改：Task 3 在首个 provider 调用前生成 minimum/configured/max manifest 并阻断不足预算。
3. **发布恢复边界不清**：batch 成功但最终合并失败时可能误切 CURRENT。整改：batch 只写 staging，只有最终 candidate acceptance pass 才允许 `apply-from`。

### ② 重大隐患

4. **章节边界过度依赖 taxonomy**：同一主题可能跨 taxonomy 被拆散，Book 逻辑不连贯。整改：先确定性分区，再允许 volume/chapter metadata 做跨章路径；不得靠 LLM 随意迁移 page。
5. **全量正文重复与信息稀释**：179 个 chunk 各自生成会重复相同方法论。整改：章节级合并提示词、跨页去重、volume summary 只引用章节摘要；增加重复率和来源覆盖报告。
6. **单页超上下文**：个别页面自身超过 chunk 上限。整改：隔离标记并走专门长页切分/规则保底；没有可验证正文时不得标记 complete。
7. **全量失败重跑成本高**：一次失败可能重复已完成章节。整改：prompt hash + page hash 缓存和持久 batch state。
8. **WebUI 与 CLI 输出目录可能分叉**：现有 WebUI build panel 使用 `book/`，Wiki-to-Book reader 使用 `book-wiki/`。整改：full release 明确只进入 `book-wiki` reader seam，并补 UI 状态提示。

### ③ 优化疏漏

9. **sources 附录可发现性不足**：只写 manifest 不等于用户可读。整改：生成 source index，并在 WebUI 显示来源入口。
10. **人工抽样策略未量化**：全量人工通读不可执行。整改：每个 volume + 长章节 + 高冲突页做风险抽样，报告不阻塞发布。
11. **版本空间增长**：179 章多批次会积累中间产物。整改：candidate/staging 分层，保留最近 N 个正式 release，过期 batch 可清理。

## Audit — Round 2: stress-test scenarios

| Scenario | Chain reaction | Hardening |
|---|---|---|
| 第 80 章后预算耗尽 | partial batch → 若误发布会污染 CURRENT | provider call reservation + final acceptance blocks promotion |
| MiniMax 结构响应再次变成数组 | 单章失败 → 全书 partial | chapter-local repair; no provenance guessing; retry reserve in budget |
| 某 Wiki 页在构建中被修改 | snapshot 与正文 hash 不一致 | scan freeze + snapshot mismatch blocks apply |
| 进程在写 release 时中断 | 半目录或错误 CURRENT | temp directory + manifest hash + atomic pointer switch |
| batch state 损坏 | 重复调用或跳过章节 | schema validation; fail-closed; rebuild from immutable candidate |
| 关系图存在 unresolved 激增 | 章节顺序/来源闭包不可信 | preflight threshold blocks full run before provider calls |
| WebUI 读取旧 pilot | 用户误以为全量未发布 | CURRENT version + scope badge + version selector |
| LanceDB 未同步 | Book 可读但检索结果落后 | separate vector status; never report implicit sync |
| 用户撤销外部发送授权 | 已有 batch 继续发送 | every batch checks authorization and budget lease |

## Audit result and decision

- Round 1 identified 3 fatal, 5 major, and 3 optimization issues; all are addressed in the task design above.
- Round 2 covers budget exhaustion, malformed responses, source mutation, interrupted publication, state corruption, relation quality, UI versioning, vector lag, and authorization revocation.
- The plan is technically executable only after explicit confirmation of the 1255-page scope and a new full-run LLM budget. It is not safe to reuse the previous 4-call approval.
- Human review: pending.

## Rollback

- Before apply: delete only the candidate/staging release; CURRENT remains on the 12-page pilot.
- After apply: atomically restore the previous `CURRENT.json` pointer after verifying its manifest hash; do not delete the previous release until post-publish checks pass.
- Vector rollback is independent: no vector mutation is part of Book rollback.

## Completion evidence

- Final commit: pending
- Tests: pending
- Static checks: pending
- Documentation updated: pending
- Progress ledger updated: pending
