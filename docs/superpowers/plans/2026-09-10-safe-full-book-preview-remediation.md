# Plan: 全量 Book Preview 安全整改（兼容原有功能）

status: planned
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

## Files and Responsibilities

| File | Responsibility |
|---|---|
| `src/cli.py` | 注册新参数，默认保持兼容 |
| `src/cli_ext/book_cmd.py` | 将显式输出模式和批次参数传入 compiler |
| `src/kc/views/book/wiki/compiler.py` | full-scope plain-text 分支、批次边界、发布门禁 |
| `src/kc/views/book/wiki/polish_llm.py` | 新增正文纯文本生成和最小可读性校验；保留旧 JSON 函数 |
| `src/kc/views/book/wiki/batch_state.py` | 记录批次、调用数、失败原因和 resume 信息 |
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
  - 编译器生成的 chapter/section/source metadata 可通过 provenance 校验；
  - plain-text 模式不依赖 `json.loads`、`sections` 或模型生成的来源 ID；
  - structured 模式的原有对象解析测试保持通过。
- Implementation:
  - 新增最小的纯文本正文函数；
  - 请求使用文本输出，不要求模型生成 JSON 元数据；
  - compiler 使用固定 section ID 和当前 chapter 的 page IDs 包装正文；
  - 保留现有硬契约中的安全边界、来源不可扩张和内容可读性要求；
  - 不修改全局 provider adapter，不把 plain-text 行为扩散到其他 pipeline。
- Acceptance:
  - MiniMax 返回 Markdown、标题或普通段落均可稳定落入 compiler-owned section；
  - LLM 不再负责 provenance 字段；
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
- Implementation:
  - 保留现有 batch state schema，增加当前批次边界和 resume 游标；
  - `--batch-size` 对 full-scope plain-text 成为实际执行上限；
  - 默认并发保持 1，不修改全局队列和 retry provider；
  - 每章完成即写入 state，每批结束返回可恢复状态；
  - transport retry 仍由现有 retry 层处理，内容格式不再触发 JSON 重试。
- Acceptance:
  - 179 章可以拆成多个独立进程完成；
  - 每个批次均可审计调用数、失败原因和 snapshot ID；
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
- Implementation:
  - 复用现有 release acceptance 和 promotion seam；
  - 将 output mode、实际调用数、批次信息写入 manifest；
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
- Implementation:
  1. plan-only：确认 1255 页、179 章、463 来源；
  2. 真实 MiniMax 小批量：3～5 章，只生成 staging；
  3. 检查正文可读性、失败率、实际调用数和 resume；
  4. 稳定后按 10～15 章/批次执行全量 preview；
  5. 自动验收 pass 后才执行 `apply-from`；
  6. 最后单独执行 `vector status`，不自动 reconcile。
- Acceptance:
  - 小批量失败时只停止新模式，不影响 pilot；
  - 全量满足 179/179 complete、coverage=1.0、automated acceptance=pass；
  - 调用数不超过本次明确批准的 358 次；
  - `CURRENT.json` 仅在 apply-from 后变化。
- Status: pending

## Audit

- Round 1: pending — 检查新参数是否可能改变旧默认路径；检查 plain-text 是否绕过外发授权、来源 allowlist 或 provenance gate。
- Round 2: pending — 模拟 provider 返回纯文本、数组、超时、429、进程中断、损坏 state 和重复 resume。
- Human review: pending — 在真实 MiniMax 小批量结果上检查正文可读性和 source coverage；不改变自动 acceptance report。
- Open risks:
  - MiniMax 响应延迟仍可能较高；通过真实 batch 边界和 resume 控制，不依赖单次 900 秒完成全量。
  - 纯文本模式降低了模型可控的细粒度 section 结构；换取稳定的章节完成率，section 元数据由 compiler 保证。
  - 真实 provider 仍可能出现内容质量问题；质量不合格应停在 preview，不得通过 apply-from 发布。
- Rollback:
  - 不启用 `--output-mode plain_text` 即完全回到旧路径；
  - 任何失败只保留 staging/batch state；
  - 不删除旧 pilot release，不修改 Wiki 原文，不修改 LanceDB；
  - 如代码回滚，保留 release evidence 供审计，但不提升 partial release。

## Completion evidence

- [ ] 相关测试通过，原有测试无回归。
- [ ] full-scope plan：1255 pages / 179 chapters / 463 sources。
- [ ] 小批量真实 preview 通过。
- [ ] 全量 preview：179/179 complete，自动验收 pass。
- [ ] `apply-from` 复用同一 release，未重复调用 LLM。
- [ ] `CURRENT.json` 仅由 apply-from 原子切换。
- [ ] LanceDB 状态单独检查并记录。
