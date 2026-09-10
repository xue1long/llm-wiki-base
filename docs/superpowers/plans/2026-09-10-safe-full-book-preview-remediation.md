# Plan: 全量 Book Preview 安全整改（兼容原有功能）

status: revised_pending_reaudit
branch: codex/book-safe-full-preview

## Goal

在不改变现有正常功能的前提下，使 `knowledge/novel-wiki` 可以稳定进入真实的 full-scope `preview -> apply-from` 流程。

目标验收：

- 1255/1255 个知识页进入编译范围；
- 179/179 个章节正文生成完成；
- 自动验收通过，生成 `complete` preview release；
- `apply-from` 复用同一 release，不重新调用 LLM；
- preview 不切换 `CURRENT.json`，apply-from 才原子切换；
- Book 编译不自动修改 LanceDB。

明确不改变：

- `book build`；
- `book build-from-wiki --scope pilot`；
- 旧版 `--use-llm --polish`；
- 现有结构化 JSON 章节模式；
- 全局重试、队列、WebUI 和 LanceDB 行为。

## Root Cause

本次 partial release 同时暴露了三类问题：

1. MiniMax 多次返回纯 Markdown、字符串数组或缺少 `sections` 的对象，说明当前 provider/model 未可靠执行业务 JSON 契约。
2. 编译器把章节正文、section 元数据和 provenance 同时交给 LLM，导致内容生成失败直接演变为章节失败。
3. 179 章串行运行在单次 900 秒进程内，网络重试和格式失败共同消耗运行时间。

结论：整改重点是隔离 LLM 输出契约和编译器元数据，并将全量执行切成真实可恢复批次；不是全局重写提示词或全局替换 provider。

## Compatibility Contract

新增显式参数：

```text
--output-mode structured|plain_text
```

默认值为 `structured`。只有同时满足以下条件时才允许 `plain_text`：

```text
--scope full_knowledge --output-mode plain_text
```

pilot、普通 Book 和旧版调用如果未显式指定新参数，必须继续走现有路径。

安全边界：

- provider、预算、外发授权、source allowlist 和 sensitivity gate 每批仍先检查；
- plain-text 模式只改变章节正文的 LLM 输出格式；
- page ID、chapter ID、section ID、source_page_ids 和 release 状态仍由编译器生成；
- 失败批次只写 staging 和 batch state，不得写 `CURRENT.json`；
- 不自动提升预算、不自动放宽 allowed paths、不自动切换 provider。

## Run Identity and Release Contract

每次 full-scope 编译必须先生成不可变 run manifest，至少包含：

```text
snapshot_id
scope_mode
output_mode
provider
model
rules_hash
prompt_version
compiler_version
budget_cap
batch_size
```

将以上字段的规范化 JSON 哈希作为 `run_signature`。`--resume` 只有在完整签名一致时才允许；任一字段变化都必须创建新 run，禁止复用旧章节结果。

批次状态和 release 分层：

1. batch state 只保存章节结果、调用记录、失败原因和恢复游标；
2. batch state 不得被 `apply-from` 直接提升；
3. 只有所有 179 个章节完成后，`finalize release` 才能基于同一个 run manifest 生成唯一的 complete preview release；
4. partial/failed/pending 状态只能停留在 staging。

全量覆盖拆成三个独立指标：

- `page_assignment_coverage`：1255 个页面是否恰好分配一次；
- `body_generation_coverage`：179 个章节是否全部生成有效正文；
- `content_evidence_sample_coverage`：抽样页面是否在正文中有可验证表达。

任何一个自动硬门不通过，都不得生成可提升 release。

## Files and Responsibilities

| File | Responsibility |
|---|---|
| `src/cli.py` | 注册新参数，默认保持兼容 |
| `src/cli_ext/book_cmd.py` | 将显式输出模式和批次参数传入 compiler |
| `src/kc/views/book/wiki/compiler.py` | full-scope plain-text 分支、批次边界、发布门禁 |
| `src/kc/views/book/wiki/polish_llm.py` | 新增正文纯文本生成和最小可读性校验；保留旧 JSON 函数 |
| `src/kc/views/book/wiki/batch_state.py` | 记录批次、调用数、失败原因、run signature 和 resume 信息 |
| `src/kc/views/book/wiki/preflight.py` | 仅补充新模式的显式参数校验，不改变旧门禁 |
| `tests/test_cli_ext/test_book_build_from_wiki_modes.py` | CLI 兼容和参数转发测试 |
| `tests/test_kc/test_book_chapter_body.py` | 纯文本正文、编译器元数据和失败行为测试 |
| `tests/test_kc/test_book_wiki_compiler.py` | full-scope 批次、resume、release 状态测试 |
| `tests/test_project/test_discovery.py` | 项目注册名不被自动发现覆盖的回归测试 |

## Tasks

### Task 1: 锁定兼容性和新模式入口

- Files: `src/cli.py`, `src/cli_ext/book_cmd.py`
- Test first:
  - 未传 `--output-mode` 时仍为 `structured`；
  - pilot 仍调用旧 structured path；
  - `full_knowledge + plain_text` 才进入新分支；
  - `pilot + plain_text` 明确阻塞，不静默改变模式；
  - 旧 CLI namespace 无新字段时仍可运行。
- Implementation:
  - 增加 `--output-mode`；
  - 通过 keyword argument 传入 compiler；
  - 不修改旧参数默认值和旧函数签名的既有行为。
- Acceptance:
  - 原有 Book CLI 测试全部通过；
  - 新模式可被 parser 识别但尚不发送 LLM 请求。
- Status: pending

### Task 2: 增加 compiler-owned plain-text chapter path

- Files: `src/kc/views/book/wiki/compiler.py`, `src/kc/views/book/wiki/polish_llm.py`
- Test first:
  - fake provider 返回 Markdown 正文时章节为 `complete`；
  - 返回空文本或过短文本时章节为 failed；
  - 返回 `<think>`、Markdown code fence 或截断标记时按规则清洗或失败，不把诊断内容写入正文；
  - 编译器生成的 chapter/section/source metadata 可通过 provenance 校验；
  - plain-text 模式不依赖 `json.loads`、`sections` 或模型生成的来源 ID；
  - plain-text 正文通过非空、最小长度、截断、占位符、重复率和异常控制字符检查；
  - structured 模式的原有对象解析测试保持通过。
- Implementation:
  - 新增最小的纯文本正文函数；
  - 请求使用文本输出，不要求模型生成 JSON 元数据；
  - compiler 使用固定 section ID 和当前 chapter 的 page IDs 包装正文；
  - plain-text 分支在入口处与 structured 分支显式分派，禁止经过旧 JSON parser；
  - 将 `content_status`、`body_generation_coverage` 和失败分类写入 manifest；
  - 保留现有硬契约中的安全边界、来源不可扩张和内容可读性要求；
  - 不修改全局 provider adapter，不把 plain-text 行为扩散到其他 pipeline。
- Acceptance:
  - MiniMax 返回 Markdown、标题或普通段落均可稳定落入 compiler-owned section；
  - LLM 不再负责 provenance 字段；
  - 明显空泛、截断、重复或占位符正文不能被标记为 complete；
  - 旧 structured path 无行为变化。
- Status: pending

### Task 3: 把 full-scope batch 变成真实执行边界

- Files: `src/kc/views/book/wiki/compiler.py`, `src/kc/views/book/wiki/batch_state.py`, `src/cli_ext/book_cmd.py`
- Test first:
  - 一次运行最多处理一个 batch；
  - batch 完成后状态持久化并安全退出；
  - 进程重启后 `--resume` 只处理未完成章节；
  - 已完成章节不重复调用；
  - 单批超时只产生 partial staging，不更新 `CURRENT.json`；
  - 损坏或 snapshot 不匹配的 batch state fail-closed。
  - provider、model、rules、prompt 或 output mode 变化时 resume 被拒绝；
  - 两个进程同时 resume 同一 run 时只有一个获得 batch claim。
- Implementation:
  - 保留现有 batch state schema，增加 run manifest、当前批次边界、batch claim 和 resume 游标；
  - `--batch-size` 对 full-scope plain-text 成为实际执行上限；
  - 在每次新 LLM 请求前检查 batch deadline；到期后不再发新请求，保存 pending 状态并正常退出；
  - 默认并发保持 1，不修改全局队列和 retry provider；
  - 使用 run 级锁和单 writer 规则，已有运行时 fail-closed；
  - 每章完成即写入 state，每批结束返回可恢复状态；
  - transport retry 仍由现有 retry 层处理；plain-text 的空响应、截断和 policy 错误使用有限状态分类，不触发无限重试；
  - 每批开始前计算最低调用数、重试预留和剩余预算，不足时在首次 provider 调用前阻断。
- Acceptance:
  - 179 章可以拆成多个独立进程完成；
  - 每个批次均可审计调用数、失败原因和 snapshot ID；
  - 每个批次均绑定唯一 run signature，不能混入其他 provider/model/prompt 结果；
  - 未完成批次不能被误识别为可发布 release。
- Status: pending

### Task 4: 强化 preview/apply-from 发布门禁

- Files: `src/kc/views/book/wiki/compiler.py`, `tests/test_kc/test_book_promotion.py`, `tests/test_kc/test_book_wiki_compiler.py`
- Test first:
  - 所有章节 complete 才能生成可提升 preview release；
  - partial/failed release 的 `apply-from` 必须拒绝；
  - `apply-from` 不调用 provider；
  - preview 不修改 `CURRENT.json`；
  - apply-from 只原子切换同一 release；
  - 发布后 vector 状态仍为独立状态。
  - 只有 finalize 后的 complete release 才能被 `apply-from` 接受；
  - finalize 只生成一个 release manifest，且其 run signature 与所有 batch 一致。
- Implementation:
  - 复用现有 release acceptance 和 promotion seam；
  - 增加显式 finalize 步骤：汇总 batch state，重新校验 1255/1255、179/179、source appendix 和 body quality gates，再写唯一 candidate release；
  - 将 output mode、实际调用数、批次信息写入 manifest；
  - `apply-from` 只接受 finalize 产物，拒绝直接传入 batch state 或 partial release；
  - 不增加人工可读性或人工验收为硬阻塞；保留其报告字段。
- Acceptance:
  - preview release 与 apply-from release ID、snapshot ID 和 manifest hash 一致；
  - partial 永远不能成为 `CURRENT`。
- Status: pending

### Task 5: 离线回归、小批量真实验证和全量执行

- Files: tests above plus release evidence under `knowledge/novel-wiki/.index/book-wiki/`
- Test first:
  - 相关 Python 测试和 CLI parser 测试通过；
  - fake provider 端到端覆盖 179 章的状态机；
  - 原有 pilot/Book/legacy 测试无回归。
  - run signature 变化、双进程 resume、deadline、预算不足和 finalize 失败均有回归测试。
- Implementation:
  1. plan-only：确认 1255 页、179 章、463 来源；
  2. 真实 MiniMax canary：3～5 章，只生成 staging；必须 100% complete、0 个 provider/截断/格式失败，并通过人工抽样；
  3. canary 通过后，按 10～15 章/批次执行 full-scope preview；每批独立进程并使用 `--resume`；
  4. 全部批次完成后执行 finalize，生成唯一 complete preview release；
  5. 自动验收 pass 后才执行 `apply-from`；
  6. 最后单独执行 `vector status`，不自动 reconcile。
- Acceptance:
  - 小批量失败时只停止新模式，不影响 pilot；
  - 全量满足 179/179 complete、coverage=1.0、automated acceptance=pass；
  - `page_assignment_coverage=1.0`、`body_generation_coverage=1.0`，抽样内容覆盖达到预设阈值；
  - 调用数不超过本次明确批准的 358 次；
  - 所有 batch 和 finalize 使用同一个 run signature；
  - `CURRENT.json` 仅在 apply-from 后变化。
- Status: pending

## Audit

- Round 1: completed with findings — 已完成全面漏洞审计；C1/C2、M1～M8、O1～O4 已转化为本次方案的 finalize、run signature、质量门、预算门、锁和 canary 条款。
- Round 2: pending — 模拟 provider 返回纯文本、数组、超时、429、进程中断、损坏 state 和重复 resume。
- Re-audit gate: pending — 进入编码前必须复核上述增补没有改变旧默认路径，并完成 fake provider 的中断恢复链路。
- Human review: pending — 在真实 MiniMax canary 结果上检查正文可读性和 source coverage；不改变自动 acceptance report。
- Open risks:
  - MiniMax 响应延迟仍可能较高；由 deadline、批次边界和 resume 控制，不依赖单次进程完成全量。
  - 纯文本模式降低了模型可控的细粒度 section 结构；通过 compiler-owned metadata 和 content evidence 抽样控制风险。
  - canary 可能通过但长尾章节仍失败；全量 finalize 必须重新执行完整性硬门。
- Rollback:
  - 不启用 `--output-mode plain_text` 即完全回到旧路径；
  - 任何失败只保留 staging/batch state；
  - 不删除旧 pilot release，不修改 Wiki 原文，不修改 LanceDB；
  - 如代码回滚，保留 release evidence 供审计，但不提升 partial release。

## Completion evidence

- [ ] 相关测试通过，原有测试无回归。
- [ ] run manifest 和 run signature 可审计，模式/provider/model/rules 变化会阻止 resume。
- [ ] fake provider 完成“中断 → resume → finalize → apply-from”链路测试。
- [ ] batch deadline、预算预留、单 writer 锁和失败分类测试通过。
- [ ] full-scope plan：1255 pages / 179 chapters / 463 sources。
- [ ] 小批量真实 canary 通过：3～5 章 100% complete、0 个 provider/截断/格式失败。
- [ ] 全量 preview：179/179 complete，自动验收 pass。
- [ ] finalize 生成唯一 complete preview release。
- [ ] `apply-from` 复用同一 release，未重复调用 LLM。
- [ ] `CURRENT.json` 仅由 apply-from 原子切换。
- [ ] LanceDB 状态单独检查并记录。
