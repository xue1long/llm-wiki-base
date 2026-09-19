# Plan: V7 Stage 6 关系落地修复

> ## ⛔ DEFERRED —— 两轮 plan-audit 未通过，本方案不得进入编码阶段
>
> **状态（2026-09-19）**：Round 1 与 Round 2 均判**不通过**。致命缺陷 F1（召回层对 CJK
> 结构性失效）+ M5（提示词只给 page_id 与 score，不给候选标题/正文）使本方案的 **Goal
> 不可达**：即使 Task 1/3/4 全部落地，真实中文语料下仍是 `candidates == []` →
> LLM 拿到空候选表 → `parse_llm_edges` 把所有 target 判 `REJECTED` → `relations == []`。
>
> 详见本文档 **## Audit** 一节（含本机独立复核结果与 12 条待整改清单）。
>
> **关系生成功能改为独立方案**，需先完成召回层（CJK 分词/2-gram + 剔除模板 boilerplate
> + 候选证据门槛）与提示词（候选标题 + 摘要）设计。
>
> 期间已实测确认、与本方案解耦的严重缺陷，改由
> [`2026-09-19-v7-verified-severe-defects.md`](2026-09-19-v7-verified-severe-defects.md) 承接
> （D7 静默丢页 / F3 预算丢弃已算完页面 / F2 lint 词表分叉 / M1 全链无超时）。
>
> 本文档保留为审计记录与后续关系功能的输入，**不要再按下面的 Tasks 实施**。

status: deferred（审计未通过）
branch: codex/book-series-target（当前 worktree）
date: 2026-09-19

## Goal

**用户可见结果**：V7 摄取管线产出的 concept 页在 frontmatter 里带上真实的类型化
关系（`relations:` 非空）与正文 `## Related pages` 段落，与 candidate 路径对齐；
不再出现「关系抽取悄悄降级成子串启发式、算完又被丢弃」的情况。

**明确的非目标（non-goals）**：

- 不改 candidate / chunked / unified 路径（属 Stage 2/3）。
- 不改 `RUFLO_PIPELINE_MODE` 默认值，不删旧代码。
- 不接入 `vector_neighbors`（Stage 6 的向量召回策略）——另开一笔，见 Open risks R5。
- 不做谓词词表之外的语义扩展（不新增 `x-*` 用户类型）。
- 不动 Task 24 的 `RelationStore` / `relations.jsonl` 权威存储（本次仍写 legacy
  frontmatter + 正文视图）。

## 背景：缺陷与实测证据

### 实测复现

`.tmp-stage6-repro.py`（临时脚本，不入库）在 `asyncio.run(main())` 内调用：

| # | 调用方式 | `llm.complete` 实际执行次数 | 返回 |
|---|---|---|---|
| 1 | async LLM，不传 `index`（**= bridge 当前行为**） | **0** | 启发式边 `supported_by(b→a)` |
| 2 | 仅补 `index`，仍 async LLM | **0** | `[]` |
| 3 | 同样的 `index`，LLM 是 sync | 2 | `refines(a→b)`，`context='llm_direct'` |
| 4 | 无 `index` + sync LLM（legacy） | 1 | `[]` |

并捕获到 3 条 `RuntimeWarning: coroutine '_AsyncLLM.complete' was never awaited`。

**结论**：`llm.complete` 是 `async def`，调用只创建协程；`asyncio.run()` 在已运行的
事件循环内抛 `RuntimeError`，被 `_extract_with_llm` 的 `except (... RuntimeError)`
吞掉（`relation_extractor.py:271-272` 返回 `None`），于是 `extract_relations`
回退到 `_heuristic_relations`（`relation_extractor.py:292`）。**LLM 请求从未发出，
不产生费用**，所以这不是"花了钱没效果"，而是"悄悄降级 + 结果被丢弃"。

### 缺陷清单

| ID | 位置 | 问题 | 严重度 |
|---|---|---|---|
| D1 | `bridge.py:488` | `_ = extract_relations(...)` 返回值被丢弃 | 致命（关系永远不落地） |
| D2 | `bridge.py:488` | 未传 `index` → 走文档标注的 legacy/tests 分支，生产本应走的 `_extract_with_ontology` 从未执行 | 重大 |
| D3 | `relation_extractor.py:220`、`:252` | 两处 `asyncio.run()` 在事件循环内必然失败且被 `except` 吞掉 → 静默降级 | 致命 |
| D4 | `page_adapter.py:79` | `adapt_concept_page` 从不设置 `WikiPage.relations` | 致命（D1 的孪生） |
| D5 | `relation_extractor.py:13` vs `ALLOWED_PREDICATES_FOR_LLM` | 提示给 LLM 12 个谓词，只放行 2 个 | 重大 |
| D6 | `bridge.py:486` `_check_budget` | 只检查"已达上限"，Stage 6 变成 N 次调用后会越过上限 | 重大 |
| D7 | `bridge.py:470-475` | P1-3 去重按 `topic.id` 计数，但唯一性约束在 `page_id` 上；`_stable_page_id` = `md5(rel)[:8] + slugify(topic_id)[:32]`，**两个不同 `topic.id` 截断/规范化后碰撞 → 同一 page_id → 静默覆盖丢页 + 重复边** | 致命（数据丢失） |

### D7 的现场证据

`knowledge/novel-wiki-v2/wiki/sources/大纲写作技巧-7a51192d.md`（1583 B，写于
2026-09-19 10:52）frontmatter 有**两条完全相同的 `references` 边**指向同一个 target。
对应 `wiki/log.md` 的记录是 `kb-20260919105159-24b4a79f — generated 3 pages`，
而 `wiki/concepts/` 里只有 **1 个** concept 文件。

`3 pages = 1 stub + 2 concept`，但两个 concept 的 id 相同 → 第二个覆盖第一个，
`concept_page_ids` = `[X, X]` → stub 写出 2 条相同边。**这是一个可验证的假说**
（Task 0），不是已确认的结论。

> 已排除的误判：`280f64ec` 与 `7a51192d` 是**两个不同的源文件**
> （`02进阶视频教程/大纲写作技巧.md` 3132 B 与 `音频教程/大纲写作技巧.md` 70966 B）
> 的同名 stub，不是重复页 bug。

## 已定决策（用户 2026-09-19 拍定）

| 决策点 | 选择 |
|---|---|
| Stage 6 生产分支 | **A. ontology 分支**（传 `PageIndex` + 修异步） |
| 谓词词表 | **A. 放宽到与 wiki `RelationType` 的交集** = `{refines, supported_by, causes, contradicts, depends_on}` |
| concept→source 反向边 | **B. 一并加上** `references` 边 |

## Tasks

每个 Task 一个逻辑切片，TDD：先写测试（红）→ 实现（绿）→ 提交。

### Task 0: 判定 D7（topic 页 id 碰撞）—— **已复现，确认为活 bug**

- Files: 无生产改动
- 实测（`_page_id` / `topic_id` 直接调用）：

  ```
  rel = 'raw/sources/视频音频转录教程/音频教程/大纲写作技巧.md'
  topic1 = derive_topic_id(source_id=rel, candidate_ids=['item-a','item-b'])
        = raw/sources/视频音频转录教程/音频教程/大纲写作技巧.md-topic-1bee59b7e87abd47
  topic2 = derive_topic_id(source_id=rel, candidate_ids=['item-c','item-d','item-e'])
        = raw/sources/视频音频转录教程/音频教程/大纲写作技巧.md-topic-07bb6f49822a5fb6
  topic1 != topic2                      ← topic 身份是区分开的
  _slugify(topic1) == _slugify(topic2)  ← 但 slug 相同
        = 'raw-sources-视频音频转录教程-音频教程-大纲写作技巧'   (恰好 32 字符)
  _stable_page_id(rel, topic1) == _stable_page_id(rel, topic2)
        = 'd237368f-raw-sources-视频音频转录教程-音频教程-大纲写作技巧'
  ```

  对照 ASCII 源路径 `raw/sources/notes.md`：`2d0bbfbc-raw-sources-notes-md-topic-dd358` 与
  `...-topic-f5de5`，**能区分**。

- **根因**：`_page_id._MAX_SLUG_LEN = 32`，`_slugify` 取 `lowered[:32]`。
  `topic_id` 形如 `<source_id>-topic-<16hex>`，而 CJK 源路径经 `-` 替换后前缀就已吃满 32 字符
  （`raw-sources-` 12 + `视频音频转录教程` 8 + `-` + `音频教程` 4 + `-` + `大纲写作技巧` 6 = 32），
  **判别符 `-topic-<16hex>` 被整段截断**。`md5(rel)[:8]` 只区分源、不区分 topic，
  于是同一源的所有 topic 得到**同一个 page_id**。
- **严重度：致命（静默数据丢失）**。P1-3 去重按 `topic.id` 计数，而两个 topic 的 `topic.id`
  确实不同 → 两者的 `n_occurrence` 都是 0 → 都拿到同一个 `page_id` → 第二个覆盖第一个。
- **现场佐证**：`kb-20260919105159-24b4a79f — generated 3 pages`（= 1 stub + 2 concept），
  但 `wiki/concepts/` 里只有 1 个 V7 concept 文件
  （`d237368f-...md`，9606 B，2026-09-19 10:52:26），且 stub 有 2 条相同 `references` 边。
- **影响面**：不是罕见碰撞，而是**该语料下任意多 topic 源的常态**——V7 路径对
  `raw/sources/<CJK 目录>/<CJK 目录>/<CJK 文件>.md` 形态的源，**每个源只能落 1 个 concept 页**，
  其余 topic 内容静默丢失。
- Status: **done（已证实）**

> 注：这也修正了本文档先前的一处判断——70 KB 靶子"只有 1 个 concept"**不是该源的固有属性，
> 而是这个 bug 的产物**。修复后同一源可能产出多个 concept 页。

### Task 0b: 修 topic 页 id 碰撞（条件任务，依赖 Task 0 判定）

- Files: `src/pipeline/v7_extract/bridge.py`
- Test: 两个 collision 的 `topic.id` → 断言产出 2 个**不同** `page_id`、
  `concept_page_ids` 无重复、stub 只有 1 条 `references` 边/每个 concept。
- Implementation: 去重的 key 从 `topic.id` 改为「派生的 `base_page_id`」——
  即在 `base_page_id` 上计数并加 `-{n}` 后缀，保证最终 `page_id` 全局唯一。
- Acceptance: 去重不变量改为「同一 bridge run 内 `page_id` 唯一」，并有用例覆盖
  「不同 topic.id / 同 slug」与「同 topic.id」两种碰撞。
- Status: pending

### Task 1: `relation_extractor` 异步化

- Files: `src/pipeline/v7_extract/relation_extractor.py`、
  **`src/pipeline/v7_extract/gold_corpus.py`**（见下方"必须一并改"）
- Test: `tests/test_pipeline/test_v7_extract_stage6.py`（扩充）
  - `extract_relations_async` + async LLM + `index` → 返回 `llm_direct` 边（复现表第 2 行由 `[]` 变非空）。
  - `extract_relations`（sync）在已运行的事件循环内被调用 → **抛明确异常**，不再静默返回。
  - 三个既有 legacy 用例（heuristic / llm 去重 / self-loop+unknown）**行为不变**。
- Implementation:
  - 新增 `async def extract_relations_async(...)`，承载全部 dispatch 与 LLM 调用。
  - `_extract_with_ontology` / `_invoke_ontology_llm` / `_extract_with_llm` 改为 async 孪生，
    用 `await` 处理 awaitable，删除两处 `asyncio.run()`。
  - `extract_relations` 保留为 sync 包装：检测到运行中的事件循环则抛
    `RuntimeError` 并指明改用 `extract_relations_async`；否则 `asyncio.run(...)`。
  - `_heuristic_relations` / `_deduplicate` / `_page_parts` 保持同步不变。
- **必须一并改（草案遗漏，已核实）**：`gold_corpus.py:540` 是 `async def run_stage6r(...)`，
  却在 `:563` 同步调用 `extract_relations(pages, llm=None)`。加了"循环内即抛"的守卫后，
  它会**从能跑变成抛异常**（即使 `llm=None` 根本不需要事件循环）。
  改法：`run_stage6r` 内改成 `relations = await extract_relations_async(pages, llm=None)`。
  它本来就是 async 函数，改动是自然的一行。gold corpus 的 3 个既有用例必须保持全绿
  （注意其中 2 个是已知的顺序相关 flaky，需与基线对比判定）。
- Acceptance: 全仓 `grep -rn "extract_relations(" src/ scripts/` 的每个调用点都被覆盖——
  `bridge.py`（改 await）、`gold_corpus.py`（改 await）、`tests/test_v7_extract_stage6.py`（同步，
  无 LLM 或 sync LLM，不受影响）。
- Status: pending

### Task 2: 谓词词表对齐 + 漂移守卫

- Files: `src/pipeline/v7_extract/relation_extractor.py`
- Test: `tests/test_pipeline/test_v7_extract_stage6.py`（扩充）
  - `ALLOWED_RELATION_TYPES == {"refines","supported_by","causes","contradicts","depends_on"}`。
  - **漂移守卫**：`ALLOWED_RELATION_TYPES ⊆ set(ALLOWED_PREDICATES_FOR_LLM)`
    且 `⊆ {t.value for t in RelationType}`。任一侧新增/改名而另一侧没跟上 → 测试失败。
- Implementation: 常量替换 + 注释说明「必须同时属于 ontology 白名单与 wiki RelationType」。
- Acceptance: 守卫测试在人为改坏任一侧时确实失败（人工验证一次）。
- Status: pending

### Task 3: `adapt_concept_page` 接收关系 + 反向边

- Files: `src/pipeline/v7_extract/page_adapter.py`
- Test: `tests/test_pipeline/test_v7_extract_page_adapter.py`（扩充）
  - 传入 2 条关系 → `WikiPage.relations` 有 2 条，type/weight/context 正确。
  - self-loop（target == page.id）被丢弃；不在白名单的 type 被丢弃。
  - `source_page_id` 非空 → 追加 1 条 concept→source 的 `references` 边。
  - `source_page_id` 为空 / 不传 → 不加该边（保持向后兼容）。
  - 不传 `relations` → 行为与今天完全一致（`relations == []`）。
- Implementation: `adapt_concept_page(page, *, relations=(), source_page_id="")`；
  关系对象按 duck-typing 消费（`getattr(r, "target_id"/"type"/...)`），
  避免 `page_adapter` → `relation_extractor` 的硬依赖；annotation 用 `TYPE_CHECKING`。
- Acceptance: 既有 14 个 page_adapter 用例全绿（含 2 个 timestamp 回归）。
- Status: pending

### Task 4: bridge Stage 6/7 接线

- Files: `src/pipeline/v7_extract/bridge.py`
- Test: `tests/test_pipeline/test_v7_extract_bridge.py`（扩充）
  - 脚本化 async provider + 2 个 concept → 两个 `WikiPage` 各自带上期望的关系。
  - Stage 6 抛异常时（模拟）→ 记 warning、`relations` 为空、**ingest 不失败**（best-effort 契约不变）。
  - 关系按 `source_id` 分组正确：A 的关系不会挂到 B 上。
- Implementation:
  1. `from .candidate_retrieval import PageIndex`，`index=PageIndex.build(concept_pages)`。
  2. 改为 `relations = await extract_relations_async(...)`，捕获返回值（去掉 `_ =`）。
  3. 按 `rel.source_id` 分组为 `dict[str, list[PageRelation]]`。
  4. **调整 Stage 7 顺序**：先 `build_source_stub_page(...)` 拿到 `stub.id`，
     再 `adapt_concept_page(cp, relations=by_source.get(cp.id, ()), source_page_id=stub.id)`。
     注意 stub 的 `concept_page_ids` 仍取自 concept 页 id 列表（不依赖 adapt 结果）。
- Acceptance: 既有 11 个 bridge 用例全绿（脚本 provider 的调用序列需补
  `extract_relations_ontology` 条目）。
- Status: pending

### Task 5: Stage 6 预算守卫

- Files: `src/pipeline/v7_extract/bridge.py`
- Test: `tests/test_pipeline/test_v7_extract_bridge.py`（扩充）
  - `max_calls` 不足以容纳 `len(concept_pages)` 次关系调用 → **整个 Stage 6 跳过**、
    记 warning、`meta["stage6_skipped"] == "budget"`、ingest **仍成功**、页数不变。
  - 预算充足 → 正常执行、`meta` 无 `stage6_skipped`。
  - **`_check_budget` 既有的「已超上限即 raise」行为不变**（v3 路径 23 calls 的
    budget abort 是已验证行为，不得改变）。
- Implementation: Stage 6 前做 look-ahead：
  `if llm.calls_count + len(concept_pages) > budget.max_calls: skip`。
  保留原 `_check_budget(llm, budget, "stage6")` 调用在其之前。
- Acceptance: 默认 `max_calls=20` **不上调**（避免改变 v3 路径已验证的 abort 行为）。
- Status: pending

### Task 6: 端到端验证 + 文档

- Files: `docs/ops/handoff-v7-stage1-remote.md`（§6.4 判据、§9 坑 7）、
  `.memory/feedback-*.md`、`.superpowers/sdd/progress.md`
- Verification:
  1. `python -m pytest --import-mode=importlib PYTHONPATH=. tests/test_pipeline/test_v7_extract_*`
  2. `python -X utf8 scripts/smoke_v7_bridge.py`（真实 provider）
  3. 确认 `RuntimeWarning: coroutine ... was never awaited` **消失**
  4. 确认 H1–H5 = 0、`wiki-quality --strict` 无 error
  5. 若产出 concept 页 → 确认 `relations:` 非空且正文有 `## Related pages`
- Acceptance: 见下方「验收标准」。
- Status: pending

## 预埋审查标准（9 维度）

| 维度 | 本方案的落点 |
|---|---|
| 目标对齐 | 只修「关系不落地」+ 直接致因（D7 若证实）；non-goals 已列明 |
| 前提假设 | ① `extract_relations` ontology 分支可用且被文档指定为生产路径；② `Relation.type` 接受 `{refines,supported_by,causes,contradicts,depends_on}`（均为 `RelationType` 成员）；③ 真实 LLM 会按提示输出这 12 个谓词 |
| 边界场景 | 0 concept / 1 concept（**无候选 → 无关系**）/ N concept；LLM 返回空 `edges`；LLM 返回未知谓词；关系 target 不在本批；预算不足；LLM 超时/429 |
| 依赖项 | `candidate_retrieval.PageIndex`、`relation_ontology`、`src.wiki.features.relations.Relation`、`materialize_relations`；缺失兜底 = Stage 6 整段 best-effort 捕获 |
| 风险与副作用 | 正文新增 `## Related pages` 段落；concept 页首次出现关系边 → H2 检查面变化；每 concept 1 次 LLM 调用 → 成本上升 |
| 可执行性 | 每个 Task 有 Files/Test/Acceptance；Task 0 先判定再做条件任务 |
| 验收标准 | 见下 |
| 盲区清单 | 真实 provider 仍 429（无法端到端验证多 concept 场景）；无 vector_neighbors 时候选召回质量未知 |
| 回滚预案 | 三个 commit 逐个 revert；无数据迁移；关系边可随重摄取消失 |

## 验收标准（可量化）

1. `tests/test_pipeline/test_v7_extract_*` 全绿，且新增用例覆盖 D1–D7。
2. `RuntimeWarning: coroutine '...complete' was never awaited` 在 bridge 冒烟输出中**为 0 条**。
3. 2-concept 场景下 `WikiPage.relations` 非空，且每条 target 都能在 `build_target_slugs` 中解析。
4. H1–H5 = 0；`wiki-quality --strict` 0 error。
5. 同一源连续摄取两次：无重复 page、无重复 gap、无重复 KC bundle，且不重复追加 `## Related pages`。
6. 默认 `RUFLO_V7_MAX_CALLS=20` 不变；v3 路径仍在 23 calls 时 abort（既有行为）。
7. `_heuristic_relations` 在无 LLM 路径（`gold_corpus`）行为不变。

## Audit

- Round 1: **未通过** —— 2 条致命（F1/F2）+ 1 条致命（F3）+ 1 条致命（F5）需整改，详见下节。
- Round 2: **未通过** —— 失效边界见下节。
- Human review: pending
- **结论：本方案不得进入编码阶段。**

### 审计发现与本机独立复核

两轮审计由独立 subagent 完成（只读）。以下逐条标注**我是否已在本机独立复现**——
未复核的一律标注「采信审计」，不作为既定事实。

| ID | 级别 | 断言 | 我的复核结果 |
|---|---|---|---|
| **F1** | 致命 | `PageIndex` 召回对 CJK 结构性失效：`_TOKEN_RE=[A-Za-z0-9]+` 切不出中文 token → 候选恒空；含模板注释时 token 全为 boilerplate → 所有 V7 页 Jaccard≈1.0 | ✅ **已实测复现**。场景A（纯 CJK 双页）`entity_tokens=[] candidates=[]`；场景B/C 的 token 全是 `['0','3','item','template','version','wiki']`（来自 `<!-- wiki-template-version: 3.0.0 -->`），候选由 boilerplate 驱动 |
| **F2** | 致命 | `refines` 不在 `lint._BUILTIN_RELATIONS` → `LINT-ILLEGAL-RELATION` ERROR；且 `wiki-quality --strict` 不跑 lint → 假绿 | ✅ **已实测**。`lint._BUILTIN_RELATIONS` 21 项**无 `refines`/`refined_by`**（而 `relations.py RelationType` 有）——两个"权威集合"已分叉；lint 判定式为 `if rtype not in _BUILTIN_RELATIONS and not rtype.startswith("x-")` |
| **F3** | 致命 | `_check_budget` 在 Stage 6 边界 raise → `failure_stage="budget"` → `ingest.py` 抛 `RetryableDependencyError` → **`commit_ingest` 从未执行，已算完的页面整批丢弃**；我的 look-ahead 放在 raise 之后，在"已超上限"支上不可达 | 采信审计（机制与 `bridge.py:206-218`、`bridge.py:527-535`、`ingest.py` v7 分支 raise 一致，逻辑成立） |
| **F4** | 致命 | sync 守卫若写在函数入口，`extract_relations(pages)`（`llm=None`，纯启发式零 IO）在任意 coroutine 内都会抛异常 | 采信审计（我的 Task 1 确实未写死守卫位置） |
| **F5** | 致命 | 验收不可观测/不可证伪：#3 垃圾关系也能过；#5 的 gap/KC 判据对 V7 是空判据（V7 提前 return）；#4 不含 lint | 采信审计（与 `ingest.py` v7 提前 return 的事实一致） |
| **M1** | 重大 | `_bounded_complete` 是死代码，从未被调用 → Stage 6 的 N 次调用无逐调用预算门、无超时 | ✅ **已实测**。`grep _bounded_complete src/pipeline/v7_extract/*.py` 只命中定义处 `bridge.py:162`，无调用点 |
| **M2** | 重大 | Task 4 重排 Stage 7 会使 `concept_page_ids` 语义从"会落盘的页 id"变成"adapt 前列表" → stub 指向被质量门丢弃的页 → 因 V7 跳过 `collect_missing_slugs`，断链进不了 gap 账本 → H2 ERROR。**建议抽纯函数不重排** | 采信审计（**方案方向确实反了**，我的注记把"不依赖 adapt 结果"当优点写了） |
| **M3** | 重大 | `-{n}` 位置后缀使 page_id 依赖 topic 顺序 → 跨运行不稳定 | 已被用户决策覆盖（改为 `{源md5}-{源stem}-{topic哈希}`） |
| **M5** | 重大 | `render_llm_prompt` 只给 `target=<page_id> (score, kind)`，不给候选标题/正文/证据 → LLM 信息上不可能判对 | ✅ **已实测**。提示词实际输出：`Source page: 大纲写作技巧` + 空的 `Candidates` 列表 + 仅谓词名 |
| **P11** | 重大 | `health` **没有 H3**；我的验收与交接 runbook 写"H1–H5"是错的 | ✅ **已实测**。`src/cli_ext/health_cmd.py:14 CHECKS_AVAILABLE = {"H1","H2","H4","H5"}` |
| **P9** | 重大 | D7 非 CJK 特有：`len(slug(源路径)) ≥ 25` 即全塌缩（纯 ASCII 长路径同样） | 采信审计（机制与 `_MAX_SLUG_LEN=32` 一致；`raw/sources/` 前缀已占 12 字符） |
| **P2** | 致命 | 预算悬崖：3+T 基础调用下，T≤8 正常、9≤T≤16 静默跳过 Stage 6、T≥17 整轮失败丢弃全部页面 | 采信审计（算式与 `_check_budget`/`MAX_RETRIES=3` 一致） |
| **P8** | 重大 | `materialize_relations` 用 `body.split("\n## Related pages\n",1)[0]` 截断 → 正文出现该字面量时静默丢内容 | 采信审计（`gbrain_compat.py:65` 确实如此） |
| **O4** | 优化 | 我的 Task 6 命令 `python -m pytest --import-mode=importlib PYTHONPATH=. ...` 写法错（`PYTHONPATH=.` 会被当测试路径）；PowerShell 下需 `$env:PYTHONPATH="."` | ✅ 确认写法有误，按 AGENTS.md 应为 `PYTHONPATH=. python -m pytest ...` |

### 复核后的核心结论

**F1 + M5 使本方案的 Goal 不可达。** 即使 Task 1/3/4 全部按方案落地：
1. 真实 CJK 语料下 `candidates == []` → LLM 拿到空候选表；
2. `parse_llm_edges` 对不在 `candidate_ids` 的 target 一律 `REJECTED`；
3. 结果 `relations == []`，正文无 `## Related pages`。

即"修好了管道，但管道里没有东西"。而失败形态恰恰是本方案 Goal 点名要消灭的
**静默空**。要让关系真正落地，必须先解决**召回层**（CJK 分词/2-gram + 剔除模板
boilerplate + 候选最小证据门槛）与**提示词**（给候选标题与摘要），这超出了
"修 Stage 6 关系不落地"这个缺陷的范围，属独立设计工作。

### 待整改清单（阻塞编码）

1. **F1** 召回层：`_TOKEN_RE` 增 CJK 路径（2-gram 或分词）；剔除模板注释/`item`/纯数字等
   boilerplate token；候选设最小证据门槛；把"每页候选数"变成可观测指标。
2. **M5** 提示词：给候选 `title` + `detail` + 正文摘要；`parse_llm_edges` 接受候选序号并归一化；
   **候选为空时直接跳过该页、不消耗预算**。
3. **F2** 词表：把 `refines`/`refined_by` 补进 `lint._BUILTIN_RELATIONS`（附 lint 用例），
   或收窄词表为 `{supported_by, causes, contradicts, depends_on}`；漂移守卫改断言
   `lint._BUILTIN_RELATIONS`（**不是** `RelationType`）；验收加 `python -m src.cli lint` 0 ERROR。
4. **F3** 预算：look-ahead 移到 `_check_budget` **之前**，命中时 skip 而非 raise；
   或把 stage6 预算语义由"raise 中止整轮"改为"skip 本阶段"；补"`calls_count >= max_calls`
   时页面照常落盘、Stage 6 跳过"用例。
5. **M1** 超时：Stage 6 调用统一走带 `asyncio.wait_for` + 计数门的代理（复活 `_bounded_complete`）。
6. **M2** 不重排 Stage 7：抽 `_source_stub_page_id(source_path, task_id)` 纯函数先取 id，
   `concept_page_ids` 保持"adapt 之后"语义。
7. **F4** 守卫写死为 `if llm is not None and _running_loop(): raise`；保留非 awaitable 放行。
8. **F5** 重写验收为可证伪指标（候选数 ≥1、关系带 context、frontmatter 与正文一致、
   `meta["stage6"]` 统计、lint 0 ERROR）。
9. **M4** `contradicts` 在 wiki 侧对称、V7 侧定向 → 需 canonical 折叠或从词表移除。
10. **M8** 验收补"frontmatter relations 集合 == 正文 `## Related pages` 条目集合"。
11. **P11/O4** 修正交本文档与 runbook 的 `H1–H5` → `H1/H2/H4/H5`；修正 pytest 命令写法。
12. **P8** `materialize_relations` 改用 `_RELATIONS_MARKER` 定位，无 marker 只追加不截断。

- Open risks:
  - **R1（已降级）**：原判断"单 70 KB 靶子只有 1 个 concept → 无法证明修复生效"基于错误前提。
    `wiki/log.md` 的 `kb-20260919105159-24b4a79f — generated 3 pages`（= 1 stub + 2 concept）
    说明 Stage 4 聚类**确实产出了 ≥2 个 topic**；"只有 1 个 concept"是 D7 覆盖的结果。
    但 **R2 审计指出该结论仍不充分**：T≥2 只是候选生成的必要条件，
    按 F1 实测中文页候选仍为空 → **撤回"该靶子可端到端证明关系修复生效"的结论**。
  - **R2（已升级为致命 F1）**：不再是"召回可能很差"，而是**零召回 / precision 崩塌两极**。
  - **R3（已排除）**：核对了 `src/wiki/features/lint.py:698-702`，`LINT-MISSING-SECTION`
    只算 `missing = required - body_headings`，**不惩罚多余段落**；且 source stub 已带
    `## Related pages` 而 `wiki-quality --strict` 仍为 HEALTHY。故 concept 页新增该段落不触发 lint。
  - **R4**：真实 provider 仍 429 → 端到端证据可能只能停在合成 provider 层面。
  - **R5**：`vector_neighbors` 未接入（non-goal），Stage 6 召回质量提升留待后续。
  - **R6**：D7 的修复会改变已写页面的 id（现磁盘上
    `d237368f-raw-sources-视频音频转录教程-音频教程-大纲写作技巧` 一个）。
    V7 尚未成为默认路径，迁移面极小；已决定**接受孤儿，验证时手工清理**。
  - **R7（新，来自审计）**：`wiki-quality --strict` **不调用 lint**，所以它能给出假绿；
    凡涉及关系词表的验收必须显式跑 `python -m src.cli lint`。
  - **R8（新，来自审计）**：V7 路径跳过 `_compute_reverse_relations`
    （`ingest.py` 提前 return），"双向图"不变量对 V7 页不成立；哪些谓词需要桥内自补反向边、
    哪些接受单向，需显式声明。
- Rollback: 逐个 revert Task 0b–5 的提交；`page_adapter` 新参数有默认值，
  回滚不破坏已写页面。**注意代码 revert 不回滚磁盘副作用**（已写入的 `relations:` 与
  `## Related pages` 会留在页面上，V7 只在重摄取时整页重写），
  回滚后必须重跑 `wiki-quality --strict` + `lint` + H2，并清理 D7 的旧 id 孤儿页。
- Rollback: 逐个 revert Task 0b–5 的提交；`page_adapter` 新参数有默认值，
  回滚不破坏已写页面。

## Completion evidence

- Final commit:
- Tests:
- Static checks: 无 linter/formatter/type checker（仓库未配置）
- Documentation updated:
- Progress ledger updated: no
