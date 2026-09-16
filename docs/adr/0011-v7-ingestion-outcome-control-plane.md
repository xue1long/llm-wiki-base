# ADR 0011: V7 摄取 outcome 控制面重构

- **状态**: Accepted
- **日期**: 2026-09-15
- **计划**: `docs/superpowers/plans/2026-09-15-v7-ingestion-pipeline-control-plane-refactor.md`

V7 摄取采用 source outcome 作为唯一控制面：Writer 的实际结果先落入 queue 与
source-level checkpoint，再汇总报告。这个选择消除“候选页已生成”与“页面已写盘”
之间的假成功，同时把 Stage 5 的语义生成和 Stage 6 的可选后处理从首轮终局判定
中分离出来。

## 背景

V7 摄取管线在 4918 / 1362 source 全量 apply 前发现以下控制面缺陷
(审计 + 单文档真实 apply 复现):

1. **状态分裂**:`_extract_one` dict、`ExtractionResult`、`WriteReport`、
   `reviews_queue`、`v7_full_checkpoint` 各自记录、各自失败,
   caller 无法从任一对象可靠推断"这个 source 实际发生了什么"。
2. **假成功**:真实 apply 跑出 `errors=0` 但页面被 WikiWriter 阻断,
   报告仍显示 `pages=1`。
3. **page ID 不可移植**:Stage 5 让 LLM 回填 `item_id` 字符串,
   跨文档同名 topic 产生 page 冲突与覆盖。
4. **batch-level checkpoint 粒度太粗**:`completed_batches: [int]`
   无法区分"该 source 真写盘"与"该 source 被静默跳过"。
5. **Stage 5 摘录硬门误伤 paraphrase**:LLM 对 source 做改写时,
   `_excerpt_in_source` substring 校验误标 `needs_review`。

## 决策

### 决策 1:唯一 source outcome 对象(`ExtractionResult` 五态)

把 `_extract_one` 的返回值收敛为 `ExtractionResult` dataclass,
含五态 `status`(written / blocked / failed / incomplete / skipped)
+ v3 三态 `legacy_status` 兼容字段,序列化入口唯一为 `to_dict()`。

- 五态 ↔ v3 三态映射(§2.2.1):written → ok、blocked/failed → needs_review、
  incomplete → incomplete、skipped → ok / needs_review。
- `ExtractionResult` 新增字段:`source_md5`、`attempts`、
  `written_page_ids` / `blocked_page_ids` / `failed_page_ids`
  (三列拆分)、`legacy_status`、`metadata`(向后兼容)。
- LLM schema 不合规归 `failed`(技术失败,触发 retry 3 次);
  缺失 evidence 永远走 `blocked`(Gate B/C 阻断,不视为成功)。

### 决策 2:脚本接管 item / page ID

LLM 只负责语义判断和内容,不再回填 `item_id` 或 `page_id`:

- item ID 由 Stage 2 脚本按 source 内切片顺序生成：heading 切片使用
  `{source_relative}#section-{N}`，编号条目使用 `{source_relative}#item-{N}`，
  未切片全文使用 `{source_relative}`。LLM 只返回当前 topic 内的 `item_index`。
- page ID 当前由 `_stable_page_id(relative, topic.id)` 生成，格式为
  `{md5(source_relative)[:8]}-{slugify(topic.id)[:32]}`；source 路径先归一为
  POSIX 分隔符，保证跨 OS 一致。
- `validate_page_id` 拒绝包含 `/` `\` `..` 的 page id。
- `_extract_one` 把 page id 改为 `_stable_page_id(relative, topic.id)` 生成,
  `page.topic_id` 由 `__dict__` 注入改为正式 dataclass 字段
  (向后兼容 `getattr` 兼容层)。

### 决策 3:Writer 集成 reviews queue + page_writes

`WikiWriter.commit_and_index` 在每个 Gate 后入 queue:

- 新增 `WriteReport.page_writes: dict[page_id, Path|None]` —
  page 写盘的 Path,blocked / failed / skipped / 无效 page_id 时为 None。
- 新增 `WriteReport.dry_run: bool`(预留)。
- 入队参数:`source_id = page.sources[0]`、`stage = "stage7_gate" |
  "stage7_content_filter" | "stage7_path" | "stage7_write"`、`reason`
  含 `prompt_kind` + `provider` 标签(便于 triage)。
- 入队失败不抛(P2 兼容):queue I/O 错误只丢日志,不阻止 Writer 主流程。
- 修 v3 实施 T2.5 遗留:Guard A 改用 `getattr(page, 'topic_id', None)` 兼容
  直接构造的 ConceptPage 实例(与 `failures.filter_failed_topics` 模式一致)。

### 决策 4:source-level v2 checkpoint + dry-run 安全

`v7_full_checkpoint.json` 升级为 source-level(version=2):

- 保留 v1 `completed_batches` 字段(向后兼容),新增
  `sources[<relative>]` 字典。
- 每个 source outcome 含 `md5`、`status`、`legacy_status`、
  `written_page_ids` / `blocked_page_ids` / `failed_page_ids`、
  `attempts`、`last_attempt_at`、`llm_provider`、`dry_run`。
- **Atomic write**:写 `.tmp` sibling 后 rename(P5 加固,避免半写)。
- **md5 skip**:同一 relative + 同一 md5 + status 是 written / blocked /
  incomplete 且 **dry_run=False** → skip,否则重跑。
- **Dry-run safety**(P6):dry-run 不把 batch 加到 `completed_batches`
  (避免下次 apply 被静默跳过);per-source 写入 `dry_run: True`
  标记供审计;in-memory summary 仍展示 dry-run 投影的 written / blocked 计数。
- 兼容层:读 v1 checkpoint 时不自动升级;旧 batch 视为 done,
  但不假设 source-level terminal。

### 决策 5:page-level outcome 在 _extract_one 阶段分流

`_extract_one` 不再把所有 page 计入 `written_page_ids`:

- `needs_review_slots` 非空 → 进 `blocked_page_ids`(Gate B)。
- `not has_evidence` → 进 `blocked_page_ids`(Gate C)。
- `topic_id == "__other__"` → 进 `blocked_page_ids`(Gate A)。
- 仅在四道闸门全通过时才进 `written_page_ids`。
- verdict:全部 page 都 blocked → status=BLOCKED;
  至少 1 written → status=WRITTEN;全部 topic Stage 5 失败 →
  status=BLOCKED(原 v3 行为保留)。

### 决策 6:Stage 6 关系抽取降级为可选 best-effort 后处理

`scripts/extract_full.py` 主链路不再自动调用
`extract_relations(pages)`:

- `src/pipeline/v7_extract/relation_extractor.py` 已实现
  (LLM + heuristic 双模式),但 `scripts/` 无任何调用方。
- Stage 6 是可选后处理,需要关系时由独立的后处理任务(单独 plan)调用,
  必须复用本控制面的 page_id / queue / checkpoint / outcome 契约。
- Stage 6 不计入首轮 source → concept 写盘的成功条件。
- 首轮 `written` outcome 一旦 durable,Stage 6 失败不得删除页面、回退 source
  checkpoint，或把既有 outcome 降级为 `blocked` / `failed`。未来接入时应把
  失败记录为可重试、可审计的后处理结果。

### 决策 7:Stage 5 摘录硬门改为可选人工参考

`slot_filler._payload_to_page` 删除 `_excerpt_in_source` exact-match substring gate
(commit `8943f696`),把 excerpt 降级为可选人工参考字段:

- 改前的 hard gate 在 LLM paraphrase 时误伤,导致 `needs_review` 假阳性。
- 改后 excerpt 字段保留,供人工 review,不再阻断自动写盘。
- canonical item provenance 与页面级 source 闭环仍是硬约束；缺失、越界或跨
  topic 的 item 引用继续阻断，不能用 excerpt 替代。
- `_excerpt_in_source` 函数保留(向后兼容),新契约不依赖。

## 不做的重构

- 不重写 Collector/Analyzer/Generator 全套模块。
- 不把所有 Stage 变成独立队列或后台 worker。
- 不新增 PromptAST/多层热加载配置(本计划不动 prompts/ 子系统)。
- 不将 Stage 1/3 的软判断继续升级成更多硬阻断。
- 不在本计划内追求 80% spot-check 作为 apply 前置门槛
  (`V7_ALLOW_APPLY` 仍是显式确认)。
- 不重写 `_legacy.py` 占位实现(v3 实施 T1.0 遗留,留给后续 task)。

## 兼容性矩阵

| v3 行为 | 本次 plan 行为 | 兼容性 |
|---|---|---|
| `_extract_one` 返回 dict | 返回 `ExtractionResult` | 新增 `__getitem__` / `get` / `__contains__` 兼容层 |
| `v7_full_checkpoint.json` v1 batch-level | v2 source-level | v1 字段保留,v2 是新增 |
| `WikiWriter` 直接 `page.topic_id` | `getattr(page, 'topic_id', None)` | 兼容直接构造的 ConceptPage |
| `enqueue_failure` 随机 uuid ID | sha1 稳定 hash | 旧 uuid 项保留,不删;新 entry 走稳定 hash |
| Stage 6 主链路默认调用 | 可选 best-effort | 首轮 scripts 不调用；后续独立接入 |
| Stage 5 excerpt 硬门 | 人工参考 | Gate B 仍可标 needs_review(其他原因) |

## 验证证据与未决验收

截至 2026-09-15，可追溯证据如下：

- Wave 1 聚焦套件记录为 `123 passed / 0 failed`；Writer 与 source checkpoint
  提交分别记录 `169 passed / 0 failed`、`172 passed / 0 failed`。
- commit `7c565c9b` 增加单 source 自动化 apply smoke，覆盖 raw md5 不变、实际
  写盘、source checkpoint、二次 skip 与 queue 去重。主会话随后实际重跑该 smoke：
  `1 passed in 3.03s`；完整 V7 聚焦套件为 `298 passed, 1 skipped in 8.34s`，
  `compileall` 与 `git diff --check` 均 exit 0。第二次 apply 的精确 summary 为
  `skipped=1, written=0, blocked=0, failed=0, incomplete=0, generated_pages=0,
  pages=1`；产物位于临时 root，未修改正式 raw/Wiki。
- 本轮只读调用关系检查确认：V7 `extract_relations()` 只有实现和 Stage 6 测试，
  `scripts/` 没有调用方；因此“Stage 6 不在首轮主链路”与当前接线一致。
- `v7-control-plane-wave1`、`v7-control-plane-wave2`、
  `v7-control-plane-wave3` 标签存在；专属 ledger 还记录了当前 `compileall` exit 0。
- 外部 provider 未对正式生产 raw 执行；因此本 ADR 只证明控制面与确定性临时
  root smoke 已验证，不把它扩大解释为 4918/1362 source 全量 apply 的生产证明。
  `v7-control-plane-final` 由主会话在验收提交后建立；在此之前仍不得启动全量 apply。

Task 6 文档验收要求：两份计划与本 ADR 对 Stage 5/6 边界表述一致；报告记录
本轮判断和待验证项；文档提交只包含计划与 ADR，进度账本由控制面收尾提交单独
记录实际验证证据。

## 回滚决策

1. 以 `v7-control-plane-wave1/2/3` 标签和逐 Task commit 作为可审计回滚点；
   回滚控制面代码时按依赖逆序 revert，不删除 raw、正式 Wiki 或 review queue。
2. 计划选择的运行时开关是 `V7_USE_V3_CONTROL_PLANE=false`，但本 ADR 编辑时
   的源码检查没有找到该开关实现，所以它目前**不是已验证的可用回滚手段**。
   在实现并验证前，回滚只依赖标签/commit；不得用文档中的预期替代运行证据。
3. `V7_USE_V3=false` 指向的 `_legacy.py` 仍是已知 placeholder，不纳入本决策，
   也不能作为本控制面重构的安全回退。
4. Stage 6 的即时回滚是停止/撤销独立后处理调用；由于它不参与首轮成功条件，
   该动作不改已持久化 page、checkpoint 或 source outcome。

## 替代方案

- **替代 A**:不重写 `ExtractionResult`,只补充 `legacy_status` 字段。
  放弃:无法修复"假成功"问题(plan §1 审计结论)。
- **替代 B**:用 SQL / SQLite 替换 JSON checkpoint。
  放弃:个人使用单进程场景下过度工程;plan §6 "不做的重构" 明确排除。
- **替代 C**:Stage 5 摘录硬门继续保留,改用 LLM 二次校验 paraphrase。
  放弃:plan §4 Task 1 已说明 "不将 Stage 1/3 的软判断继续升级成更多硬阻断",
  且二次校验增加 LLM 调用成本(~1.5x 放大系数)。

## 后续扩展（2026-09-17, ADR 0012 补注）

本 ADR 控制面在 2026-09-17 master plan 中按以下方式扩展，**不修改**既有 outcome 流：

- **claim-level evidence (Task 14–18)**：Stage 5A 不再让 LLM 生成 byte offset / excerpt，
  改为 LLM 返回 `span_id`（来自 Stage 2 的 `CanonicalSpan`），脚本把 `span_id` 映射回
  source-absolute byte range 作为 `EvidenceRef`。Stage 5B `claim_reviewer` 对 HIGH-risk
  claims（数字 / 否定 / 因果 / 比较）二次裁决 → fail-closed；最终通过 `filter_substantive_claims`
  闸门后才进 page。Outcome 流仍由本 ADR 的 `ExtractionResult` 5 态控制，
  内部 `FillResult` 是 Stage 5-local enum（`FILLED / PARTIAL / INSUFFICIENT / CONFLICTING /
  COHERENCE_FAILED / TECHNICAL_FAILURE`）映射到 5 态。

- **crash consistency (Task 19–21)**：`CommitManifest` 9 态机 (`PREPARED / STAGING / PUBLISHING /
  INDEXING / CHECKPOINTING / FINALIZING / COMMITTED / FAILED / RECONCILED`) + 每 page outcome
  record + `reconcile_unfinished_commits()` startup 扫描。durable_failure.jsonl（每 page
  outcome 全量）与 reviews_queue.json（仅 review-needed）显式分工（F11 整改：committed 永
  不污染 queue）。Outcome 流末端的"committed/blocked/failed" 与本 ADR 5 态映射不变。

- **canonical_id 解耦 (Task 27–31)**：新增 Reconciliation Plane（ADR 0012），`canonical_id`
  **永不**进 wiki frontmatter；frontmatter 仍是 page view，`page_id` 维度由本 ADR 控制面管，
  `canonical_id` 维度由 ADR 0012 单独管。两层单向耦合：reconciliation 读 wiki `revision_hash`
  做 stale 检测，wiki writer 不知道 reconciliation 存在（F8 决策回退）。

本 ADR 仍是 source 维度 outcome 控制面的权威 ADR；ADR 0012 是其上层的 cross-source
收敛平面，不替代、不冲突。

## 参考

- 计划:`docs/superpowers/plans/2026-09-15-v7-ingestion-pipeline-control-plane-refactor.md`
- 架构:`docs/superpowers/plans/2026-09-15-v7-pipeline-architecture-v3.md`
- 实施:`docs/superpowers/plans/2026-09-15-v7-pipeline-v3-implementation.md`
- Ledger:`.superpowers/sdd/2026-09-15-v7-ingestion-pipeline-control-plane-refactor/progress.md`
- plan-audit 整改记录:`plan §9 + ledger §Wave 0/1`
- Stage 5 provenance:`8943f696`;fixture 同步:`e3b5ee73`
- Writer integration:`c306b552`;source checkpoint:`ac1ef971`;自动化 smoke:`7c565c9b`
