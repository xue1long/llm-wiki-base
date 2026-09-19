# V7 摄取管线指南

> 本文是 V7（`pipeline/v7_extract`）摄取管线的**单一入口文档**。设计决策以
> `docs/adr/0011-v7-ingestion-outcome-control-plane.md` 为权威，本文只做整合与索引。
> 状态核对日：2026-09-16。

## 1. 一句话定位

V7 是 novel-wiki 知识库的**第二代摄取管线**：把 `raw/sources/**` 下的原始
文章（1362 个）经 7 个阶段转成 wiki 概念页（concept / entity / source /
synthesis），核心原则是 **LLM 管语义、脚本管机制**，任何阶段失败一律降级为
`needs_review` 而不抛异常、不污染存量。

三代演进：

| 代际 | 位置 | 形态 |
|---|---|---|
| v1 legacy | `src/pipeline/stages/` | Collector → Analyzer → Generator，模板驱动 |
| **v2 / v7** | `src/pipeline/v7_extract/` | 7 阶段 LLM 驱动抽取（当前生产路径） |
| v3（v7 的架构对齐版） | 同目录 | 继承 v2 语义驱动 + 继承 v1 模板架构（PromptAST / async 一致性） |

V7 与 legacy pipeline **并行存在、互不干扰**——`src/pipeline/stages/` 保持原样，
V7 独立演进。

## 2. 文件地图

```
src/pipeline/v7_extract/
├── __init__.py                  # 公共 API + V7_USE_V3 开关（PEP 562 懒加载）
├── doc_classifier.py            # Stage 1  classify_doc
├── article_segmenter.py         # Stage 2  ArticleBoundary / segment_articles
├── completeness_checker.py      # Stage 3  check_completeness
├── topic_clusterer.py           # Stage 4  cluster_topics
├── slot_filler.py               # Stage 5  fill_slots
├── relation_extractor.py        # Stage 6  关系抽取（可选后处理，首轮不调用）
├── wiki_writer.py               # Stage 7  WikiWriter.commit_and_index
├── concept_deduplicator.py      # 概念去重
├── failures.py                  # ExtractionResult / ExtractionStatus / enqueue_failure
├── _page_id.py                  # _stable_page_id / validate_page_id（脚本拥有 page id）
├── _queue_lock.py               # 每个 root 的 queue 文件锁
├── content_filter.py            # 敏感词闸门
├── audit_logger.py              # 反向索引 + failure 记录
├── llm_client.py                # LLMClient / FakeLLMClient / AnthropicLLMClient
├── prompts/
│   ├── ast.py                   # PromptAST / PromptSlot / PromptSection / PromptTemplate
│   ├── parser.py                # TOML → AST + D9 schema 校验
│   ├── renderer.py              # render_prompt / parse_llm_response
│   ├── resolver.py              # 三层覆盖 + 路径白名单 + 热加载
│   └── builtin/*.toml           # 5 个内置 prompt
├── _legacy*.py                  # v2 实现，V7_USE_V3=false 时的回滚目标（placeholder）

scripts/
├── extract_pilot.py             # 单文档/小样本 dry-run（_extract_one 在这里）
├── extract_full.py              # 批量 + source-level checkpoint（异步）
└── review_queue_cli.py          # 失败队列 CLI（list / resolve / stats）
```

## 3. 七阶段详解

| # | 阶段 | 实现 | 类型 | 输入 → 输出 | 失败行为 |
|---|---|---|---|---|---|
| 1 | classify_doc | `doc_classifier.py` | LLM async | content + filename_hint → doc_type / confidence / rationale | `failed`，源文档级 review |
| 2 | segment + 切片 | `article_segmenter.py` + `_extract_items_async` | 脚本优先 | content → `[{id, text, title?}]` | 回退整篇单 item（零 items 会崩 Stage 4） |
| 3 | check_completeness | `completeness_checker.py` | LLM async | content + doc_type **软 hint** → (bool, reason) | LLM 失败视为 incomplete，跳到末尾 |
| 4 | cluster_topics | `topic_clusterer.py` | LLM async | items + doc_type → `list[Topic]` | `failed`，源文档级 review |
| 5 | fill_slots | `slot_filler.py` | LLM async × N | topic + source_text → ConceptPage + evidence | 单 topic 失败 → 过滤 + `blocked_topic_ids` |
| 6 | extract_relations | `relation_extractor.py` | LLM/启发式 | 已落盘 pages → PageRelation[] | best-effort，不影响首轮终局 |
| 7 | commit_and_index | `wiki_writer.py` | 脚本 | pages → WriteReport | retry 3 次 → review queue |

### 3.1 Stage 2 的三级优先（Plan 5 的根修复）

`_extract_items_async` 按顺序尝试，命中即返回：

1. **确定性 metadata 头正则**（不调 LLM）——匹配
   `更新时间YYYY-MM-DD HH:MM:SS  字数：<n>` 这类连载专栏头。这是"LLM 只看到第一篇
   文章"bug 的**根修复**：LLM 输入会被 provider 的 max_tokens 截断，看不到后面
   文章的边界。切出的 item id 为 `{relative}#article-{N}`。
2. **LLM 分段**——仅当 Stage 1 判为 `collection` 且没有 metadata 头时启用
   （`segment_articles`，prompt 见 `builtin/segment_articles.toml`）。LLM 返回字节
   偏移，脚本负责排序 / 去重 / 夹紧重叠 / 补空隙，保证**不丢内容**。
3. **v2 heading / 编号正则**——`## 标题`（≥2 个）或 `^\d+[.、,，)]`（≥3 行）。

item id 由脚本生成，三种形态：`#section-N`（标题切片）、`#item-N`（编号条目）、
`{relative}`（未切片全文）。**LLM 永远不回填 item_id，只返回 topic 内的 item_index。**

### 3.2 Stage 4 的 collection 拆分（Plan 5）

- `cluster_topics()` 接受 `doc_type` 参数，并以 `Document type: {X}` 头部注入 prompt。
  `builtin/cluster.toml`（version **1.1**）内含 collection 拆分规则：文档被判为
  `collection` 时，按文章（H2 标题或"作者 XXX"署名）一篇一 topic，
  **不允许**折叠成 umbrella topic。
- `max_topics` 默认已从 5 提升到 **20**。
- P4 兜底：LLM 漏分配的 item 强制进 `__other__` 桶（只保证覆盖度，桶内不写盘）。

背景动机：53 KB 的 collection 文档原本被聚成 1 个 topic，产出 1 张 1321 B 的概念页
（压缩率 2.5%），9 个具体条目全部丢失。

### 3.3 Stage 5 的 evidence 边界（ADR 0011 决策 7）

- `source_text_excerpt` **已从 substring 硬门降级为人工参考字段**（commit
  `8943f696`）。原因是 LLM 做 paraphrase 时会被误判 `needs_review`，产生假阳性。
- 仍是硬约束的是 **canonical item provenance**：item 引用缺失、越界或跨 topic
  继续阻断，不能用 excerpt 顶替。

### 3.4 Stage 6 为何不在首轮主链路（ADR 0011 决策 6）

`scripts/` 下没有任何 `extract_relations()` 的调用方。Stage 6 是**终局之后**的
可选后处理：需要关系时由独立任务调用，必须复用同一 `page_id` / queue /
checkpoint / outcome 契约；**失败不得删除页面、回退 checkpoint，或把 `written`
降级成 `blocked`。**

## 4. 核心契约

### 4.1 ExtractionResult 五态（ADR 0011 决策 1）

`_extract_one` 的唯一返回类型，取代此前散落的 dict / WriteReport / checkpoint
各自记账。序列化入口唯一为 `to_dict()`。

| 五态 | 含义 | 映射到 v3 三态 |
|---|---|---|
| `written` | 至少 1 张 page 过闸门并落盘 | ok |
| `blocked` | 全部 page 被闸门拦下，或全部 topic 在 Stage 5 失败 | needs_review |
| `failed` | 技术失败（LLM schema 不合规 / 写盘失败），触发 retry | needs_review |
| `incomplete` | Stage 3 判为不完整，主动终止 | incomplete |
| `skipped` | checkpoint + md5 命中，本次未重跑 | ok / needs_review |

新增字段：`source_md5`、`attempts`、`written_page_ids` / `blocked_page_ids` /
`failed_page_ids`（三列拆分，不再混算）、`legacy_status`、`metadata`（承载旧
dict 契约，JSON 报告格式不变）。

**关键修正**：LLM schema 不合规 → `failed`（技术失败，可重试）；**缺失 evidence
永远走 `blocked`**（闸门阻断，绝不算成功）。这修掉了"`errors=0` 但页面实际被拦"
的假成功。

### 4.2 ID 归属：脚本拥有 ID，LLM 只给语义（决策 2）

- `page_id` = `_stable_page_id(relative, topic.id)`，格式
  `{md5(source_relative)[:8]}-{slugify(source_stem)[:32]}-{md5(topic_id)[:8]}`。
  source 路径先归一为 POSIX 分隔符并 NFC 归一化；调用方传 `project_root` 时
  还会走 `canonical_raw_key`，使绝对路径与项目相对路径解析为**同一个** page id。
- **2026-09-19（D7 修复）**：旧格式是 `{md5}-{slugify(topic_id)[:32]}`。因为
  `topic_id` 形如 `<source_id>-topic-<16hex>`、把整条源路径包了进去，
  `_slugify` 的 32 字符预算全被路径前缀吃掉，判别符 `-topic-<16hex>` 被整段截断
  ——同一源的**所有 topic 得到同一个 page_id**，第二个起静默覆盖第一个
  （现场：日志记 "generated 3 pages"，磁盘只有 1 个 concept）。
  该塌缩**与是否 CJK 无关**，凡是 slug 前缀吃满 32 字符的源都会中招。
  现在判别符放在截断预算之外，唯一性由 `md5(topic_id)[:8]`（32 位）+ bridge 内
  按派生 id 去重共同保证；`-{n}` 后缀仍保留为兜底。
- `validate_page_id` 拒绝含 `/`、`\`、`..` 的 page id。
- id 总长恒 ≤ 50 字符（`8+1+32+1+8`）：id 会直接当文件名用，
  长度必须有界，否则会在 `AtomicContext` 内写盘失败并整批回滚。
- 此前 LLM 回填 item_id 字符串导致跨文档同名 topic 互相覆盖，已根除。

### 4.3 Stage 7 四道闸门（P3 + P4）

`WikiWriter.commit_and_index` 逐 page 顺序检查，任一命中即进 `WriteReport.blocked`：

| 闸门 | 条件 | 依据 |
|---|---|---|
| A | `topic_id == "__other__"` | P4：兜底桶不写盘 |
| B | `needs_review_slots` 非空 | P3 |
| C | `content_filter.check(body).blocked` | P3 敏感词 |
| D | `not page.has_evidence()` | P3 evidence chain |

四道全过才写盘。`WriteReport.page_writes: dict[page_id, Path|None]` 记录每个 page
的真实落点，`dry_run: bool` 预留。

## 5. Prompt 子系统

### 5.1 三层覆盖 + 热加载（D1 / D6 / D9）

优先级 **project > user > bundled**：

```
项目级   <project_root>/.v7-prompts/<kind>.toml        # 例：knowledge/novel-wiki/.v7-prompts/
用户级   ~/.config/ruflo-kb/v7-prompts/<kind>.toml
bundled  src/pipeline/v7_extract/prompts/builtin/*.toml  # 只读默认
```

- **热加载**：`resolve()` 每次重新读盘 + 解析 + 校验，**不做缓存**，改完立即生效。
- **D9 安全**：路径白名单（`PromptPathNotAllowedError`）防止恶意 toml 经 symlink
  注入；parse 后校验 `output_schema.enum.doc_type ⊆ KNOWN_DOC_TYPES`，防止靠
  enum 绕过 evidence 校验。

### 5.2 内置 prompt 现状

| 文件 | kind | version | 说明 |
|---|---|---:|---|
| `classify.toml` | classify | 1.5 | 7 类 doc_type：single_method / multi_section / collection / qa_chat / list / tool / incomplete |
| `segment_articles.toml` | segment_articles | 1.0 | 按字节偏移切文章（collection 兜底） |
| `completeness.toml` | completeness | 1.0 | 完整性判定 |
| `cluster.toml` | cluster | 1.1 | 含 Plan 5 collection 拆分规则 |
| `fill_slots.toml` | fill_slots | 2.0 | 5 槽 + slot_evidence |

`PromptAST` 100% 镜像 `src/wiki/templates/` 的 `TemplateAST`（`PromptSlot`↔`Slot`、
`PromptSection`↔`TemplateSection`、`render_prompt`↔`render_body`），学习成本为零。

## 6. 运行方式

### 6.1 环境变量

| 变量 | 默认 | 作用 |
|---|---|---|
| `V7_ALLOW_APPLY` | 未设置 | **apply 的显式开关**。未设置时 `--apply` 直接 raise，这是 fail-closed 设计 |
| `V7_USE_V3` | `true` | `false` → 回退 `_legacy_*.py`（**当前是 placeholder，不是安全回退**） |
| `RUFLO_BUDGET_PRINT` | `1` | 设 `0` 抑制 Markdown 报告的 Cost 段（JSON 仍有 cost 字段） |

### 6.2 小样本 dry-run（`extract_pilot.py`）

```bash
export PYTHONPATH=.
python scripts/extract_pilot.py --root knowledge/novel-wiki --count 50 --seed 42 \
  --json-out docs/superpowers/reports/extract-pilot.json \
  --markdown-out docs/superpowers/reports/extract-pilot-report.md \
  --provider <provider-name>
```

- 确定性抽样：同 seed 同结果。`--sources <json>` 可指定精确清单（覆盖抽样）。
- 源文件范围固定为 `<root>/raw/sources/**`，后缀白名单 `.md .txt .html .htm`。
- **永不调用 WikiWriter，永不改 `wiki/`**——pilot 只写报告和 review 记录。

### 6.3 批量 apply（`extract_full.py`）

```bash
export PYTHONPATH=. V7_ALLOW_APPLY=1
python scripts/extract_full.py --root knowledge/novel-wiki --batch-size 500 \
  --max-retries 3 --max-attempts 5 --provider <provider-name> --apply
```

- 默认 `dry-run`；`--apply` 必须先设 `V7_ALLOW_APPLY`。
- 全程持有 `<root>` 级 queue 锁（`_queue_lock.py`），并发进程会直接失败。
- 退出码：`errors == 0` → 0，否则 2。

## 7. 产物与幂等

| 产物 | 路径 | 内容 |
|---|---|---|
| source checkpoint | `<root>/.index/v7_full_checkpoint.json` | v2：`sources[<relative>] = {md5, status, legacy_status, written/blocked/failed_page_ids, attempts, last_attempt_at, llm_provider, dry_run}` |
| page checkpoint | `<root>/.index/v7_checkpoint.json` | page 级幂等 |
| 抽取报告 | `--json-out` / `--markdown-out` | 五态 summary + 逐源结果 + Cost 段 |
| 失败队列 | `<root>/.index/reviews_queue.json` | 复用 `src/wiki/storage/reviews_queue.py`（D4），不新建 |

**双键去重**：`checkpoint + source_md5`。`_source_can_skip` 的跳过条件很严——
必须 `dry_run=False` 且 md5 一致，且 status 是
`blocked` / `incomplete`，或 `written` 且 `written_page_ids` 非空、
`blocked_page_ids` 与 `failed_page_ids` 均为空。

三个易踩的坑：

- **checkpoint 是原子写**（写 `.tmp` 兄弟文件再 rename），避免半写。
- **dry-run 不写 `completed_batches`**，且 per-source 标 `dry_run: true`，
  否则下次 apply 会被静默跳过。
- **v1 checkpoint 不自动升级**：读到旧 batch-level 格式时 `sources` 为空，需要
  操作者重跑一次填充 v2 schema。
- provider 变化会被记录为 `provider_changed_since_last_run:<relative>` 警告。

## 8. 失败与人工队列

- 所有 V7 失败项带 `source="v7_extract"` 标记（D10），与 Generator 流水线的
  review 项区分开。
- ID 是 **sha1 稳定 hash**（不再随机 uuid），重复失败自动去重。
- payload 脱敏（D11）：`api_key` / `email` / `phone` / `id_card` / `password`
  替换为 `[REDACTED]`，字符串截断到 500 字符——**保留排错信息，不删 payload**。
- 入队失败**不抛异常**（P2 兼容）：queue I/O 错误只记日志，不阻断 Writer 主流程。
- CLI：`python scripts/review_queue_cli.py {list|resolve|stats}`。

## 9. 成本可观测（Plan 4）

- 进程级 `CostLedger`（`src/lib/budget.py`），由 `extract_full.py` 构造并注入
  `AnthropicLLMClient`。
- summary 的 `cost` 字段：`cumulative_usd`、`input_tokens`、`output_tokens`、
  `call_count`、`cost_per_call_avg`、`cost_by_stage`。
- Markdown 报告只在 `cumulative_usd > 0` 且 `RUFLO_BUDGET_PRINT != 0` 时渲染
  Cost 段。
- **成本上限估算**：D2 的 schema 重试上限 3 次意味着单 stage 最多 3 倍调用。
  单文档最坏 `(3+3+3) + 3×topics`；若每篇聚 1 个 topic → 12 次/文档。
  4918 页全量最坏 ~59000 次。Plan 5 引入 collection 拆分后，53 KB / ~19 篇
  的文档成本会从 ~0.02 USD 升到 ~0.4 USD（N 篇 → N×4 次调用）。

## 10. 当前状态（2026-09-16）

已落地：

- v3 架构（PromptAST / async 一致性 / 统一失败语义）——见 `2026-09-15-v7-pipeline-architecture-v3.md`。
- 控制面重构（五态 ExtractionResult / 脚本拥有 ID / Writer 接 queue / checkpoint v2 /
  Stage 6 降级 / excerpt 降级）——ADR 0011，tag `v7-control-plane-wave1/2/3`。
- Plan 4 成本可观测；Plan 5 Stage 4 collection 拆分（cluster.toml v1.1）。

**尚未发生的事**（重要）：

- `knowledge/novel-wiki/wiki/` **目录不存在**——V7 全量 apply 从未在生产 KB 上跑过。
  1362 个源文档仍是原始素材，wiki 页尚未产出。
- 仓库根 `.index/v7_full_checkpoint.json` 是 **68 字节的 v1 残留**
  （`completed_batches: [4]`，无 `sources` 字段），来自早期的 batch 级 dry-run。
- `.index/reviews_queue.json` 尚不存在。
- ADR 0011 明确：`v7-control-plane-final` 标签建立前**不得启动全量 apply**；外部
  provider 目前只对确定性临时 root 做过 smoke。

已验证的测试证据：V7 聚焦套件 `298 passed, 1 skipped`；单 source apply smoke
`1 passed`（raw md5 不变、实际写盘、二次 skip、queue 去重）；`compileall` 与
`git diff --check` 均 exit 0。Plan 5 完成后目标为 V7 全套 ≥ 322 passed。

## 11. 设计原则速查（P1–P9）

| 原则 | 表述 |
|---|---|
| P1 | LLM 管语义，脚本管机制 |
| P2 | 失败可逆——任何 stage 失败 = needs_review，不抛异常 |
| P3 | 三道闸门（Stage 5 evidence / Stage 7 needs_review / content_filter） |
| P4 | 100% 覆盖度——漏分配的 item 进 `__other__` 桶，**桶内不写盘** |
| P5 | Stage 解耦——Stage 1 的结论只作 Stage 3 的软 hint |
| P6 | 幂等性——checkpoint + source_md5 双键去重 |
| P7 | 集中 Prompt——PromptAST 镜像 TemplateAST，三层覆盖 + TOML 版本化 |
| P8 | async 一致性——顶层函数全 async，不混用 sync/async 桥接 |
| P9 | 向后兼容——CLI 接口与对外行为不变 |

## 12. 参考

- 控制面权威决策：`docs/adr/0011-v7-ingestion-outcome-control-plane.md`
- 架构 v3.0：`docs/superpowers/plans/2026-09-15-v7-pipeline-architecture-v3.md`
- v3 实施计划：`docs/superpowers/plans/2026-09-15-v7-pipeline-v3-implementation.md`
- 控制面重构计划：`docs/superpowers/plans/2026-09-15-v7-ingestion-pipeline-control-plane-refactor.md`
- Plan 4 成本：`docs/superpowers/plans/2026-09-16-v7-budget-observability.md`
- Plan 5 collection 拆分：`docs/superpowers/plans/2026-09-16-v7-collection-split-topics.md`
- 领域词表（页面模型 / 槽位 / 关系）：`knowledge/novel-wiki/CONTEXT.md`
- 控制面过程账本：`.superpowers/sdd/2026-09-15-v7-ingestion-pipeline-control-plane-refactor/progress.md`
- 2026-09-17 master plan（Stage 1-7 + Stage 6R + Reconciliation Phase 1）：`docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan.md`
- ADR 0012（Knowledge Reconciliation Plane）：`docs/adr/0012-v7-knowledge-reconciliation-plane.md`

## 13. 2026-09-17 整改：Stage-local Status + Fingerprint + Bounded Evidence

> 本节记录 master plan `docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan.md`
> Tasks 1–16 在现有 Stage 1–7 之上叠加的 4 个 Contract 与 6 个 stage-local enum 落地。
> 详细 commit 对照表见 master plan §8.1；本节只做索引。

### 13.1 Stage-local Status（不再污染全局五态）

每个 stage 输出自己的 stage-local enum，caller 端做映射到 `ExtractionStatus` 五态。
详见 §3 各 stage 的 `<EnumName>` 字段。

| Stage | Stage-local Enum | 关键约束 |
|---|---|---|
| 1 | `Classification.failed` / `uncertain` / `traits` | **技术失败不映射 `incomplete`**（Task 2）|
| 2 | `SegmentationStatus.{SEGMENTED, SINGLE_EXPECTED, DEGRADED, UNCERTAIN}` | structural_signals 独立于 Stage 1 |
| 3 | `CompletenessStatus.{COMPLETE, INCOMPLETE, UNCERTAIN, TECHNICAL_FAILURE}` | **失败返回 `None`（不假装 `INCOMPLETE`）**（Task 6）|
| 4 | `ClusterStatus.{CLUSTERED, DEGRADED, UNCERTAIN, FAILED, EMPTY}` | `FAILED` ≠ `DEGRADED`（Task 9）|
| 5 | `FillStatus.{FILLED, PARTIAL, INSUFFICIENT, CONFLICTING, COHERENCE_FAILED, TECHNICAL_FAILURE}` | **TECHNICAL_FAILURE → FAILED 永 → WRITTEN**（Task 18）|
| 7 | `CommitPhase.{PREPARED, STAGING, PUBLISHING, INDEXING, CHECKPOINTING, FINALIZING, COMMITTED, FAILED, RECONCILED}` | 9 态机 + 启动 `reconcile_unfinished_commits`（Task 19）|

### 13.2 Fingerprint 双键（pipeline 升级自动重判）

每个 stage 输出 `*_fingerprint = sha1(stage_inputs + template_hashes)[:16]`。
source checkpoint 从 `md5_match` 升级为 `md5 + pipeline_fingerprint` 双键：
`md5 匹配 AND pipeline_fingerprint 匹配 AND status in {WRITTEN with all pages}` 才能 skip。

落地：
- Stage 3：`_source_outcome_from_result`（Task 8, commit `a84e1c11`）
- Stage 5：`claim_extractor` / `claim_validator` / `claim_reviewer` 各自 fingerprint
- Stage 7：page frontmatter `pipeline_fingerprint` 字段（Task 20, commit `3022ebb1`）

### 13.3 Bounded Evidence Contract §3.2

所有 LLM 路径必须真 bounded，**不**允许"head + tail + 全部内容"伪预算：

| Stage | 形态 | 硬预算 |
|---|---|---|
| 1 | evidence_pack | 4000 bytes |
| 2 | candidate windows | 1500 chars / window |
| 3 | HEAD + TAIL + structural signals | 2000 + 2000 bytes |
| 4 | `TopicDescriptor` per item | 600 bytes |
| 5 | `CanonicalSpan` per claim evidence | 1500 + 200 bytes |
| 6R | candidate pairs | 30 pairs / page |
| Reconciliation | `build_evidence_pack` | key_slots 600B + body 1500B |

违规 = 测试 fail；review 时人工检查。

### 13.4 Canonical Identity（脚本管身份）

LLM 永远不生成 canonical / page / topic / claim / relation id：
- `topic_id` / `page_id` = sha1(source_id + mapped_ids)（Task 12）
- `claim_id` = sha1(slot_name + local_index + text + span_ids)（Task 15）
- `relation_id` = sha1(source + predicate + target)（Task 23，对称折叠）
- `canonical_id` = `c-<uuid4_hex[:16]>`（Task 27）
- `decision_id` = sha1(page_id + canonical_id + decision)[:12]（Task 29）

LLM 只能在候选列表里"复制 canonical_id verbatim"，**不能**编造。

### 13.5 Stage 5B claim-level evidence（Task 14–18 详情）

```
source → Stage 2 CanonicalSpan (byte offset)
       → Stage 5A extract_slot_claims (LLM returns span_ids)
       → ClaimValidator (10 mechanical invariants)
       → ClaimReviewer (HIGH-risk only: numbers/negation/causality)
       → synthesize_slot (Markdown rendering)
       → FillResult (FILLED/PARTIAL/INSUFFICIENT/CONFLICTING/COHERENCE_FAILED/TECHNICAL_FAILURE)
       → map_fill_to_extraction → ExtractionStatus 5 态
```

`fill_slots` 旧入口**保留**作为向后兼容 adapter；新入口 `fill_slots_v2`。

### 13.6 Stage 7 crash consistency（Task 19–21）

`CommitManifest` 9 态机（详见 §13.1）+ 每 page outcome `PageCommitRecord` 持久化到
`<.index/commit_manifests/<commit_id>.json`。`reconcile_unfinished_commits()` 在 startup
扫描未完成 manifest，校验 on-disk file hash：
- file 存在 + hash 匹配 → `COMMITTED` / `RECONCILED`
- file 存在 + hash mismatch → `FAILED`（防 corrupt 写入）
- file 缺失 → 保持原 phase（重跑）

`durable_failure.jsonl`（每 page outcome 全量）与 `reviews_queue.json`（仅 review-needed）
**显式分工**（F11 整改）：committed outcome 永不污染 queue。

page frontmatter 6 字段（Task 20）：
- `owner: v7` / `pipeline: v7`
- `commit_id: <manifest.commit_id>`
- `pipeline_fingerprint: <WikiWriter kwarg>`
- `revision_hash: sha1(frontmatter_with_empty_hash + body)` 两遍 dump
- `committed_at: <unix ms>`

### 13.7 Stage 6R 异步关系抽取（Task 23–26，详情）

独立于 Stage 7 主链路，跑在 page written 之后：

```
Stage 7 committed → RelationStore 待 refresh
                  → Stage 6R retrieve_candidates (6 策略)
                  → LLM 受控 ontology 裁决
                  → validate (12 invariants)
                  → RelationStore.apply_result
```

6 策略：explicit wikilink → entity Jaccard → lexical → acronym → alias → vector_neighbor。
F8 决策回退：frontmatter relations 字段保留为 best-effort 视图，RelationStore（`.index/relations.jsonl`）
是权威源——零 reader 改造 blast radius。

## 14. 2026-09-17 扩展：Knowledge Reconciliation Plane

> 新增 Layer 8（plan §1.3）+ ADR 0012。完整设计见 `docs/adr/0012-v7-knowledge-reconciliation-plane.md`。
> 本节只做接入索引。

### 14.1 与 Stage 1–7 的关系

```
Layer 7 (wiki pages) ← source-local identity, page_id 维度
         ↑ 单向耦合
Layer 8 (canonical concepts) ← cross-source identity, canonical_id 维度
```

- canonical_id **永不**进 wiki frontmatter
- wiki writer 不知道 reconciliation 存在（零 reader 改造）
- reconciliation 读 wiki `revision_hash` 做 stale 检测（F4）

### 14.2 决策流程

```
new page → CanonicalIndex.build
        → retrieve_candidates (6 strategies, top-20)
        → resolve_identity (LLM, 受控 ontology, bounded evidence)
        → CanonicalRegistry.apply_decisions (priority: same > alias > ... > unresolved)
        → append decision_log.jsonl
```

### 14.3 CLI 子命令（Task 31，commit `97d85ec3`）

`src/cli_ext/reconciliation_cmd.py` 提供 4 个子命令：
- `reconcile` 处理所有 page
- `show-canonical <canonical_id>` 查看概念
- `list-canonicals [--active-only]` 列出 ACTIVE 概念
- `undo <page_id> [--canonical <canonical_id>]` reversible membership 撤销

`register(subparsers)` 函数已写但**未自动接入** `src/cli.py`——主会话后续接线。

### 14.4 关键硬指标（验收）

- **F4**：`test_resolver_fingerprint_drift_marks_stale` — fingerprint 升级 → STALE（commit `495ad547`）
- **F10**：`test_vector_neighbor_performance_under_10k_canonical` < 100ms — 实测 24-26ms（commit `662cecfd`）
- **F11**：`test_durable_failure_does_not_pollute_reviews_queue` — committed 不进 queue（commit `d6dce6c3`）
- **F15**：`test_alias_single_source_of_truth` — alias 单写入路径（commit `495ad547`）

## 15. E2E 故障注入（Task 32，commit `98f8adc0`）

`tests/test_integration/test_v7_e2e_remediation.py` 8 个测试覆盖：
- `test_e2e_normal_source_to_written_pages` — happy path 写到 wiki
- `test_e2e_stage1_failure_does_not_proceed` — Stage 1 fail 不进 Stage 3
- `test_e2e_stage3_technical_failure_not_mapped_to_incomplete` — **技术失败永不 INCOMPLETE**
- `test_e2e_crash_during_publish_recovers_via_manifest` — Stage 7 crash + reconcile
- `test_e2e_source_update_reconciles_stale_pages` — wiki 升级触发 stale
- `test_e2e_reconciliation_attaches_pages_to_canonical` — Reconciliation 合并同概念
- `test_e2e_unresolved_decision_does_not_force_merge` — UNRESOLVED 不强合并
- `test_e2e_pipeline_upgrade_triggers_re_evaluation` — fingerprint 升级触发重审

---

**状态核对日：2026-09-17** — Master plan Tasks 1–32 全部落地；Task 33 文档同步完成（本文即其一）。ADR 0011 追加 reconciliation 扩展注；ADR 0012 新建 Reconciliation Plane 架构决策。
